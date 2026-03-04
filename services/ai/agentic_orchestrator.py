from __future__ import annotations

from typing import Any

try:
    from langgraph.graph import StateGraph, END
except Exception:  # pragma: no cover
    StateGraph = None
    END = None

from services.ai.agentic_store import append_agent_run_event, append_agent_chat_log
import logging
from services.ai.agentic_agents import (
    build_schema_graph,
    profile_tables,
    extract_context,
    propose_ontology,
    propose_joins,
    propose_metrics,
    propose_chart_candidates,
    select_charts,
    classify_models,
    propose_rollups,
    build_dashboard_spec,
)
from services.ai.semantic_graph_store import persist_semantic_graph, persist_dashboard_spec
from services.ai.views import create_views_from_schema, create_joined_views
from services.ai.charts_store import create_chart_request, update_chart_request
from services.ai.charts import build_chart_payload
from services.ai.db import run_query


def _log_agent_conversation(settings, run_id: str, payload: dict[str, Any], event_type: str) -> None:
    append_agent_run_event(
        settings,
        run_id,
        "AgentConversation",
        event_type,
        payload.get("question") or payload.get("answer") or "agent_conversation",
        payload,
    )


def _check_unique(settings, schema_name: str, table: str, column: str) -> tuple[bool | None, dict[str, Any]]:
    try:
        rows = run_query(
            settings,
            f"SELECT COUNT(*) AS cnt, COUNT(DISTINCT {column}) AS distinct_cnt FROM {schema_name}.{table}",
            [],
        )
        if not rows:
            return None, {}
        cnt = rows[0]["cnt"]
        distinct_cnt = rows[0]["distinct_cnt"]
        return cnt == distinct_cnt, {"row_count": cnt, "distinct_count": distinct_cnt}
    except Exception:
        return None, {}
from services.ai.rollups import create_rollup, build_rollup_table, update_rollup_status


def _emit(settings, run_id: str, agent_name: str, status: str, message: str, artifacts: dict[str, Any] | None = None) -> None:
    append_agent_run_event(settings, run_id, agent_name, status, message, artifacts)
    if status in {"running", "completed", "failed"}:
        append_agent_chat_log(settings, run_id, "agent", message, artifacts)
    logging.getLogger(__name__).info(
        "agentic.%s | status=%s message=%s artifacts=%s",
        agent_name,
        status,
        message,
        "none" if not artifacts else list(artifacts.keys()),
    )


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _chart_insight(chart_type: str, rows: list[dict], metric_name: str, dim_key: str | None) -> dict[str, Any]:
    if not rows or not metric_name:
        return {"summary": "No data available", "type": chart_type}
    if chart_type in {"bar", "pie"} and dim_key:
        best = None
        for row in rows:
            value = _safe_float(row.get(metric_name))
            if value is None:
                continue
            if not best or value > best[1]:
                best = (row.get(dim_key), value)
        if best:
            return {
                "summary": f"Top {dim_key}: {best[0]}",
                "value": best[1],
                "type": chart_type,
            }
    if chart_type == "line" and dim_key:
        ordered = []
        for row in rows:
            value = _safe_float(row.get(metric_name))
            if value is None:
                continue
            ordered.append((row.get(dim_key), value))
        if len(ordered) >= 2:
            last = ordered[-1]
            prev = ordered[-2]
            delta = last[1] - prev[1]
            return {
                "summary": f"Latest {metric_name}: {last[1]:.2f} (Δ {delta:.2f})",
                "value": last[1],
                "type": chart_type,
            }
        if ordered:
            return {
                "summary": f"Latest {metric_name}: {ordered[-1][1]:.2f}",
                "value": ordered[-1][1],
                "type": chart_type,
            }
    return {"summary": f"{metric_name} insights generated", "type": chart_type}


def _chart_stats(rows: list[dict], metric_name: str) -> dict[str, Any]:
    values = []
    for row in rows:
        value = _safe_float(row.get(metric_name))
        if value is not None:
            values.append(value)
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": sum(values) / len(values),
        "total": sum(values),
    }


