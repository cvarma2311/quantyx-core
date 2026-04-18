from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from services.ai.config import Settings
from services.ai.connection_registry import resolve_database_credentials_cached
from services.ai.db import ScopedConnection, run_query
from services.ai.data_quality_enrichment import canonical_column_alias, canonical_column_aliases
from services.ai.data_quality_store import (
    get_quality_enrichment_proposal,
    get_quality_run_by_run_id,
    list_quality_duplicate_candidates,
    list_quality_rules,
    list_quality_tables,
)


def _qident(name: str | None) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def _safe_limit(value: int | None, default: int = 100, max_value: int = 500) -> int:
    raw = int(value or default)
    return max(1, min(raw, max_value))


def _safe_offset(value: int | None) -> int:
    raw = int(value or 0)
    return max(0, raw)


def resolve_quality_run_scoped_conn(settings: Settings, run_row: dict[str, Any]) -> ScopedConnection | None:
    connection_id = str(run_row.get("connection_id") or "").strip()
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    if not connection_id:
        return None
    return resolve_database_credentials_cached(settings, connection_id, schema_name)


def load_quality_run(settings: Settings, *, run_id: str, tenant_id: str, domain_id: str) -> dict[str, Any]:
    run_row = get_quality_run_by_run_id(settings, run_id)
    if not run_row:
        raise HTTPException(status_code=404, detail="Data quality run not found")
    if str(run_row.get("tenant_id") or "") != str(tenant_id) or str(run_row.get("domain_id") or "") != str(domain_id):
        raise HTTPException(status_code=404, detail="Data quality run not found")
    return run_row


def fetch_missingness_evidence(
    settings: Settings,
    *,
    run_row: dict[str, Any],
    table_name: str,
    column_name: str,
    include_blank: bool,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    if not scoped_conn:
        raise HTTPException(status_code=500, detail="Failed to resolve source connection")
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    q_schema = _qident(schema_name)
    q_table = _qident(table_name)
    q_col = _qident(column_name)
    predicate = f"{q_col} IS NULL"
    if include_blank:
        predicate = f"({q_col} IS NULL OR btrim({q_col}::text) = '')"
    count_sql = f"SELECT COUNT(*) AS affected_row_count FROM {q_schema}.{q_table} WHERE {predicate}"
    rows_sql = f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate} ORDER BY ctid LIMIT {_safe_limit(limit)} OFFSET {_safe_offset(offset)}"
    count_row = (run_query(settings, count_sql, [], scoped_conn=scoped_conn) or [{}])[0]
    rows = run_query(settings, rows_sql, [], scoped_conn=scoped_conn)
    return {
        "table_name": table_name,
        "column_name": column_name,
        "column_alias": canonical_column_alias(column_name),
        "include_blank": include_blank,
        "affected_row_count": int(count_row.get("affected_row_count") or 0),
        "rows": rows,
        "limit": _safe_limit(limit),
        "offset": _safe_offset(offset),
    }


def _get_rule_row(settings: Settings, *, tenant_id: str, domain_id: str, rule_id: str) -> dict[str, Any]:
    rows = list_quality_rules(settings, tenant_id=tenant_id, domain_id=domain_id, limit=500)
    for row in rows:
        if str(row.get("rule_id") or "") == str(rule_id):
            return row
    raise HTTPException(status_code=404, detail="Data quality rule not found")


def fetch_rule_evidence(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    rule_id: str,
    limit: int,
) -> dict[str, Any]:
    rule = _get_rule_row(settings, tenant_id=tenant_id, domain_id=domain_id, rule_id=rule_id)
    run_row = load_quality_run(
        settings,
        run_id=str(rule.get("run_id") or ""),
        tenant_id=tenant_id,
        domain_id=domain_id,
    )
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    evidence_rows = list(rule.get("sample_rows_json") or [])
    execution_plan = rule.get("execution_plan_json") or {}
    sample_sql = str(execution_plan.get("sample_sql") or "").strip()
    if scoped_conn and sample_sql and "SELECT" in sample_sql.upper():
        try:
            # Execution-plan SQL is stored as preview text with placeholders; only run safe, fully concrete plans.
            if ":" not in sample_sql and "<" not in sample_sql:
                evidence_rows = run_query(settings, sample_sql, [], scoped_conn=scoped_conn)[: _safe_limit(limit)]
        except Exception:
            pass
    return {
        "rule_id": rule_id,
        "rule": rule,
        "aliases": {
            "column_alias": canonical_column_alias(rule.get("column_name")),
            "reference_column_alias": canonical_column_alias(rule.get("reference_column")),
        },
        "evidence_rows": evidence_rows[: _safe_limit(limit)],
    }


