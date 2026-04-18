from types import SimpleNamespace

import services.ai.domain_refinement_store as store


def test_update_refinement_artifact_approval_sets_expected_sql_params(monkeypatch) -> None:
    calls: list[tuple[str, list]] = []
    monkeypatch.setattr(store, "execute_non_query", lambda settings, sql, params: calls.append((sql, params)))

    store.update_refinement_artifact_approval(
        SimpleNamespace(),
        "art_1",
        tenant_id="tenant_a",
        approval_status="approved",
        approved_by="reviewer",
    )

    assert calls
    assert calls[0][1] == ["approved", "reviewer", "approved", "art_1", "tenant_a"]


def test_activate_semantic_state_switches_active_scope(monkeypatch) -> None:
    calls: list[tuple[str, list]] = []
    states = [
        {
            "semantic_state_id": "sem_1",
            "tenant_id": "tenant_a",
            "domain_id": "domain_a",
            "connection_id": "conn",
            "database_name": "db",
            "schema_name": "public",
        }
    ]
    monkeypatch.setattr(store, "get_semantic_state", lambda settings, semantic_state_id, tenant_id: states[0])
    monkeypatch.setattr(store, "execute_non_query", lambda settings, sql, params: calls.append((sql, params)))

    result = store.activate_semantic_state(SimpleNamespace(), "sem_1", tenant_id="tenant_a")

    assert result["semantic_state_id"] == "sem_1"
    assert len(calls) == 2
    assert calls[0][1] == ["tenant_a", "domain_a", "conn", "db", "public"]
    assert calls[1][1] == ["sem_1", "tenant_a"]
