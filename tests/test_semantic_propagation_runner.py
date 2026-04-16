from types import SimpleNamespace

import services.ai.semantic_propagation_runner as runner


def test_run_semantic_propagation_job_executes_supported_and_deferred_actions(monkeypatch) -> None:
    calls: dict[str, object] = {"statuses": [], "result": None}
    job = {
        "job_id": "semprop_1",
        "tenant_id": "tenant_a",
        "domain_id": "domain_a",
        "connection_id": "conn_1",
        "database_name": "db",
        "schema_name": "public",
        "trigger_type": "refinement_auto_approved",
        "affected_scope_json": {
            "refresh_actions": ["refresh_semantic_state", "refresh_chart_interaction_metadata", "refresh_metrics"],
            "affected_columns": ["region"],
        },
        "status": "queued",
    }

    monkeypatch.setattr(runner, "get_semantic_propagation_job", lambda settings, job_id, tenant_id: job)
    monkeypatch.setattr(
        runner,
        "update_semantic_propagation_job_status",
        lambda settings, job_id, status: calls["statuses"].append(status),
    )
    monkeypatch.setattr(
        runner,
        "update_semantic_propagation_job_result",
        lambda settings, job_id, status, affected_scope_json: calls.update(
            {"result": {"status": status, "affected_scope_json": affected_scope_json}}
        ),
    )
    monkeypatch.setattr(
        runner,
        "rebuild_semantic_state",
        lambda settings, **kwargs: {"semantic_state_id": "sem_state_1"},
    )
    monkeypatch.setattr(
        runner,
        "_refresh_chart_interaction_metadata",
        lambda settings, **kwargs: {
            "action": "refresh_chart_interaction_metadata",
            "status": "completed",
            "refreshed_chart_ids": ["chart_1"],
        },
    )
    monkeypatch.setattr(
        runner,
        "_refresh_metrics",
        lambda settings, **kwargs: {
            "action": "refresh_metrics",
            "status": "completed",
            "matched_artifact_count": 1,
            "applied": [{"artifact_id": "ref_art_metric", "status": "applied"}],
            "failed": [],
        },
    )

    result = runner.run_semantic_propagation_job(SimpleNamespace(), "semprop_1", tenant_id="tenant_a")

    assert calls["statuses"] == ["running"]
    assert result["status"] == "completed"
    action_results = result["affected_scope_json"]["action_results"]
    assert action_results[0] == {
        "action": "refresh_semantic_state",
        "status": "completed",
        "semantic_state_id": "sem_state_1",
    }
    assert action_results[1]["refreshed_chart_ids"] == ["chart_1"]
    assert action_results[2]["action"] == "refresh_metrics"
    assert action_results[2]["applied"] == [{"artifact_id": "ref_art_metric", "status": "applied"}]
    assert calls["result"]["status"] == "completed"


def test_chart_scope_match_uses_columns_metrics_and_tables() -> None:
    chart = {
        "query_payload": {
            "dimensions": ["region"],
            "metrics": ["total_volume"],
            "table": "fact_transactions",
        }
    }

    assert runner._chart_matches_scope(chart, {"affected_columns": ["region"]})
    assert runner._chart_matches_scope(chart, {"affected_metrics": ["total_volume"]})
    assert runner._chart_matches_scope(chart, {"affected_tables": ["fact_transactions"]})
    assert not runner._chart_matches_scope(chart, {"affected_columns": ["missing_column"]})


def test_refresh_metrics_upserts_refinement_metric(monkeypatch) -> None:
    upserted: list[dict] = []
    artifacts = [
        {
            "artifact_id": "ref_art_metric",
            "refinement_input_id": "ref_input_1",
            "tenant_id": "tenant_a",
            "domain_id": "domain_a",
            "artifact_type": "metric_refinement",
            "artifact_json": {
                "metric_name": "growth_rate",
                "description": "Use month over month",
                "formula": "month_over_month_growth",
                "grain": "month",
            },
            "approved_by": "system:auto_approve",
        }
    ]

    monkeypatch.setattr(runner, "_load_refinement_artifacts_for_scope", lambda settings, **kwargs: artifacts)
    monkeypatch.setattr(
        runner,
        "_current_metric_for_refinement",
        lambda settings, **kwargs: {
            "metric_name": "growth_rate",
            "artifact_key": "domain_a__growth_rate",
            "display_name": "Growth Rate",
            "description": "Old description",
            "type": "ratio",
            "sql": "old_sql",
            "dimensions": ["month"],
        },
    )
    monkeypatch.setattr(
        runner,
        "upsert_metric",
        lambda settings, payload: upserted.append(payload) or "domain_a__growth_rate__v2",
    )

    result = runner._refresh_metrics(
        SimpleNamespace(),
        tenant_id="tenant_a",
        domain_id="domain_a",
        job={"tenant_id": "tenant_a", "domain_id": "domain_a", "connection_id": "conn", "database_name": "db", "schema_name": "public"},
        scope={"artifact_ids": ["ref_art_metric"]},
    )

    assert result["status"] == "completed"
    assert result["applied"][0]["metric_id"] == "domain_a__growth_rate__v2"
    assert upserted[0]["source_type"] == "refinement"
    assert upserted[0]["description"] == "Use month over month"
    assert upserted[0]["grain"] == "month"
    assert upserted[0]["sql"] == "old_sql"
    assert upserted[0]["semantic_metadata"]["refinement_formula"] == "month_over_month_growth"


