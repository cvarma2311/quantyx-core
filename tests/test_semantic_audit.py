from services.ai.semantic_audit import build_semantic_audit
from services.api.schemas import SemanticAuditResponse


def test_build_semantic_audit_links_jobs_to_refinement_artifacts() -> None:
    audit = build_semantic_audit(
        refinements=[
            {
                "refinement_input_id": "ref_1",
                "tenant_id": "tenant_a",
                "domain_id": "domain_a",
                "refinement_kind": "metric_refinement",
                "source_type": "text",
                "status": "processed",
                "submitted_by": "ui:user",
                "created_at": "2026-04-18T10:00:00",
            }
        ],
        artifacts_by_refinement={
            "ref_1": [
                {
                    "artifact_id": "art_1",
                    "artifact_type": "metric_refinement",
                    "validation_status": "valid",
                    "approval_status": "auto_approved",
                }
            ]
        },
        semantic_states=[
            {
                "semantic_state_id": "sem_1",
                "tenant_id": "tenant_a",
                "domain_id": "domain_a",
                "version_no": 2,
                "is_active": True,
                "trigger_type": "semantic_intake_auto_approved",
                "created_from_artifact_ids": ["art_1"],
                "created_at": "2026-04-18T10:01:00",
            }
        ],
        propagation_jobs=[
            {
                "job_id": "job_1",
                "tenant_id": "tenant_a",
                "domain_id": "domain_a",
                "trigger_type": "semantic_intake_auto_approved",
                "status": "queued",
                "affected_scope_json": {"artifact_ids": ["art_1"], "refresh_actions": ["refresh_metrics"]},
                "created_at": "2026-04-18T10:02:00",
            }
        ],
    )

    assert audit["refinements"][0]["artifact_count"] == 1
    assert audit["refinements"][0]["propagation_jobs"][0]["job_id"] == "job_1"
    assert [event["event_type"] for event in audit["timeline"]] == [
        "propagation_job",
        "semantic_state",
        "refinement",
    ]


def test_semantic_audit_response_shape() -> None:
    response = SemanticAuditResponse(
        tenant_id="tenant_a",
        domain_id="domain_a",
        refinements=[{"event_id": "ref_1"}],
        semantic_states=[{"event_id": "sem_1"}],
        propagation_jobs=[{"event_id": "job_1"}],
        timeline=[
            {
                "event_type": "refinement",
                "event_id": "ref_1",
                "created_at": "2026-04-18T10:00:00",
                "summary": "metric_refinement refinement processed",
                "details": {"refinement_kind": "metric_refinement"},
            }
        ],
    )

    assert response.timeline[0].event_type == "refinement"
    assert response.timeline[0].details["refinement_kind"] == "metric_refinement"
