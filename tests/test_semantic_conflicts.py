from services.ai.semantic_conflicts import detect_semantic_conflicts, semantic_conflict_key


def test_conflict_key_normalizes_metric_and_join_targets() -> None:
    assert (
        semantic_conflict_key(
            {
                "artifact_type": "metric_refinement",
                "artifact_json": {"metric_name": "Growth Rate"},
            }
        )
        == "metric_refinement:growth_rate"
    )
    assert (
        semantic_conflict_key(
            {
                "artifact_type": "join_rule",
                "artifact_json": {"rule_type": "join_restriction", "left_table": "Orders", "right_table": "Customer Reference"},
            }
        )
        == "join_rule:join_restriction:customer_reference:orders"
    )


def test_detect_semantic_conflicts_returns_differing_payloads_only() -> None:
    conflicts = detect_semantic_conflicts(
        [
            {
                "artifact_id": "art_1",
                "artifact_type": "metric_refinement",
                "approval_status": "auto_approved",
                "artifact_json": {"metric_name": "growth_rate", "formula": "month_over_month_growth"},
            },
            {
                "artifact_id": "art_2",
                "artifact_type": "metric_refinement",
                "approval_status": "pending",
                "artifact_json": {"metric_name": "growth_rate", "formula": "day_over_day_growth"},
            },
            {
                "artifact_id": "art_3",
                "artifact_type": "column_annotation",
                "artifact_json": {"column": "ship_to_id", "business_label": "Ship-To Customer"},
            },
        ]
    )

    assert len(conflicts) == 1
    assert conflicts[0]["conflict_key"] == "metric_refinement:growth_rate"
    assert conflicts[0]["severity"] == "high"
    assert conflicts[0]["artifact_ids"] == ["art_1", "art_2"]