def test_refresh_hierarchies_persists_override_and_business_hierarchy(monkeypatch) -> None:
    executed: list[tuple[str, list]] = []
    business_hierarchies: list[dict] = []
    artifacts = [
        {
            "artifact_id": "ref_art_hier",
            "refinement_input_id": "ref_input_1",
            "tenant_id": "tenant_a",
            "domain_id": "domain_a",
            "artifact_type": "hierarchy_override",
            "artifact_json": {
                "name": "Geo Drill",
                "levels": ["zone", "region", "site"],
                "preferred": True,
                "description": "Preferred geo drill path",
            },
            "approved_by": "system:auto_approve",
        }
    ]

    monkeypatch.setattr(runner, "_load_refinement_artifacts_for_scope", lambda settings, **kwargs: artifacts)
    monkeypatch.setattr(runner, "_existing_current_hierarchy_override_version", lambda settings, **kwargs: (0, None))
    monkeypatch.setattr(runner, "execute_non_query", lambda settings, sql, params: executed.append((sql, params)))
    monkeypatch.setattr(
        runner,
        "upsert_business_hierarchies",
        lambda settings, hierarchies: business_hierarchies.extend(hierarchies),
    )

    result = runner._refresh_hierarchies(
        SimpleNamespace(),
        tenant_id="tenant_a",
        domain_id="domain_a",
        job={"tenant_id": "tenant_a", "domain_id": "domain_a", "connection_id": "conn", "database_name": "db", "schema_name": "public"},
        scope={"artifact_ids": ["ref_art_hier"]},
    )

    assert result["status"] == "completed"
    assert result["applied"][0]["levels"] == ["zone", "region", "site"]
    assert executed
    assert business_hierarchies[0]["name"] == "Geo Drill"
    assert business_hierarchies[0]["levels_json"] == [
        {"level_id": "zone", "column": "zone", "label": "Zone"},
        {"level_id": "region", "column": "region", "label": "Region"},
        {"level_id": "site", "column": "site", "label": "Site"},
    ]


def test_read_through_refresh_actions_load_active_state(monkeypatch) -> None:
    state = {
        "summary": {"approved_refinement_artifact_count": 3},
        "refinements": {
            "join_rules": [
                {"artifact_json": {"rule_type": "join_restriction", "left_table": "a", "right_table": "b", "allowed": False}},
                {"artifact_json": {"rule_type": "reference_table_usage", "table": "labels", "usage": "labels_only"}},
                {"artifact_json": {"rule_type": "exclusion_filter", "condition": "volume > 0"}},
            ],
            "interpretation_rules": [{"artifact_json": {"rule": "Ignore planned downtime"}}],
            "metric_overrides": [{"artifact_json": {"metric_name": "growth_rate"}}],
            "chart_guidance": [{"artifact_json": {"guidance": "Prefer monthly trends"}}],
        },
    }
    monkeypatch.setattr(runner, "load_active_semantic_state", lambda settings, **kwargs: state)

    job = {"connection_id": "conn", "database_name": "db", "schema_name": "public"}

    planner = runner._refresh_query_planner_constraints(SimpleNamespace(), tenant_id="tenant_a", domain_id="domain_a", job=job)
    workspace = runner._refresh_workspace_semantics(SimpleNamespace(), tenant_id="tenant_a", domain_id="domain_a", job=job)
    correlation = runner._refresh_anomaly_correlation_context(SimpleNamespace(), tenant_id="tenant_a", domain_id="domain_a", job=job)

    assert planner["restricted_join_pair_count"] == 2
    assert planner["excluded_table_count"] == 1
    assert planner["default_filter_count"] == 1
    assert workspace["approved_refinement_artifact_count"] == 3
    assert correlation["interpretation_rule_count"] == 1
    assert correlation["metric_refinement_count"] == 1
    assert correlation["chart_guidance_count"] == 1


def test_refresh_glossary_persists_semantic_terms(monkeypatch) -> None:
    monkeypatch.setattr(runner, "load_active_semantic_state", lambda settings, **kwargs: {"refinements": {}})
    monkeypatch.setattr(runner, "persist_semantic_glossary_terms", lambda settings, **kwargs: 2)

    result = runner._refresh_glossary(
        SimpleNamespace(),
        tenant_id="tenant_a",
        domain_id="domain_a",
        job={"connection_id": "conn", "database_name": "db", "schema_name": "public"},
    )

    assert result == {"action": "refresh_glossary", "status": "completed", "applied_term_count": 2}