def _get_duplicate_row(settings: Settings, *, tenant_id: str, domain_id: str, candidate_id: str) -> dict[str, Any]:
    rows = list_quality_duplicate_candidates(settings, tenant_id=tenant_id, domain_id=domain_id, limit=500)
    for row in rows:
        if str(row.get("candidate_id") or "") == str(candidate_id):
            return row
    raise HTTPException(status_code=404, detail="Duplicate candidate not found")


def fetch_duplicate_evidence(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    candidate_id: str,
    limit: int,
) -> dict[str, Any]:
    candidate = _get_duplicate_row(settings, tenant_id=tenant_id, domain_id=domain_id, candidate_id=candidate_id)
    run_row = load_quality_run(
        settings,
        run_id=str(candidate.get("run_id") or ""),
        tenant_id=tenant_id,
        domain_id=domain_id,
    )
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    rows = list(candidate.get("sample_rows_json") or [])
    if scoped_conn and str(candidate.get("duplicate_type") or "").startswith("exact_"):
        schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
        q_schema = _qident(schema_name)
        q_table = _qident(candidate.get("table_name"))
        match_columns = list(candidate.get("match_columns_json") or [])
        sample_rows = list(candidate.get("sample_rows_json") or [])
        if len(match_columns) == 1 and sample_rows:
            col = _qident(match_columns[0])
            values = [row.get("duplicate_value") for row in sample_rows if row.get("duplicate_value") is not None]
            if values:
                sql = f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {col} = ANY(%s) LIMIT {_safe_limit(limit)}"
                rows = run_query(settings, sql, [values], scoped_conn=scoped_conn)
        elif len(match_columns) > 1 and sample_rows:
            predicates: list[str] = []
            params: list[Any] = []
            for sample in sample_rows[:10]:
                per_row = []
                for col_name in match_columns:
                    if sample.get(col_name) is None:
                        per_row = []
                        break
                    per_row.append(f"{_qident(col_name)} = %s")
                    params.append(sample.get(col_name))
                if per_row:
                    predicates.append("(" + " AND ".join(per_row) + ")")
            if predicates:
                sql = f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {' OR '.join(predicates)} LIMIT {_safe_limit(limit)}"
                rows = run_query(settings, sql, params, scoped_conn=scoped_conn)
    return {
        "candidate_id": candidate_id,
        "candidate": candidate,
        "match_column_aliases": canonical_column_aliases(candidate.get("match_columns_json") or []),
        "evidence_rows": rows[: _safe_limit(limit)],
    }


def fetch_freshness_evidence(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    table_name: str,
) -> dict[str, Any]:
    tables = list_quality_tables(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=500)
    for row in tables:
        if str(row.get("table_name") or "") != str(table_name):
            continue
        summary = row.get("summary_json") or {}
        return {
            "table_name": table_name,
            "freshness_analysis": summary.get("freshness_analysis") or {},
            "stability_analysis": summary.get("stability_analysis") or {},
            "freshness_column_alias": canonical_column_alias((summary.get("freshness_analysis") or {}).get("freshness_column")),
            "trust_components": summary.get("trust_components") or {},
            "trust_component_explanations": summary.get("trust_component_explanations") or {},
        }
    raise HTTPException(status_code=404, detail="Table freshness evidence not found")


def fetch_enrichment_evidence(
    settings: Settings,
    *,
    proposal_id: str,
    tenant_id: str,
    limit: int,
) -> dict[str, Any]:
    proposal = get_quality_enrichment_proposal(settings, proposal_id, tenant_id=tenant_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Enrichment proposal not found")
    proposed_values = list(proposal.get("proposed_values_json") or [])
    return {
        "proposal_id": proposal_id,
        "proposal": proposal,
        "target_column_alias": proposal.get("target_column_alias") or canonical_column_alias(proposal.get("target_column")),
        "source_column_aliases": proposal.get("source_column_aliases_json") or canonical_column_aliases(proposal.get("source_columns_json") or []),
        "proposed_rows": proposed_values[: _safe_limit(limit)],
        "summary": {
            "matched_count": proposal.get("matched_count"),
            "unmatched_count": proposal.get("unmatched_count"),
            "source_references": proposal.get("source_references_json") or [],
        },
    }
