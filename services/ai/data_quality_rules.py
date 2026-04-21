from __future__ import annotations

from typing import Any
from datetime import date, datetime
import json
import logging
import os
import re
import urllib.request

from services.ai.config import Settings
from services.ai.data_quality_store import insert_quality_rule_result
from services.ai.db import ScopedConnection, run_query

logger = logging.getLogger(__name__)


def data_quality_rule_auto_approve_all_enabled() -> bool:
    value = str(os.getenv("DATA_QUALITY_RULE_AUTO_APPROVE_ALL", "")).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _sql_date_literal(value: date) -> str:
    return f"DATE '{value.isoformat()}'"


def _compile_date_bound_expression(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _sql_date_literal(value.date())
    if isinstance(value, date):
        return _sql_date_literal(value)
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"today", "current_date"}:
        return "CURRENT_DATE"
    if lowered == "yesterday":
        return "CURRENT_DATE - INTERVAL '1 day'"
    if lowered == "tomorrow":
        return "CURRENT_DATE + INTERVAL '1 day'"
    relative_match = re.match(
        r"^(?:today|current_date)\s*([+-])\s*(\d+)\s*(?:day|days)?$",
        lowered,
    )
    if relative_match:
        operator, magnitude = relative_match.groups()
        return f"CURRENT_DATE {operator} INTERVAL '{int(magnitude)} day'"
    try:
        return _sql_date_literal(date.fromisoformat(text))
    except ValueError:
        return None


def _build_date_range_predicate_parts(column_sql: str, condition: dict[str, Any]) -> tuple[list[str], list[str]]:
    predicates: list[str] = []
    notes: list[str] = []
    min_expr = _compile_date_bound_expression(condition.get("min_date"))
    max_expr = _compile_date_bound_expression(condition.get("max_date"))
    if condition.get("min_date") is not None:
        if min_expr:
            predicates.append(f"{column_sql} IS NOT NULL AND {column_sql}::date < {min_expr}")
        else:
            notes.append(f"Unsupported min_date expression: {condition.get('min_date')!r}")
    if condition.get("max_date") is not None:
        if max_expr:
            predicates.append(f"{column_sql} IS NOT NULL AND {column_sql}::date > {max_expr}")
        else:
            notes.append(f"Unsupported max_date expression: {condition.get('max_date')!r}")
    if condition.get("not_future"):
        predicates.append(f"{column_sql} IS NOT NULL AND {column_sql}::date > CURRENT_DATE")
    return predicates, notes