def _chart_narrative(rows: list[dict], metric_name: str, dim_key: str | None) -> dict[str, Any]:
    if not rows or not metric_name:
        return {"summary": "No narrative available"}
    values = []
    for row in rows:
        value = _safe_float(row.get(metric_name))
        if value is None:
            continue
        values.append(value)
    if not values:
        return {"summary": "No narrative available"}
    best_idx = values.index(max(values))
    worst_idx = values.index(min(values))
    best_label = rows[best_idx].get(dim_key) if dim_key else None
    worst_label = rows[worst_idx].get(dim_key) if dim_key else None
    summary = f"Top {dim_key}: {best_label} ({values[best_idx]:.2f}); "
    summary += f"Lowest {dim_key}: {worst_label} ({values[worst_idx]:.2f})"
    return {"summary": summary, "top": best_label, "bottom": worst_label}


def _qualify_formula(formula: str, table_ref: str, table_profile: dict[str, Any]) -> str:
    cols = set((table_profile.get("numeric_columns") or []) + (table_profile.get("time_columns") or []) + (table_profile.get("categorical_columns") or []))
    qualified = formula
    for col in sorted(cols, key=len, reverse=True):
        qualified = qualified.replace(col, f"{table_ref}.{col}")
    return qualified


def run_agentic_workflow(settings, run_id: str, initial_state: dict[str, Any]) -> dict[str, Any]:
    if StateGraph is None:
        raise RuntimeError("LangGraph is not available")

    graph = StateGraph(dict)

    def schema_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "SchemaAgent", "running", "Schema Agent started")
        append_agent_chat_log(settings, run_id, "system", "Scanning schema for tables.")
        schema_payload = state.get("schema_payload") or {}
        state["schema_graph"] = build_schema_graph(schema_payload)
        _emit(
            settings,
            run_id,
            "SchemaAgent",
            "completed",
            "Schema Agent completed",
            {
                "tables": len(state["schema_graph"].get("tables", [])),
                "table_names": [t.get("name") for t in state["schema_graph"].get("tables", [])],
                "tables_detail": state["schema_graph"].get("tables", []),
            },
        )
        return state

    def profiling_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "ProfilingAgent", "running", "Profiling Agent started")
        schema_name = state.get("schema_name") or "public"
        state["profiling_stats"] = profile_tables(settings, state.get("schema_graph", {}), schema_name)
        append_agent_chat_log(
            settings,
            run_id,
            "system",
            "Profiling completed: detected %s tables."
            % len(state["profiling_stats"].get("tables", [])),
        )
        _emit(
            settings,
            run_id,
            "ProfilingAgent",
            "completed",
            "Profiling Agent completed",
            {
                "tables": len(state["profiling_stats"].get("tables", [])),
                "profiles": state["profiling_stats"].get("tables", []),
            },
        )
        return state

    def context_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "ContextAgent", "running", "Context Agent started")
        context_text = state.get("context_text")
        extracted = extract_context(settings, context_text, state.get("schema_graph", {}))
        state["context_entities"] = extracted.get("context_entities", [])
        state["hierarchy_hints"] = extracted.get("hierarchy_hints", [])
        state["glossary_terms"] = extracted.get("glossary_terms", [])
        if not state["glossary_terms"] and state.get("schema_graph"):
            # fallback if context extraction yielded nothing
            extracted = extract_context(settings, None, state.get("schema_graph", {}))
            state["context_entities"] = extracted.get("context_entities", [])
            state["hierarchy_hints"] = extracted.get("hierarchy_hints", [])
            state["glossary_terms"] = extracted.get("glossary_terms", [])
        _emit(
            settings,
            run_id,
            "ContextAgent",
            "completed",
            "Context Agent completed",
            {
                "entities": len(state["context_entities"]),
                "sample_entities": state["context_entities"][:10],
                "glossary_terms": state["glossary_terms"],
            },
        )
        if state.get("context_entities"):
            append_agent_chat_log(
                settings,
                run_id,
                "system",
                "Context applied: %s terms detected." % len(state["context_entities"]),
            )
        return state

    def glossary_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "GlossaryAgent", "running", "Glossary Agent started")
        if "glossary_terms" not in state:
            state["glossary_terms"] = []
        if not state["glossary_terms"] and state.get("profiling_stats"):
            inferred_terms = []
            for table in state["profiling_stats"].get("tables", []):
                name = table.get("name")
                if name:
                    inferred_terms.append({"term": name.replace("_", " "), "synonyms": [name], "abbreviations": []})
                for col in (table.get("numeric_columns") or []) + (table.get("time_columns") or []) + (
                    table.get("categorical_columns") or []
                ):
                    inferred_terms.append({"term": col.replace("_", " "), "synonyms": [col], "abbreviations": []})
            state["glossary_terms"] = inferred_terms
        _emit(
            settings,
            run_id,
            "GlossaryAgent",
            "completed",
            "Glossary Agent completed",
            {"terms": len(state["glossary_terms"]), "terms_detail": state["glossary_terms"]},
        )
        return state

    def ontology_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "OntologyAgent", "running", "Ontology Agent started")
        ontology = propose_ontology(
            state.get("context_entities") or [],
            state.get("hierarchy_hints") or [],
            state.get("glossary_terms") or [],
        )
        if not ontology.get("concepts") and state.get("profiling_stats"):
            inferred = []
            for table in state["profiling_stats"].get("tables", []):
                name = table.get("name")
                if name:
                    inferred.append(name.replace("_", " "))
            if inferred:
                ontology["concepts"] = inferred
        state["ontology"] = ontology
        _emit(
            settings,
            run_id,
            "OntologyAgent",
            "completed",
            "Ontology Agent completed",
            {
                "concepts": len(ontology.get("concepts", [])),
                "hierarchy_edges": len(ontology.get("hierarchy_edges", [])),
                "synonym_edges": len(ontology.get("synonym_edges", [])),
                "concepts_detail": ontology.get("concepts", []),
                "hierarchy_edges_detail": ontology.get("hierarchy_edges", []),
                "synonym_edges_detail": ontology.get("synonym_edges", []),
            },
        )
        return state

    def join_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "JoinAgent", "running", "Join Agent started")
        state["join_edges"] = propose_joins(
            state.get("schema_graph", {}),
            state.get("profiling_stats", {}),
        )
        schema_name = state.get("schema_name") or "public"
        # Agent-to-agent validation for first few joins
        for join in state["join_edges"][:2]:
            table = join.get("left_table")
            column = join.get("left_key")
            if not table or not column:
                continue
            request_payload = {
                "from_agent": "JoinAgent",
                "to_agent": "SchemaAgent",
                "question": f"Is {column} unique in {table}?",
                "expected_answer_type": "boolean",
                "context": {"table": table, "column": column},
            }
            _log_agent_conversation(settings, run_id, request_payload, "request")
            answer, evidence = _check_unique(settings, schema_name, table, column)
            response_payload = {
                "from_agent": "SchemaAgent",
                "to_agent": "JoinAgent",
                "answer": answer,
                "confidence": 0.9 if answer else 0.4 if answer is not None else 0.2,
                "evidence": evidence,
            }
            _log_agent_conversation(settings, run_id, response_payload, "response")
            if answer is not None:
                base_conf = join.get("confidence") or 0.5
                join["confidence"] = min(1.0, (base_conf + response_payload["confidence"]) / 2)
        # Join coverage check for top joins
        for join in state["join_edges"][:5]:
            left_table = join.get("left_table")
            right_table = join.get("right_table")
            left_key = join.get("left_key")
            right_key = join.get("right_key")
            if not (left_table and right_table and left_key and right_key):
                continue
            try:
                sql = (
                    f"SELECT COUNT(*) AS total, "
                    f"COUNT(*) FILTER (WHERE r.{right_key} IS NOT NULL) AS matched "
                    f"FROM {schema_name}.{left_table} l "
                    f"LEFT JOIN {schema_name}.{right_table} r "
                    f"ON l.{left_key} = r.{right_key}"
                )
                rows = run_query(settings, sql, [])
                if rows:
                    total = rows[0].get("total") or 0
                    matched = rows[0].get("matched") or 0
                    join["coverage_ratio"] = (matched / total) if total else None
                    join["coverage_total"] = total
                    join["coverage_matched"] = matched
            except Exception:
                continue
        _emit(
            settings,
            run_id,
            "JoinAgent",
            "completed",
            "Join Agent completed",
            {
                "joins": len(state["join_edges"]),
                "join_edges_detail": state["join_edges"],
            },
        )
        return state

    def metric_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "MetricAgent", "running", "Metric Agent started")
        state["metric_defs"] = propose_metrics(state.get("profiling_stats", {}))
        if state.get("metric_defs"):
            append_agent_chat_log(
                settings,
                run_id,
                "system",
                "Metrics generated: %s"
                % ", ".join([m.get("metric_name") for m in state["metric_defs"][:5]]),
            )
        _emit(
            settings,
            run_id,
            "MetricAgent",
            "completed",
            "Metric Agent completed",
            {"metrics": len(state["metric_defs"]), "metric_defs_detail": state["metric_defs"]},
        )
        return state

    def model_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "SemanticModelAgent", "running", "Semantic Model Agent started")
        state["model_classifications"] = classify_models(state.get("profiling_stats", {}))
        append_agent_chat_log(settings, run_id, "system", "Semantic model classified.")
        _emit(
            settings,
            run_id,
            "SemanticModelAgent",
            "completed",
            "Semantic Model Agent completed",
            {
                "models": len(state["model_classifications"]),
                "model_classifications_detail": state["model_classifications"],
            },
        )
        return state

    def rollup_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "RollupPlannerAgent", "running", "Rollup Planner Agent started")
        rollups = propose_rollups(state.get("metric_defs", []), state.get("profiling_stats", {}))
        created = 0
        created_defs: list[dict[str, Any]] = []
        for rollup in rollups:
            try:
                created_rollup = create_rollup(
                    settings,
                    tenant_id=state.get("tenant_id") or "",
                    domain_id=state.get("domain_id") or "",
                    metric_name=rollup["metric_name"],
                    dimensions=rollup["dimensions"],
                    time_grain=rollup["time_grain"],
                )
                update_rollup_status(settings, created_rollup["rollup_id"], "building")
                build_rollup_table(settings, created_rollup, schema_name=settings.db_schema)
                update_rollup_status(settings, created_rollup["rollup_id"], "active")
                created += 1
                created_defs.append(created_rollup)
            except Exception:
                continue
        _emit(
            settings,
            run_id,
            "RollupPlannerAgent",
            "completed",
            "Rollup Planner Agent completed",
            {"rollups": created, "rollup_defs": created_defs, "rollup_candidates": rollups},
        )
        if created:
            append_agent_chat_log(settings, run_id, "system", f"Rollups created: {created}")
        return state

    def chart_planner_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "ChartPlannerAgent", "running", "Chart Planner started")
        candidates = propose_chart_candidates(
            state.get("profiling_stats", {}),
            state.get("metric_defs", []),
            state.get("join_edges", []),
        )
        selected = select_charts(candidates, min_charts=4, max_charts=8)
        state["chart_candidates"] = candidates
        state["chart_plan"] = selected
        _emit(
            settings,
            run_id,
            "ChartPlannerAgent",
            "completed",
            "Chart Planner completed",
            {
                "candidates": len(candidates),
                "selected": len(selected),
                "chart_plan": selected,
            },
        )
        return state

    def quality_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "QualityGateAgent", "running", "Quality Gate started")
        low_conf = 0
        total = 0
        low_conf_edges: list[dict[str, Any]] = []
        for edge in (state.get("join_edges") or []):
            total += 1
            if edge.get("confidence") is not None and edge.get("confidence") < 0.7:
                low_conf += 1
                low_conf_edges.append(edge)
        for edge in (state.get("ontology", {}).get("hierarchy_edges") or []):
            total += 1
            if edge.get("confidence") is not None and edge.get("confidence") < 0.7:
                low_conf += 1
                low_conf_edges.append(edge)
        _emit(
            settings,
            run_id,
            "QualityGateAgent",
            "completed",
            "Quality Gate completed",
            {
                "edges_checked": total,
                "low_confidence": low_conf,
                "threshold": 0.7,
                "low_confidence_edges": low_conf_edges,
            },
        )
        return state

    def dashboard_node(state: dict[str, Any]) -> dict[str, Any]:
        logger = logging.getLogger(__name__)
        _emit(settings, run_id, "DashboardAgent", "running", "Dashboard Agent started")
        dashboard_spec = build_dashboard_spec(
            state.get("metric_defs", []),
            state.get("profiling_stats", {}),
        )
        charts_spec = state.get("chart_plan") or dashboard_spec.get("charts", [])
        dashboard_spec["chart_plan"] = state.get("chart_plan") or []
        dashboard_spec["chart_candidates"] = state.get("chart_candidates") or []
        chart_ids = []
        schema_name = state.get("schema_name") or "public"
        enriched_charts = []
        profiling_map = {t.get("name"): t for t in (state.get("profiling_stats", {}).get("tables") or [])}
        join_edges = state.get("join_edges") or []
        for chart in charts_spec:
            metric_name = chart.get("metric") or "metric"
            metric_col = chart.get("metric_column")
            table_name = chart.get("table")
            time_col = chart.get("time_column")
            category_col = chart.get("category_column")

            if table_name:
                fact_table = table_name if table_name.startswith("fact_") else f"fact_{table_name}"
                table_ref = f"{schema_name}.{fact_table}"
            else:
                fact_table = None
                table_ref = None

            chart_type = chart.get("type") or "bar"
            sql = None
            params: list[Any] = []
            dimensions: list[str] = []
            rows: list[dict] = []

            metric_expr = chart.get("metric_expr")
            metric_name = chart.get("metric") or metric_name
            if table_ref and metric_col:
                table_profile = profiling_map.get(table_name) or {}
                numeric_cols = set(table_profile.get("numeric_columns") or [])
                if metric_col in numeric_cols:
                    metric_expr = f"SUM({table_ref}.{metric_col})"
                else:
                    metric_expr = (
                        f"SUM(CASE WHEN {table_ref}.{metric_col}::text ~ '^[0-9]+(\\\\.[0-9]+)?$' "
                        f"THEN {table_ref}.{metric_col}::numeric END)"
                    )
                    logger.warning(
                        "dashboard.chart.metric_cast | table=%s column=%s",
                        table_name,
                        metric_col,
                    )
            if metric_expr and table_ref and not metric_expr.startswith("SUM("):
                metric_expr = _qualify_formula(metric_expr, table_ref, profiling_map.get(table_name) or {})
            if not metric_expr:
                logger.warning(
                    "dashboard.chart.skip | title=%s reason=invalid_metric metric=%s table=%s",
                    chart.get("title"),
                    metric_col,
                    table_name,
                )
                enriched_charts.append({**chart, "skipped": True, "reason": "invalid_metric"})
                continue

            # choose a better dimension using join metadata if none provided
            if not category_col:
                for edge in join_edges:
                    if edge.get("left_table") == table_name and edge.get("relationship") in {
                        "many_to_one",
                        "one_to_many",
                    }:
                        category_col = edge.get("left_key")
                        break

            if table_ref and metric_col:
                if chart_type == "line":
                    if time_col:
                        dim_expr = f"date_trunc('month', {table_ref}.{time_col})"
                        dim_alias = "period"
                        if category_col:
                            cat_alias = "category"
                            sql = (
                                f"SELECT {dim_expr} AS {dim_alias}, "
                                f"{table_ref}.{category_col} AS {cat_alias}, "
                                f"{metric_expr} AS \"{metric_name}\" "
                                f"FROM {table_ref} "
                                f"GROUP BY {dim_alias}, {cat_alias} "
                                f"ORDER BY {dim_alias} ASC "
                                f"LIMIT 500"
                            )
                            dimensions = [dim_alias, cat_alias]
                        else:
                            sql = (
                                f"SELECT {dim_expr} AS {dim_alias}, "
                                f"{metric_expr} AS \"{metric_name}\" "
                                f"FROM {table_ref} "
                                f"GROUP BY {dim_alias} "
                                f"ORDER BY {dim_alias} ASC "
                                f"LIMIT 200"
                            )
                            dimensions = [dim_alias]
                    elif category_col:
                        dim_alias = "category"
                        sql = (
                            f"SELECT {table_ref}.{category_col} AS {dim_alias}, "
                            f"{metric_expr} AS \"{metric_name}\" "
                            f"FROM {table_ref} "
                            f"GROUP BY {dim_alias} "
                            f"ORDER BY \"{metric_name}\" DESC "
                            f"LIMIT 50"
                        )
                        dimensions = [dim_alias]
                elif chart_type in {"bar", "pie"}:
                    dim_col = category_col or time_col
                    if dim_col:
                        dim_alias = "category"
                        limit = 20 if chart_type == "bar" else 10
                        sql = (
                            f"SELECT {table_ref}.{dim_col} AS {dim_alias}, "
                            f"{metric_expr} AS \"{metric_name}\" "
                            f"FROM {table_ref} "
                            f"GROUP BY {dim_alias} "
                            f"ORDER BY \"{metric_name}\" DESC "
                            f"LIMIT {limit}"
                        )
                        dimensions = [dim_alias]

            if sql:
                try:
                    rows = run_query(settings, sql, params)
                    logger.info(
                        "dashboard.chart.sql_ok | title=%s rows=%s",
                        chart.get("title"),
                        len(rows),
                    )
                except Exception as exc:
                    logger.exception(
                        "dashboard.chart.sql_failed | title=%s sql=%s params=%s",
                        chart.get("title"),
                        sql,
                        params,
                    )
                    rows = []
            logger.info(
                "dashboard.chart | title=%s type=%s table=%s sql=%s rows=%s",
                chart.get("title"),
                chart_type,
                table_ref,
                sql,
                len(rows),
            )

            chart_id = create_chart_request(
                settings,
                state.get("tenant_id") or "",
                state.get("domain_id"),
                question=chart.get("title"),
                query_payload={
                    "metrics": [metric_name],
                    "dimensions": dimensions,
                    "chart": chart_type,
                },
                sql=sql,
                params=params,
                rows_json=rows,
            ).get("chart_id")
            if chart_id:
                chart_ids.append(chart_id)
                payload = build_chart_payload(chart_type, rows, metric_name, dimensions or ["category"])
                dim_key = dimensions[0] if dimensions else None
                insight = _chart_insight(chart_type, rows, metric_name, dim_key)
                stats = _chart_stats(rows, metric_name)
                narrative = _chart_narrative(rows, metric_name, dim_key)
                update_chart_request(
                    settings,
                    chart_id,
                    status="ready",
                    sql=sql,
                    params=params,
                    rows_json=rows,
                    chart_type=chart_type,
                    chart_payload=payload.get("chart_payload"),
                    chart_data=payload.get("data"),
                )
                enriched_charts.append(
                    {
                        **chart,
                        "chart_id": chart_id,
                        "chart_type": chart_type,
                        "dimensions": dimensions,
                        "metric_name": metric_name,
                        "sql": sql,
                        "rows_count": len(rows),
                        "insight": insight,
                        "stats": stats,
                        "narrative": narrative,
                        "chart_payload": payload.get("chart_payload"),
                        "chart_data": payload.get("data"),
                    }
                )
            else:
                enriched_charts.append(chart)

        dashboard_spec["charts"] = enriched_charts
        dashboard_spec["story"] = {
            "title": dashboard_spec.get("title") or "Auto Dashboard",
            "cards": [
                {
                    "title": "Trend",
                    "summary": "Track change over time with a KPI trend chart.",
                },
                {
                    "title": "Breakdown",
                    "summary": "Compare categories to identify top contributors.",
                },
                {
                    "title": "Share",
                    "summary": "Visualize distribution across key categories.",
                },
            ],
        }
        dashboard_spec["insights"] = [chart.get("insight") for chart in enriched_charts if chart.get("insight")]
        state["dashboard_spec"] = dashboard_spec
        append_agent_chat_log(
            settings,
            run_id,
            "system",
            f"Dashboard ready: {dashboard_spec.get('title')}",
        )
        counts = persist_semantic_graph(
            settings,
            state.get("domain_id") or "",
            state.get("schema_graph", {}),
            state.get("profiling_stats", {}),
            state.get("join_edges", []),
            state.get("metric_defs", []),
            glossary_terms=state.get("glossary_terms", []),
            hierarchy_hints=state.get("hierarchy_hints", []),
            ontology=state.get("ontology", {}),
            model_classifications=state.get("model_classifications", []),
        )
        created_views = create_views_from_schema(
            settings,
            state.get("tenant_id") or "",
            state.get("domain_id") or "",
            state.get("connection_id") or "",
            state.get("database_name") or "",
            state.get("schema_name") or "public",
            state.get("schema_payload") or {},
        )
        joined_views = create_joined_views(
            settings,
            state.get("tenant_id") or "",
            state.get("domain_id") or "",
            state.get("schema_name") or "public",
            state.get("join_edges") or [],
        )
        dash_id = persist_dashboard_spec(
            settings,
            state.get("tenant_id") or "",
            state.get("domain_id") or "",
            dashboard_spec,
        )
        _emit(
            settings,
            run_id,
            "DashboardAgent",
            "completed",
            "Dashboard Agent completed",
            {
                "charts": len(state["dashboard_spec"].get("charts", [])),
                "semantic_nodes": counts.get("nodes"),
                "semantic_edges": counts.get("edges"),
                "dashboard_id": dash_id,
                "views": len(created_views),
                "joined_views": joined_views,
                "chart_ids": chart_ids,
                "chart_details": enriched_charts,
                "views_detail": created_views,
            },
        )
        return state

    graph.add_node("schema", schema_node)
    graph.add_node("profiling", profiling_node)
    graph.add_node("context", context_node)
    graph.add_node("ontology", ontology_node)
    graph.add_node("glossary", glossary_node)
    graph.add_node("join", join_node)
    graph.add_node("metric", metric_node)
    graph.add_node("model", model_node)
    graph.add_node("rollup", rollup_node)
    graph.add_node("chart_planner", chart_planner_node)
    graph.add_node("quality", quality_node)
    graph.add_node("dashboard", dashboard_node)

    graph.set_entry_point("schema")
    # Parallel branches after schema
    graph.add_edge("schema", "profiling")
    graph.add_edge("schema", "context")

    # Context branch
    graph.add_edge("context", "ontology")
    graph.add_edge("ontology", "glossary")

    # Profiling branch to join/metric/model in parallel
    graph.add_edge("profiling", "join")
    graph.add_edge("profiling", "metric")
    graph.add_edge("profiling", "model")

    # Rollup depends on metric + profiling (profiling already done)
    graph.add_edge("metric", "rollup")

    # Quality depends on join + ontology
    graph.add_edge("join", "quality")
    graph.add_edge("ontology", "quality")

    # Dashboard waits on rollup + quality
    graph.add_edge("rollup", "chart_planner")
    graph.add_edge("quality", "chart_planner")
    graph.add_edge("chart_planner", "dashboard")
    graph.add_edge("dashboard", END)

    app = graph.compile()
    return app.invoke(initial_state)
