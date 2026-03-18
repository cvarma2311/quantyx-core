from __future__ import annotations

from typing import Any
import logging
import os
import re

from services.ai.config import Settings
from services.ai.db import run_query
from services.ai import semantic_extraction
from services.ai.semantic_extraction import extract_semantic_contract
from services.ai.semantic_layer.pack_loader import load_pack

NUMERIC_TYPES = {
    "integer",
    "bigint",
    "smallint",
    "numeric",
    "double precision",
    "real",
}
TIME_TYPES = {
    "date",
    "timestamp",
    "timestamp without time zone",
    "timestamp with time zone",
}
BOOLEAN_TYPES = {"boolean", "bool"}
MEASURE_HINT_TOKENS = {
    "total",
    "count",
    "amount",
    "volume",
    "sales",
    "production",
    "hours",
    "hour",
    "pending",
    "rejection",
    "reject",
    "utilization",
    "throughput",
    "qty",
    "quantity",
    "rate",
    "avg",
    "mean",
}
IDENTIFIER_CODE_TOKENS = {"code", "sap", "jde", "idx"}
IDENTIFIER_KEY_TOKENS = {"id", "identifier", "key", "uuid"}
STATUS_HINT_TOKENS = {"status", "flag", "active", "enabled", "valid", "is_"}
INTENT_HINT_MAP = {
    "production": "volume",
    "sales": "volume",
    "volume": "volume",
    "pending": "backlog",
    "reject": "quality",
    "rejection": "quality",
    "failure": "quality",
    "utilization": "utilization",
    "productivity": "productivity",
    "hour": "utilization",
    "count": "volume",
}
DEFAULT_KPI_PRIORITY_HINTS = {
    "total_productivity": 120,
    "total_production": 115,
    "productivity": 100,
    "production": 95,
    "throughput": 85,
    "efficiency": 80,
    "utilization": 75,
}
DEFAULT_TIME_PRIORITY_COLUMNS = [
    "process_date",
    "execution_date",
    "delivery_date",
    "created_at",
    "date",
]
DEFAULT_BREAKDOWN_PRIORITY_TOKENS = [
    "plant",
    "zone",
    "region",
    "sales_area",
    "location",
    "site",
    "state",
    "city",
]
BREAKDOWN_FALLBACK_LIMIT = 3
_CONTEXT_SECTION_HEADERS = {"metric definition", "business formula", "reference sql", "semantic rules"}
_KPI_FAMILY_PREFIXES = ("total", "normal", "break", "overtime")
_SQL_IDENTIFIER_IGNORE = {
    "sum",
    "avg",
    "average",
    "count",
    "distinct",
    "round",
    "nullif",
    "coalesce",
    "case",
    "when",
    "then",
    "else",
    "end",
    "as",
    "date",
    "extract",
    "year",
    "month",
    "day",
    "from",
    "and",
    "or",
    "not",
    "null",
    "cast",
    "on",
    "in",
    "over",
    "partition",
    "by",
    "order",
    "desc",
    "asc",
    "current_date",
}


def _qident(name: str) -> str:
    # Defensive quoting for mixed-case/special-character identifiers.
    return '"' + str(name).replace('"', '""') + '"'


def _split_tokens(name: str | None) -> list[str]:
    if not name:
        return []
    cleaned = str(name).strip().lower().replace(".", "_").replace("-", "_")
    return [part for part in cleaned.split("_") if part]


def _csv_lower_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip().lower() for item in str(raw).split(",") if item.strip()}


