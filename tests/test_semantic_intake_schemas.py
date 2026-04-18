from services.api.schemas import SemanticIntakeRequest, SemanticIntakeResponse


def test_semantic_intake_request_accepts_minimal_ui_payload() -> None:
    payload = SemanticIntakeRequest(
        tenant_id="tenant_a",
        type="semantics",
        text="Growth rate should use prior month as the baseline.",
    )

    assert payload.tenant_id == "tenant_a"
    assert payload.type == "semantics"
    assert payload.domain_id is None
    assert payload.text == "Growth rate should use prior month as the baseline."


def test_semantic_intake_response_shape() -> None:
    response = SemanticIntakeResponse(
        status="processed",
        type="semantics",
        tenant_id="tenant_a",
        domain_id="domain_a",
        inferred_refinement_kind="metric_refinement",
        refinement_input_id="ref_1",
        semantic_state_id="sem_1",
        artifacts=[
            {
                "artifact_id": "art_1",
                "artifact_type": "metric_refinement",
                "validation_status": "valid",
                "approval_status": "auto_approved",
                "artifact_json": {"metric_name": "growth_rate"},
                "summary": "Metric refinement for growth_rate",
            }
        ],
        propagation_jobs=[
            {
                "job_id": "semprop_1",
                "status": "queued",
                "refresh_actions": ["refresh_semantic_state", "refresh_metrics"],
                "affected_scope_json": {"artifact_ids": ["art_1"]},
            }
        ],
    )

    assert response.artifacts[0].artifact_type == "metric_refinement"
    assert response.propagation_jobs[0].refresh_actions == ["refresh_semantic_state", "refresh_metrics"]
