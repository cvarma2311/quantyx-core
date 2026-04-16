from types import SimpleNamespace

import services.ai.semantic_conversation_refinement as conversation_refinement


def test_infer_conversation_refinement_kind() -> None:
    assert (
        conversation_refinement.infer_conversation_refinement_kind(
            "Actually do not join orders with customer_reference."
        )
        == "join_rule"
    )
    assert (
        conversation_refinement.infer_conversation_refinement_kind(
            "Growth rate should use prior month as the baseline."
        )
        == "metric_refinement"
    )
    assert conversation_refinement.infer_conversation_refinement_kind("Show me sales by month") is None


def test_infer_refinement_kind_for_ui_auto_mode() -> None:
    assert (
        conversation_refinement.infer_refinement_kind(
            "Use hierarchy Zone > Region > Plant for drill downs."
        )
        == "hierarchy"
    )
    assert (
        conversation_refinement.infer_refinement_kind(
            "Field ship_to_id means Ship-To Customer and should be shown as a business identifier."
        )
        == "column_annotation"
    )
    assert (
        conversation_refinement.infer_refinement_kind(
            payload={"question_id": "preferred_drill_path", "answer_text": "Zone > Region > Plant"}
        )
        == "context_question_answer"
    )
    assert conversation_refinement.infer_refinement_kind("Additional planning context for this domain.") == "business_context"


def test_maybe_writeback_conversation_refinement_auto_processes_and_enqueues(monkeypatch) -> None:
    calls: dict[str, object] = {}
    refinement_row = {
        "refinement_input_id": "ref_1",
        "tenant_id": "tenant_a",
        "domain_id": "domain_a",
        "connection_id": "conn",
        "database_name": "db",
        "schema_name": "public",
        "source_text": "Actually do not join orders with customer_reference.",
    }
    artifact = {
        "artifact_id": "art_1",
        "validation_status": "valid",
        "approval_status": "auto_approved",
    }

    monkeypatch.setattr(
        conversation_refinement,
        "create_refinement_input",
        lambda settings, **kwargs: calls.setdefault("created", kwargs) and "ref_1",
    )
    monkeypatch.setattr(conversation_refinement, "get_refinement_input", lambda settings, refinement_input_id: refinement_row)
    monkeypatch.setattr(conversation_refinement, "process_refinement_input", lambda settings, row, **kwargs: [artifact])
    monkeypatch.setattr(
        conversation_refinement,
        "rebuild_semantic_state",
        lambda settings, **kwargs: calls.update({"rebuild": kwargs}) or {"semantic_state_id": "sem_1"},
    )
    monkeypatch.setattr(
        conversation_refinement,
        "enqueue_semantic_propagation_for_artifacts",
        lambda settings, **kwargs: calls.update({"enqueue": kwargs}) or ["job_1"],
    )

    result = conversation_refinement.maybe_writeback_conversation_refinement(
        SimpleNamespace(),
        tenant_id="tenant_a",
        domain_id="domain_a",
        connection_id="conn",
        database_name="db",
        schema_name="public",
        source_run_id="run_1",
        conversation_id="conv_1",
        source_text="Actually do not join orders with customer_reference.",
    )

    assert result["refinement_kind"] == "join_rule"
    assert result["semantic_state_id"] == "sem_1"
    assert calls["created"]["source_type"] == "conversation"
    assert calls["created"]["conversation_id"] == "conv_1"
    assert calls["enqueue"]["trigger_type"] == "conversation_auto_writeback"
