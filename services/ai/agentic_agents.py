from __future__ import annotations

from typing import Any
import logging
import os

from services.ai.config import Settings
from services.ai.db import run_query
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


def _eligible_cols_by_token(table: dict[str, Any], tokens: list[str]) -> list[str]:
    allowed = set(table.get("eligible_numeric_columns") or [])
    matches: list[str] = []
    for col in allowed:
        lower = str(col).lower()
        if any(tok in lower for tok in tokens):
            matches.append(col)
    return matches


def _load_domain_templates(domain_id: str | None) -> list[dict[str, Any]]:
    if not domain_id:
        return []
    try:
        pack = load_pack(f"packs/{domain_id}")
    except Exception:
        return []
    templates = (pack.get("metric_templates") or {}).get("templates") or []
    return [t for t in templates if isinstance(t, dict) and t.get("name")]


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
        return {"context_entities": context_entities, "hierarchy_hints": [], "glossary_terms": glossary_terms}
    tables_and_columns = ", ".join(
        [
            f"{t.get('name')}: {', '.join([c.get('name') for c in t.get('columns', []) if c.get('name')])}"
            for t in schema_graph.get("tables", [])
        ]
    )
    contract = extract_semantic_contract(settings, context_text, tables_and_columns=tables_and_columns)
    glossary_terms = contract.get("business_terms", [])
    context_entities = [term.get("term") for term in glossary_terms if term.get("term")]
    hierarchy_hints = []
    for line in context_text.splitlines():
        if ">" in line:
            hierarchy_hints.append(line.strip())
    if not glossary_terms:
        logger.warning("extract_context: context_text provided but no glossary_terms returned")
    return {
        "context_entities": context_entities,
        "hierarchy_hints": hierarchy_hints,
        "glossary_terms": glossary_terms,
    }


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


def propose_metrics(profiling: dict[str, Any], domain_id: str | None = None) -> list[dict[str, Any]]:
    metrics = []
    metrics.extend(_propose_template_metrics(profiling, domain_id))
    existing = {(m.get("base_table"), m.get("metric_name")) for m in metrics}
    for table in profiling.get("tables", []):
        semantic_map = {c.get("name"): c for c in (table.get("column_semantics") or []) if c.get("name")}
        numeric_cols = (table.get("eligible_numeric_columns") or [])[:10]
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
                }
            )
            existing.add((table.get("name"), metric_name))
        # derived metrics (productivity / efficiency style)
        cols = set(table.get("eligible_numeric_columns", []) or [])
        production_cols = [c for c in cols if "production" in c]
        hours_cols = [c for c in cols if "hour" in c]
        if production_cols and hours_cols:
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
                }
            )
            existing.add((table.get("name"), metric_name))
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
) -> str:
    metric_label = _pretty_name(metric_name or "Metric")
    category_label = _pretty_name(category_column)
    table_label = _pretty_name(table_name)
    if intent == "trend":
        if time_column:
            return f"{metric_label} Trend Over {_pretty_name(time_column)}"
        return f"{metric_label} Trend"
    if intent == "multi_series":
        if category_label:
            return f"{metric_label} Trend by {category_label}"
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


