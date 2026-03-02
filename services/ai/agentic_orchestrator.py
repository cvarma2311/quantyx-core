from __future__ import annotations

from typing import Any

try:
    from langgraph.graph import StateGraph, END
except Exception:  # pragma: no cover
    StateGraph = None
    END = None

from services.ai.agentic_store import append_agent_run_event, append_agent_chat_log
from services.ai.agentic_agents import (
    build_schema_graph,
    profile_tables,
    extract_context,
    propose_ontology,
    propose_joins,
    propose_metrics,
    classify_models,
    propose_rollups,
    build_dashboard_spec,
)
from services.ai.semantic_graph_store import persist_semantic_graph, persist_dashboard_spec
from services.ai.views import create_views_from_schema
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
            {"tables": len(state["schema_graph"].get("tables", []))},
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
            {"tables": len(state["profiling_stats"].get("tables", []))},
        )
        return state

    def context_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "ContextAgent", "running", "Context Agent started")
        context_text = state.get("context_text")
        extracted = extract_context(settings, context_text, state.get("schema_graph", {}))
        state["context_entities"] = extracted.get("context_entities", [])
        state["hierarchy_hints"] = extracted.get("hierarchy_hints", [])
        state["glossary_terms"] = extracted.get("glossary_terms", [])
        _emit(
            settings,
            run_id,
            "ContextAgent",
            "completed",
            "Context Agent completed",
            {"entities": len(state["context_entities"])},
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
        _emit(
            settings,
            run_id,
            "GlossaryAgent",
            "completed",
            "Glossary Agent completed",
            {"terms": len(state["glossary_terms"])},
        )
        return state

    def ontology_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "OntologyAgent", "running", "Ontology Agent started")
        ontology = propose_ontology(
            state.get("context_entities") or [],
            state.get("hierarchy_hints") or [],
            state.get("glossary_terms") or [],
        )
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
            },
        )
        return state

    def join_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "JoinAgent", "running", "Join Agent started")
        state["join_edges"] = propose_joins(state.get("schema_graph", {}))
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
        _emit(
            settings,
            run_id,
            "JoinAgent",
            "completed",
            "Join Agent completed",
            {"joins": len(state["join_edges"])},
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
            {"metrics": len(state["metric_defs"])},
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
            {"models": len(state["model_classifications"])},
        )
        return state

    def rollup_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "RollupPlannerAgent", "running", "Rollup Planner Agent started")
        rollups = propose_rollups(state.get("metric_defs", []), state.get("profiling_stats", {}))
        created = 0
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
            except Exception:
                continue
        _emit(
            settings,
            run_id,
            "RollupPlannerAgent",
            "completed",
            "Rollup Planner Agent completed",
            {"rollups": created},
        )
        if created:
            append_agent_chat_log(settings, run_id, "system", f"Rollups created: {created}")
        return state

    def quality_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "QualityGateAgent", "running", "Quality Gate started")
        low_conf = 0
        total = 0
        for edge in (state.get("join_edges") or []):
            total += 1
            if edge.get("confidence") is not None and edge.get("confidence") < 0.7:
                low_conf += 1
        for edge in (state.get("ontology", {}).get("hierarchy_edges") or []):
            total += 1
            if edge.get("confidence") is not None and edge.get("confidence") < 0.7:
                low_conf += 1
        _emit(
            settings,
            run_id,
            "QualityGateAgent",
            "completed",
            "Quality Gate completed",
            {"edges_checked": total, "low_confidence": low_conf},
        )
        return state

    def dashboard_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(settings, run_id, "DashboardAgent", "running", "Dashboard Agent started")
        dashboard_spec = build_dashboard_spec(
            state.get("metric_defs", []),
            state.get("profiling_stats", {}),
        )
        charts_spec = dashboard_spec.get("charts", [])
        chart_ids = []
        schema_name = state.get("schema_name") or "public"
        enriched_charts = []
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

            if table_ref and metric_col:
                metric_expr = f"SUM({table_ref}.{metric_col})"
                if chart_type == "line":
                    if time_col:
                        dim_expr = f"date_trunc('month', {table_ref}.{time_col})"
                        dim_alias = "period"
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
                except Exception:
                    rows = []

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
                        "insight": insight,
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
                "chart_ids": chart_ids,
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
    graph.add_node("quality", quality_node)
    graph.add_node("dashboard", dashboard_node)

    graph.set_entry_point("schema")
    graph.add_edge("schema", "profiling")
    graph.add_edge("profiling", "context")
    graph.add_edge("context", "ontology")
    graph.add_edge("ontology", "glossary")
    graph.add_edge("glossary", "join")
    graph.add_edge("join", "metric")
    graph.add_edge("metric", "model")
    graph.add_edge("model", "rollup")
    graph.add_edge("rollup", "quality")
    graph.add_edge("quality", "dashboard")
    graph.add_edge("dashboard", END)

    app = graph.compile()
    return app.invoke(initial_state)
