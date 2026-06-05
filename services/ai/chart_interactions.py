from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings
from services.ai.hierarchy_store import list_business_hierarchies
from services.ai.db import run_query, ScopedConnection
from services.ai.charts import build_chart_payload, build_chart_inference


_ci_logger = logging.getLogger("quantyx.chart_interactions")


def _is_date_like(value: Any) -> bool:
    if isinstance(value, (datetime, date)):
        return True
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _sql_metric_expressions(sql: str) -> dict[str, str]:
    """Parse SELECT clause to extract aggregate expressions.

    Returns {alias_lower: full_expression} for aggregate items (those with parentheses).
    e.g. "SUM(t.\"qty_in_kg\") AS value" → {"value": "SUM(t.\"qty_in_kg\")"}
    """
    mapping: dict[str, str] = {}
    if not sql:
        return mapping
    select_match = re.search(r"(?i)\bSELECT\b(.+?)\bFROM\b", sql, re.DOTALL)
    if not select_match:
        return mapping
    select_clause = select_match.group(1)
    for item in select_clause.split(","):
        item = item.strip()
        if "(" not in item:
            continue
        # Match: EXPR AS alias  (alias at the end)
        alias_match = re.search(r'(.+)\s+AS\s+["\']?(\w+)["\']?\s*$', item, re.IGNORECASE)
        if alias_match:
            expression = alias_match.group(1).strip()
            alias = alias_match.group(2).strip().strip('"').strip("'")
            if expression and alias:
                mapping[alias.lower()] = expression
    return mapping


def _sql_alias_to_column(sql: str) -> dict[str, str]:
    """Parse SELECT clause to build alias→real_column mapping.

    Handles patterns like:
      t."zone" AS category
      "zone" AS category
      zone AS category
    Returns {alias: real_column} for all dimension-like columns (non-aggregate).
    """
    mapping: dict[str, str] = {}
    if not sql:
        return mapping
    # Extract the SELECT ... FROM portion
    select_match = re.search(r"(?i)\bSELECT\b(.+?)\bFROM\b", sql, re.DOTALL)
    if not select_match:
        return mapping
    select_clause = select_match.group(1)
    # Split by comma — each item is one selected expression
    for item in select_clause.split(","):
        item = item.strip()
        # Skip aggregate expressions (contain parentheses → SUM, COUNT, AVG, etc.)
        if "(" in item:
            continue
        # Match: [table.]"column" AS alias  or  [table.]column AS alias
        alias_match = re.search(
            r'(?:[\w]+\.)?["\']?(\w+)["\']?\s+AS\s+["\']?(\w+)["\']?',
            item,
            re.IGNORECASE,
        )
        if alias_match:
            real_col = alias_match.group(1).strip().strip('"').strip("'")
            alias = alias_match.group(2).strip().strip('"').strip("'")
            if real_col and alias and real_col.lower() != alias.lower():
                mapping[alias.lower()] = real_col
    return mapping


def _resolve_filter_aliases(filters: list[dict[str, Any]], alias_map: dict[str, str]) -> list[dict[str, Any]]:
    if not filters or not alias_map:
        return filters
    resolved: list[dict[str, Any]] = []
    for flt in filters:
        if not isinstance(flt, dict):
            continue
        field = str(flt.get("field") or "").strip()
        physical_field = alias_map.get(field.lower()) if field else None
        resolved.append({**flt, "field": physical_field or field})
    return resolved