def build_dashboard_spec(metrics: list[dict[str, Any]], profiling: dict[str, Any]) -> dict[str, Any]:
    charts = []
    view_suggestions = []
    picked = _pick_dashboard_table(profiling)
    metric_col = None
    time_col = None
    category_col = None
    table_name = None
    if picked:
        table_name = picked.get("name")
        numeric = picked.get("eligible_numeric_columns") or []
        time_cols = picked.get("time_columns") or []
        categorical = picked.get("categorical_columns") or []
        metric_col = numeric[0] if numeric else None
        time_col = time_cols[0] if time_cols else None
        category_col = categorical[0] if categorical else None

    metric_name = None
    metric_expr = None
    metric_intent = None
    if metric_col:
        # prefer derived metrics for the picked table if available
        table_metrics = [m for m in metrics if m.get("base_table") == table_name]
        preferred = [m for m in table_metrics if m.get("is_executive_kpi")]
        if not preferred:
            preferred = [m for m in table_metrics if m.get("metric_type")]
        if preferred:
            metric_name = preferred[0].get("metric_name")
            metric_expr = preferred[0].get("formula")
            metric_intent = preferred[0].get("metric_intent")
            metric_col = None
        else:
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

    charts.append(
        {
            "type": "line",
            "intent": "trend",
            "title": _contextual_chart_title(
                intent="trend",
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
            "time_column": time_col,
            "category_column": category_col,
        }
    )
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
            "time_column": time_col,
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
            "time_column": time_col,
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
        numeric_cols = table.get("eligible_numeric_columns") or []
        time_cols = table.get("time_columns") or []
        cat_cols = table.get("categorical_columns") or []
        samples = table.get("sample_values") or {}
        table_metrics = metrics_by_table.get(table_name, [])
        approved_metrics = [
            m
            for m in table_metrics
            if m.get("formula")
            and (m.get("is_executive_kpi") or m.get("metric_type") or m.get("eligible_measure"))
        ]
        approved_metrics.sort(
            key=lambda m: (
                1 if m.get("is_executive_kpi") else 0,
                float(m.get("measure_confidence") or 0.0),
            ),
            reverse=True,
        )
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
        selected_metric = approved_metrics[0]
        metric_name = selected_metric.get("metric_name")
        metric_expr = selected_metric.get("formula")
        metric_intent = selected_metric.get("metric_intent") or _derive_metric_intent(metric_name)
        metric_col = None
        # Trend candidate
        if time_cols:
            candidates.append(
                {
                    "type": "line",
                    "intent": "trend",
                    "title": _contextual_chart_title(
                        intent="trend",
                        metric_name=metric_name,
                        category_column=None,
                        time_column=time_cols[0],
                        table_name=table_name,
                    ),
                    "table": table_name,
                    "metric": metric_name,
                    "metric_intent": metric_intent,
                    "metric_column": metric_col,
                    "metric_expr": metric_expr,
                    "time_column": time_cols[0],
                    "category_column": None,
                }
            )
        # Breakdown candidate
        if cat_cols:
            best_cat = cat_cols[0]
            # pick category with small cardinality for pie
            for col in cat_cols:
                if len(samples.get(col) or []) <= 10:
                    best_cat = col
                    break
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
        # multi-series trend if time + category small
        if time_cols and cat_cols:
            for col in cat_cols:
                if len(samples.get(col) or []) <= 6:
                    candidates.append(
                        {
                            "type": "line",
                            "intent": "multi_series",
                            "title": _contextual_chart_title(
                                intent="multi_series",
                                metric_name=metric_name,
                                category_column=col,
                                time_column=time_cols[0],
                                table_name=table_name,
                            ),
                            "table": table_name,
                            "metric": metric_name,
                            "metric_intent": metric_intent,
                            "metric_column": metric_col,
                            "metric_expr": metric_expr,
                            "time_column": time_cols[0],
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
        if cand.get("intent") == "share":
            score += 2
        if cand.get("intent") == "breakdown":
            score += 2
        if cand.get("intent") == "multi_series":
            score += 3
        if cand.get("metric_expr"):
            score += 1
        scored.append((score, cand))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict[str, Any]] = []
    seen = set()
    for score, cand in scored:
        key = (cand.get("table"), cand.get("metric"), cand.get("type"), cand.get("category_column"), cand.get("time_column"))
        if key in seen:
            continue
        seen.add(key)
        selected.append(cand)
        if len(selected) >= max_charts:
            break
    if len(selected) < min_charts:
        # pad with remaining candidates
        for score, cand in scored:
            if cand in selected:
                continue
            selected.append(cand)
            if len(selected) >= min_charts:
                break
    return selected
