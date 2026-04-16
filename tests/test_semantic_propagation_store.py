from services.ai.semantic_propagation_store import plan_semantic_propagation_scope


def test_plan_semantic_propagation_scope_for_hierarchy() -> None:
    scope = plan_semantic_propagation_scope(
        [
            {
                "artifact_id": "ref_art_1",
                "artifact_type": "hierarchy_override",
                "artifact_json": {"levels": ["country", "state", "site"]},
            }
        ]
    )

    assert scope["artifact_ids"] == ["ref_art_1"]
    assert scope["artifact_types"] == ["hierarchy_override"]
    assert scope["affected_columns"] == ["country", "state", "site"]
    assert scope["impact_level"] == "broad"
    assert scope["refresh_actions"] == [
        "refresh_hierarchies",
        "refresh_chart_interaction_metadata",
        "refresh_affected_dashboards",
        "refresh_workspace_semantics",
    ]


def test_plan_semantic_propagation_scope_for_metric_and_join_is_high_impact() -> None:
    scope = plan_semantic_propagation_scope(
        [
            {
                "artifact_id": "ref_art_1",
                "artifact_type": "metric_refinement",
                "artifact_json": {"metric_name": "total_volume"},
            },
            {
                "artifact_id": "ref_art_2",
                "artifact_type": "join_rule",
                "artifact_json": {
                    "rule_type": "join_restriction",
                    "left_table": "fact_transactions",
                    "right_table": "external_reference",
                },
            },
        ]
    )

    assert scope["artifact_ids"] == ["ref_art_1", "ref_art_2"]
    assert scope["artifact_types"] == ["metric_refinement", "join_rule"]
    assert scope["affected_metrics"] == ["total_volume"]
    assert scope["affected_tables"] == ["fact_transactions", "external_reference"]
    assert scope["impact_level"] == "high"
    assert "refresh_metrics" in scope["refresh_actions"]
    assert "refresh_query_planner_constraints" in scope["refresh_actions"]
    assert "refresh_affected_dashboards" in scope["refresh_actions"]


def test_plan_semantic_propagation_scope_defaults_unknown_artifact_to_state_refresh() -> None:
    scope = plan_semantic_propagation_scope(
        [{"artifact_id": "ref_art_1", "artifact_type": "custom_refinement", "artifact_json": {}}]
    )

    assert scope["artifact_ids"] == ["ref_art_1"]
    assert scope["artifact_types"] == ["custom_refinement"]
    assert scope["refresh_actions"] == ["refresh_semantic_state"]
    assert scope["impact_level"] == "local"