def _normalized_dimensions(chart_row: dict[str, Any]) -> list[str]:
    query_payload = chart_row.get("query_payload") or {}
    source_dims = [str(v) for v in (query_payload.get("source_dimensions") or []) if str(v).strip()]
    if source_dims:
        return source_dims
    fallback_source_dims: list[str] = []
    time_col = str(query_payload.get("time_column") or query_payload.get("time_dimension") or "").strip()
    category_col = str(query_payload.get("category_column") or "").strip()
    if time_col:
        fallback_source_dims.append(time_col)
    if category_col and category_col not in fallback_source_dims:
        fallback_source_dims.append(category_col)
    if fallback_source_dims:
        return fallback_source_dims
    dims = [str(v) for v in (query_payload.get("dimensions") or []) if str(v).strip()]
    if not dims:
        return dims
    # Resolve SQL aliases to real column names so hierarchy matching works
    # e.g. query_payload.dimensions=["category"] but SQL has t."zone" AS category
    alias_map = _sql_alias_to_column(str(chart_row.get("sql") or ""))
    return [alias_map.get(d.lower(), d) for d in dims]


def _detect_time_dimension(chart_row: dict[str, Any], dims: list[str]) -> str | None:
    query_payload = chart_row.get("query_payload") or {}
    for key in ("time_dimension", "time_column"):
        value = str(query_payload.get(key) or "").strip()
        if value:
            return value
    for dim in dims:
        lowered = dim.lower()
        if lowered in {"date", "period", "month", "week", "day", "transaction_date", "process_date"}:
            return dim
    rows = (chart_row.get("rows_json") or [])[:3]
    for dim in dims:
        values = [row.get(dim) for row in rows if isinstance(row, dict)]
        if values and all(_is_date_like(v) for v in values):
            return dim
    return None


def _match_level_bindings(dim: str, hierarchies: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int]]:
    lowered = dim.lower()
    matches: list[tuple[dict[str, Any], int]] = []
    for hierarchy in hierarchies:
        levels = hierarchy.get("levels_json") or []
        for idx, level in enumerate(levels):
            candidates = {
                str(level.get("level_id") or "").lower(),
                str(level.get("column") or "").lower(),
                str(level.get("label") or "").lower().replace(" ", "_"),
            }
            if lowered in candidates:
                matches.append((hierarchy, idx))
                break
    return matches


def _select_primary_binding(
    bindings: list[tuple[dict[str, Any], int]],
    *,
    preferred_hierarchy_id: str | None = None,
) -> tuple[dict[str, Any], int] | None:
    if not bindings:
        return None
    if preferred_hierarchy_id:
        chosen = next(
            (
                (hierarchy, idx)
                for hierarchy, idx in bindings
                if str(hierarchy.get("hierarchy_id") or "").strip() == preferred_hierarchy_id
            ),
            None,
        )
        if chosen:
            return chosen
    ranked = sorted(
        bindings,
        key=lambda item: (
            0 if bool(item[0].get("preferred")) else 1,
            -float(item[0].get("confidence_score") or 0.0),
            str(item[0].get("hierarchy_id") or ""),
        ),
    )
    return ranked[0]


def _build_dimension_navigation(hierarchy: dict[str, Any], current_idx: int) -> list[dict[str, Any]]:
    levels = hierarchy.get("levels_json") or []
    current_level_id = str((levels[current_idx] or {}).get("level_id") or "")
    items: list[dict[str, Any]] = []
    for idx, level in enumerate(levels):
        target = str(level.get("level_id") or "").strip()
        if not target or target == current_level_id:
            continue
        if idx < current_idx:
            action_type = "drill_up"
            relation = "ancestor"
        elif idx > current_idx:
            action_type = "drill_down"
            relation = "descendant"
        else:
            action_type = "switch_level"
            relation = "peer"
        items.append(
            {
                "hierarchy_id": hierarchy.get("hierarchy_id"),
                "source_level_id": current_level_id,
                "target_level_id": target,
                "action_type": action_type,
                "relation": relation,
                "distance": abs(idx - current_idx),
                "label": f"View by {str(level.get('label') or target).strip()}",
                "priority": abs(idx - current_idx),
            }
        )
    return items


