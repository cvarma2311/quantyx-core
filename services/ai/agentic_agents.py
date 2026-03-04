from __future__ import annotations

from typing import Any
import logging

from services.ai.config import Settings
from services.ai.db import run_query
from services.ai.semantic_extraction import extract_semantic_contract

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


def build_schema_graph(schema_payload: dict) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    tables = []
    for table in schema_payload.get("tables", []) or []:
        table_name = table.get("table") or table.get("name") or table.get("table_name")
        columns = []
        for col in table.get("columns", []) or []:
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


def profile_tables(settings: Settings, schema_graph: dict[str, Any], schema_name: str) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    profiling: dict[str, Any] = {"tables": []}
    for table in schema_graph.get("tables", []):
        name = table.get("name")
        if not name:
            continue
        columns = table.get("columns", [])
        numeric = [c["name"] for c in columns if c.get("data_type") in NUMERIC_TYPES]
        time_cols = [c["name"] for c in columns if c.get("data_type") in TIME_TYPES]
        categorical = [c["name"] for c in columns if c.get("data_type") not in NUMERIC_TYPES | TIME_TYPES]
        samples: dict[str, list[Any]] = {}
        candidate_keys: list[dict[str, Any]] = []
        row_count = None
        try:
            rows = run_query(
                settings,
                f"SELECT COUNT(*) AS cnt FROM {schema_name}.{name}",
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
                    f"SELECT DISTINCT {col} AS value FROM {schema_name}.{name} WHERE {col} IS NOT NULL LIMIT 5000",
                    [],
                )
                samples[col] = [r["value"] for r in sample_rows]
            except Exception:
                logger.warning("profile_tables: failed sampling %s.%s", name, col)
                samples[col] = []
        # candidate key profiling for id/code columns
        key_cols = [c.get("name") for c in columns if c.get("name") and (c.get("name").endswith("_id") or c.get("name").endswith("_code"))]
        for col in key_cols[:3]:
            try:
                distinct_rows = run_query(
                    settings,
                    f"SELECT COUNT(DISTINCT {col}) AS distinct_cnt FROM {schema_name}.{name}",
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
            except Exception:
                logger.warning("profile_tables: failed distinct count %s.%s", name, col)
        profiling["tables"].append(
            {
                "name": name,
                "row_count": row_count,
                "numeric_columns": numeric,
                "time_columns": time_cols,
                "categorical_columns": categorical,
                "sample_values": samples,
                "candidate_keys": candidate_keys,
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


def propose_metrics(profiling: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = []
    for table in profiling.get("tables", []):
        numeric_cols = table.get("numeric_columns", [])[:10]
        for col in numeric_cols:
            metrics.append(
                {
                    "metric_name": f"sum_{col}",
                    "formula": f"SUM({col})",
                    "base_table": table.get("name"),
                }
            )
        # derived metrics (productivity / efficiency style)
        cols = set(table.get("numeric_columns", []) or [])
        production_cols = [c for c in cols if "production" in c]
        hours_cols = [c for c in cols if "hour" in c]
        if production_cols and hours_cols:
            prod_col = production_cols[0]
            hour_col = hours_cols[0]
            metrics.append(
                {
                    "metric_name": f"productivity_{prod_col}_per_{hour_col}",
                    "formula": f"SUM({prod_col}) / NULLIF(SUM({hour_col}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "efficiency",
                }
            )
        handled_cols = [c for c in cols if "handled" in c]
        reject_cols = [c for c in cols if "rejection" in c or "reject" in c]
        if handled_cols and reject_cols:
            hcol = handled_cols[0]
            rcol = reject_cols[0]
            metrics.append(
                {
                    "metric_name": f"rejection_rate_{rcol}_per_{hcol}",
                    "formula": f"SUM({rcol}) / NULLIF(SUM({hcol}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "rate",
                }
            )
        # utilization metrics (run_time / total_time)
        time_cols = [c for c in cols if "time" in c or "hours" in c]
        run_cols = [c for c in time_cols if "run" in c or "net" in c]
        total_cols = [c for c in time_cols if "total" in c]
        if run_cols and total_cols:
            rcol = run_cols[0]
            tcol = total_cols[0]
            metrics.append(
                {
                    "metric_name": f"utilization_{rcol}_per_{tcol}",
                    "formula": f"SUM({rcol}) / NULLIF(SUM({tcol}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "utilization",
                }
            )
        # yield metrics (good / total)
        good_cols = [c for c in cols if "good" in c or "pass" in c or "ok" in c]
        total_cols = [c for c in cols if "total" in c]
        if good_cols and total_cols:
            gcol = good_cols[0]
            tcol = total_cols[0]
            metrics.append(
                {
                    "metric_name": f"yield_{gcol}_per_{tcol}",
                    "formula": f"SUM({gcol}) / NULLIF(SUM({tcol}), 0)",
                    "base_table": table.get("name"),
                    "metric_type": "yield",
                }
            )
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
        numeric = table.get("numeric_columns") or []
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
        numeric = picked.get("numeric_columns") or []
        time_cols = picked.get("time_columns") or []
        categorical = picked.get("categorical_columns") or []
        metric_col = numeric[0] if numeric else None
        time_col = time_cols[0] if time_cols else None
        category_col = categorical[0] if categorical else None

    metric_name = None
    if metric_col:
        # prefer derived metrics for the picked table if available
        derived = [m for m in metrics if m.get("base_table") == table_name and m.get("metric_type")]
        if derived:
            metric_name = derived[0].get("metric_name")
        else:
            metric_name = f"sum_{metric_col}"

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
        if not (table.get("numeric_columns") and table.get("time_columns")):
            continue
        view_suggestions.append(
            {
                "table": table.get("name"),
                "time_column": (table.get("time_columns") or [None])[0],
                "category_column": (table.get("categorical_columns") or [None])[0],
                "metric_column": (table.get("numeric_columns") or [None])[0],
                "recommended_view": f"{table.get('name')}_overview",
            }
        )
    if not metric_name and metrics:
        metric_name = metrics[0].get("metric_name")
    metric_name = metric_name or "metric"

    charts.append(
        {
            "type": "line",
            "title": "Trend",
            "metric": metric_name,
            "table": table_name,
            "metric_column": metric_col,
            "time_column": time_col,
            "category_column": category_col,
        }
    )
    charts.append(
        {
            "type": "bar",
            "title": "Breakdown",
            "metric": metric_name,
            "table": table_name,
            "metric_column": metric_col,
            "time_column": time_col,
            "category_column": category_col,
        }
    )
    charts.append(
        {
            "type": "pie",
            "title": "Share",
            "metric": metric_name,
            "table": table_name,
            "metric_column": metric_col,
            "time_column": time_col,
            "category_column": category_col,
        }
    )
    return {
        "title": "Auto Dashboard",
        "charts": charts,
        "view_suggestions": view_suggestions,
        "story": {
            "title": "KPI Overview",
            "cards": [
                {"title": "Trend", "summary": "Track the KPI trend over time."},
                {"title": "Breakdown", "summary": "Compare categories to spot leaders."},
                {"title": "Share", "summary": "See contribution by category."},
            ],
        },
    }