EXECUTABLE_RULE_TYPES = {
    "referential_integrity",
    "not_null",
    "not_blank",
    "email_pattern",
    "numeric_min",
    "numeric_max",
    "allowed_values",
    "regex_pattern",
    "unique",
    "composite_unique",
    "date_range",
    "freshness_sla",
    "conditional_required",
    "cross_column_consistency",
    "numeric_range",
    "length",
    "null_pct_threshold",
    "row_count_change_pct",
    "custom_sql",
}


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _schema_index(schema_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for table in schema_graph.get("tables") or []:
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        cols = {
            _norm(col.get("name")): str(col.get("name") or "").strip()
            for col in table.get("columns") or []
            if str(col.get("name") or "").strip()
        }
        indexed[_norm(table_name)] = {"name": table_name, "columns": cols}
    return indexed


def _resolve_table_column(
    schema_graph: dict[str, Any],
    table_hint: str | None,
    column_hint: str | None,
) -> tuple[str | None, str | None]:
    index = _schema_index(schema_graph)
    table_key = _norm(table_hint)
    column_key = _norm(column_hint)
    if table_key in index:
        table = index[table_key]
        col = table["columns"].get(column_key)
        return table["name"], col
    for _, table in index.items():
        col = table["columns"].get(column_key)
        if col and (not table_key or table_key in _norm(table["name"]) or _norm(table["name"]) in table_key):
            return table["name"], col
    return None, None


def _resolve_column(schema_graph: dict[str, Any], table_name: str | None, column_hint: str | None) -> str | None:
    table, column = _resolve_table_column(schema_graph, table_name, column_hint)
    return column if table else None


def _resolve_columns(schema_graph: dict[str, Any], table_name: str | None, columns: Any) -> list[str]:
    resolved: list[str] = []
    for column in columns or []:
        col = _resolve_column(schema_graph, table_name, str(column))
        if col:
            resolved.append(col)
    return resolved


def _has_any(condition_json: dict[str, Any], keys: set[str]) -> bool:
    return any(condition_json.get(key) is not None for key in keys)


def _schema_prompt(schema_graph: dict[str, Any]) -> list[dict[str, Any]]:
    tables = []
    for table in schema_graph.get("tables") or []:
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        tables.append(
            {
                "table_name": table_name,
                "columns": [
                    {
                        "column_name": str(col.get("name") or "").strip(),
                        "data_type": col.get("data_type"),
                    }
                    for col in table.get("columns") or []
                    if str(col.get("name") or "").strip()
                ],
            }
        )
    return tables


def _validate_llm_rule(rule: dict[str, Any], schema_graph: dict[str, Any]) -> dict[str, Any] | None:
    rule_type = str(rule.get("rule_type") or "").strip().lower()
    if rule_type not in EXECUTABLE_RULE_TYPES:
        return None
    table_name, column_name = _resolve_table_column(schema_graph, rule.get("table_name"), rule.get("column_name"))
    if not table_name:
        return None
    if rule_type not in {
        "referential_integrity",
        "custom_sql",
        "composite_unique",
        "conditional_required",
        "cross_column_consistency",
        "row_count_change_pct",
    } and not column_name:
        return None
    condition_json = rule.get("condition_json") if isinstance(rule.get("condition_json"), dict) else {}
    if rule_type == "numeric_min" and "min_value" not in condition_json:
        return None
    if rule_type == "numeric_max" and "max_value" not in condition_json:
        return None
    if rule_type == "allowed_values" and not condition_json.get("allowed_values"):
        return None
    if rule_type == "regex_pattern" and not str(condition_json.get("pattern") or "").strip():
        return None
    if rule_type == "composite_unique":
        columns = _resolve_columns(schema_graph, table_name, condition_json.get("columns") or rule.get("columns"))
        if len(columns) < 2:
            return None
        condition_json["columns"] = columns
    if rule_type == "date_range":
        if not _has_any(condition_json, {"min_date", "max_date", "not_future"}):
            return None
    if rule_type == "freshness_sla":
        if condition_json.get("max_lag_hours") is None:
            return None
    if rule_type == "conditional_required":
        when_col = _resolve_column(schema_graph, table_name, condition_json.get("when_column"))
        req_col = _resolve_column(schema_graph, table_name, condition_json.get("required_column") or rule.get("column_name"))
        values = condition_json.get("when_values")
        if values is None and condition_json.get("when_value") is not None:
            values = [condition_json.get("when_value")]
        if not when_col or not req_col or not values:
            return None
        condition_json["when_column"] = when_col
        condition_json["required_column"] = req_col
        condition_json["when_values"] = list(values)
    if rule_type == "cross_column_consistency":
        left_col = _resolve_column(schema_graph, table_name, condition_json.get("left_column") or rule.get("column_name"))
        right_col = _resolve_column(schema_graph, table_name, condition_json.get("right_column"))
        operator = str(condition_json.get("operator") or "").strip()
        if not left_col or not right_col or operator not in {"<", "<=", ">", ">=", "=", "!="}:
            return None
        condition_json["left_column"] = left_col
        condition_json["right_column"] = right_col
        condition_json["operator"] = operator
    if rule_type == "numeric_range":
        if not _has_any(condition_json, {"min_value", "max_value"}):
            return None
    if rule_type == "length":
        if not _has_any(condition_json, {"min_length", "max_length", "exact_length"}):
            return None
    if rule_type == "null_pct_threshold":
        if condition_json.get("max_null_pct") is None:
            return None
    if rule_type == "row_count_change_pct":
        if condition_json.get("baseline_row_count") is None or condition_json.get("max_change_pct") is None:
            return None
    if rule_type == "custom_sql":
        validation_sql = str(condition_json.get("validation_sql") or "").strip()
        sample_sql = str(condition_json.get("sample_sql") or "").strip()
        rewritten_sql = _rewrite_safe_date_text_custom_sql(
            table_name=table_name,
            column_name=column_name,
            source_text=str(rule.get("source_text") or condition_json.get("source_text") or ""),
            validation_sql=validation_sql,
            sample_sql=sample_sql,
        )
        if rewritten_sql:
            condition_json["validation_sql"] = rewritten_sql["validation_sql"]
            condition_json["sample_sql"] = rewritten_sql["sample_sql"]
            validation_sql = rewritten_sql["validation_sql"]
        if not validation_sql or not _is_safe_custom_sql(validation_sql, table_name=table_name):
            return None
    validated = {
        "rule_type": rule_type,
        "severity": str(rule.get("severity") or "warning").strip().lower(),
        "table_name": table_name,
        "column_name": column_name,
        "condition_json": condition_json,
        "source": "llm_context_text",
        "confidence": rule.get("confidence") if isinstance(rule.get("confidence"), (int, float)) else 0.75,
        "status": "active",
    }
    if rule_type == "referential_integrity":
        ref_table, ref_col = _resolve_table_column(schema_graph, rule.get("reference_table"), rule.get("reference_column"))
        if not column_name or not ref_table or not ref_col:
            return None
        validated["reference_table"] = ref_table
        validated["reference_column"] = ref_col
        validated["severity"] = "critical"
    if validated["severity"] not in {"critical", "warning", "info"}:
        validated["severity"] = "warning"
    if "source_text" not in validated["condition_json"] and rule.get("source_text"):
        validated["condition_json"]["source_text"] = str(rule.get("source_text"))[:1000]
    return validated


def _rewrite_safe_date_text_custom_sql(
    *,
    table_name: str,
    column_name: str | None,
    source_text: str,
    validation_sql: str,
    sample_sql: str,
) -> dict[str, str] | None:
    column = str(column_name or "").strip()
    if not column:
        return None
    validation = str(validation_sql or "").strip()
    if not validation:
        return None
    source = str(source_text or "").lower()
    lowered = validation.lower()
    if "current_date" not in lowered:
        return None
    if column.lower() not in lowered:
        return None
    if "yyyy-mm-dd" not in source and r"\d{4}-\d{2}-\d{2}" not in validation:
        return None

    date_pattern = r"^\d{4}-\d{2}-\d{2}$"
    col = _qident(column)
    compare_operator = ">="
    if re.search(rf"{re.escape(column)}\s*>\s*current_date", lowered):
        compare_operator = ">"
    predicate = (
        f"{col} IS NULL OR "
        f"{col}::text !~ '{date_pattern}' OR "
        f"(CASE WHEN {col}::text ~ '{date_pattern}' THEN {col}::date {compare_operator} CURRENT_DATE ELSE FALSE END)"
    )
    return {
        "validation_sql": (
            f"SELECT COUNT(*) AS checked_row_count, "
            f"COUNT(*) FILTER (WHERE {predicate}) AS violation_count "
            f"FROM {_qident(table_name)}"
        ),
        "sample_sql": (
            f"SELECT {col} AS violating_value "
            f"FROM {_qident(table_name)} "
            f"WHERE {predicate} LIMIT 25"
        ),
    }


def _llm_mode() -> str:
    return os.getenv("DATA_QUALITY_RULE_LLM_MODE", "auto").strip().lower()


def _llm_rule_extraction_enabled(settings: Settings | None) -> bool:
    mode = _llm_mode()
    if mode in {"off", "false", "0", "disabled"}:
        return False
    return bool(settings and getattr(settings, "openai_api_key", None))


def _llm_sql_preview_mode() -> str:
    return os.getenv("DATA_QUALITY_RULE_SQL_PREVIEW_LLM_MODE", "auto").strip().lower()


def _llm_sql_preview_enabled(settings: Settings | None) -> bool:
    mode = _llm_sql_preview_mode()
    if mode in {"off", "false", "0", "disabled"}:
        return False
    return bool(settings and getattr(settings, "openai_api_key", None))


def _preview_allowed_tables(rule: dict[str, Any]) -> list[str]:
    tables = []
    for value in [rule.get("table_name"), rule.get("reference_table")]:
        text = str(value or "").strip()
        if text and text not in tables:
            tables.append(text)
    return tables


def _is_safe_preview_sql(sql: str, *, allowed_tables: list[str]) -> bool:
    cleaned = str(sql or "").strip()
    if not cleaned:
        return False
    if re.search(r"<[A-Za-z0-9_ ][A-Za-z0-9_ -]*>", cleaned):
        return False
    if ";" in cleaned.rstrip(";"):
        return False
    if not re.match(r"^\s*(with\b.+\bselect\b|select\b)", cleaned, flags=re.IGNORECASE | re.DOTALL):
        return False
    if _FORBIDDEN_SQL_RE.search(cleaned):
        return False
    refs = {_norm(ref) for ref in _extract_sql_table_refs(cleaned)}
    allowed = {_norm(ref) for ref in allowed_tables if str(ref or "").strip()}
    if refs and allowed and not refs.issubset(allowed):
        return False
    return True


def _validate_llm_sql_preview_payload(
    preview: dict[str, Any],
    *,
    allowed_tables: list[str],
) -> dict[str, Any] | None:
    validation_sql = str(preview.get("validation_sql") or "").strip()
    sample_sql = str(preview.get("sample_sql") or "").strip()
    if not validation_sql or not _is_safe_preview_sql(validation_sql, allowed_tables=allowed_tables):
        return None
    if sample_sql and not _is_safe_preview_sql(sample_sql, allowed_tables=allowed_tables):
        return None
    notes = preview.get("notes") if isinstance(preview.get("notes"), list) else []
    return {
        "status": "available",
        "source": "llm",
        "validation_sql": validation_sql.rstrip(";"),
        "sample_sql": sample_sql.rstrip(";") or None,
        "notes": [str(item) for item in notes if str(item or "").strip()],
        "error": None,
    }


def _build_quality_rule_sql_preview_with_llm(
    settings: Settings | None,
    *,
    rule: dict[str, Any],
    schema_name: str,
) -> dict[str, Any] | None:
    if not _llm_sql_preview_enabled(settings):
        return None
    model = os.getenv("DATA_QUALITY_RULE_SQL_PREVIEW_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("DATA_QUALITY_RULE_SQL_PREVIEW_TIMEOUT_SEC", "30"))
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Generate a read-only SQL preview for a canonical data quality rule. "
                    "Return JSON only. Produce validation_sql and sample_sql. "
                    "Use only the provided schema, table names, and column names. "
                    "Never invent identifiers. SQL must be SELECT-only. "
                    "If a clean SQL preview cannot be generated, return an empty JSON object."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "schema_name": schema_name,
                        "rule": {
                            "rule_type": rule.get("rule_type"),
                            "table_name": rule.get("table_name"),
                            "column_name": rule.get("column_name"),
                            "reference_table": rule.get("reference_table"),
                            "reference_column": rule.get("reference_column"),
                            "condition_json": rule.get("condition_json") or {},
                        },
                        "required_response_shape": {
                            "validation_sql": "SELECT ...",
                            "sample_sql": "SELECT ... LIMIT 25",
                            "notes": ["brief explanation"],
                        },
                    },
                    default=str,
                ),
            },
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        content = ((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
        preview = json.loads(content)
        if not isinstance(preview, dict):
            return None
        return _validate_llm_sql_preview_payload(preview, allowed_tables=_preview_allowed_tables(rule))
    except Exception:
        logger.warning("data_quality.rules.llm_sql_preview_failed", exc_info=True)
        if _llm_sql_preview_mode() in {"required", "require", "on"}:
            raise
        return None


def _extract_quality_rules_with_llm(
    settings: Settings | None,
    context_text: str,
    schema_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    if not _llm_rule_extraction_enabled(settings):
        return []
    model = os.getenv("DATA_QUALITY_RULE_LLM_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("DATA_QUALITY_RULE_LLM_TIMEOUT_SEC", "30"))
    payload = {
        "context_text": context_text[:12000],
        "schema": _schema_prompt(schema_graph),
        "allowed_rule_types": [
            "referential_integrity",
            "not_null",
            "not_blank",
            "email_pattern",
            "numeric_min",
            "numeric_max",
            "allowed_values",
            "regex_pattern",
            "unique",
            "composite_unique",
            "date_range",
            "freshness_sla",
            "conditional_required",
            "cross_column_consistency",
            "numeric_range",
            "length",
            "null_pct_threshold",
            "row_count_change_pct",
            "custom_sql",
        ],
        "required_response_shape": {
            "rules": [
                {
                    "rule_type": "referential_integrity",
                    "severity": "critical",
                    "table_name": "orders",
                    "column_name": "customer_id",
                    "reference_table": "customer",
                    "reference_column": "customer_id",
                    "condition_json": {"source_text": "orders.customer_id must exist in customer.customer_id"},
                    "confidence": 0.95,
                },
                {
                    "rule_type": "custom_sql",
                    "severity": "warning",
                    "table_name": "orders",
                    "column_name": None,
                    "condition_json": {
                        "validation_sql": "SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE status = 'INVALID') AS violation_count FROM public.orders",
                        "sample_sql": "SELECT order_id, status FROM public.orders WHERE status = 'INVALID' LIMIT 25"
                    },
                    "confidence": 0.8
                }
            ]
        },
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract executable data quality validation rules from user context. "
                    "Return JSON only. Use only table and column names from the provided schema. "
                    "Do not invent fields. If a rule cannot be mapped to the schema, omit it. "
                    "Use custom_sql only when no standard rule type fits. Custom SQL must be a single read-only SELECT "
                    "that returns checked_row_count and violation_count, scoped to one provided table."
                ),
            },
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        content = ((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
        raw_rules = (json.loads(content).get("rules") or [])
        if not isinstance(raw_rules, list):
            return []
        rules: list[dict[str, Any]] = []
        for raw_rule in raw_rules:
            if not isinstance(raw_rule, dict):
                continue
            validated = _validate_llm_rule(raw_rule, schema_graph)
            if validated:
                rules.append(validated)
        return _dedupe_rules(rules)
    except Exception:
        logger.warning("data_quality.rules.llm_extract_failed", exc_info=True)
        if _llm_mode() in {"required", "require", "on"}:
            raise
        return []


def _dedupe_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for rule in rules:
        key = (
            rule.get("rule_type"),
            rule.get("table_name"),
            rule.get("column_name"),
            rule.get("reference_table"),
            rule.get("reference_column"),
            str(rule.get("condition_json") or {}),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rule)
    return deduped


def _extract_quality_rules_deterministic(context_text: str | None, schema_graph: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(context_text or "").strip()
    if not text:
        return []
    rules: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def add(rule: dict[str, Any]) -> None:
        key = (
            rule.get("rule_type"),
            rule.get("table_name"),
            rule.get("column_name"),
            rule.get("reference_table"),
            rule.get("reference_column"),
            str(rule.get("condition_json") or {}),
        )
        if key in seen:
            return
        seen.add(key)
        rules.append(rule)

    for match in re.finditer(
        r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s+(?:must|should)\s+exist\s+in\s+([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b",
        text,
        flags=re.IGNORECASE,
    ):
        child_table, child_col = _resolve_table_column(schema_graph, match.group(1), match.group(2))
        parent_table, parent_col = _resolve_table_column(schema_graph, match.group(3), match.group(4))
        if child_table and child_col and parent_table and parent_col:
            add(
                {
                    "rule_type": "referential_integrity",
                    "severity": "critical",
                    "table_name": child_table,
                    "column_name": child_col,
                    "reference_table": parent_table,
                    "reference_column": parent_col,
                    "condition_json": {"source_text": match.group(0)},
                    "source": "context_text",
                    "confidence": 0.95,
                    "status": "active",
                }
            )

    for sentence in re.split(r"[\n.;]+", text):
        sent = sentence.strip()
        if not sent:
            continue
        present_match = re.search(
            r"\b([A-Za-z_][\w]*)(?:\.|\s+)([A-Za-z_][\w]*)\s+(?:must|should)\s+be\s+(?:present|required|not\s+null)\b",
            sent,
            flags=re.IGNORECASE,
        )
        if present_match:
            table_name, col_name = _resolve_table_column(schema_graph, present_match.group(1), present_match.group(2))
            if table_name and col_name:
                add(
                    {
                        "rule_type": "not_null",
                        "severity": "critical",
                        "table_name": table_name,
                        "column_name": col_name,
                        "condition_json": {"source_text": sent},
                        "source": "context_text",
                        "confidence": 0.88,
                        "status": "active",
                    }
                )
                if "email" in _norm(col_name) and re.search(r"\bvalid\b", sent, flags=re.IGNORECASE):
                    add(
                        {
                            "rule_type": "email_pattern",
                            "severity": "warning",
                            "table_name": table_name,
                            "column_name": col_name,
                            "condition_json": {"source_text": sent, "pattern": "basic_email"},
                            "source": "context_text",
                            "confidence": 0.86,
                            "status": "active",
                        }
                    )
        negative_match = re.search(
            r"\b([A-Za-z_][\w]*)(?:\.|\s+)([A-Za-z_][\w]*)\s+(?:cannot|must\s+not|should\s+not)\s+be\s+negative\b",
            sent,
            flags=re.IGNORECASE,
        )
        if negative_match:
            table_name, col_name = _resolve_table_column(schema_graph, negative_match.group(1), negative_match.group(2))
            if table_name and col_name:
                add(
                    {
                        "rule_type": "numeric_min",
                        "severity": "critical",
                        "table_name": table_name,
                        "column_name": col_name,
                        "condition_json": {"source_text": sent, "min_value": 0},
                        "source": "context_text",
                        "confidence": 0.9,
                        "status": "active",
                    }
                )
        unique_match = re.search(
            r"\b([A-Za-z_][\w]*)(?:\.|\s+)([A-Za-z_][\w]*)\s+(?:must|should)\s+be\s+unique\b",
            sent,
            flags=re.IGNORECASE,
        )
        if unique_match:
            table_name, col_name = _resolve_table_column(schema_graph, unique_match.group(1), unique_match.group(2))
            if table_name and col_name:
                add(
                    {
                        "rule_type": "unique",
                        "severity": "critical",
                        "table_name": table_name,
                        "column_name": col_name,
                        "condition_json": {"source_text": sent},
                        "source": "context_text",
                        "confidence": 0.88,
                        "status": "active",
                    }
                )
        future_match = re.search(
            r"\b([A-Za-z_][\w]*)(?:\.|\s+)([A-Za-z_][\w]*)\s+(?:cannot|must\s+not|should\s+not)\s+be\s+in\s+the\s+future\b",
            sent,
            flags=re.IGNORECASE,
        )
        if future_match:
            table_name, col_name = _resolve_table_column(schema_graph, future_match.group(1), future_match.group(2))
            if table_name and col_name:
                add(
                    {
                        "rule_type": "date_range",
                        "severity": "critical",
                        "table_name": table_name,
                        "column_name": col_name,
                        "condition_json": {"source_text": sent, "not_future": True},
                        "source": "context_text",
                        "confidence": 0.86,
                        "status": "active",
                    }
                )
        pct_match = re.search(
            r"\b([A-Za-z_][\w]*)(?:\.|\s+)([A-Za-z_][\w]*)\s+(?:missing|null)\s+(?:percentage|pct|rate)\s+(?:must|should)\s+be\s+(?:below|under|less\s+than)\s+(\d+(?:\.\d+)?)\s*%?",
            sent,
            flags=re.IGNORECASE,
        )
        if pct_match:
            table_name, col_name = _resolve_table_column(schema_graph, pct_match.group(1), pct_match.group(2))
            if table_name and col_name:
                add(
                    {
                        "rule_type": "null_pct_threshold",
                        "severity": "warning",
                        "table_name": table_name,
                        "column_name": col_name,
                        "condition_json": {"source_text": sent, "max_null_pct": float(pct_match.group(3))},
                        "source": "context_text",
                        "confidence": 0.84,
                        "status": "active",
                    }
                )
    return _dedupe_rules(rules)


def extract_quality_rules_from_context(
    context_text: str | None,
    schema_graph: dict[str, Any],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    text = str(context_text or "").strip()
    if not text:
        return []
    try:
        llm_rules = _extract_quality_rules_with_llm(settings, text, schema_graph)
        if llm_rules:
            return llm_rules
    except Exception:
        if _llm_mode() in {"required", "require", "on"}:
            raise
    return _extract_quality_rules_deterministic(text, schema_graph)


def build_quality_rule_execution_plan(
    rule: dict[str, Any],
    *,
    schema_name: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    rule_type = str(rule.get("rule_type") or "").strip()
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    condition = rule.get("condition_json") or {}

    def plan(
        *,
        executor_kind: str,
        validation_sql: str | None = None,
        sample_sql: str | None = None,
        parameter_hints: dict[str, Any] | None = None,
        notes: list[str] | None = None,
    ) -> dict[str, Any]:
        preview = _build_quality_rule_sql_preview_with_llm(
            settings,
            rule=rule,
            schema_name=schema_name,
        )
        fallback_validation = str(validation_sql or "").strip()
        fallback_sample = str(sample_sql or "").strip()
        if preview is None:
            if fallback_validation and _is_safe_preview_sql(fallback_validation, allowed_tables=_preview_allowed_tables(rule)):
                preview = {
                    "status": "available",
                    "source": "stored_rule_sql" if executor_kind == "custom_sql" else "deterministic_fallback",
                    "validation_sql": fallback_validation,
                    "sample_sql": fallback_sample or None,
                    "notes": ["LLM SQL preview unavailable; using fallback preview."],
                    "error": None,
                }
            else:
                preview = {
                    "status": "preview_unavailable",
                    "source": "unavailable",
                    "validation_sql": None,
                    "sample_sql": None,
                    "notes": ["Neither LLM nor deterministic compilation produced a safe SQL preview."],
                    "error": "preview_unavailable",
                }
        return {
            "executor_kind": executor_kind,
            "validation_sql": validation_sql,
            "sample_sql": sample_sql,
            "parameter_hints": parameter_hints or {},
            "notes": notes or [],
            "sql_preview": preview,
            "sql_preview_status": preview.get("status"),
            "sql_preview_source": preview.get("source"),
        }

    if rule_type == "referential_integrity":
        parent_table = _qident(rule.get("reference_table"))
        parent_col = _qident(rule.get("reference_column"))
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=(
                f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE child.{col} IS NOT NULL AND parent.{parent_col} IS NULL) AS violation_count "
                f"FROM {schema}.{table} child LEFT JOIN {schema}.{parent_table} parent ON child.{col} = parent.{parent_col}"
            ),
            sample_sql=(
                f"SELECT child.{col} AS violating_value FROM {schema}.{table} child "
                f"LEFT JOIN {schema}.{parent_table} parent ON child.{col} = parent.{parent_col} "
                f"WHERE child.{col} IS NOT NULL AND parent.{parent_col} IS NULL LIMIT 25"
            ),
        )
    if rule_type == "not_null":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NULL) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT * FROM {schema}.{table} WHERE {col} IS NULL LIMIT 25",
        )
    if rule_type == "email_pattern":
        pattern = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col}::text !~ :pattern) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col}::text !~ :pattern LIMIT 25",
            parameter_hints={"pattern": pattern},
        )
    if rule_type == "numeric_min":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col} < :min_value) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col} < :min_value LIMIT 25",
            parameter_hints={"min_value": condition.get("min_value", 0)},
        )
    if rule_type == "numeric_max":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col} > :max_value) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col} > :max_value LIMIT 25",
            parameter_hints={"max_value": condition.get("max_value")},
        )
    if rule_type == "not_blank":
        predicate = f"{col} IS NULL OR btrim({col}::text) = ''"
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {predicate}) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {predicate} LIMIT 25",
        )
    if rule_type == "allowed_values":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NOT NULL AND NOT ({col}::text = ANY(:allowed_values))) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND NOT ({col}::text = ANY(:allowed_values)) LIMIT 25",
            parameter_hints={"allowed_values": condition.get("allowed_values") or []},
        )
    if rule_type == "regex_pattern":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col}::text !~ :pattern) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col}::text !~ :pattern LIMIT 25",
            parameter_hints={"pattern": condition.get("pattern")},
        )
    if rule_type == "custom_sql":
        return plan(
            executor_kind="custom_sql",
            validation_sql=_normalize_custom_sql(condition.get("validation_sql") or ""),
            sample_sql=_normalize_custom_sql(condition.get("sample_sql") or "", sample=True),
            notes=["Custom SQL is stored as provided and checked for safety at execution time."],
        )
    if rule_type == "unique":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, GREATEST(COUNT({col}) - COUNT(DISTINCT {col}), 0) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS duplicate_value, COUNT(*) AS duplicate_count FROM {schema}.{table} WHERE {col} IS NOT NULL GROUP BY {col} HAVING COUNT(*) > 1 LIMIT 25",
        )
    if rule_type == "composite_unique":
        cols = [_qident(item) for item in (condition.get("columns") or [])]
        group_cols = ", ".join(cols)
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=(
                f"WITH dupes AS (SELECT {group_cols}, COUNT(*) AS cnt FROM {schema}.{table} GROUP BY {group_cols} HAVING COUNT(*) > 1) "
                f"SELECT (SELECT COUNT(*) FROM {schema}.{table}) AS checked_row_count, COALESCE((SELECT SUM(cnt - 1) FROM dupes), 0) AS violation_count"
            ),
            sample_sql=f"SELECT {group_cols}, COUNT(*) AS duplicate_count FROM {schema}.{table} GROUP BY {group_cols} HAVING COUNT(*) > 1 LIMIT 25",
            parameter_hints={"columns": condition.get("columns") or []},
        )
    if rule_type == "date_range":
        predicates, notes = _build_date_range_predicate_parts(col, condition)
        predicate_sql = " OR ".join(f"({item})" for item in predicates)
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=(
                f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {predicate_sql}) AS violation_count FROM {schema}.{table}"
                if predicate_sql
                else None
            ),
            sample_sql=(
                f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {predicate_sql} LIMIT 25"
                if predicate_sql
                else None
            ),
            parameter_hints={"min_date": condition.get("min_date"), "max_date": condition.get("max_date"), "not_future": condition.get("not_future")},
            notes=notes,
        )
    if rule_type == "freshness_sla":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT EXTRACT(EPOCH FROM (now() - MAX({col}))) / 3600.0 AS lag_hours FROM {schema}.{table}",
            parameter_hints={"max_lag_hours": condition.get("max_lag_hours")},
        )
    if rule_type == "conditional_required":
        when_col = _qident(condition.get("when_column"))
        req_col = _qident(condition.get("required_column"))
        missing = f"{req_col} IS NULL OR btrim({req_col}::text) = ''"
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) FILTER (WHERE {when_col}::text = ANY(:when_values)) AS checked_row_count, COUNT(*) FILTER (WHERE {when_col}::text = ANY(:when_values) AND ({missing})) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT * FROM {schema}.{table} WHERE {when_col}::text = ANY(:when_values) AND ({missing}) LIMIT 25",
            parameter_hints={"when_values": condition.get("when_values") or []},
        )
    if rule_type == "cross_column_consistency":
        left = _qident(condition.get("left_column"))
        right = _qident(condition.get("right_column"))
        operator = condition.get("operator")
        predicate = f"{left} IS NOT NULL AND {right} IS NOT NULL AND NOT ({left} {operator} {right})"
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {predicate}) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {left} AS left_value, {right} AS right_value FROM {schema}.{table} WHERE {predicate} LIMIT 25",
        )
    if rule_type == "numeric_range":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NOT NULL AND ({col} < :min_value OR {col} > :max_value)) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND ({col} < :min_value OR {col} > :max_value) LIMIT 25",
            parameter_hints={"min_value": condition.get("min_value"), "max_value": condition.get("max_value")},
        )
    if rule_type == "length":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE <length_predicate>) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE <length_predicate> LIMIT 25",
            parameter_hints={"exact_length": condition.get("exact_length"), "min_length": condition.get("min_length"), "max_length": condition.get("max_length")},
        )
    if rule_type == "null_pct_threshold":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NULL) AS violation_count FROM {schema}.{table}",
            sample_sql=f"SELECT * FROM {schema}.{table} WHERE {col} IS NULL LIMIT 25",
            parameter_hints={"max_null_pct": condition.get("max_null_pct")},
        )
    if rule_type == "row_count_change_pct":
        return plan(
            executor_kind="deterministic_sql",
            validation_sql=f"SELECT COUNT(*) AS current_row_count FROM {schema}.{table}",
            parameter_hints={"baseline_row_count": condition.get("baseline_row_count"), "max_change_pct": condition.get("max_change_pct")},
        )
    return plan(executor_kind="unimplemented", notes=[f"Unsupported rule type: {rule_type}"])