def _split_top_level_csv(raw: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    for ch in raw:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth > 0:
                depth -= 1
            elif ch == "," and depth == 0:
                part = "".join(buf).strip()
                if part:
                    parts.append(part)
                buf = []
                continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _sanitize_metric_identifier(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return cleaned or None


def _infer_metric_type_from_formula(formula: str | None, metric_name: str | None = None) -> str:
    text = str(formula or "").upper()
    name = str(metric_name or "").lower()
    if "AVG(" in text or "AVERAGE(" in text:
        return "avg"
    if "COUNT(DISTINCT" in text:
        return "count_distinct"
    if "COUNT(" in text:
        return "count"
    if any(token in name for token in ("rate", "ratio", "productivity", "efficiency", "utilization", "yield")):
        return "derived"
    return "sum"


def _coerce_confidence(value: Any, default: float = 0.88) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return max(0.0, min(0.99, float(value)))
    text = str(value).strip().lower()
    mapping = {
        "very high": 0.95,
        "high": 0.9,
        "medium": 0.75,
        "moderate": 0.75,
        "low": 0.6,
        "very low": 0.5,
    }
    if text in mapping:
        return mapping[text]
    try:
        return max(0.0, min(0.99, float(text)))
    except (TypeError, ValueError):
        return default


def _extract_metric_expr_from_sql(sql_text: str, preferred_metric_name: str | None = None) -> tuple[str | None, str | None]:
    if not sql_text:
        return None, None
    match = re.search(r"(?is)\bselect\b(.*?)\bfrom\b", sql_text)
    if not match:
        return None, None
    select_body = match.group(1).strip()
    candidates: list[tuple[str, str]] = []
    for item in _split_top_level_csv(select_body):
        alias_match = re.match(r'(?is)^(.*?)\s+as\s+"?([a-zA-Z_][\w]*)"?\s*$', item.strip())
        if not alias_match:
            continue
        expr = alias_match.group(1).strip()
        alias = alias_match.group(2).strip()
        candidates.append((expr, alias))
    if not candidates:
        return None, None
    preferred = _sanitize_metric_identifier(preferred_metric_name)
    for expr, alias in candidates:
        if preferred and _sanitize_metric_identifier(alias) == preferred:
            return expr, alias
    for expr, alias in candidates:
        upper_expr = expr.upper()
        if any(token in upper_expr for token in ("SUM(", "AVG(", "COUNT(", "ROUND(", "MIN(", "MAX(")):
            return expr, alias
    expr, alias = candidates[0]
    return expr, alias


def _extract_time_column_from_sql(sql_text: str) -> str | None:
    if not sql_text:
        return None
    match = re.search(r'(?is)\bdate\s*\(\s*"?(?P<col>[a-zA-Z_][\w]*)"?\s*\)\s+as\s+"?(?P<alias>[a-zA-Z_][\w]*)"?', sql_text)
    if match:
        return match.group("col")
    group_match = re.search(r'(?is)\bgroup\s+by\s+"?([a-zA-Z_][\w]*)"?', sql_text)
    if group_match:
        return group_match.group(1)
    return None


def _extract_table_from_sql(sql_text: str) -> str | None:
    if not sql_text:
        return None
    match = re.search(r'(?is)\bfrom\s+((?:"?[\w]+"?\.)?"?([a-zA-Z_][\w]*)"?)', sql_text)
    if not match:
        return None
    return match.group(2)


def _extract_metric_overrides(context_text: str | None, schema_graph: dict[str, Any]) -> list[dict[str, Any]]:
    if not context_text:
        return []
    valid_tables = {str(t.get("name") or "").strip() for t in schema_graph.get("tables", []) if t.get("name")}
    overrides: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    section: str | None = None
    sql_lines: list[str] = []
    formula_lines: list[str] = []

    def _flush_current() -> None:
        nonlocal current, sql_lines, formula_lines
        if not current and not sql_lines and not formula_lines:
            return
        candidate = dict(current)
        sql_text = "\n".join(sql_lines).strip()
        if sql_text:
            candidate["reference_sql"] = sql_text
        if formula_lines and not candidate.get("formula"):
            candidate["formula"] = " ".join(formula_lines).strip()
        metric_name = _sanitize_metric_identifier(candidate.get("metric_name") or candidate.get("display_name"))
        expr, sql_alias = _extract_metric_expr_from_sql(sql_text, metric_name)
        if expr and not candidate.get("formula"):
            candidate["formula"] = expr
        if not metric_name:
            metric_name = _sanitize_metric_identifier(sql_alias)
        if not metric_name:
            current = {}
            sql_lines = []
            formula_lines = []
            return
        base_table = str(candidate.get("base_table") or _extract_table_from_sql(sql_text) or "").strip()
        if valid_tables and base_table and base_table not in valid_tables:
            current = {}
            sql_lines = []
            formula_lines = []
            return
        time_column = str(candidate.get("time_column") or _extract_time_column_from_sql(sql_text) or "").strip() or None
        grain = str(candidate.get("grain") or ("day" if time_column else "")).strip() or None
        override = {
            "metric_name": metric_name,
            "display_name": candidate.get("display_name") or metric_name.replace("_", " ").title(),
            "description": candidate.get("description"),
            "formula": str(candidate.get("formula") or "").strip(),
            "base_table": base_table or None,
            "grain": grain,
            "preferred_time_column": time_column,
            "metric_type": candidate.get("metric_type") or None,
            "metric_source": "context_override",
            "metric_priority": 5000,
            "measure_confidence": 0.99,
            "is_executive_kpi": True,
            "reference_sql": sql_text or None,
        }
        if override["metric_name"] and override["base_table"] and override["formula"]:
            overrides.append(override)
        current = {}
        sql_lines = []
        formula_lines = []

    for raw_line in context_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        header = stripped[:-1].strip().lower() if stripped.endswith(":") else ""
        if header in _CONTEXT_SECTION_HEADERS:
            if header == "metric definition":
                _flush_current()
            section = header
            continue
        if not stripped:
            if section in {"reference sql", "business formula"}:
                continue
            continue
        if section == "metric definition":
            meta_match = re.match(r"^-\s*([a-zA-Z_][\w]*)\s*:\s*(.+?)\s*$", stripped)
            if meta_match:
                current[meta_match.group(1)] = meta_match.group(2)
        elif section == "business formula":
            formula_match = re.match(r"^-?\s*([a-zA-Z_][\w]*)\s*=\s*(.+?)\s*$", stripped)
            if formula_match:
                current.setdefault("metric_name", formula_match.group(1))
                current["formula"] = formula_match.group(2).strip()
            else:
                formula_lines.append(stripped.lstrip("- ").strip())
        elif section == "reference sql":
            sql_lines.append(line)

    _flush_current()
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in overrides:
        key = (str(item.get("base_table") or ""), str(item.get("metric_name") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _max_uniqueness_ratio() -> float:
    raw = os.getenv("AGENTIC_MEASURE_MAX_UNIQUENESS_RATIO", "0.90")
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.90


def _classify_column_semantic_role(name: str, data_type: str) -> str:
    lower_name = (name or "").strip().lower()
    dtype = (data_type or "").strip().lower()
    tokens = _split_tokens(lower_name)
    if dtype in TIME_TYPES:
        return "time_dimension"
    if dtype in BOOLEAN_TYPES:
        return "status_flag"
    if lower_name.endswith("_id") or lower_name == "id" or any(tok in IDENTIFIER_KEY_TOKENS for tok in tokens):
        return "identifier_key"
    if lower_name.endswith("_code") or "code" in tokens or any(tok in IDENTIFIER_CODE_TOKENS for tok in tokens):
        return "identifier_code"
    if any(tok in STATUS_HINT_TOKENS for tok in tokens) or lower_name.startswith("is_"):
        return "status_flag"
    if dtype in NUMERIC_TYPES:
        if any(tok in MEASURE_HINT_TOKENS for tok in tokens):
            return "measure_additive"
        return "measure_non_additive"
    return "dimension_attribute"


def _is_measure_eligible(
    *,
    col_name: str,
    data_type: str,
    semantic_role: str,
    uniqueness_ratio: float | None,
) -> tuple[bool, str]:
    lower = (col_name or "").strip().lower()
    allowlist = _csv_lower_set(os.getenv("AGENTIC_MEASURE_ALLOWLIST"))
    denylist = _csv_lower_set(os.getenv("AGENTIC_MEASURE_DENYLIST"))
    if lower in allowlist:
        return True, "allowlist_override"
    if lower in denylist:
        return False, "denylist_override"
    if semantic_role in {"identifier_code", "identifier_key", "time_dimension"}:
        return False, f"semantic_role_{semantic_role}"
    if data_type not in NUMERIC_TYPES:
        return False, "non_numeric_type"
    if lower.endswith("_id") or lower.endswith("_code"):
        return False, "blocked_id_code_suffix"
    if uniqueness_ratio is not None and uniqueness_ratio >= _max_uniqueness_ratio():
        return False, "high_uniqueness_ratio"
    if semantic_role in {"measure_additive", "measure_ratio_component"}:
        return True, "measure_role_pass"
    if semantic_role == "measure_non_additive":
        # Keep these disabled in Phase 29 until template-first metrics are fully wired.
        return False, "measure_non_additive_not_enabled"
    return False, "unsupported_role"


def _derive_metric_intent(name: str | None) -> str:
    lower = (name or "").strip().lower()
    for token, intent in INTENT_HINT_MAP.items():
        if token in lower:
            return intent
    return "volume"


def _pick_canonical_time_column(table: dict[str, Any], domain_id: str | None = None) -> str | None:
    time_cols = [str(col) for col in (table.get("time_columns") or []) if str(col or "").strip()]
    if not time_cols:
        return None
    lower_map = {col.lower(): col for col in time_cols}
    for preferred in _time_priority_columns(domain_id):
        if preferred in lower_map:
            return lower_map[preferred]
    return time_cols[0]


def _candidate_key_uniqueness(table: dict[str, Any], column_name: str | None) -> float | None:
    if not column_name:
        return None
    for key in (table.get("candidate_keys") or []):
        if str(key.get("column") or "") != str(column_name):
            continue
        try:
            return float(key.get("uniqueness_ratio"))
        except (TypeError, ValueError):
            return None
    return None


def _is_breakdown_eligible(
    table: dict[str, Any],
    column_name: str,
    domain_id: str | None = None,
) -> tuple[bool, str]:
    lower = str(column_name or "").strip().lower()
    if not lower:
        return False, "empty"
    allowlist = _breakdown_allowlist(domain_id)
    denylist = _breakdown_denylist(domain_id)
    if lower in allowlist:
        return True, "allowlist_override"
    if lower in denylist:
        return False, "denylist_override"
    if _exclude_identifier_breakdowns(domain_id):
        semantic_role = _classify_column_semantic_role(column_name, "text")
        if semantic_role in {"identifier_key", "identifier_code"}:
            return False, f"semantic_role_{semantic_role}"
        if lower.endswith("_id") or lower.endswith("_code") or lower == "id":
            return False, "blocked_id_code_suffix"
    uniqueness_ratio = _candidate_key_uniqueness(table, column_name)
    if uniqueness_ratio is not None and uniqueness_ratio >= _max_breakdown_uniqueness_ratio(domain_id):
        return False, "high_uniqueness_ratio"
    return True, "eligible"


def _rank_breakdown_columns(table: dict[str, Any], domain_id: str | None = None) -> list[str]:
    cat_cols = [str(col) for col in (table.get("categorical_columns") or []) if str(col or "").strip()]
    samples = table.get("sample_values") or {}
    priority_tokens = _breakdown_priority_tokens(domain_id)
    scored: list[tuple[float, str]] = []
    logger = logging.getLogger(__name__)
    for col in cat_cols:
        eligible, reason = _is_breakdown_eligible(table, col, domain_id)
        if not eligible:
            logger.info(
                "agentic.chart.breakdown_rejected | table=%s column=%s reason=%s",
                table.get("name"),
                col,
                reason,
            )
            continue
        lower = col.lower()
        score = 0.0
        for idx, token in enumerate(priority_tokens):
            if token in lower:
                score += 20.0 - idx
        sample_count = len(samples.get(col) or [])
        if 1 < sample_count <= 20:
            score += 5.0
        elif sample_count == 1:
            score -= 2.0
        elif sample_count > 100:
            score -= 3.0
        score += _column_quality_score(table, col)
        logger.info(
            "agentic.chart.breakdown_candidate | table=%s column=%s score=%.2f sample_count=%s",
            table.get("name"),
            col,
            score,
            sample_count,
        )
        scored.append((score, col))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [col for _, col in scored]


def _column_quality_score(table: dict[str, Any], column_name: str | None) -> float:
    if not column_name:
        return 0.0
    sample_values = table.get("sample_values") or {}
    candidate_keys = table.get("candidate_keys") or []
    score = 0.0
    sample_count = len(sample_values.get(column_name) or [])
    if sample_count > 1:
        score += min(10.0, float(sample_count))
    for key in candidate_keys:
        if key.get("column") != column_name:
            continue
        uniqueness = float(key.get("uniqueness_ratio") or 0.0)
        if uniqueness >= 0.95:
            score -= 8.0
        elif uniqueness <= 0.5:
            score += 2.0
        break
    return score


def _metric_chart_priority(metric: dict[str, Any], domain_id: str | None = None) -> float:
    score = _metric_priority_score(metric, domain_id)
    metric_type = str(metric.get("metric_type") or "").lower()
    metric_name = str(metric.get("metric_name") or "").lower()
    if metric_type in {"sum", "avg", "ratio", "efficiency", "utilization"}:
        score += 10.0
    if "total_" in metric_name:
        score += 15.0
    if metric.get("preferred_time_column"):
        score += 8.0
    if metric.get("preferred_breakdowns"):
        score += 4.0
    return score


def _mandatory_metric_rank(metric_name: str | None) -> int:
    key = str(metric_name or "").strip().lower()
    if key == "total_production":
        return 0
    if key == "total_productivity":
        return 1
    return 99


def _top_metrics_for_table(
    metrics: list[dict[str, Any]],
    table_name: str,
    limit: int = 3,
    domain_id: str | None = None,
) -> list[dict[str, Any]]:
    table_metrics = [m for m in metrics if m.get("base_table") == table_name and m.get("formula")]
    table_metrics.sort(key=lambda metric: _metric_chart_priority(metric, domain_id), reverse=True)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    mandatory: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []
    for metric in table_metrics:
        key = str(metric.get("metric_name") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        if _mandatory_metric_rank(key) < 99:
            mandatory.append(metric)
        else:
            optional.append(metric)
    mandatory.sort(key=lambda metric: _mandatory_metric_rank(metric.get("metric_name")))
    for metric in mandatory + optional:
        deduped.append(metric)
        if len(deduped) >= limit:
            break
    return deduped


def _pick_chart_breakdowns(
    table: dict[str, Any],
    metric: dict[str, Any],
    limit: int = BREAKDOWN_FALLBACK_LIMIT,
    domain_id: str | None = None,
) -> list[str]:
    preferred = [str(col) for col in (metric.get("preferred_breakdowns") or []) if str(col or "").strip()]
    ranked = _rank_breakdown_columns(table, domain_id)
    ordered: list[str] = []
    seen: set[str] = set()
    for col in preferred + ranked:
        key = col.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(col)
        if len(ordered) >= limit:
            break
    return ordered


def _time_grain_label(time_grain: str | None) -> str:
    value = str(time_grain or "").strip().lower()
    if value == "day":
        return "Day"
    if value == "month":
        return "Month"
    return "Time"


def _metric_priority_score(metric: dict[str, Any], domain_id: str | None = None) -> float:
    name = str(metric.get("metric_name") or "").lower()
    formula = str(metric.get("formula") or "").lower()
    score = float(metric.get("measure_confidence") or 0.0) * 100.0
    score += float(metric.get("llm_priority_boost") or 0.0)
    if metric.get("is_executive_kpi"):
        score += 50.0
    if metric.get("metric_source") == "context_llm":
        score += 60.0
    if metric.get("metric_source") == "context_override":
        score += 70.0
    if metric.get("metric_source") == "family_direct":
        score += 65.0
    if metric.get("metric_source") == "family_derived":
        score += 55.0
    if metric.get("metric_source") == "canonical":
        score += 40.0
    for token, bonus in _kpi_priority_hints(domain_id).items():
        if token in name or token in formula:
            score += float(bonus)
    return score


def _canonical_metric_formula(column_name: str, domain_id: str | None = None) -> tuple[str, str, str]:
    lower = str(column_name or "").lower()
    if "productivity" in lower or "efficiency" in lower or "utilization" in lower or "rate" in lower:
        return str(column_name), f"AVG({column_name})", "avg"
    return str(column_name), f"SUM({column_name})", "sum"


def _eligible_cols_by_token(table: dict[str, Any], tokens: list[str]) -> list[str]:
    allowed = set(table.get("eligible_numeric_columns") or [])
    matches: list[str] = []
    for col in allowed:
        lower = str(col).lower()
        if any(tok in lower for tok in tokens):
            matches.append(col)
    return matches


def _extract_kpi_family_parts(column_name: str | None) -> tuple[str | None, str]:
    value = str(column_name or "").strip().lower()
    if not value:
        return None, ""
    for prefix in _KPI_FAMILY_PREFIXES:
        if value.startswith(prefix + "_"):
            return prefix, value[len(prefix) + 1 :]
    return None, value


def _family_metric_name(family: str | None, suffix: str) -> str:
    suffix = str(suffix or "").strip().lower()
    return f"{family}_{suffix}" if family else suffix


def _derive_aligned_family_metrics(
    table: dict[str, Any],
    *,
    existing: set[tuple[str | None, str | None]],
    domain_id: str | None = None,
) -> list[dict[str, Any]]:
    cols = [str(col) for col in (table.get("eligible_numeric_columns") or []) if str(col or "").strip()]
    if not cols:
        return []
    canonical_time_col = _pick_canonical_time_column(table, domain_id)
    ranked_breakdowns = _rank_breakdown_columns(table, domain_id)
    direct_productivity: dict[str | None, str] = {}
    production_cols: dict[str | None, str] = {}
    hour_cols: dict[str | None, str] = {}
    for col in cols:
        family, remainder = _extract_kpi_family_parts(col)
        if "productivity" in remainder or remainder == "productivity":
            direct_productivity[family] = col
        if "production" in remainder:
            production_cols[family] = col
        if "net_hours" in remainder or remainder.endswith("hours") or remainder.endswith("hour"):
            hour_cols[family] = col
    derived: list[dict[str, Any]] = []
    for family in set(production_cols) | set(hour_cols) | set(direct_productivity):
        family_label = family or "base"
        direct_col = direct_productivity.get(family)
        if direct_col:
            metric_name = _family_metric_name(family, "productivity")
            key = (table.get("name"), metric_name)
            if key not in existing:
                derived.append(
                    {
                        "metric_name": metric_name,
                        "formula": f"AVG({direct_col})",
                        "base_table": table.get("name"),
                        "metric_type": "avg",
                        "metric_intent": "productivity",
                        "measure_confidence": 0.97,
                        "is_executive_kpi": True,
                        "metric_source": "family_direct",
                        "preferred_time_column": canonical_time_col,
                        "preferred_breakdowns": ranked_breakdowns[:4],
                        "metric_priority": 2200,
                        "eligible_measure": True,
                        "eligibility_reason": "direct_family_productivity_column",
                        "family_name": family_label,
                        "family_role": "productivity",
                    }
                )
                existing.add(key)
        prod_col = production_cols.get(family)
        hour_col = hour_cols.get(family)
        if prod_col and hour_col:
            metric_name = _family_metric_name(family, "productivity")
            key = (table.get("name"), metric_name)
            if key in existing:
                continue
            derived.append(
                {
                    "metric_name": metric_name,
                    "formula": f"SUM({prod_col}) / NULLIF(SUM({hour_col}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "derived",
                    "metric_intent": "productivity",
                    "measure_confidence": 0.92,
                    "is_executive_kpi": True,
                    "metric_source": "family_derived",
                    "preferred_time_column": canonical_time_col,
                    "preferred_breakdowns": ranked_breakdowns[:4],
                    "metric_priority": 2100,
                    "eligible_measure": True,
                    "eligibility_reason": "aligned_family_ratio",
                    "family_name": family_label,
                    "family_role": "productivity",
                    "derived_from_metrics": [prod_col, hour_col],
                }
            )
            existing.add(key)
    return derived


def _load_domain_templates(domain_id: str | None) -> list[dict[str, Any]]:
    if not domain_id:
        return []
    try:
        pack = load_pack(f"packs/{domain_id}")
    except Exception:
        return []
    templates = (pack.get("metric_templates") or {}).get("templates") or []
    return [t for t in templates if isinstance(t, dict) and t.get("name")]


def _dashboard_preferences(domain_id: str | None) -> dict[str, Any]:
    if not domain_id:
        return {}
    try:
        pack = load_pack(f"packs/{domain_id}")
    except Exception:
        return {}
    policies = pack.get("policies") or {}
    prefs = policies.get("dashboard_preferences") or {}
    return prefs if isinstance(prefs, dict) else {}


def _kpi_priority_hints(domain_id: str | None) -> dict[str, float]:
    prefs = _dashboard_preferences(domain_id)
    raw = prefs.get("kpi_priority_hints") or {}
    merged = dict(DEFAULT_KPI_PRIORITY_HINTS)
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                merged[str(key).lower()] = float(value)
            except (TypeError, ValueError):
                continue
    return merged


def _time_priority_columns(domain_id: str | None) -> list[str]:
    prefs = _dashboard_preferences(domain_id)
    raw = prefs.get("time_priority_columns") or []
    configured = [str(item).strip().lower() for item in raw if str(item or "").strip()]
    ordered: list[str] = []
    seen: set[str] = set()
    for item in configured + DEFAULT_TIME_PRIORITY_COLUMNS:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _breakdown_priority_tokens(domain_id: str | None) -> list[str]:
    prefs = _dashboard_preferences(domain_id)
    raw = prefs.get("breakdown_priority_tokens") or []
    configured = [str(item).strip().lower() for item in raw if str(item or "").strip()]
    ordered: list[str] = []
    seen: set[str] = set()
    for item in configured + DEFAULT_BREAKDOWN_PRIORITY_TOKENS:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _breakdown_allowlist(domain_id: str | None) -> set[str]:
    prefs = _dashboard_preferences(domain_id)
    raw = prefs.get("breakdown_allowlist") or []
    return {str(item).strip().lower() for item in raw if str(item or "").strip()}


def _breakdown_denylist(domain_id: str | None) -> set[str]:
    prefs = _dashboard_preferences(domain_id)
    raw = prefs.get("breakdown_denylist") or []
    return {str(item).strip().lower() for item in raw if str(item or "").strip()}


def _max_breakdown_uniqueness_ratio(domain_id: str | None) -> float:
    prefs = _dashboard_preferences(domain_id)
    raw = prefs.get("max_breakdown_uniqueness_ratio", 0.85)
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.85


def _exclude_identifier_breakdowns(domain_id: str | None) -> bool:
    prefs = _dashboard_preferences(domain_id)
    raw = prefs.get("exclude_identifier_dimensions_from_charts", True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _propose_template_metrics(profiling: dict[str, Any], domain_id: str | None) -> list[dict[str, Any]]:
    templates = _load_domain_templates(domain_id)
    if not templates:
        return []
    result: list[dict[str, Any]] = []
    for template in templates:
        tname = str(template.get("name") or "").strip().lower()
        ttype = str(template.get("type") or "").strip().lower()
        for table in profiling.get("tables", []):
            table_name = table.get("name")
            if not table_name:
                continue
            production_cols = _eligible_cols_by_token(table, ["production", "sales", "volume"])
            hours_cols = _eligible_cols_by_token(table, ["hour", "hours", "time", "net"])
            rejection_cols = _eligible_cols_by_token(table, ["reject", "rejection", "failure"])
            handled_cols = _eligible_cols_by_token(table, ["handled", "total", "count"])
            if tname.startswith("production"):
                if not production_cols:
                    continue
                pcol = production_cols[0]
                result.append(
                    {
                        "metric_name": tname,
                        "formula": f"SUM({pcol})",
                        "base_table": table_name,
                        "metric_type": "sum",
                        "metric_intent": "volume",
                        "semantic_role": "measure_additive",
                        "measure_confidence": 0.92,
                        "is_executive_kpi": True,
                        "metric_source": "template",
                    }
                )
            elif tname == "utilization_pct":
                if not hours_cols:
                    continue
                num = hours_cols[0]
                den = None
                for col in hours_cols[1:]:
                    if "total" in str(col).lower() or "available" in str(col).lower():
                        den = col
                        break
                if not den:
                    den = hours_cols[1] if len(hours_cols) > 1 else None
                if not den:
                    continue
                result.append(
                    {
                        "metric_name": tname,
                        "formula": f"(SUM({num}) / NULLIF(SUM({den}), 0)) * 100.0",
                        "base_table": table_name,
                        "metric_type": "ratio",
                        "metric_intent": "utilization",
                        "semantic_role": "measure_ratio_component",
                        "measure_confidence": 0.88,
                        "is_executive_kpi": True,
                        "metric_source": "template",
                    }
                )
            elif tname == "rejection_rate_pct":
                if not rejection_cols or not handled_cols:
                    continue
                rcol = rejection_cols[0]
                hcol = handled_cols[0]
                result.append(
                    {
                        "metric_name": tname,
                        "formula": f"(SUM({rcol}) / NULLIF(SUM({hcol}), 0)) * 100.0",
                        "base_table": table_name,
                        "metric_type": "ratio",
                        "metric_intent": "quality",
                        "semantic_role": "measure_ratio_component",
                        "measure_confidence": 0.9,
                        "is_executive_kpi": True,
                        "metric_source": "template",
                    }
                )
            elif tname == "productivity_avg":
                if production_cols and hours_cols:
                    pcol = production_cols[0]
                    hcol = hours_cols[0]
                    result.append(
                        {
                            "metric_name": tname,
                            "formula": f"SUM({pcol}) / NULLIF(SUM({hcol}), 0)",
                            "base_table": table_name,
                            "metric_type": "ratio",
                            "metric_intent": "productivity",
                            "semantic_role": "measure_ratio_component",
                            "measure_confidence": 0.87,
                            "is_executive_kpi": True,
                            "metric_source": "template",
                        }
                    )
                elif production_cols and ttype in {"avg", "average"}:
                    pcol = production_cols[0]
                    result.append(
                        {
                            "metric_name": tname,
                            "formula": f"AVG({pcol})",
                            "base_table": table_name,
                            "metric_type": "avg",
                            "metric_intent": "productivity",
                            "semantic_role": "measure_non_additive",
                            "measure_confidence": 0.8,
                            "is_executive_kpi": True,
                            "metric_source": "template",
                        }
                    )
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for metric in result:
        key = (metric.get("base_table"), metric.get("metric_name"))
        if key not in dedup:
            dedup[key] = metric
    return list(dedup.values())


def _extract_table_candidates(schema_payload: dict) -> list[Any]:
    # Supports multiple payload shapes:
    # 1) {"tables":[...]}
    # 2) {"schemas":[{"tables":[...]}]}
    # 3) {"connections":[{"databases":[{"schemas":[{"tables":[...]}]}]}]}
    tables: list[Any] = []
    if isinstance(schema_payload.get("tables"), list):
        tables.extend(schema_payload.get("tables") or [])
    for schema in schema_payload.get("schemas", []) or []:
        if isinstance(schema, dict) and isinstance(schema.get("tables"), list):
            tables.extend(schema.get("tables") or [])
    for connection in schema_payload.get("connections", []) or []:
        if not isinstance(connection, dict):
            continue
        for database in connection.get("databases", []) or []:
            if not isinstance(database, dict):
                continue
            for schema in database.get("schemas", []) or []:
                if isinstance(schema, dict) and isinstance(schema.get("tables"), list):
                    tables.extend(schema.get("tables") or [])
    return tables


def build_schema_graph(schema_payload: dict) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    tables = []
    for table in _extract_table_candidates(schema_payload):
        if isinstance(table, str):
            table_name = table
            table_columns = []
        elif isinstance(table, dict):
            table_name = table.get("table") or table.get("name") or table.get("table_name")
            table_columns = table.get("columns", []) or []
        else:
            continue
        columns = []
        for col in table_columns:
            col_name = col.get("name") or col.get("column") or col.get("column_name")
            col_type = col.get("data_type") or col.get("type") or col.get("column_type")
            columns.append(
                {
                    "name": col_name,
                    "data_type": str(col_type or "").lower(),
                }
            )
        if table_name:
            tables.append({"name": table_name, "columns": columns})
    if not tables:
        logger.warning("build_schema_graph: no tables detected in schema_payload")
    return {"tables": tables}


def enrich_schema_graph_columns(settings: Settings, schema_graph: dict[str, Any], schema_name: str) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    tables = list(schema_graph.get("tables", []) or [])
    for table in tables:
        name = table.get("name")
        if not name:
            continue
        existing = list(table.get("columns", []) or [])
        if existing:
            continue
        try:
            col_rows = run_query(
                settings,
                """
                SELECT column_name, data_type
                  FROM information_schema.columns
                 WHERE table_schema = %s
                   AND table_name = %s
                 ORDER BY ordinal_position
                """,
                [schema_name, name],
            )
            table["columns"] = [
                {
                    "name": row.get("column_name"),
                    "data_type": str(row.get("data_type") or "").lower(),
                }
                for row in col_rows
                if row.get("column_name")
            ]
        except Exception:
            logger.warning("enrich_schema_graph_columns: failed loading column metadata %s.%s", schema_name, name)
    return {"tables": tables}


def profile_tables(settings: Settings, schema_graph: dict[str, Any], schema_name: str) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    profiling: dict[str, Any] = {"tables": []}
    for table in schema_graph.get("tables", []):
        name = table.get("name")
        if not name:
            continue
        columns = list(table.get("columns", []) or [])
        if not columns:
            try:
                col_rows = run_query(
                    settings,
                    """
                    SELECT column_name, data_type
                      FROM information_schema.columns
                     WHERE table_schema = %s
                       AND table_name = %s
                     ORDER BY ordinal_position
                    """,
                    [schema_name, name],
                )
                columns = [
                    {
                        "name": row.get("column_name"),
                        "data_type": str(row.get("data_type") or "").lower(),
                    }
                    for row in col_rows
                    if row.get("column_name")
                ]
            except Exception:
                logger.warning("profile_tables: failed loading column metadata %s.%s", schema_name, name)
        numeric = [c["name"] for c in columns if c.get("data_type") in NUMERIC_TYPES]
        time_cols = [c["name"] for c in columns if c.get("data_type") in TIME_TYPES]
        categorical = [c["name"] for c in columns if c.get("data_type") not in NUMERIC_TYPES | TIME_TYPES]
        samples: dict[str, list[Any]] = {}
        candidate_keys: list[dict[str, Any]] = []
        key_profile_map: dict[str, dict[str, Any]] = {}
        column_semantics: list[dict[str, Any]] = []
        row_count = None
        try:
            rows = run_query(
                settings,
                f"SELECT COUNT(*) AS cnt FROM {_qident(schema_name)}.{_qident(name)}",
                [],
            )
            row_count = rows[0]["cnt"] if rows else None
        except Exception:
            row_count = None
        logger.info(
            "profile_tables | table=%s row_count=%s numeric=%s time=%s categorical=%s",
            name,
            row_count,
            len(numeric),
            len(time_cols),
            len(categorical),
        )
        # sample a few categorical values for heuristics
        for col in categorical[:5]:
            try:
                sample_rows = run_query(
                    settings,
                    (
                        f"SELECT DISTINCT {_qident(col)} AS value "
                        f"FROM {_qident(schema_name)}.{_qident(name)} "
                        f"WHERE {_qident(col)} IS NOT NULL LIMIT 5000"
                    ),
                    [],
                )
                samples[col] = [r["value"] for r in sample_rows]
            except Exception:
                logger.warning("profile_tables: failed sampling %s.%s", name, col)
                samples[col] = []
        # candidate key profiling for id/code columns
        key_cols = [
            c.get("name")
            for c in columns
            if c.get("name")
            and (str(c.get("name")).lower().endswith("_id") or str(c.get("name")).lower().endswith("_code"))
        ]
        for col in key_cols:
            try:
                distinct_rows = run_query(
                    settings,
                    (
                        f"SELECT COUNT(DISTINCT {_qident(col)}) AS distinct_cnt "
                        f"FROM {_qident(schema_name)}.{_qident(name)}"
                    ),
                    [],
                )
                distinct_cnt = distinct_rows[0]["distinct_cnt"] if distinct_rows else None
                candidate_keys.append(
                    {
                        "column": col,
                        "distinct_count": distinct_cnt,
                        "row_count": row_count,
                        "uniqueness_ratio": (distinct_cnt / row_count) if row_count and distinct_cnt is not None else None,
                    }
                )
                key_profile_map[col] = candidate_keys[-1]
            except Exception:
                logger.warning("profile_tables: failed distinct count %s.%s", name, col)
        for col in columns:
            col_name = col.get("name")
            if not col_name:
                continue
            data_type = str(col.get("data_type") or "").lower()
            semantic_role = _classify_column_semantic_role(str(col_name), data_type)
            uniqueness_ratio = (key_profile_map.get(col_name) or {}).get("uniqueness_ratio")
            eligible_measure, eligibility_reason = _is_measure_eligible(
                col_name=str(col_name),
                data_type=data_type,
                semantic_role=semantic_role,
                uniqueness_ratio=uniqueness_ratio,
            )
            column_semantics.append(
                {
                    "name": col_name,
                    "data_type": data_type,
                    "semantic_role": semantic_role,
                    "eligible_measure": eligible_measure,
                    "eligibility_reason": eligibility_reason,
                    "uniqueness_ratio": uniqueness_ratio,
                }
            )
        eligible_numeric_columns = [
            c.get("name")
            for c in column_semantics
            if c.get("eligible_measure") and c.get("data_type") in NUMERIC_TYPES
        ]
        profiling["tables"].append(
            {
                "name": name,
                "row_count": row_count,
                "numeric_columns": numeric,
                "eligible_numeric_columns": eligible_numeric_columns,
                "time_columns": time_cols,
                "categorical_columns": categorical,
                "sample_values": samples,
                "candidate_keys": candidate_keys,
                "column_semantics": column_semantics,
            }
        )
    return profiling


def extract_context(settings: Settings, context_text: str | None, schema_graph: dict[str, Any]) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    if not context_text:
        # infer glossary/ontology hints from schema alone
        glossary_terms = []
        context_entities = []
        for table in schema_graph.get("tables", []):
            tname = table.get("name")
            if tname:
                term = tname.replace("_", " ")
                glossary_terms.append(
                    {"term": term, "definition": None, "synonyms": [tname], "abbreviations": []}
                )
                context_entities.append(term)
            for col in table.get("columns", []):
                cname = col.get("name")
                if not cname:
                    continue
                term = cname.replace("_", " ")
                glossary_terms.append(
                    {"term": term, "definition": None, "synonyms": [cname], "abbreviations": []}
                )
                context_entities.append(term)
        if not glossary_terms:
            logger.warning("extract_context: no glossary terms inferred from schema")
        return {
            "context_entities": context_entities,
            "hierarchy_hints": [],
            "glossary_terms": glossary_terms,
            "metric_overrides": [],
        }
    tables_and_columns = ", ".join(
        [
            f"{t.get('name')}: {', '.join([c.get('name') for c in t.get('columns', []) if c.get('name')])}"
            for t in schema_graph.get("tables", [])
        ]
    )
    logger.info(
        "extract_context.start | context_chars=%s schema_tables=%s",
        len(context_text or ""),
        len(schema_graph.get("tables", []) or []),
    )
    logger.info(
        "extract_context.runtime | semantic_extraction_file=%s prompt_builder=%s",
        getattr(semantic_extraction, "__file__", None),
        "_build_prompt" if hasattr(semantic_extraction, "_build_prompt") else "_render_prompt" if hasattr(semantic_extraction, "_render_prompt") else "missing",
    )
    try:
        contract = extract_semantic_contract(settings, context_text, tables_and_columns=tables_and_columns)
    except Exception:
        logger.exception(
            "extract_context.semantic_contract_failed | context_chars=%s schema_tables=%s",
            len(context_text or ""),
            len(schema_graph.get("tables", []) or []),
        )
        raise
    glossary_terms = contract.get("business_terms", [])
    context_entities = [term.get("term") for term in glossary_terms if term.get("term")]
    hierarchy_hints = []
    for line in context_text.splitlines():
        if ">" in line:
            hierarchy_hints.append(line.strip())
    if not glossary_terms:
        logger.warning("extract_context: context_text provided but no glossary_terms returned")
    metric_overrides = _extract_metric_overrides(context_text, schema_graph)
    logger.info(
        "extract_context.completed | entities=%s glossary_terms=%s hierarchy_hints=%s metric_overrides=%s",
        len(context_entities),
        len(glossary_terms),
        len(hierarchy_hints),
        len(metric_overrides),
    )
    return {
        "context_entities": context_entities,
        "hierarchy_hints": hierarchy_hints,
        "glossary_terms": glossary_terms,
        "metric_overrides": metric_overrides,
    }


def _extract_formula_identifiers(formula: str | None, base_table: str | None = None) -> set[str]:
    text = str(formula or "")
    if not text:
        return set()
    refs = {match for match in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', text)}
    bare_tokens = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", text)
    for token in bare_tokens:
        lower = token.lower()
        if lower in _SQL_IDENTIFIER_IGNORE:
            continue
        if base_table and lower == str(base_table).lower():
            continue
        refs.add(token)
    return refs


def validate_metric_candidates(
    candidates: list[dict[str, Any]] | None,
    profiling: dict[str, Any],
    domain_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    profiling_tables = {str(t.get("name") or "").strip(): t for t in profiling.get("tables", []) if t.get("name")}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates or []:
        metric_name = _sanitize_metric_identifier(candidate.get("metric_name") or candidate.get("display_name"))
        base_table = str(candidate.get("base_table") or "").strip()
        formula = str(candidate.get("formula") or candidate.get("sql_expression") or "").strip()
        if not metric_name or not base_table or not formula:
            rejected.append(
                {
                    "candidate": candidate,
                    "reason": "missing_required_fields",
                }
            )
            continue
        table = profiling_tables.get(base_table)
        if not table:
            rejected.append({"candidate": candidate, "reason": "unknown_base_table"})
            continue
        all_columns = set(
            list(table.get("numeric_columns") or [])
            + list(table.get("time_columns") or [])
            + list(table.get("categorical_columns") or [])
        )
        missing_formula_columns = sorted(
            {
                ref
                for ref in _extract_formula_identifiers(formula, base_table=base_table)
                if ref not in all_columns
            }
        )
        if missing_formula_columns:
            rejected.append(
                {
                    "candidate": candidate,
                    "reason": "unknown_formula_columns",
                    "missing_columns": missing_formula_columns,
                }
            )
            continue
        preferred_time_column = str(candidate.get("preferred_time_column") or candidate.get("time_column") or "").strip() or None
        if preferred_time_column and preferred_time_column not in all_columns:
            rejected.append(
                {
                    "candidate": candidate,
                    "reason": "unknown_time_column",
                    "time_column": preferred_time_column,
                }
            )
            continue
        preferred_breakdowns = [
            str(col)
            for col in (candidate.get("preferred_dimensions") or candidate.get("preferred_breakdowns") or [])
            if str(col or "").strip()
        ]
        valid_breakdowns = [col for col in preferred_breakdowns if col in all_columns]
        canonical_time_col = preferred_time_column or _pick_canonical_time_column(table, domain_id)
        ranked_breakdowns = valid_breakdowns or _rank_breakdown_columns(table, domain_id)[:3]
        metric_type = (
            candidate.get("metric_type")
            or _infer_metric_type_from_formula(formula, metric_name)
        )
        key = (base_table, metric_name)
        if key in seen:
            rejected.append({"candidate": candidate, "reason": "duplicate_metric"})
            continue
        seen.add(key)
        accepted.append(
            {
                "metric_name": metric_name,
                "display_name": candidate.get("display_name") or metric_name.replace("_", " ").title(),
                "description": candidate.get("description"),
                "formula": formula,
                "base_table": base_table,
                "metric_type": metric_type,
                "metric_intent": candidate.get("metric_intent") or _derive_metric_intent(metric_name),
                "measure_confidence": max(
                    0.5,
                    _coerce_confidence(candidate.get("confidence") or candidate.get("measure_confidence") or 0.88),
                ),
                "is_executive_kpi": bool(candidate.get("is_executive_kpi", True)),
                "metric_source": candidate.get("metric_source") or "context_llm",
                "preferred_time_column": canonical_time_col,
                "preferred_breakdowns": ranked_breakdowns[:3],
                "metric_priority": int(candidate.get("metric_priority") or 3000),
                "grain": candidate.get("grain") or ("day" if canonical_time_col else None),
                "eligible_measure": True,
                "eligibility_reason": "context_llm_validated",
                "validation_status": "accepted",
                "validation_details": {
                    "base_table": base_table,
                    "resolved_time_column": canonical_time_col,
                    "resolved_breakdowns": ranked_breakdowns[:3],
                },
                "llm_rationale": candidate.get("rationale"),
                "provenance": {
                    "derivation_source": "context_text",
                    "derivation_method": candidate.get("derivation_method") or "llm_proposed",
                    "validation_status": "accepted",
                },
            }
        )
    return accepted, rejected


def propose_ontology(
    context_entities: list[str] | None,
    hierarchy_hints: list[str] | None,
    glossary_terms: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    concepts: list[str] = []
    seen = set()
    for name in (context_entities or []):
        if name and name.lower() not in seen:
            seen.add(name.lower())
            concepts.append(name)
    for term in (glossary_terms or []):
        name = term.get("term")
        if name and name.lower() not in seen:
            seen.add(name.lower())
            concepts.append(name)

    hierarchy_edges: list[dict[str, Any]] = []
    for hint in (hierarchy_hints or []):
        if ">" not in hint:
            continue
        parts = [part.strip() for part in hint.split(">") if part.strip()]
        for idx in range(len(parts) - 1):
            hierarchy_edges.append(
                {
                    "parent": parts[idx],
                    "child": parts[idx + 1],
                    "confidence": 0.6,
                    "source": "context",
                }
            )
            for part in (parts[idx], parts[idx + 1]):
                if part.lower() not in seen:
                    seen.add(part.lower())
                    concepts.append(part)

    synonym_edges: list[dict[str, Any]] = []
    for term in (glossary_terms or []):
        head = term.get("term")
        if not head:
            continue
        for syn in (term.get("synonyms") or []) + (term.get("abbreviations") or []):
            if not syn:
                continue
            synonym_edges.append(
                {
                    "term": head,
                    "synonym": syn,
                    "confidence": 0.7,
                    "source": "glossary",
                }
            )

    if not concepts and not synonym_edges and not hierarchy_edges:
        logger.warning("propose_ontology: no concepts inferred")
    return {
        "concepts": concepts,
        "hierarchy_edges": hierarchy_edges,
        "synonym_edges": synonym_edges,
    }


def propose_joins(schema_graph: dict[str, Any], profiling: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    joins = []
    tables = schema_graph.get("tables", [])
    profiling_map = {t.get("name"): t for t in (profiling or {}).get("tables", [])}
    for left in tables:
        left_cols = {c.get("name") for c in left.get("columns", [])}
        for right in tables:
            if left is right:
                continue
            right_cols = {c.get("name") for c in right.get("columns", [])}
            common = [c for c in left_cols & right_cols if c and (c.endswith("_id") or c.endswith("_code"))]
            for col in common:
                confidence = 0.6
                reason = "name_match"
                relationship = "many_to_many"
                cardinality = None
                overlap_ratio = None
                left_sample_count = 0
                right_sample_count = 0
                # boost confidence if sample overlap is high
                left_profile = profiling_map.get(left.get("name")) or {}
                right_profile = profiling_map.get(right.get("name")) or {}
                left_samples = set((left_profile.get("sample_values") or {}).get(col) or [])
                right_samples = set((right_profile.get("sample_values") or {}).get(col) or [])
                left_sample_count = len(left_samples)
                right_sample_count = len(right_samples)
                if left_samples and right_samples:
                    overlap_ratio = len(left_samples & right_samples) / max(
                        1, min(len(left_samples), len(right_samples))
                    )
                    if overlap_ratio >= 0.5:
                        confidence = 0.8
                        reason = "sample_overlap"
                # boost if left column looks unique (candidate key)
                left_unique = False
                right_unique = False
                for key in (left_profile.get("candidate_keys") or []):
                    if key.get("column") == col and (key.get("uniqueness_ratio") or 0) >= 0.9:
                        left_unique = True
                for key in (right_profile.get("candidate_keys") or []):
                    if key.get("column") == col and (key.get("uniqueness_ratio") or 0) >= 0.9:
                        right_unique = True
                if left_unique and not right_unique:
                    relationship = "one_to_many"
                    cardinality = "left_one_right_many"
                    confidence = max(confidence, 0.85)
                    reason = "candidate_key_left"
                elif right_unique and not left_unique:
                    relationship = "many_to_one"
                    cardinality = "left_many_right_one"
                    confidence = max(confidence, 0.85)
                    reason = "candidate_key_right"
                elif left_unique and right_unique:
                    relationship = "one_to_one"
                    cardinality = "one_to_one"
                    confidence = max(confidence, 0.8)
                    reason = "candidate_keys_both"
                joins.append(
                    {
                        "left_table": left.get("name"),
                        "right_table": right.get("name"),
                        "left_key": col,
                        "right_key": col,
                        "confidence": confidence,
                        "reason": reason,
                        "relationship": relationship,
                        "cardinality": cardinality,
                        "overlap_ratio": overlap_ratio,
                        "left_sample_count": left_sample_count,
                        "right_sample_count": right_sample_count,
                    }
                )
    return joins


def propose_metrics(
    profiling: dict[str, Any],
    domain_id: str | None = None,
    metric_overrides: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    metrics = []
    profiling_tables = {str(t.get("name") or "").strip(): t for t in profiling.get("tables", []) if t.get("name")}
    kpi_priority_hints = _kpi_priority_hints(domain_id)
    for metric in metric_overrides or []:
        base_table = str(metric.get("base_table") or "").strip()
        metric_name = str(metric.get("metric_name") or "").strip()
        formula = str(metric.get("formula") or "").strip()
        if not base_table or not metric_name or not formula:
            continue
        table = profiling_tables.get(base_table) or {}
        canonical_time_col = str(metric.get("preferred_time_column") or _pick_canonical_time_column(table, domain_id) or "").strip() or None
        ranked_breakdowns = _rank_breakdown_columns(table, domain_id)
        metrics.append(
            {
                "metric_name": metric_name,
                "display_name": metric.get("display_name") or metric_name.replace("_", " ").title(),
                "description": metric.get("description"),
                "formula": formula,
                "base_table": base_table,
                "metric_type": metric.get("metric_type") or _infer_metric_type_from_formula(formula, metric_name),
                "metric_intent": _derive_metric_intent(metric_name),
                "measure_confidence": metric.get("measure_confidence") or 0.99,
                "is_executive_kpi": True,
                "metric_source": metric.get("metric_source") or "context_override",
                "preferred_time_column": canonical_time_col,
                "preferred_breakdowns": metric.get("preferred_breakdowns") or ranked_breakdowns[:3],
                "metric_priority": metric.get("metric_priority") or 5000,
                "grain": metric.get("grain"),
                "reference_sql": metric.get("reference_sql"),
                "eligible_measure": True,
                "eligibility_reason": "context_override",
            }
        )
    metrics.extend(_propose_template_metrics(profiling, domain_id))
    existing = {(m.get("base_table"), m.get("metric_name")) for m in metrics}
    for table in profiling.get("tables", []):
        semantic_map = {c.get("name"): c for c in (table.get("column_semantics") or []) if c.get("name")}
        numeric_cols = (table.get("eligible_numeric_columns") or [])[:10]
        canonical_time_col = _pick_canonical_time_column(table, domain_id)
        ranked_breakdowns = _rank_breakdown_columns(table, domain_id)
        metrics.extend(
            _derive_aligned_family_metrics(
                table,
                existing=existing,
                domain_id=domain_id,
            )
        )
        preferred_cols = sorted(
            [str(col) for col in (table.get("eligible_numeric_columns") or []) if str(col or "").strip()],
            key=lambda col: (
                -max((bonus for token, bonus in kpi_priority_hints.items() if token in col.lower()), default=0),
                col,
            ),
        )
        for col in preferred_cols[:5]:
            lower = col.lower()
            if not any(token in lower for token in kpi_priority_hints):
                continue
            metric_name, formula, metric_type = _canonical_metric_formula(col, domain_id)
            if (table.get("name"), metric_name) in existing:
                continue
            metrics.append(
                {
                    "metric_name": metric_name,
                    "formula": formula,
                    "base_table": table.get("name"),
                    "semantic_role": (semantic_map.get(col) or {}).get("semantic_role"),
                    "eligible_measure": True,
                    "eligibility_reason": (semantic_map.get(col) or {}).get("eligibility_reason") or "canonical_kpi_column",
                    "metric_type": metric_type,
                    "metric_intent": _derive_metric_intent(col),
                    "measure_confidence": 0.96,
                    "is_executive_kpi": True,
                    "metric_source": "canonical",
                    "preferred_time_column": canonical_time_col,
                    "preferred_breakdowns": ranked_breakdowns[:3],
                    "metric_priority": 1000,
                }
            )
            existing.add((table.get("name"), metric_name))
        for col in numeric_cols:
            semantic_col = semantic_map.get(col) or {}
            metric_name = f"sum_{col}"
            if (table.get("name"), metric_name) in existing:
                continue
            metrics.append(
                {
                    "metric_name": metric_name,
                    "formula": f"SUM({col})",
                    "base_table": table.get("name"),
                    "semantic_role": semantic_col.get("semantic_role"),
                    "eligible_measure": True,
                    "eligibility_reason": semantic_col.get("eligibility_reason"),
                    "metric_type": "sum",
                    "metric_intent": _derive_metric_intent(col),
                    "measure_confidence": 0.72,
                    "is_executive_kpi": False,
                    "metric_source": "fallback",
                    "preferred_time_column": canonical_time_col,
                    "preferred_breakdowns": ranked_breakdowns[:3],
                    "metric_priority": 100,
                }
            )
            existing.add((table.get("name"), metric_name))
        # derived metrics (productivity / efficiency style)
        cols = set(table.get("eligible_numeric_columns", []) or [])
        production_cols = [c for c in cols if "production" in c]
        hours_cols = [c for c in cols if "hour" in c]
        family_aligned_present = any(
            str(metric.get("base_table") or "") == str(table.get("name") or "")
            and str(metric.get("metric_source") or "").startswith("family_")
            for metric in metrics
        )
        if production_cols and hours_cols and not family_aligned_present:
            prod_col = production_cols[0]
            hour_col = hours_cols[0]
            metric_name = f"productivity_{prod_col}_per_{hour_col}"
            if (table.get("name"), metric_name) in existing:
                metric_name = f"{metric_name}_derived"
            metrics.append(
                {
                    "metric_name": metric_name,
                    "formula": f"SUM({prod_col}) / NULLIF(SUM({hour_col}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "efficiency",
                    "eligible_measure": True,
                    "eligibility_reason": "derived_from_eligible_measures",
                    "metric_intent": "productivity",
                    "measure_confidence": 0.84,
                    "is_executive_kpi": True,
                    "metric_source": "derived",
                    "preferred_time_column": canonical_time_col,
                    "preferred_breakdowns": ranked_breakdowns[:3],
                    "metric_priority": 400,
                }
            )
            existing.add((table.get("name"), metric_name))
        handled_cols = [c for c in cols if "handled" in c]
        reject_cols = [c for c in cols if "rejection" in c or "reject" in c]
        if handled_cols and reject_cols:
            hcol = handled_cols[0]
            rcol = reject_cols[0]
            metric_name = f"rejection_rate_{rcol}_per_{hcol}"
            if (table.get("name"), metric_name) in existing:
                metric_name = f"{metric_name}_derived"
            metrics.append(
                {
                    "metric_name": metric_name,
                    "formula": f"SUM({rcol}) / NULLIF(SUM({hcol}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "rate",
                    "eligible_measure": True,
                    "eligibility_reason": "derived_from_eligible_measures",
                    "metric_intent": "quality",
                    "measure_confidence": 0.86,
                    "is_executive_kpi": True,
                    "metric_source": "derived",
                    "preferred_time_column": canonical_time_col,
                    "preferred_breakdowns": ranked_breakdowns[:3],
                    "metric_priority": 300,
                }
            )
            existing.add((table.get("name"), metric_name))
        # utilization metrics (run_time / total_time)
        time_cols = [c for c in cols if "time" in c or "hours" in c]
        run_cols = [c for c in time_cols if "run" in c or "net" in c]
        total_cols = [c for c in time_cols if "total" in c]
        if run_cols and total_cols:
            rcol = run_cols[0]
            tcol = total_cols[0]
            metric_name = f"utilization_{rcol}_per_{tcol}"
            if (table.get("name"), metric_name) in existing:
                metric_name = f"{metric_name}_derived"
            metrics.append(
                {
                    "metric_name": metric_name,
                    "formula": f"SUM({rcol}) / NULLIF(SUM({tcol}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "utilization",
                    "eligible_measure": True,
                    "eligibility_reason": "derived_from_eligible_measures",
                    "metric_intent": "utilization",
                    "measure_confidence": 0.84,
                    "is_executive_kpi": True,
                    "metric_source": "derived",
                    "preferred_time_column": canonical_time_col,
                    "preferred_breakdowns": ranked_breakdowns[:3],
                    "metric_priority": 300,
                }
            )
            existing.add((table.get("name"), metric_name))
        # yield metrics (good / total)
        good_cols = [c for c in cols if "good" in c or "pass" in c or "ok" in c]
        total_cols = [c for c in cols if "total" in c]
        if good_cols and total_cols:
            gcol = good_cols[0]
            tcol = total_cols[0]
            metric_name = f"yield_{gcol}_per_{tcol}"
            if (table.get("name"), metric_name) in existing:
                metric_name = f"{metric_name}_derived"
            metrics.append(
                {
                    "metric_name": metric_name,
                    "formula": f"SUM({gcol}) / NULLIF(SUM({tcol}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "yield",
                    "eligible_measure": True,
                    "eligibility_reason": "derived_from_eligible_measures",
                    "metric_intent": "quality",
                    "measure_confidence": 0.82,
                    "is_executive_kpi": True,
                    "metric_source": "derived",
                    "preferred_time_column": canonical_time_col,
                    "preferred_breakdowns": ranked_breakdowns[:3],
                    "metric_priority": 250,
                }
            )
            existing.add((table.get("name"), metric_name))
    metrics.sort(key=lambda metric: _metric_priority_score(metric, domain_id), reverse=True)
    return metrics


def classify_models(profiling: dict[str, Any]) -> list[dict[str, Any]]:
    classifications = []
    for table in profiling.get("tables", []):
        numeric_count = len(table.get("numeric_columns") or [])
        time_count = len(table.get("time_columns") or [])
        cat_count = len(table.get("categorical_columns") or [])
        score = numeric_count + time_count
        model_type = "fact" if score >= 3 else "dimension"
        classifications.append(
            {
                "table": table.get("name"),
                "model_type": model_type,
                "confidence": 0.6 if model_type == "fact" else 0.5,
                "numeric_columns": numeric_count,
                "time_columns": time_count,
                "categorical_columns": cat_count,
            }
        )
    return classifications


def propose_rollups(metrics: list[dict[str, Any]], profiling: dict[str, Any]) -> list[dict[str, Any]]:
    logger = logging.getLogger(__name__)
    rollups: list[dict[str, Any]] = []
    profiling_map = {t.get("name"): t for t in profiling.get("tables", [])}
    for metric in metrics:
        base_table = metric.get("base_table")
        metric_name = metric.get("metric_name")
        if not base_table or not metric_name:
            continue
        table_info = profiling_map.get(base_table) or {}
        time_cols = table_info.get("time_columns") or []
        cat_cols = table_info.get("categorical_columns") or []
        sample_values = table_info.get("sample_values") or {}
        if not time_cols:
            # heuristic: detect time-like categorical columns
            for col in cat_cols:
                samples = sample_values.get(col) or []
                if any(_is_date_like(v) for v in samples):
                    time_cols = [col]
                    break
        if not time_cols:
            logger.info("propose_rollups: no time column for %s", base_table)
            continue
        dimensions = [time_cols[0]]
        if cat_cols:
            # prefer a categorical column with some sample values
            preferred = None
            for col in cat_cols:
                if sample_values.get(col):
                    preferred = col
                    break
            dimensions.append(preferred or cat_cols[0])
        rollups.append(
            {
                "metric_name": metric_name,
                "dimensions": dimensions,
                "time_grain": "month",
            }
        )
    return rollups


def _is_date_like(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str,)):
        return any(ch.isdigit() for ch in value) and ("-" in value or "/" in value)
    return False


def _pick_dashboard_table(profiling: dict[str, Any]) -> dict[str, Any] | None:
    tables = profiling.get("tables", []) if profiling else []
    if not tables:
        return None
    scored = []
    for table in tables:
        numeric = table.get("eligible_numeric_columns") or []
        time_cols = table.get("time_columns") or []
        categorical = table.get("categorical_columns") or []
        if not numeric:
            continue
        score = 0
        if time_cols:
            score += 2
        if categorical:
            score += 1
        scored.append((score, table))
    if not scored:
        return tables[0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _pretty_name(value: str | None) -> str:
    if not value:
        return ""
    return str(value).replace("_", " ").strip().title()


def _contextual_dashboard_title(metric_name: str | None, table_name: str | None) -> str:
    metric_label = _pretty_name(metric_name or "KPI")
    table_label = _pretty_name(table_name)
    if table_label:
        return f"{table_label} Performance Overview"
    return f"{metric_label} Performance Dashboard"


def _contextual_chart_title(
    *,
    intent: str | None,
    metric_name: str | None,
    category_column: str | None,
    time_column: str | None,
    table_name: str | None,
    time_grain: str | None = None,
) -> str:
    metric_label = _pretty_name(metric_name or "Metric")
    category_label = _pretty_name(category_column)
    table_label = _pretty_name(table_name)
    if intent == "trend":
        if time_column:
            grain_label = _time_grain_label(time_grain)
            return f"{metric_label} by {grain_label}"
        return f"{metric_label} Trend"
    if intent == "multi_series":
        if category_label:
            grain_label = _time_grain_label(time_grain)
            return f"{metric_label} by {grain_label} and {category_label}"
        return f"{metric_label} Multi-Series Trend"
    if intent in {"breakdown", "join_breakdown"}:
        if category_label:
            return f"{metric_label} by {category_label}"
        if table_label:
            return f"{metric_label} Breakdown for {table_label}"
        return f"{metric_label} Breakdown"
    if intent == "share":
        if category_label:
            return f"{category_label} Share of {metric_label}"
        return f"{metric_label} Contribution Share"
    if table_label:
        return f"{metric_label} Overview for {table_label}"
    return f"{metric_label} Overview"


def build_dashboard_spec(
    metrics: list[dict[str, Any]],
    profiling: dict[str, Any],
    domain_id: str | None = None,
) -> dict[str, Any]:
    charts = []
    view_suggestions = []
    picked = _pick_dashboard_table(profiling)
    metric_col = None
    time_col = None
    category_col = None
    table_name = None
    primary_metric: dict[str, Any] | None = None
    if picked:
        table_name = picked.get("name")
        time_col = _pick_canonical_time_column(picked, domain_id)
        top_metrics = _top_metrics_for_table(metrics, table_name, limit=3, domain_id=domain_id)
        if top_metrics:
            primary_metric = top_metrics[0]
        breakdowns = _pick_chart_breakdowns(picked, primary_metric or {}, limit=3, domain_id=domain_id)
        category_col = breakdowns[0] if breakdowns else None

    metric_name = None
    metric_expr = None
    metric_intent = None
    if primary_metric:
        metric_name = primary_metric.get("metric_name")
        metric_expr = primary_metric.get("formula")
        metric_intent = primary_metric.get("metric_intent")
    elif metric_col:
        metric_name = f"sum_{metric_col}"
        metric_intent = _derive_metric_intent(metric_col)

    if table_name:
        view_suggestions.append(
            {
                "table": table_name,
                "time_column": time_col,
                "category_column": category_col,
                "metric_column": metric_col,
                "recommended_view": f"{table_name}_overview",
            }
        )
    # add additional suggested views for other fact-like tables
    for table in profiling.get("tables", []):
        if table.get("name") == table_name:
            continue
        if not (table.get("eligible_numeric_columns") and table.get("time_columns")):
            continue
        view_suggestions.append(
            {
                "table": table.get("name"),
                "time_column": (table.get("time_columns") or [None])[0],
                "category_column": (table.get("categorical_columns") or [None])[0],
                "metric_column": (table.get("eligible_numeric_columns") or [None])[0],
                "recommended_view": f"{table.get('name')}_overview",
            }
        )
    if not metric_name and metrics:
        metric_name = metrics[0].get("metric_name")
        metric_expr = metrics[0].get("formula")
        metric_intent = metrics[0].get("metric_intent")
    metric_name = metric_name or "metric"
    metric_intent = metric_intent or _derive_metric_intent(metric_name)

    if time_col:
        charts.append(
            {
                "type": "line",
                "intent": "trend",
                "title": _contextual_chart_title(
                    intent="trend",
                    metric_name=metric_name,
                    category_column=None,
                    time_column=time_col,
                    table_name=table_name,
                    time_grain="day",
                ),
                "metric": metric_name,
                "metric_intent": metric_intent,
                "table": table_name,
                "metric_column": metric_col,
                "metric_expr": metric_expr,
                "time_column": time_col,
                "time_grain": "day",
                "category_column": None,
            }
        )
        charts.append(
            {
                "type": "line",
                "intent": "trend",
                "title": _contextual_chart_title(
                    intent="trend",
                    metric_name=metric_name,
                    category_column=None,
                    time_column=time_col,
                    table_name=table_name,
                    time_grain="month",
                ),
                "metric": metric_name,
                "metric_intent": metric_intent,
                "table": table_name,
                "metric_column": metric_col,
                "metric_expr": metric_expr,
                "time_column": time_col,
                "time_grain": "month",
                "category_column": None,
            }
        )
    if category_col:
        charts.append(
            {
                "type": "bar",
                "intent": "breakdown",
                "title": _contextual_chart_title(
                    intent="breakdown",
                    metric_name=metric_name,
                    category_column=category_col,
                    time_column=time_col,
                    table_name=table_name,
                ),
                "metric": metric_name,
                "metric_intent": metric_intent,
                "table": table_name,
                "metric_column": metric_col,
                "metric_expr": metric_expr,
                "time_column": None,
                "category_column": category_col,
            }
        )
        charts.append(
            {
                "type": "pie",
                "intent": "share",
                "title": _contextual_chart_title(
                    intent="share",
                    metric_name=metric_name,
                    category_column=category_col,
                    time_column=time_col,
                    table_name=table_name,
                ),
                "metric": metric_name,
                "metric_intent": metric_intent,
                "table": table_name,
                "metric_column": metric_col,
                "metric_expr": metric_expr,
                "time_column": None,
                "category_column": category_col,
            }
        )
    dashboard_title = _contextual_dashboard_title(metric_name, table_name)
    return {
        "title": dashboard_title,
        "charts": charts,
        "view_suggestions": view_suggestions,
        "story": {
            "title": dashboard_title,
            "cards": [
                {"title": "Trend", "summary": "Track the KPI trend over time."},
                {"title": "Breakdown", "summary": "Compare categories to spot leaders."},
                {"title": "Share", "summary": "See contribution by category."},
            ],
        },
    }


def propose_chart_candidates(
    profiling: dict[str, Any],
    metrics: list[dict[str, Any]],
    join_edges: list[dict[str, Any]] | None = None,
    domain_id: str | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    metrics_by_table: dict[str, list[dict[str, Any]]] = {}
    for metric in metrics:
        base = metric.get("base_table")
        if not base:
            continue
        metrics_by_table.setdefault(base, []).append(metric)
    join_edges = join_edges or []
    for table in profiling.get("tables", []):
        table_name = table.get("name")
        if not table_name:
            continue
        samples = table.get("sample_values") or {}
        time_col = _pick_canonical_time_column(table, domain_id)
        approved_metrics = _top_metrics_for_table(metrics, table_name, limit=3, domain_id=domain_id)
        if not approved_metrics:
            candidates.append(
                {
                    "table": table_name,
                    "skipped": True,
                    "reason": "missing_approved_metric",
                    "semantic_validation": {
                        "status": "rejected",
                        "reason": "missing_metric_binding",
                    },
                }
            )
            continue
        for selected_metric in approved_metrics:
            metric_name = selected_metric.get("metric_name")
            metric_expr = selected_metric.get("formula")
            metric_intent = selected_metric.get("metric_intent") or _derive_metric_intent(metric_name)
            metric_col = None
            breakdown_cols = _pick_chart_breakdowns(table, selected_metric, limit=3, domain_id=domain_id)
            logger = logging.getLogger(__name__)
            logger.info(
                "agentic.chart.metric_selected | table=%s metric=%s priority=%s time_col=%s breakdowns=%s",
                table_name,
                metric_name,
                round(_metric_chart_priority(selected_metric, domain_id), 2),
                time_col,
                breakdown_cols,
            )
            if time_col:
                for time_grain in ("day", "month"):
                    candidates.append(
                        {
                            "type": "line",
                            "intent": "trend",
                            "title": _contextual_chart_title(
                                intent="trend",
                                metric_name=metric_name,
                                category_column=None,
                                time_column=time_col,
                                table_name=table_name,
                                time_grain=time_grain,
                            ),
                            "table": table_name,
                            "metric": metric_name,
                            "metric_intent": metric_intent,
                            "metric_column": metric_col,
                            "metric_expr": metric_expr,
                            "time_column": time_col,
                            "time_grain": time_grain,
                            "category_column": None,
                        }
                    )
            for best_cat in breakdown_cols:
                candidates.append(
                    {
                        "type": "bar",
                        "intent": "breakdown",
                        "title": _contextual_chart_title(
                            intent="breakdown",
                            metric_name=metric_name,
                            category_column=best_cat,
                            time_column=None,
                            table_name=table_name,
                        ),
                        "table": table_name,
                        "metric": metric_name,
                        "metric_intent": metric_intent,
                        "metric_column": metric_col,
                        "metric_expr": metric_expr,
                        "time_column": None,
                        "category_column": best_cat,
                    }
                )
            for best_cat in breakdown_cols:
                if len(samples.get(best_cat) or []) <= 10:
                    candidates.append(
                        {
                            "type": "pie",
                            "intent": "share",
                            "title": _contextual_chart_title(
                                intent="share",
                                metric_name=metric_name,
                                category_column=best_cat,
                                time_column=None,
                                table_name=table_name,
                            ),
                            "table": table_name,
                            "metric": metric_name,
                            "metric_intent": metric_intent,
                            "metric_column": metric_col,
                            "metric_expr": metric_expr,
                            "time_column": None,
                            "category_column": best_cat,
                        }
                    )
                    break
            if time_col:
                for col in breakdown_cols:
                    if len(samples.get(col) or []) <= 6:
                        candidates.append(
                            {
                                "type": "line",
                                "intent": "multi_series",
                                "title": _contextual_chart_title(
                                    intent="multi_series",
                                    metric_name=metric_name,
                                    category_column=col,
                                    time_column=time_col,
                                    table_name=table_name,
                                    time_grain="month",
                                ),
                                "table": table_name,
                                "metric": metric_name,
                                "metric_intent": metric_intent,
                                "metric_column": metric_col,
                                "metric_expr": metric_expr,
                                "time_column": time_col,
                                "time_grain": "month",
                                "category_column": col,
                            }
                        )
                        break
    # add join-driven candidates (dimension lookups)
    for edge in join_edges:
        if edge.get("relationship") in {"many_to_one", "one_to_many"}:
            left_table = edge.get("left_table")
            if not left_table:
                continue
            left_metrics = [
                m
                for m in (metrics_by_table.get(left_table, []) or [])
                if m.get("formula")
                and (m.get("is_executive_kpi") or m.get("metric_type") or m.get("eligible_measure"))
            ]
            if not left_metrics:
                continue
            left_metrics.sort(
                key=lambda m: (
                    1 if m.get("is_executive_kpi") else 0,
                    float(m.get("measure_confidence") or 0.0),
                ),
                reverse=True,
            )
            metric = left_metrics[0]
            candidates.append(
                {
                    "type": "bar",
                    "intent": "join_breakdown",
                    "title": _contextual_chart_title(
                        intent="join_breakdown",
                        metric_name=metric.get("metric_name"),
                        category_column=edge.get("left_key"),
                        time_column=None,
                        table_name=left_table,
                    ),
                    "table": left_table,
                    "metric": metric.get("metric_name"),
                    "metric_intent": metric.get("metric_intent") or _derive_metric_intent(metric.get("metric_name")),
                    "metric_column": None,
                    "metric_expr": metric.get("formula"),
                    "time_column": None,
                    "time_grain": None,
                    "category_column": edge.get("left_key"),
                }
            )
    return candidates


def select_charts(
    candidates: list[dict[str, Any]],
    min_charts: int = 4,
    max_charts: int = 8,
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    # score candidates
    scored = []
    for cand in candidates:
        if cand.get("skipped"):
            continue
        score = 0
        if cand.get("intent") == "trend":
            score += 3
            if cand.get("time_grain") == "day":
                score += 2
            elif cand.get("time_grain") == "month":
                score += 2
        if cand.get("intent") == "share":
            score += 2
        if cand.get("intent") == "breakdown":
            score += 2
        if cand.get("intent") == "multi_series":
            score += 3
        if cand.get("metric_expr"):
            score += 1
        if cand.get("category_column"):
            score += 1
        if cand.get("chart_source") == "llm_proposed":
            score += 1
        scored.append((score, cand))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict[str, Any]] = []
    seen = set()

    def _chart_key(cand: dict[str, Any]) -> tuple[Any, ...]:
        return (
            cand.get("table"),
            cand.get("metric"),
            cand.get("type"),
            cand.get("category_column"),
            cand.get("time_column"),
            cand.get("time_grain"),
        )

    def _try_add(cand: dict[str, Any]) -> bool:
        key = _chart_key(cand)
        if key in seen:
            return False
        if cand.get("intent") in {"breakdown", "join_breakdown"}:
            for existing in selected:
                if (
                    existing.get("intent") in {"breakdown", "join_breakdown"}
                    and existing.get("table") == cand.get("table")
                    and existing.get("metric") == cand.get("metric")
                    and existing.get("category_column") == cand.get("category_column")
                ):
                    return False
        if cand.get("intent") == "share":
            for existing in selected:
                if existing.get("intent") == "share" and existing.get("table") == cand.get("table") and existing.get("metric") == cand.get("metric"):
                    return False
        seen.add(key)
        selected.append(cand)
        return True

    trend_count = 0
    breakdown_count = 0
    share_count = 0

    for required_metric in ("total_production", "total_productivity"):
        for score, cand in scored:
            intent = cand.get("intent")
            if str(cand.get("metric") or "").strip().lower() != required_metric:
                continue
            if intent not in {"trend", "multi_series"}:
                continue
            if _try_add(cand):
                trend_count += 1
                break

    for score, cand in scored:
        intent = cand.get("intent")
        if trend_count < 2 and intent in {"trend", "multi_series"}:
            if _try_add(cand):
                trend_count += 1
        elif intent == "share" and share_count < 1:
            if _try_add(cand):
                share_count += 1
        elif breakdown_count < 4 and intent in {"breakdown", "join_breakdown"}:
            if _try_add(cand):
                breakdown_count += 1
        if len(selected) >= max_charts:
            break

    for score, cand in scored:
        if len(selected) >= max_charts:
            break
        _try_add(cand)
    if len(selected) < min_charts:
        # pad with remaining candidates
        for score, cand in scored:
            if cand in selected:
                continue
            selected.append(cand)
            if len(selected) >= min_charts:
                break
    return selected
