from services.ai.semantic_impact_preview import build_semantic_impact_preview
from services.api.schemas import SemanticImpactPreviewRequest, SemanticImpactPreviewResponse


def test_impact_preview_marks_new_high_impact_metric() -> None:
    preview = build_semantic_impact_preview(
        [
            {
                "artifact_id": "art_metric",
                "artifact_type": "metric_refinement",
                "artifact_json": {
                    "metric_name": "growth_rate",
                    "formula": "month_over_month_growth",
                },
            }
        ],
        active_state={"refinements": {"metric_overrides": []}},
    )

    assert preview["impact_level"] == "high"
    assert preview["affected_scope"]["affected_metrics"] == ["growth_rate"]
    assert preview["diff_summary"][0]["change_type"] == "add_new"
    assert preview["diff_summary"][0]["target"] == "growth_rate"


def test_impact_preview_detects_existing_target_update() -> None:
    active_state = {
        "refinements": {
            "column_annotations": [
                {
                    "artifact_id": "existing_col",
                    "artifact_type": "column_annotation",
                    "artifact_json": {
                        "column": "ship_to_id",
                        "business_label": "Ship To",
                    },
                }
            ]
        }
    }

    preview = build_semantic_impact_preview(
        [
            {
                "artifact_id": "new_col",
                "artifact_type": "column_annotation",
                "artifact_json": {
                    "column": "ship_to_id",
                    "business_label": "Ship-To Customer",
                },
            }
        ],
        active_state=active_state,
    )

    assert preview["impact_level"] == "local"
    assert preview["diff_summary"][0]["change_type"] == "update_existing"
    assert preview["diff_summary"][0]["current_artifact_id"] == "existing_col"


def test_semantic_impact_preview_schema_shapes() -> None:
    request = SemanticImpactPreviewRequest(
        tenant_id="tenant_a",
        text="Do not join orders with customer_reference.",
    )
    response = SemanticImpactPreviewResponse(
        tenant_id="tenant_a",
        domain_id="domain_a",
        inferred_refinement_kind="join_rule",
        impact_level="high",
        artifact_count=1,
        affected_scope={"refresh_actions": ["refresh_query_planner_constraints"]},
        diff_summary=[
            {
                "artifact_type": "join_rule",
                "change_type": "add_new",
                "target": "orders<->customer_reference",
                "summary": "Applies join rule orders<->customer_reference",
                "artifact_json": {"allowed": False},
            }
        ],
    )

    assert request.refinement_kind == "auto"
    assert response.diff_summary[0].artifact_type == "join_rule"
    assert response.affected_scope["refresh_actions"] == ["refresh_query_planner_constraints"]