def _pct(violations: int | None, checked: int | None) -> float | None:
    if checked in (None, 0) or violations is None:
        return None
    return round((float(violations) / float(checked)) * 100.0, 4)


def _run_scalar(settings: Settings, sql: str, params: list[Any], scoped_conn: ScopedConnection | None) -> dict[str, Any]:
    rows = run_query(settings, sql, params, scoped_conn=scoped_conn)
    return rows[0] if rows else {}


_FORBIDDEN_SQL_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|call|execute|merge|vacuum|analyze)\b",
    re.IGNORECASE,
)


def _is_safe_custom_sql(sql: str, *, table_name: str) -> bool:
    cleaned = str(sql or "").strip()
    if not cleaned:
        return False
    if ";" in cleaned.rstrip(";"):
        return False
    if not re.match(r"^\s*select\b", cleaned, flags=re.IGNORECASE):
        return False
    if _FORBIDDEN_SQL_RE.search(cleaned):
        return False
    if _norm(table_name) not in {_norm(ref) for ref in _extract_sql_table_refs(cleaned)}:
        return False
    return True


def _extract_sql_table_refs(sql: str) -> list[str]:
    refs = []
    for match in re.finditer(
        r'\b(?:from|join)\s+(?:(?:"[^"]+"|[A-Za-z_][\w]*)\s*\.\s*)?(?:"([^"]+)"|([A-Za-z_][\w]*))',
        sql,
        flags=re.IGNORECASE,
    ):
        refs.append(match.group(1) or match.group(2))
    return refs


