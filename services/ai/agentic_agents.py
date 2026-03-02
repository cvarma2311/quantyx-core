from __future__ import annotations

from typing import Any

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
    tables = []
    for table in schema_payload.get("tables", []) or []:
        columns = []
        for col in table.get("columns", []) or []:
            columns.append(
                {
                    "name": col.get("name"),
                    "data_type": str(col.get("data_type") or "").lower(),
                }
            )
        tables.append({"name": table.get("table"), "columns": columns})
    return {"tables": tables}


def profile_tables(settings: Settings, schema_graph: dict[str, Any], schema_name: str) -> dict[str, Any]:
    profiling: dict[str, Any] = {"tables": []}
    for table in schema_graph.get("tables", []):
        name = table.get("name")
        if not name:
            continue
        columns = table.get("columns", [])
        numeric = [c["name"] for c in columns if c.get("data_type") in NUMERIC_TYPES]
        time_cols = [c["name"] for c in columns if c.get("data_type") in TIME_TYPES]
        categorical = [c["name"] for c in columns if c.get("data_type") not in NUMERIC_TYPES | TIME_TYPES]
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
        profiling["tables"].append(
            {
                "name": name,
                "row_count": row_count,
                "numeric_columns": numeric,
                "time_columns": time_cols,
                "categorical_columns": categorical,
            }
        )
    return profiling


def extract_context(settings: Settings, context_text: str | None, schema_graph: dict[str, Any]) -> dict[str, Any]:
    if not context_text:
        return {"context_entities": [], "hierarchy_hints": [], "glossary_terms": []}
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

    return {
        "concepts": concepts,
        "hierarchy_edges": hierarchy_edges,
        "synonym_edges": synonym_edges,
    }


def propose_joins(schema_graph: dict[str, Any]) -> list[dict[str, Any]]:
    joins = []
    tables = schema_graph.get("tables", [])
    for left in tables:
        left_cols = {c.get("name") for c in left.get("columns", [])}
        for right in tables:
            if left is right:
                continue
            right_cols = {c.get("name") for c in right.get("columns", [])}
            common = [c for c in left_cols & right_cols if c and (c.endswith("_id") or c.endswith("_code"))]
            for col in common:
                joins.append(
                    {
                        "left_table": left.get("name"),
                        "right_table": right.get("name"),
                        "left_key": col,
                        "right_key": col,
                        "confidence": 0.6,
                    }
                )
    return joins


def propose_metrics(profiling: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = []
    for table in profiling.get("tables", []):
        for col in table.get("numeric_columns", [])[:10]:
            metrics.append(
                {
                    "metric_name": f"sum_{col}",
                    "formula": f"SUM({col})",
                    "base_table": table.get("name"),
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
        if not time_cols:
            continue
        dimensions = [time_cols[0]]
        if cat_cols:
            dimensions.append(cat_cols[0])
        rollups.append(
            {
                "metric_name": metric_name,
                "dimensions": dimensions,
                "time_grain": "month",
            }
        )
    return rollups


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
        metric_name = f"sum_{metric_col}"
    elif metrics:
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
        "story": {
            "title": "KPI Overview",
            "cards": [
                {"title": "Trend", "summary": "Track the KPI trend over time."},
                {"title": "Breakdown", "summary": "Compare categories to spot leaders."},
                {"title": "Share", "summary": "See contribution by category."},
            ],
        },
    }