def _build_alternate_switch_navigation(
    *,
    bindings: list[tuple[dict[str, Any], int]],
    current_level_id: str,
    primary_hierarchy_id: str | None,
    existing_target_ids: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for hierarchy, idx in bindings:
        hierarchy_id = str(hierarchy.get("hierarchy_id") or "").strip()
        if hierarchy_id == (primary_hierarchy_id or ""):
            continue
        levels = hierarchy.get("levels_json") or []
        for level_idx, level in enumerate(levels):
            target = str(level.get("level_id") or "").strip()
            if not target or target == current_level_id or target in existing_target_ids:
                continue
            items.append(
                {
                    "hierarchy_id": hierarchy_id,
                    "source_level_id": current_level_id,
                    "target_level_id": target,
                    "action_type": "switch_level",
                    "relation": "peer",
                    "distance": abs(level_idx - idx),
                    "label": f"View by {str(level.get('label') or target).strip()}",
                    "priority": 10 + abs(level_idx - idx),
                }
            )
            existing_target_ids.add(target)
    return items


def build_chart_interaction_context(
    *,
    chart_row: dict[str, Any],
    hierarchies: list[dict[str, Any]],
) -> dict[str, Any]:
    query_payload = chart_row.get("query_payload") or {}
    dims = _normalized_dimensions(chart_row)
    time_dimension = _detect_time_dimension(chart_row, dims)
    group_dimensions = [dim for dim in dims if dim != time_dimension]
    current_level = group_dimensions[0] if group_dimensions else None
    preferred_hierarchy_id = str(chart_row.get("drill_hierarchy_id") or "").strip() or None
    metric_expressions = []
    for metric in query_payload.get("metrics") or []:
        metric_name = str(metric or "").strip()
        if metric_name:
            metric_expressions.append({"metric_id": metric_name, "expression": None})
    if not metric_expressions and query_payload.get("metric_name"):
        metric_expressions.append({"metric_id": str(query_payload.get("metric_name")), "expression": None})
    bindings = _match_level_bindings(current_level, hierarchies) if current_level else []
    binding = _select_primary_binding(bindings, preferred_hierarchy_id=preferred_hierarchy_id) if current_level else None
    hierarchy_bindings: dict[str, Any] = {}
    available_dimension_navigation: list[dict[str, Any]] = []
    available_drilldowns: list[dict[str, Any]] = []
    suggested_drilldowns: list[dict[str, Any]] = []
    if binding and current_level:
        hierarchy, idx = binding
        levels = hierarchy.get("levels_json") or []
        next_level = str((levels[idx + 1] or {}).get("level_id") or "").strip() if idx + 1 < len(levels) else None
        hierarchy_bindings[current_level] = {
            "hierarchy_id": hierarchy.get("hierarchy_id"),
            "current_level_id": current_level,
            "next_level_id": next_level,
        }
        available_dimension_navigation = _build_dimension_navigation(hierarchy, idx)
        seen_targets = {
            str(item.get("target_level_id") or "").strip()
            for item in available_dimension_navigation
            if str(item.get("target_level_id") or "").strip()
        }
        available_dimension_navigation.extend(
            _build_alternate_switch_navigation(
                bindings=bindings,
                current_level_id=current_level,
                primary_hierarchy_id=str(hierarchy.get("hierarchy_id") or "").strip() or None,
                existing_target_ids=seen_targets,
            )
        )
        available_dimension_navigation = sorted(
            available_dimension_navigation,
            key=lambda item: (
                {"drill_down": 0, "switch_level": 1, "drill_up": 2}.get(str(item.get("action_type") or ""), 3),
                int(item.get("priority") or 999),
                str(item.get("label") or ""),
            ),
        )
        available_drilldowns = [item for item in available_dimension_navigation if item.get("action_type") == "drill_down"]
        suggested_drilldowns = [
            {**item, "reason": "preferred next level from persisted business hierarchy"}
            for item in available_drilldowns[:2]
        ]
        _ci_logger.info(
            "chart_interactions.binding_selected | chart_id=%s title=%s current_level=%s hierarchy_id=%s available_drilldowns=%s suggested_drilldowns=%s",
            chart_row.get("chart_id"),
            chart_row.get("title") or chart_row.get("question"),
            current_level,
            hierarchy.get("hierarchy_id"),
            len(available_drilldowns),
            len(suggested_drilldowns),
        )
    else:
        _ci_logger.info(
            "chart_interactions.binding_missing | chart_id=%s title=%s current_level=%s candidate_bindings=%s preferred_hierarchy_id=%s hierarchy_count=%s",
            chart_row.get("chart_id"),
            chart_row.get("title") or chart_row.get("question"),
            current_level,
            len(bindings),
            preferred_hierarchy_id,
            len(hierarchies or []),
        )
    available_filter_fields = [{"field": dim, "kind": "dimension", "label": dim.replace("_", " ").title()} for dim in group_dimensions]
    if time_dimension:
        available_filter_fields.append({"field": time_dimension, "kind": "time", "label": time_dimension.replace("_", " ").title()})
    interaction_context = {
        "source_scope": {
            "schema_name": query_payload.get("schema_name") or "public",
            "base_table": query_payload.get("table"),
            "base_view": query_payload.get("view"),
        },
        "query_shape": {
            "metric_expressions": metric_expressions,
            "group_dimensions": group_dimensions,
            "series_dimension": query_payload.get("series_dimension"),
            "time_dimension": time_dimension,
            "query_grain": query_payload.get("time_grain") or query_payload.get("query_grain"),
            "chart_intent": query_payload.get("chart_intent") or query_payload.get("chart"),
        },
        "filters": query_payload.get("filters") or [],
        "current_level": current_level,
        "hierarchy_bindings": hierarchy_bindings,
        "available_filter_fields": available_filter_fields,
        "available_drilldowns": available_drilldowns,
        "available_dimension_navigation": available_dimension_navigation,
        "suggested_drilldowns": suggested_drilldowns,
        "lineage": chart_row.get("lineage_json") or {
            "root_chart_id": chart_row.get("root_chart_id") or chart_row.get("chart_id"),
            "parent_chart_id": chart_row.get("parent_chart_id"),
            "interaction_type": None,
        },
    }
    return interaction_context


def build_chart_interaction_response(
    *,
    chart_row: dict[str, Any],
    interaction_context: dict[str, Any] | None,
) -> dict[str, Any]:
    ctx = interaction_context or {}
    lineage = ctx.get("lineage") or {}
    hierarchy_bindings = ctx.get("hierarchy_bindings") or {}
    available_areas = {
        "dimensions": (ctx.get("query_shape") or {}).get("group_dimensions") or [],
        "time": [v for v in [(ctx.get("query_shape") or {}).get("time_dimension")] if v],
        "series": [v for v in [(ctx.get("query_shape") or {}).get("series_dimension")] if v],
        "drill_paths": [
            {
                "hierarchy_id": value.get("hierarchy_id"),
                "current_level": key,
            }
            for key, value in hierarchy_bindings.items()
            if isinstance(value, dict) and value.get("hierarchy_id")
        ],
    }
    breadcrumb = []
    if lineage.get("parent_chart_id"):
        breadcrumb.append(
            {
                "chart_id": lineage.get("parent_chart_id"),
                "level_id": ctx.get("current_level"),
            }
        )
    return {
        "interaction_context": {
            "source_table": ((ctx.get("source_scope") or {}).get("base_table")),
            "time_dimension": (ctx.get("query_shape") or {}).get("time_dimension"),
            "group_dimensions": (ctx.get("query_shape") or {}).get("group_dimensions") or [],
            "query_grain": (ctx.get("query_shape") or {}).get("query_grain"),
            "current_level": ctx.get("current_level"),
        },
        "available_filters": ctx.get("available_filter_fields") or [],
        "available_drilldowns": ctx.get("available_drilldowns") or [],
        "available_dimension_navigation": ctx.get("available_dimension_navigation") or [],
        "suggested_drilldowns": ctx.get("suggested_drilldowns") or [],
        "available_areas": available_areas,
        "breadcrumb": breadcrumb,
        "lineage_summary": {
            "root_chart_id": chart_row.get("root_chart_id") or chart_row.get("chart_id"),
            "parent_chart_id": chart_row.get("parent_chart_id"),
            "depth": 1 if chart_row.get("parent_chart_id") else 0,
        },
    }


def ensure_chart_interaction_metadata(settings: Settings, chart_row: dict[str, Any]) -> dict[str, Any]:
    tenant_id = str(chart_row.get("tenant_id") or "").strip()
    domain_id = str(chart_row.get("domain_id") or "").strip() or None
    if not tenant_id:
        return chart_row
    hierarchies = list_business_hierarchies(settings, tenant_id, domain_id)
    interaction_context = chart_row.get("interaction_context_json") or {}
    if not interaction_context:
        interaction_context = build_chart_interaction_context(chart_row=chart_row, hierarchies=hierarchies)
    return {
        **chart_row,
        "interaction_context_json": interaction_context,
    }


def build_chart_interaction_context_for_creation(
    settings: Settings,
    *,
    chart_row: dict[str, Any],
    tenant_id: str,
    domain_id: str | None,
    hierarchies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_hierarchies = hierarchies if hierarchies is not None else list_business_hierarchies(settings, tenant_id, domain_id)
    return build_chart_interaction_context(
        chart_row=chart_row,
        hierarchies=resolved_hierarchies,
    )


def _qident(name: str) -> str:
    safe = str(name or "").strip()
    return '"' + safe.replace('"', '""') + '"'


def _conn(settings: Settings):
    return psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )


def create_chart_interaction(
    settings: Settings,
    *,
    interaction_id: str,
    tenant_id: str,
    domain_id: str | None,
    source_chart_id: str,
    result_chart_id: str | None,
    interaction_type: str,
    selected_dimension: str | None = None,
    selected_value_json: Any = None,
    source_level_id: str | None = None,
    target_level_id: str | None = None,
    interaction_payload_json: dict[str, Any] | None = None,
) -> None:
    conn = _conn(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.quantyx_chart_interactions
                  (interaction_id, tenant_id, domain_id, source_chart_id, result_chart_id, interaction_type,
                   selected_dimension, selected_value_json, source_level_id, target_level_id, interaction_payload_json)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb)
                """,
                [
                    interaction_id,
                    tenant_id,
                    domain_id,
                    source_chart_id,
                    result_chart_id,
                    interaction_type,
                    selected_dimension,
                    _jsonable(selected_value_json),
                    source_level_id,
                    target_level_id,
                    _jsonable(interaction_payload_json or {}),
                ],
            )
        conn.commit()
    finally:
        conn.close()


def _jsonable(value: Any) -> str:
    import json
    return json.dumps(value, default=lambda v: v.isoformat() if isinstance(v, (datetime, date)) else float(v) if isinstance(v, Decimal) else str(v))


def _normalize_filters(filters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in filters or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        operator = str(item.get("operator") or "=").strip()
        if not field:
            continue
        out.append(
            {
                "field": field,
                "operator": operator,
                "value": item.get("value"),
                "kind": item.get("kind"),
                "grain": item.get("grain"),
            }
        )
    return out


def _compile_where(filters: list[dict[str, Any]], alias: str) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for flt in filters:
        field = str(flt.get("field") or "").strip()
        op = str(flt.get("operator") or "=").strip().upper()
        value = flt.get("value")
        if not field:
            continue
        if op == "IN" and isinstance(value, list) and value:
            placeholders = ", ".join(["%s"] * len(value))
            clauses.append(f"{alias}.{_qident(field)} IN ({placeholders})")
            params.extend(value)
        elif op == "BETWEEN" and isinstance(value, list) and len(value) == 2:
            clauses.append(f"{alias}.{_qident(field)} BETWEEN %s AND %s")
            params.extend(value)
        elif op == "BUCKET_EQUALS":
            grain = str(flt.get("grain") or "month").strip().lower()
            clauses.append(f"date_trunc('{grain}', {alias}.{_qident(field)}) = %s")
            params.append(value)
        else:
            clauses.append(f"{alias}.{_qident(field)} {op} %s")
            params.append(value)
    return clauses, params


def _sql_select_output_columns(sql: str) -> list[str]:
    """Return the ordered output column names from a SELECT clause (using AS alias when present)."""
    columns: list[str] = []
    select_match = re.search(r"(?i)\bSELECT\b(.+?)\bFROM\b", sql, re.DOTALL)
    if not select_match:
        return columns
    for item in select_match.group(1).split(","):
        item = item.strip()
        alias_match = re.search(r'\s+AS\s+["\']?(\w+)["\']?\s*$', item, re.IGNORECASE)
        if alias_match:
            columns.append(alias_match.group(1).strip().strip('"').strip("'"))
        else:
            ident_match = re.search(r'["\']?(\w+)["\']?\s*$', item)
            if ident_match:
                columns.append(ident_match.group(1).strip().strip('"').strip("'"))
    return columns


def _inject_where_into_sql(
    original_sql: str,
    extra_filters: list[dict[str, Any]],
    alias: str = "t",
) -> tuple[str, list[Any]]:
    """Append extra WHERE conditions to an existing SQL string without rebuilding it.

    If the SQL already has a WHERE clause, the new conditions are ANDed in.
    If not, a WHERE clause is inserted before GROUP BY / ORDER BY / LIMIT.
    Returns (modified_sql, params).
    """
    if not extra_filters:
        return original_sql, []
    alias_map = _sql_alias_to_column(original_sql)
    filters = _resolve_filter_aliases(_normalize_filters(extra_filters), alias_map)
    clauses, params = _compile_where(filters, alias)
    if not clauses:
        return original_sql, []
    extra_sql = " AND ".join(clauses)
    where_match = re.search(r'(?i)\bWHERE\b', original_sql)
    keyword_match = re.search(r'(?i)\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b', original_sql)
    if where_match:
        if keyword_match:
            pos = keyword_match.start()
            modified = original_sql[:pos].rstrip() + f" AND {extra_sql} " + original_sql[pos:]
        else:
            modified = original_sql.rstrip() + f" AND {extra_sql}"
    else:
        if keyword_match:
            pos = keyword_match.start()
            modified = original_sql[:pos].rstrip() + f" WHERE {extra_sql} " + original_sql[pos:]
        else:
            modified = original_sql.rstrip() + f" WHERE {extra_sql}"
    return modified, params


def compile_chart_query(
    *,
    chart_row: dict[str, Any],
    interaction_context: dict[str, Any],
    override_dimensions: list[str] | None = None,
    appended_filters: list[dict[str, Any]] | None = None,
    limit: int = 200,
) -> tuple[str, list[Any], list[str], str]:
    """Rebuild SQL from scratch — used when dimensions change (drill-down/up/switch)."""
    query_shape = interaction_context.get("query_shape") or {}
    source_scope = interaction_context.get("source_scope") or {}
    table_name = str(source_scope.get("base_table") or "").strip()
    schema_name = str(source_scope.get("schema_name") or "public").strip()
    if not table_name:
        raise ValueError("chart interaction source_table_unavailable")
    metric_exprs = query_shape.get("metric_expressions") or []
    metric_entry = metric_exprs[0] if metric_exprs else {}
    metric_id = str(metric_entry.get("metric_id") or "").strip()
    expression = str(metric_entry.get("expression") or "").strip()
    if not expression:
        if not metric_id:
            raise ValueError("chart interaction metric_unavailable")
        original_sql = str(chart_row.get("sql") or "")
        sql_exprs = _sql_metric_expressions(original_sql) if original_sql else {}
        expression = (
            sql_exprs.get(metric_id.lower())
            or sql_exprs.get("value")
            or next(iter(sql_exprs.values()), None)
            or f"SUM(t.{_qident(metric_id)})"
        )
    dims = [str(v) for v in (override_dimensions if override_dimensions is not None else (query_shape.get("group_dimensions") or [])) if str(v).strip()]
    time_dimension = str(query_shape.get("time_dimension") or "").strip()
    query_grain = str(query_shape.get("query_grain") or "day").strip().lower()
    select_parts: list[str] = []
    group_parts: list[str] = []
    order_parts: list[str] = []
    output_dims: list[str] = []
    if time_dimension:
        time_expr = f"date_trunc('{query_grain}', t.{_qident(time_dimension)})"
        select_parts.append(f"{time_expr} AS period")
        group_parts.append(time_expr)
        order_parts.append("period ASC")
        output_dims.append("period")
    for dim in dims:
        select_parts.append(f"t.{_qident(dim)} AS {_qident(dim)}")
        group_parts.append(f"t.{_qident(dim)}")
        order_parts.append(f"{_qident(dim)} ASC")
        output_dims.append(dim)
    select_parts.append(f"{expression} AS value")
    original_sql = str(chart_row.get("sql") or "")
    alias_map = _sql_alias_to_column(original_sql)
    filters = _resolve_filter_aliases(_normalize_filters(interaction_context.get("filters") or []), alias_map)
    filters.extend(_resolve_filter_aliases(_normalize_filters(appended_filters), alias_map))
    where_clauses, sql_params = _compile_where(filters, "t")
    if time_dimension:
        where_clauses.insert(0, f"t.{_qident(time_dimension)} IS NOT NULL")
    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = (
        f"SELECT {', '.join(select_parts)} "
        f"FROM {_qident(schema_name)}.{_qident(table_name)} t"
        f"{where_sql} "
        f"GROUP BY {', '.join(group_parts)} "
        f"ORDER BY {', '.join(order_parts)} "
        f"LIMIT {int(limit)}"
    )
    return sql, sql_params, output_dims, metric_id or "value"


def execute_chart_compilation(
    settings: Settings,
    *,
    chart_row: dict[str, Any],
    interaction_context: dict[str, Any],
    override_dimensions: list[str] | None = None,
    appended_filters: list[dict[str, Any]] | None = None,
    scoped_conn: ScopedConnection | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    original_sql = str(chart_row.get("sql") or "").strip()

    # Filter-only: inject conditions directly into the original SQL — no rebuild
    if override_dimensions is None and original_sql and appended_filters:
        sql, sql_params = _inject_where_into_sql(original_sql, appended_filters)
        # Output column names come from the original SELECT clause
        out_cols = _sql_select_output_columns(original_sql)
        # Last column is the metric; the rest are dimensions
        output_dims = out_cols[:-1] if len(out_cols) > 1 else out_cols
        metric_name = out_cols[-1] if out_cols else "value"
    else:
        sql, sql_params, output_dims, metric_name = compile_chart_query(
            chart_row=chart_row,
            interaction_context=interaction_context,
            override_dimensions=override_dimensions,
            appended_filters=appended_filters,
            limit=limit,
        )

    rows = run_query(settings, sql, sql_params, scoped_conn=scoped_conn)
    chart_type = "line" if (interaction_context.get("query_shape") or {}).get("time_dimension") else "bar"
    payload = build_chart_payload(chart_type, rows, metric_name, output_dims or ["category"])
    dim_key = output_dims[0] if output_dims else None
    inference = build_chart_inference(
        settings,
        chart_type=chart_type,
        rows=rows,
        metric_name=metric_name,
        dim_key=dim_key,
        chart_title=str(chart_row.get("title") or chart_row.get("question") or "Derived Chart"),
    )
    return {
        "sql": sql,
        "params": sql_params,
        "rows": rows,
        "chart_type": chart_type,
        "chart_payload": payload.get("chart_payload"),
        "chart_data": payload.get("data"),
        "metric_name": metric_name,
        "dimensions": output_dims,
        "inference": inference,
    }