def _normalize_custom_sql(sql: str, *, sample: bool = False) -> str:
    cleaned = str(sql or "").strip().rstrip(";")
    if sample and not re.search(r"\blimit\s+\d+\b", cleaned, flags=re.IGNORECASE):
        cleaned = f"{cleaned} LIMIT 25"
    return cleaned


def classify_quality_rule_review_status(
    rule: dict[str, Any],
    *,
    confidence_threshold: float | None = None,
) -> str:
    if data_quality_rule_auto_approve_all_enabled():
        return "active"
    threshold = confidence_threshold
    if threshold is None:
        try:
            threshold = float(os.getenv("DATA_QUALITY_RULE_AUTO_APPROVE_THRESHOLD", "0.85"))
        except Exception:
            threshold = 0.85
    executor_kind = str(rule.get("executor_kind") or "").strip().lower()
    if executor_kind == "unimplemented":
        return "unsupported"
    preview_status = str(((rule.get("execution_plan_json") or {}).get("sql_preview_status")) or "").strip().lower()
    if preview_status == "preview_unavailable":
        return "needs_review"
    try:
        confidence = float(rule.get("confidence"))
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and confidence < float(threshold):
        return "needs_review"
    return "active"


def _execute_referential_integrity(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    child_table = _qident(rule.get("table_name"))
    child_col = _qident(rule.get("column_name"))
    parent_table = _qident(rule.get("reference_table"))
    parent_col = _qident(rule.get("reference_column"))
    schema = _qident(schema_name or "public")
    counts = _run_scalar(
        settings,
        f"""
        SELECT
          COUNT(*) AS checked_row_count,
          COUNT(*) FILTER (
            WHERE child.{child_col} IS NOT NULL
              AND parent.{parent_col} IS NULL
          ) AS violation_count
        FROM {schema}.{child_table} child
        LEFT JOIN {schema}.{parent_table} parent
          ON child.{child_col} = parent.{parent_col}
        """,
        [],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"""
        SELECT child.{child_col} AS violating_value
        FROM {schema}.{child_table} child
        LEFT JOIN {schema}.{parent_table} parent
          ON child.{child_col} = parent.{parent_col}
        WHERE child.{child_col} IS NOT NULL
          AND parent.{parent_col} IS NULL
        LIMIT 25
        """,
        [],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_not_null(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    counts = _run_scalar(
        settings,
        f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {col} IS NULL) AS violation_count FROM {schema}.{table}",
        [],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT * FROM {schema}.{table} WHERE {col} IS NULL LIMIT 25",
        [],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_email_pattern(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    pattern = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
    counts = _run_scalar(
        settings,
        f"""
        SELECT COUNT(*) AS checked_row_count,
               COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col}::text !~ %s) AS violation_count
          FROM {schema}.{table}
        """,
        [pattern],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col}::text !~ %s LIMIT 25",
        [pattern],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_numeric_min(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    min_value = (rule.get("condition_json") or {}).get("min_value", 0)
    counts = _run_scalar(
        settings,
        f"""
        SELECT COUNT(*) AS checked_row_count,
               COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col} < %s) AS violation_count
          FROM {schema}.{table}
        """,
        [min_value],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col} < %s LIMIT 25",
        [min_value],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_not_blank(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    predicate = f"{col} IS NULL OR btrim({col}::text) = ''"
    counts = _run_scalar(
        settings,
        f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {predicate}) AS violation_count FROM {schema}.{table}",
        [],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {predicate} LIMIT 25",
        [],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_numeric_max(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    max_value = (rule.get("condition_json") or {}).get("max_value")
    counts = _run_scalar(
        settings,
        f"""
        SELECT COUNT(*) AS checked_row_count,
               COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col} > %s) AS violation_count
          FROM {schema}.{table}
        """,
        [max_value],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col} > %s LIMIT 25",
        [max_value],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_allowed_values(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    allowed = [str(item) for item in ((rule.get("condition_json") or {}).get("allowed_values") or [])]
    counts = _run_scalar(
        settings,
        f"""
        SELECT COUNT(*) AS checked_row_count,
               COUNT(*) FILTER (WHERE {col} IS NOT NULL AND NOT ({col}::text = ANY(%s))) AS violation_count
          FROM {schema}.{table}
        """,
        [allowed],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND NOT ({col}::text = ANY(%s)) LIMIT 25",
        [allowed],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_regex_pattern(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    pattern = str((rule.get("condition_json") or {}).get("pattern") or "").strip()
    counts = _run_scalar(
        settings,
        f"""
        SELECT COUNT(*) AS checked_row_count,
               COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col}::text !~ %s) AS violation_count
          FROM {schema}.{table}
        """,
        [pattern],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col}::text !~ %s LIMIT 25",
        [pattern],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_custom_sql(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    condition = rule.get("condition_json") or {}
    validation_sql = _normalize_custom_sql(condition.get("validation_sql") or "")
    sample_sql = _normalize_custom_sql(condition.get("sample_sql") or "", sample=True)
    table_name = str(rule.get("table_name") or "").strip()
    if not _is_safe_custom_sql(validation_sql, table_name=table_name):
        return "error", None, None, None, [], "Unsafe custom validation SQL rejected"
    if sample_sql and not _is_safe_custom_sql(sample_sql, table_name=table_name):
        return "error", None, None, None, [], "Unsafe custom sample SQL rejected"
    counts = _run_scalar(settings, validation_sql, [], scoped_conn)
    checked = int(counts.get("checked_row_count") or counts.get("total_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(settings, sample_sql, [], scoped_conn=scoped_conn) if sample_sql else []
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_unique(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    counts = _run_scalar(
        settings,
        f"SELECT COUNT(*) AS checked_row_count, GREATEST(COUNT({col}) - COUNT(DISTINCT {col}), 0) AS violation_count FROM {schema}.{table}",
        [],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT {col} AS duplicate_value, COUNT(*) AS duplicate_count FROM {schema}.{table} WHERE {col} IS NOT NULL GROUP BY {col} HAVING COUNT(*) > 1 LIMIT 25",
        [],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_composite_unique(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    cols = [_qident(col) for col in (rule.get("condition_json") or {}).get("columns") or []]
    if len(cols) < 2:
        return "error", None, None, None, [], "composite_unique requires at least two columns"
    group_cols = ", ".join(cols)
    counts = _run_scalar(
        settings,
        f"""
        WITH dupes AS (
          SELECT {group_cols}, COUNT(*) AS cnt
            FROM {schema}.{table}
           GROUP BY {group_cols}
          HAVING COUNT(*) > 1
        )
        SELECT
          (SELECT COUNT(*) FROM {schema}.{table}) AS checked_row_count,
          COALESCE((SELECT SUM(cnt - 1) FROM dupes), 0) AS violation_count
        """,
        [],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(
        settings,
        f"SELECT {group_cols}, COUNT(*) AS duplicate_count FROM {schema}.{table} GROUP BY {group_cols} HAVING COUNT(*) > 1 LIMIT 25",
        [],
        scoped_conn=scoped_conn,
    )
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_date_range(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    condition = rule.get("condition_json") or {}
    predicates, notes = _build_date_range_predicate_parts(col, condition)
    if notes and not predicates:
        return ("error", None, None, None, [], "; ".join(notes))
    predicate = " OR ".join(f"({item})" for item in predicates) or "false"
    counts = _run_scalar(
        settings,
        f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {predicate}) AS violation_count FROM {schema}.{table}",
        [],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(settings, f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {predicate} LIMIT 25", [], scoped_conn=scoped_conn)
    error_message = "; ".join(notes) if notes else None
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, error_message


def _execute_freshness_sla(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    max_lag_hours = float((rule.get("condition_json") or {}).get("max_lag_hours"))
    row = _run_scalar(
        settings,
        f"SELECT EXTRACT(EPOCH FROM (now() - MAX({col}))) / 3600.0 AS lag_hours FROM {schema}.{table}",
        [],
        scoped_conn,
    )
    lag_hours = row.get("lag_hours")
    violation = 1 if lag_hours is None or float(lag_hours) > max_lag_hours else 0
    sample = [{"lag_hours": lag_hours, "max_lag_hours": max_lag_hours}]
    return ("failed" if violation else "passed"), 1, violation, float(violation) * 100.0, sample, None


def _execute_conditional_required(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    condition = rule.get("condition_json") or {}
    when_col = _qident(condition.get("when_column"))
    req_col = _qident(condition.get("required_column"))
    values = [str(item) for item in condition.get("when_values") or []]
    where_when = f"{when_col}::text = ANY(%s)"
    missing = f"{req_col} IS NULL OR btrim({req_col}::text) = ''"
    counts = _run_scalar(
        settings,
        f"SELECT COUNT(*) FILTER (WHERE {where_when}) AS checked_row_count, COUNT(*) FILTER (WHERE {where_when} AND ({missing})) AS violation_count FROM {schema}.{table}",
        [values, values],
        scoped_conn,
    )
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(settings, f"SELECT * FROM {schema}.{table} WHERE {where_when} AND ({missing}) LIMIT 25", [values], scoped_conn=scoped_conn)
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_cross_column_consistency(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    condition = rule.get("condition_json") or {}
    left = _qident(condition.get("left_column"))
    right = _qident(condition.get("right_column"))
    op = condition.get("operator")
    predicate = f"{left} IS NOT NULL AND {right} IS NOT NULL AND NOT ({left} {op} {right})"
    counts = _run_scalar(settings, f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {predicate}) AS violation_count FROM {schema}.{table}", [], scoped_conn)
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(settings, f"SELECT {left} AS left_value, {right} AS right_value FROM {schema}.{table} WHERE {predicate} LIMIT 25", [], scoped_conn=scoped_conn)
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_numeric_range(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    condition = rule.get("condition_json") or {}
    if condition.get("min_value") is not None and condition.get("max_value") is not None:
        min_result = _execute_numeric_min(settings, rule={**rule, "condition_json": {"min_value": condition["min_value"]}}, schema_name=schema_name, scoped_conn=scoped_conn)
        max_result = _execute_numeric_max(settings, rule={**rule, "condition_json": {"max_value": condition["max_value"]}}, schema_name=schema_name, scoped_conn=scoped_conn)
        checked = min_result[1] or max_result[1]
        violations = (min_result[2] or 0) + (max_result[2] or 0)
        return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), (min_result[4] or []) + (max_result[4] or []), None
    if condition.get("min_value") is not None:
        return _execute_numeric_min(settings, rule={**rule, "condition_json": {"min_value": condition["min_value"]}}, schema_name=schema_name, scoped_conn=scoped_conn)
    return _execute_numeric_max(settings, rule={**rule, "condition_json": {"max_value": condition["max_value"]}}, schema_name=schema_name, scoped_conn=scoped_conn)


def _execute_length(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    col = _qident(rule.get("column_name"))
    condition = rule.get("condition_json") or {}
    predicates: list[str] = []
    params: list[Any] = []
    if condition.get("exact_length") is not None:
        predicates.append(f"length({col}::text) != %s")
        params.append(condition.get("exact_length"))
    if condition.get("min_length") is not None:
        predicates.append(f"length({col}::text) < %s")
        params.append(condition.get("min_length"))
    if condition.get("max_length") is not None:
        predicates.append(f"length({col}::text) > %s")
        params.append(condition.get("max_length"))
    predicate = f"{col} IS NOT NULL AND (" + " OR ".join(predicates) + ")"
    counts = _run_scalar(settings, f"SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE {predicate}) AS violation_count FROM {schema}.{table}", params, scoped_conn)
    checked = int(counts.get("checked_row_count") or 0)
    violations = int(counts.get("violation_count") or 0)
    samples = run_query(settings, f"SELECT {col} AS violating_value FROM {schema}.{table} WHERE {predicate} LIMIT 25", params, scoped_conn=scoped_conn)
    return ("failed" if violations else "passed"), checked, violations, _pct(violations, checked), samples, None


def _execute_null_pct_threshold(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    status, checked, violations, violation_pct, samples, error = _execute_not_null(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
    max_null_pct = float((rule.get("condition_json") or {}).get("max_null_pct"))
    threshold_violation = 1 if violation_pct is not None and violation_pct > max_null_pct else 0
    sample = [{"null_pct": violation_pct, "max_null_pct": max_null_pct, "null_count": violations}]
    return ("failed" if threshold_violation else "passed"), checked, threshold_violation, float(threshold_violation) * 100.0, sample, error


def _execute_row_count_change_pct(
    settings: Settings,
    *,
    rule: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> tuple[str, int | None, int | None, float | None, list[dict[str, Any]], str | None]:
    schema = _qident(schema_name or "public")
    table = _qident(rule.get("table_name"))
    condition = rule.get("condition_json") or {}
    baseline = float(condition.get("baseline_row_count"))
    max_change_pct = float(condition.get("max_change_pct"))
    row = _run_scalar(settings, f"SELECT COUNT(*) AS current_row_count FROM {schema}.{table}", [], scoped_conn)
    current = float(row.get("current_row_count") or 0)
    change_pct = abs((current - baseline) / baseline * 100.0) if baseline else 100.0
    violation = 1 if change_pct > max_change_pct else 0
    sample = [{"baseline_row_count": baseline, "current_row_count": current, "change_pct": round(change_pct, 4), "max_change_pct": max_change_pct}]
    return ("failed" if violation else "passed"), 1, violation, float(violation) * 100.0, sample, None


def execute_quality_rules(
    settings: Settings,
    *,
    rules: list[dict[str, Any]],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
) -> dict[str, Any]:
    results = []
    for rule in rules:
        try:
            rule_type = str(rule.get("rule_type") or "").strip()
            if rule_type == "referential_integrity":
                result = _execute_referential_integrity(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "not_null":
                result = _execute_not_null(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "email_pattern":
                result = _execute_email_pattern(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "numeric_min":
                result = _execute_numeric_min(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "not_blank":
                result = _execute_not_blank(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "numeric_max":
                result = _execute_numeric_max(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "allowed_values":
                result = _execute_allowed_values(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "regex_pattern":
                result = _execute_regex_pattern(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "custom_sql":
                result = _execute_custom_sql(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "unique":
                result = _execute_unique(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "composite_unique":
                result = _execute_composite_unique(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "date_range":
                result = _execute_date_range(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "freshness_sla":
                result = _execute_freshness_sla(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "conditional_required":
                result = _execute_conditional_required(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "cross_column_consistency":
                result = _execute_cross_column_consistency(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "numeric_range":
                result = _execute_numeric_range(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "length":
                result = _execute_length(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "null_pct_threshold":
                result = _execute_null_pct_threshold(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            elif rule_type == "row_count_change_pct":
                result = _execute_row_count_change_pct(settings, rule=rule, schema_name=schema_name, scoped_conn=scoped_conn)
            else:
                result = ("not_executed", None, None, None, [], f"Unsupported rule type: {rule_type}")
            status, checked, violations, violation_pct, samples, error = result
        except Exception as exc:  # noqa: BLE001
            status, checked, violations, violation_pct, samples, error = "error", None, None, None, [], str(exc)
        insert_quality_rule_result(
            settings,
            rule=rule,
            status=status,
            checked_row_count=checked,
            violation_count=violations,
            violation_pct=violation_pct,
            sample_rows_json=samples,
            error_message=error,
        )
        results.append(
            {
                "rule_id": rule.get("rule_id"),
                "rule_type": rule.get("rule_type"),
                "status": status,
                "checked_row_count": checked,
                "violation_count": violations,
                "violation_pct": violation_pct,
                "error_message": error,
            }
        )
    return {
        "rules_executed": len(results),
        "failed_rules": sum(1 for item in results if item.get("status") == "failed"),
        "passed_rules": sum(1 for item in results if item.get("status") == "passed"),
        "error_rules": sum(1 for item in results if item.get("status") == "error"),
        "not_executed_rules": sum(1 for item in results if item.get("status") == "not_executed"),
        "results": results,
    }
