from __future__ import annotations

from typing import Any

from services.ai.config import Settings
from services.ai.connection_registry import resolve_database_credentials_cached
from services.ai.data_quality_rules import (
    build_quality_rule_execution_plan,
    classify_quality_rule_review_status,
    derive_quality_rule_label,
    execute_quality_rules,
)
from services.ai.data_quality_store import get_quality_rule, list_quality_rules, update_quality_rule_review


def _rule_patch(rule: dict[str, Any], patch: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(rule)
    patch = patch or {}
    for key in ["source_text", "severity", "table_name", "column_name", "reference_table", "reference_column"]:
        if patch.get(key) is not None:
            merged[key] = patch.get(key)
    if isinstance(patch.get("condition_json"), dict):
        merged["condition_json"] = patch.get("condition_json")
    return merged


def _resolve_rule_scoped_conn(settings: Settings, rule_row: dict[str, Any]):
    connection_id = str(rule_row.get("connection_id") or "").strip()
    schema_name = str(rule_row.get("schema_name") or "public").strip() or "public"
    if not connection_id:
        return None
    return resolve_database_credentials_cached(settings, connection_id, schema_name)


def apply_quality_rule_review_action(
    settings: Settings,
    *,
    rule_row: dict[str, Any],
    action: str,
    reviewed_by: str,
    review_notes: str | None = None,
    rule_patch: dict[str, Any] | None = None,
    execute_after_approval: bool = True,
) -> dict[str, Any]:
    action_text = str(action or "").strip().lower()
    if action_text not in {"approve", "reject", "edit"}:
        raise ValueError("Unsupported review action")

    current = dict(rule_row)
    updated_rule = _rule_patch(current, rule_patch if action_text == "edit" else None)
    if action_text == "reject":
        stored = update_quality_rule_review(
            settings,
            rule_id=str(current.get("rule_id")),
            tenant_id=str(current.get("tenant_id") or "") or None,
            status="rejected",
            reviewed_by=reviewed_by,
            review_notes=review_notes,
        )
        return {
            "rule_id": current.get("rule_id"),
            "status": "rejected",
            "stored_rule": stored or current,
            "execution": None,
        }

    execution_plan = build_quality_rule_execution_plan(
        updated_rule,
        schema_name=str(updated_rule.get("schema_name") or "public"),
        settings=settings,
    )
    updated_rule["executor_kind"] = execution_plan.get("executor_kind")
    updated_rule["execution_plan_json"] = execution_plan
    updated_rule["status"] = "active" if action_text == "approve" else classify_quality_rule_review_status(updated_rule)
    if action_text == "edit" and updated_rule["status"] == "unsupported":
        updated_rule["status"] = "needs_review"

    stored = update_quality_rule_review(
        settings,
        rule_id=str(current.get("rule_id")),
        tenant_id=str(current.get("tenant_id") or "") or None,
        status=str(updated_rule.get("status") or "needs_review"),
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        source_text=updated_rule.get("source_text"),
        severity=updated_rule.get("severity"),
        table_name=updated_rule.get("table_name"),
        column_name=updated_rule.get("column_name"),
        reference_table=updated_rule.get("reference_table"),
        reference_column=updated_rule.get("reference_column"),
        condition_json=updated_rule.get("condition_json") or {},
        executor_kind=updated_rule.get("executor_kind"),
        execution_plan_json=updated_rule.get("execution_plan_json") or {},
    )
    execution = None
    if execute_after_approval and str(updated_rule.get("status") or "").strip().lower() == "active":
        scoped_conn = _resolve_rule_scoped_conn(settings, updated_rule)
        execution = execute_quality_rules(
            settings,
            rules=[updated_rule],
            schema_name=str(updated_rule.get("schema_name") or "public"),
            scoped_conn=scoped_conn,
        )
    return {
        "rule_id": current.get("rule_id"),
        "status": updated_rule.get("status"),
        "stored_rule": stored or updated_rule,
        "execution": execution,
    }


def get_quality_rule_review_queue(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
) -> dict[str, Any]:
    rows = list_quality_rules(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=1200,
    )
    reviewable = [
        row for row in rows
        if str(row.get("status") or "").strip().lower() in {"needs_review", "unsupported"}
    ]
    accepted = [
        row for row in rows
        if str(row.get("status") or "").strip().lower() == "active"
    ]
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "summary": {
            "total_rule_count": len(rows),
            "accepted_auto_count": len(accepted),
            "needs_review_count": sum(1 for row in reviewable if str(row.get("status") or "").strip().lower() == "needs_review"),
            "unsupported_count": sum(1 for row in reviewable if str(row.get("status") or "").strip().lower() == "unsupported"),
        },
        "rules": [
            {
                **row,
                "rule_label": derive_quality_rule_label(row),
            }
            for row in reviewable
        ],
    }


def get_quality_rule_for_review(
    settings: Settings,
    *,
    rule_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    return get_quality_rule(settings, rule_id, tenant_id=tenant_id)
