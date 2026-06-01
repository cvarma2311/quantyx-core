from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from services.ai.config import Settings
from services.ai.connection_registry import resolve_database_credentials_cached
from services.ai.db import ScopedConnection, run_query
from services.ai.data_quality_enrichment import canonical_column_alias, canonical_column_aliases
from services.ai.data_quality_rules import _build_date_range_predicate_parts
from services.ai.data_quality_stages import fetch_final_dataset_rows_tool
from services.ai.data_quality_store import (
    get_quality_final_dataset_artifact,
    get_quality_enrichment_proposal,
    get_quality_dataset_stage,
    get_quality_join_artifact,
    get_quality_run_by_run_id,
    list_quality_duplicate_candidates,
    list_quality_dataset_stages,
    list_quality_lineage_edges,
    list_quality_stage_row_outcomes,
    list_quality_rules,
    list_quality_tables,
)
from services.ai.data_quality_stages import _build_filter_predicate, _lineage_id, parse_lineage_id


def _qident(name: str | None) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def _safe_limit(value: int | None, default: int = 1200, max_value: int = 4000) -> int:
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
    rows = list_quality_rules(settings, tenant_id=tenant_id, domain_id=domain_id, limit=1200)
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


def _rule_record_query_plan(
    *,
    rule: dict[str, Any],
    run_row: dict[str, Any],
    outcome: str,
) -> tuple[str | None, list[Any], str | None]:
    rule_type = str(rule.get("rule_type") or "").strip().lower()
    condition = rule.get("condition_json") or {}
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    table_name = str(rule.get("table_name") or "").strip()
    column_name = str(rule.get("column_name") or "").strip()
    q_schema = _qident(schema_name)
    q_table = _qident(table_name)
    q_col = _qident(column_name) if column_name else None
    failed = outcome == "failed"

    if not table_name:
        return None, [], "rule_has_no_primary_table"

    if rule_type == "referential_integrity":
        ref_table = _qident(rule.get("reference_table"))
        ref_col = _qident(rule.get("reference_column"))
        predicate = (
            f"child.{q_col} IS NOT NULL AND parent.{ref_col} IS NULL"
            if failed
            else f"child.{q_col} IS NULL OR parent.{ref_col} IS NOT NULL"
        )
        sql = (
            f"SELECT child.ctid::text AS __row_ref, child.* "
            f"FROM {q_schema}.{q_table} child "
            f"LEFT JOIN {q_schema}.{ref_table} parent ON child.{q_col} = parent.{ref_col} "
            f"WHERE {predicate}"
        )
        return sql, [], None
    if rule_type == "not_null":
        predicate = f"{q_col} IS NULL" if failed else f"{q_col} IS NOT NULL"
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [], None
    if rule_type == "not_blank":
        predicate = f"({q_col} IS NULL OR btrim({q_col}::text) = '')" if failed else f"({q_col} IS NOT NULL AND btrim({q_col}::text) <> '')"
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [], None
    if rule_type == "email_pattern":
        pattern = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
        predicate = f"{q_col} IS NOT NULL AND {q_col}::text !~ %s" if failed else f"{q_col} IS NOT NULL AND {q_col}::text ~ %s"
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [pattern], None
    if rule_type == "numeric_min":
        predicate = f"{q_col} IS NOT NULL AND {q_col} < %s" if failed else f"{q_col} IS NULL OR {q_col} >= %s"
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [condition.get("min_value", 0)], None
    if rule_type == "numeric_max":
        predicate = f"{q_col} IS NOT NULL AND {q_col} > %s" if failed else f"{q_col} IS NULL OR {q_col} <= %s"
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [condition.get("max_value")], None
    if rule_type == "numeric_range":
        predicate = (
            f"{q_col} IS NOT NULL AND ({q_col} < %s OR {q_col} > %s)"
            if failed
            else f"{q_col} IS NULL OR ({q_col} >= %s AND {q_col} <= %s)"
        )
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [condition.get("min_value"), condition.get("max_value")], None
    if rule_type == "allowed_values":
        allowed = [str(item) for item in (condition.get("allowed_values") or [])]
        predicate = (
            f"{q_col} IS NOT NULL AND NOT ({q_col}::text = ANY(%s))"
            if failed
            else f"{q_col} IS NULL OR ({q_col}::text = ANY(%s))"
        )
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [allowed], None
    if rule_type == "regex_pattern":
        predicate = f"{q_col} IS NOT NULL AND {q_col}::text !~ %s" if failed else f"{q_col} IS NOT NULL AND {q_col}::text ~ %s"
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [condition.get("pattern")], None
    if rule_type == "unique":
        comparison = "> 1" if failed else "= 1"
        sql = (
            f"SELECT t.ctid::text AS __row_ref, t.* "
            f"FROM {q_schema}.{q_table} t "
            f"WHERE t.{q_col} IS NOT NULL "
            f"AND t.{q_col} IN ("
            f"SELECT {q_col} FROM {q_schema}.{q_table} WHERE {q_col} IS NOT NULL GROUP BY {q_col} HAVING COUNT(*) {comparison}"
            f")"
        )
        return sql, [], None
    if rule_type == "cross_column_consistency":
        left = _qident(condition.get("left_column"))
        right = _qident(condition.get("right_column"))
        operator = condition.get("operator")
        predicate = (
            f"{left} IS NOT NULL AND {right} IS NOT NULL AND NOT ({left} {operator} {right})"
            if failed
            else f"{left} IS NULL OR {right} IS NULL OR ({left} {operator} {right})"
        )
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [], None
    if rule_type == "date_range":
        predicates, _notes = _build_date_range_predicate_parts(q_col, condition)
        if not predicates:
            return None, [], "rule_has_no_row_level_date_predicate"
        failed_predicate = " OR ".join(f"({item})" for item in predicates)
        predicate = failed_predicate if failed else f"NOT ({failed_predicate})"
        return f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{q_table} WHERE {predicate}", [], None
    if rule_type == "custom_sql":
        if not failed:
            return None, [], "passed_records_not_supported_for_custom_sql"
        execution_plan = rule.get("execution_plan_json") or {}
        sample_sql = str(execution_plan.get("sample_sql") or "").strip()
        if sample_sql and ":" not in sample_sql and "<" not in sample_sql and sample_sql.lower().startswith("select"):
            return sample_sql, [], None
        return None, [], "custom_sql_failed_records_require_safe_sample_sql"
    return None, [], f"row_level_evidence_not_supported_for_{rule_type}"


def fetch_rule_records(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    rule_id: str,
    outcome: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    if outcome not in {"failed", "passed"}:
        raise HTTPException(status_code=400, detail="Unsupported rule record outcome")
    rule = _get_rule_row(settings, tenant_id=tenant_id, domain_id=domain_id, rule_id=rule_id)
    if str(rule.get("run_id") or "") != str(run_id):
        raise HTTPException(status_code=404, detail="Data quality rule not found for run")
    run_row = load_quality_run(settings, run_id=run_id, tenant_id=tenant_id, domain_id=domain_id)
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    if not scoped_conn:
        raise HTTPException(status_code=500, detail="Failed to resolve source connection")
    sql, params, unsupported_reason = _rule_record_query_plan(rule=rule, run_row=run_row, outcome=outcome)
    if not sql:
        return {
            "rule_id": rule_id,
            "run_id": run_id,
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "outcome": outcome,
            "supported": False,
            "unsupported_reason": unsupported_reason,
            "affected_row_count": None,
            "rows": [],
            "limit": _safe_limit(limit),
            "offset": _safe_offset(offset),
            "rule": rule,
        }
    limited_sql = f"SELECT * FROM ({sql}) dq_rule_rows LIMIT {_safe_limit(limit)} OFFSET {_safe_offset(offset)}"
    count_sql = f"SELECT COUNT(*) AS affected_row_count FROM ({sql}) dq_rule_rows"
    count_row = (run_query(settings, count_sql, params, scoped_conn=scoped_conn) or [{}])[0]
    rows = run_query(settings, limited_sql, params, scoped_conn=scoped_conn) or []
    return {
        "rule_id": rule_id,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "outcome": outcome,
        "supported": True,
        "unsupported_reason": None,
        "affected_row_count": int(count_row.get("affected_row_count") or 0),
        "rows": rows,
        "limit": _safe_limit(limit),
        "offset": _safe_offset(offset),
        "rule": rule,
    }


def _get_duplicate_row(settings: Settings, *, tenant_id: str, domain_id: str, candidate_id: str) -> dict[str, Any]:
    rows = list_quality_duplicate_candidates(settings, tenant_id=tenant_id, domain_id=domain_id, limit=1200)
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
    tables = list_quality_tables(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
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


def fetch_stage_evidence(
    settings: Settings,
    *,
    stage_id: str,
    tenant_id: str,
    domain_id: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    stage = get_quality_dataset_stage(settings, stage_id, tenant_id=tenant_id)
    if not stage or str(stage.get("domain_id") or "") != str(domain_id):
        raise HTTPException(status_code=404, detail="Data quality stage not found")
    stage_summary = stage.get("summary_json") or {}
    stage_type = str(stage.get("stage_type") or "").strip()
    run_row = load_quality_run(
        settings,
        run_id=str(stage.get("run_id") or ""),
        tenant_id=tenant_id,
        domain_id=domain_id,
    )
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    if not scoped_conn:
        return {
            "stage_id": stage_id,
            "stage": stage,
            "evidence_type": stage_type,
            "rows": [],
            "summary": stage_summary,
        }
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    q_schema = _qident(schema_name)
    row_limit = _safe_limit(limit)
    row_offset = _safe_offset(offset)
    if stage_type == "source_profile":
        table_name = str(stage_summary.get("output_dataset") or "").strip()
        if not table_name:
            raise HTTPException(status_code=404, detail="Source stage table is missing")
        rows = run_query(
            settings,
            f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{_qident(table_name)} ORDER BY ctid LIMIT {row_limit} OFFSET {row_offset}",
            [],
            scoped_conn=scoped_conn,
        )
        for row in rows:
            row["row_lineage_id"] = _lineage_id(table_name, row.get("__row_ref"))
        return {
            "stage_id": stage_id,
            "stage": stage,
            "evidence_type": "source_profile_rows",
            "table_name": table_name,
            "rows": rows,
            "summary": stage_summary,
            "limit": row_limit,
            "offset": row_offset,
        }
    if stage_type == "join_validation":
        join = stage_summary.get("join") or {}
        left_table = str(join.get("left_table") or "").strip()
        right_table = str(join.get("right_table") or "").strip()
        left_key = str(join.get("left_key") or "").strip()
        right_key = str(join.get("right_key") or "").strip()
        if not left_table or not right_table or not left_key or not right_key:
            raise HTTPException(status_code=404, detail="Join stage keys are missing")
        q_left_table = f"{q_schema}.{_qident(left_table)}"
        q_right_table = f"{q_schema}.{_qident(right_table)}"
        q_left_key = _qident(left_key)
        q_right_key = _qident(right_key)
        matched_rows = run_query(
            settings,
            (
                f"SELECT l.ctid::text AS __left_row_ref, r.ctid::text AS __right_row_ref, "
                f"l.{q_left_key} AS left_key_value, r.{q_right_key} AS right_key_value "
                f"FROM {q_left_table} l "
                f"JOIN {q_right_table} r ON r.{q_right_key} = l.{q_left_key} "
                f"WHERE l.{q_left_key} IS NOT NULL "
                f"ORDER BY l.ctid LIMIT {row_limit} OFFSET {row_offset}"
            ),
            [],
            scoped_conn=scoped_conn,
        )
        for row in matched_rows:
            row["left_row_lineage_id"] = _lineage_id(left_table, row.get("__left_row_ref"))
            row["right_row_lineage_id"] = _lineage_id(right_table, row.get("__right_row_ref"))
            row["row_lineage_id"] = _lineage_id(left_table, row.get("__left_row_ref"), right_table, row.get("__right_row_ref"))
        unmatched_left_rows = run_query(
            settings,
            (
                f"SELECT l.ctid::text AS __left_row_ref, l.{q_left_key} AS left_key_value, * "
                f"FROM {q_left_table} l "
                f"WHERE l.{q_left_key} IS NULL "
                f"OR NOT EXISTS (SELECT 1 FROM {q_right_table} r WHERE r.{q_right_key} = l.{q_left_key}) "
                f"ORDER BY l.ctid LIMIT {row_limit} OFFSET {row_offset}"
            ),
            [],
            scoped_conn=scoped_conn,
        )
        for row in unmatched_left_rows:
            row["row_lineage_id"] = _lineage_id(left_table, row.get("__left_row_ref"))
        unmatched_right_rows = run_query(
            settings,
            (
                f"SELECT r.ctid::text AS __right_row_ref, r.{q_right_key} AS right_key_value, * "
                f"FROM {q_right_table} r "
                f"WHERE r.{q_right_key} IS NULL "
                f"OR NOT EXISTS (SELECT 1 FROM {q_left_table} l WHERE l.{q_left_key} = r.{q_right_key}) "
                f"ORDER BY r.ctid LIMIT {row_limit} OFFSET {row_offset}"
            ),
            [],
            scoped_conn=scoped_conn,
        )
        for row in unmatched_right_rows:
            row["row_lineage_id"] = _lineage_id(right_table, row.get("__right_row_ref"))
        return {
            "stage_id": stage_id,
            "stage": stage,
            "evidence_type": "join_validation",
            "join_name": join.get("join_name"),
            "match_key_aliases": {
                "left_key_alias": canonical_column_alias(left_key),
                "right_key_alias": canonical_column_alias(right_key),
            },
            "matched_rows": matched_rows,
            "unmatched_left_rows": unmatched_left_rows,
            "unmatched_right_rows": unmatched_right_rows,
            "summary": stage_summary,
            "limit": row_limit,
            "offset": row_offset,
        }
    if stage_type == "filter":
        parsed_filter = stage_summary.get("parsed_filter") or {}
        table_name = str(parsed_filter.get("table_name") or stage_summary.get("output_dataset") or "").strip()
        predicate, params = _build_filter_predicate(parsed_filter)
        passed_rows: list[dict[str, Any]] = []
        if table_name and predicate:
            passed_rows = run_query(
                settings,
                (
                    f"SELECT ctid::text AS __row_ref, * FROM {q_schema}.{_qident(table_name)} "
                    f"WHERE {predicate} ORDER BY ctid LIMIT {row_limit} OFFSET {row_offset}"
                ),
                params,
                scoped_conn=scoped_conn,
            )
            for row in passed_rows:
                row["row_lineage_id"] = _lineage_id(table_name, row.get("__row_ref"))
        rejected_rows = [
            row
            for row in list_quality_stage_row_outcomes(
                settings,
                tenant_id=tenant_id,
                domain_id=domain_id,
                run_id=str(stage.get("run_id") or ""),
                stage_id=stage_id,
                outcome_type="rejected",
                limit=row_limit,
            )
        ]
        return {
            "stage_id": stage_id,
            "stage": stage,
            "evidence_type": "filter",
            "table_name": table_name,
            "passed_rows": passed_rows,
            "rejected_rows": rejected_rows,
            "summary": stage_summary,
            "limit": row_limit,
            "offset": row_offset,
        }
    return {
        "stage_id": stage_id,
        "stage": stage,
        "evidence_type": stage_type,
        "rows": [],
        "summary": stage_summary,
        "message": "This stage is planned or derived and does not have row-level evidence yet.",
    }


def fetch_join_evidence(
    settings: Settings,
    *,
    join_artifact_id: str,
    tenant_id: str,
    domain_id: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    join = get_quality_join_artifact(settings, join_artifact_id, tenant_id=tenant_id)
    if not join or str(join.get("domain_id") or "") != str(domain_id):
        raise HTTPException(status_code=404, detail="Data quality join artifact not found")
    run_row = load_quality_run(
        settings,
        run_id=str(join.get("run_id") or ""),
        tenant_id=tenant_id,
        domain_id=domain_id,
    )
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    if not scoped_conn:
        return {
            "join_artifact_id": join_artifact_id,
            "join": join,
            "summary": join.get("summary_json") or {},
            "matched_rows": [],
            "unmatched_left_rows": [],
            "unmatched_right_rows": [],
        }
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    q_schema = _qident(schema_name)
    join_summary = join.get("summary_json") or {}
    left_table = str(join.get("left_table") or "").strip()
    right_table = str(join.get("right_table") or "").strip()
    join_keys = list(join.get("join_keys_json") or [])
    left_key = str((join_keys[0] or {}).get("left_key") or "").strip() if join_keys else ""
    right_key = str((join_keys[0] or {}).get("right_key") or "").strip() if join_keys else ""
    if not left_table or not right_table or not left_key or not right_key:
        raise HTTPException(status_code=404, detail="Join artifact keys are missing")
    q_left_table = f"{q_schema}.{_qident(left_table)}"
    q_right_table = f"{q_schema}.{_qident(right_table)}"
    q_left_key = _qident(left_key)
    q_right_key = _qident(right_key)
    row_limit = _safe_limit(limit)
    row_offset = _safe_offset(offset)
    matched_rows = run_query(
        settings,
        (
            f"SELECT l.ctid::text AS __left_row_ref, r.ctid::text AS __right_row_ref, "
            f"l.{q_left_key} AS left_key_value, r.{q_right_key} AS right_key_value "
            f"FROM {q_left_table} l "
            f"JOIN {q_right_table} r ON r.{q_right_key} = l.{q_left_key} "
            f"WHERE l.{q_left_key} IS NOT NULL "
            f"ORDER BY l.ctid LIMIT {row_limit} OFFSET {row_offset}"
        ),
        [],
        scoped_conn=scoped_conn,
    )
    for row in matched_rows:
        row["left_row_lineage_id"] = _lineage_id(left_table, row.get("__left_row_ref"))
        row["right_row_lineage_id"] = _lineage_id(right_table, row.get("__right_row_ref"))
        row["row_lineage_id"] = _lineage_id(left_table, row.get("__left_row_ref"), right_table, row.get("__right_row_ref"))
    unmatched_left_rows = run_query(
        settings,
        (
            f"SELECT l.ctid::text AS __left_row_ref, l.{q_left_key} AS left_key_value, * "
            f"FROM {q_left_table} l "
            f"WHERE l.{q_left_key} IS NULL "
            f"OR NOT EXISTS (SELECT 1 FROM {q_right_table} r WHERE r.{q_right_key} = l.{q_left_key}) "
            f"ORDER BY l.ctid LIMIT {row_limit} OFFSET {row_offset}"
        ),
        [],
        scoped_conn=scoped_conn,
    )
    for row in unmatched_left_rows:
        row["row_lineage_id"] = _lineage_id(left_table, row.get("__left_row_ref"))
    unmatched_right_rows = run_query(
        settings,
        (
            f"SELECT r.ctid::text AS __right_row_ref, r.{q_right_key} AS right_key_value, * "
            f"FROM {q_right_table} r "
            f"WHERE r.{q_right_key} IS NULL "
            f"OR NOT EXISTS (SELECT 1 FROM {q_left_table} l WHERE l.{q_left_key} = r.{q_right_key}) "
            f"ORDER BY r.ctid LIMIT {row_limit} OFFSET {row_offset}"
        ),
        [],
        scoped_conn=scoped_conn,
    )
    for row in unmatched_right_rows:
        row["row_lineage_id"] = _lineage_id(right_table, row.get("__right_row_ref"))
    return {
        "join_artifact_id": join_artifact_id,
        "join": join,
        "match_key_aliases": {
            "left_key_alias": canonical_column_alias(left_key),
            "right_key_alias": canonical_column_alias(right_key),
        },
        "matched_rows": matched_rows,
        "unmatched_left_rows": unmatched_left_rows,
        "unmatched_right_rows": unmatched_right_rows,
        "summary": join_summary,
        "limit": row_limit,
        "offset": row_offset,
    }


def fetch_final_dataset_rows(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    run_row = load_quality_run(settings, run_id=run_id, tenant_id=tenant_id, domain_id=domain_id)
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    dataset_stages = list_quality_dataset_stages(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    final_dataset = get_quality_final_dataset_artifact(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id) or {}
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    rows, basis_stage = fetch_final_dataset_rows_tool(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        stages=dataset_stages,
        final_dataset=final_dataset,
        limit=limit,
        offset=offset,
    )
    return {
        "run_id": run_id,
        "final_dataset": final_dataset,
        "basis_stage": basis_stage or {},
        "rows": rows,
        "limit": _safe_limit(limit),
        "offset": _safe_offset(offset),
    }


def fetch_lineage_trace(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    row_lineage_id: str,
    final_limit: int = 4000,
) -> dict[str, Any]:
    run_row = load_quality_run(settings, run_id=run_id, tenant_id=tenant_id, domain_id=domain_id)
    stages = list_quality_dataset_stages(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    stage_by_id = {str(item.get("stage_id") or ""): item for item in stages if str(item.get("stage_id") or "").strip()}
    edges = list_quality_lineage_edges(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        row_lineage_id=row_lineage_id,
        limit=1200,
    )
    outcomes = [
        row
        for row in list_quality_stage_row_outcomes(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=4000)
        if str(row.get("row_lineage_id") or "") == str(row_lineage_id)
    ]
    parsed = parse_lineage_id(row_lineage_id)
    source_snapshot = None
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    if scoped_conn and parsed and len(parsed.get("parts") or []) == 2:
        source_table, row_ref = parsed["parts"]
        try:
            rows = run_query(
                settings,
                f'SELECT ctid::text AS __row_ref, * FROM {_qident(schema_name)}.{_qident(source_table)} WHERE ctid::text = %s LIMIT 1',
                [row_ref],
                scoped_conn=scoped_conn,
            )
            source_snapshot = rows[0] if rows else None
            if source_snapshot:
                source_snapshot["row_lineage_id"] = row_lineage_id
        except Exception:
            source_snapshot = None
    final_dataset = get_quality_final_dataset_artifact(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id) or {}
    final_rows, basis_stage = fetch_final_dataset_rows_tool(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        stages=stages,
        final_dataset=final_dataset,
        limit=final_limit,
        offset=0,
    )
    final_membership_row = next((row for row in final_rows if str(row.get("row_lineage_id") or "") == str(row_lineage_id)), None)
    stage_trace: list[dict[str, Any]] = []
    seen_stage_ids: set[str] = set()
    for edge in edges:
        from_stage_id = str(edge.get("from_stage_id") or "")
        to_stage_id = str(edge.get("to_stage_id") or "")
        if from_stage_id and from_stage_id not in seen_stage_ids:
            stage = stage_by_id.get(from_stage_id) or {}
            stage_trace.append(
                {
                    "stage_id": from_stage_id,
                    "stage_name": edge.get("from_stage_name") or stage.get("stage_name"),
                    "stage_type": stage.get("stage_type"),
                    "stage_seq": stage.get("stage_seq"),
                    "state": "entered",
                }
            )
            seen_stage_ids.add(from_stage_id)
        if to_stage_id and to_stage_id not in seen_stage_ids:
            stage = stage_by_id.get(to_stage_id) or {}
            stage_trace.append(
                {
                    "stage_id": to_stage_id,
                    "stage_name": edge.get("to_stage_name") or stage.get("stage_name"),
                    "stage_type": stage.get("stage_type"),
                    "stage_seq": stage.get("stage_seq"),
                    "state": edge.get("edge_type"),
                }
            )
            seen_stage_ids.add(to_stage_id)
    for outcome in outcomes:
        stage_id = str(outcome.get("stage_id") or "")
        if stage_id and stage_id not in seen_stage_ids:
            stage = stage_by_id.get(stage_id) or {}
            stage_trace.append(
                {
                    "stage_id": stage_id,
                    "stage_name": outcome.get("stage_name") or stage.get("stage_name"),
                    "stage_type": stage.get("stage_type"),
                    "stage_seq": stage.get("stage_seq"),
                    "state": outcome.get("reason_code") or outcome.get("outcome_type"),
                }
            )
            seen_stage_ids.add(stage_id)
    if final_membership_row is not None:
        stage_trace.append(
            {
                "stage_id": (basis_stage or {}).get("stage_id"),
                "stage_name": (basis_stage or {}).get("stage_name"),
                "stage_type": (basis_stage or {}).get("stage_type"),
                "stage_seq": (basis_stage or {}).get("stage_seq"),
                "state": "final_dataset_member",
            }
        )
    stage_trace.sort(key=lambda item: (999999 if item.get("stage_seq") is None else int(item.get("stage_seq") or 0), str(item.get("stage_name") or "")))
    return {
        "run_id": run_id,
        "row_lineage_id": row_lineage_id,
        "decoded_lineage": parsed,
        "source_snapshot": source_snapshot,
        "edges": edges,
        "outcomes": outcomes,
        "stage_trace": stage_trace,
        "final_dataset_membership": {
            "is_member": final_membership_row is not None,
            "basis_stage": basis_stage or {},
            "row": final_membership_row,
        },
    }


def _journey_status_category(state: str | None) -> str:
    text = str(state or "").strip().lower()
    if text in {"final_dataset_member", "join_matched", "passed", "entered"}:
        return "progressed"
    if text in {"join_unmatched_left", "join_unmatched_right", "filter_rejected", "rejected", "join_exception"}:
        return "rejected"
    return "observed"


def _journey_display_label(*, stage_name: str | None, stage_type: str | None, state: str | None) -> str:
    stage_text = str(stage_name or stage_type or "stage").strip()
    state_text = str(state or "").strip().lower()
    if state_text == "entered":
        return f"Entered {stage_text}"
    if state_text == "final_dataset_member":
        return f"Included in final dataset from {stage_text}"
    if state_text == "join_matched":
        return f"Matched join in {stage_text}"
    if state_text == "join_unmatched_left":
        return f"Rejected by left-side join mismatch in {stage_text}"
    if state_text == "join_unmatched_right":
        return f"Rejected by right-side join mismatch in {stage_text}"
    if state_text == "filter_rejected":
        return f"Rejected by filter in {stage_text}"
    if state_text == "rejected":
        return f"Rejected in {stage_text}"
    pretty_state = state_text.replace("_", " ").strip() if state_text else "tracked"
    return f"{pretty_state.title()} in {stage_text}"


def fetch_lineage_journey(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    row_lineage_id: str,
) -> dict[str, Any]:
    trace = fetch_lineage_trace(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        row_lineage_id=row_lineage_id,
    )
    journey: list[dict[str, Any]] = []
    for index, item in enumerate(trace.get("stage_trace") or [], start=1):
        stage_name = item.get("stage_name")
        stage_type = item.get("stage_type")
        state = item.get("state")
        journey.append(
            {
                "step_index": index,
                "stage_id": item.get("stage_id"),
                "stage_seq": item.get("stage_seq"),
                "stage_name": stage_name,
                "stage_type": stage_type,
                "state": state,
                "status_category": _journey_status_category(state),
                "display_label": _journey_display_label(stage_name=stage_name, stage_type=stage_type, state=state),
            }
        )
    parsed = trace.get("decoded_lineage") or {}
    source = {
        "source_table": (parsed.get("parts") or [None, None])[0] if isinstance(parsed, dict) else None,
        "source_row_ref": (parsed.get("parts") or [None, None])[1] if isinstance(parsed, dict) and len(parsed.get("parts") or []) > 1 else None,
        "decoded_lineage": parsed.get("raw") if isinstance(parsed, dict) else None,
        "source_snapshot": trace.get("source_snapshot"),
    }
    final_membership = trace.get("final_dataset_membership") or {}
    return {
        "run_id": run_id,
        "row_lineage_id": row_lineage_id,
        "source": source,
        "summary": {
            "step_count": len(journey),
            "transition_count": len(trace.get("edges") or []),
            "outcome_count": len(trace.get("outcomes") or []),
            "final_dataset_member": bool(final_membership.get("is_member")),
            "final_state": journey[-1]["state"] if journey else None,
        },
        "journey": journey,
        "final_dataset_membership": final_membership,
        "trace_path": f"/data-quality/lineage/{row_lineage_id}?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
    }


def fetch_lineage_overview(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    limit: int = 1200,
) -> dict[str, Any]:
    run_row = load_quality_run(settings, run_id=run_id, tenant_id=tenant_id, domain_id=domain_id)
    stages = list_quality_dataset_stages(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    stage_by_id = {str(item.get("stage_id") or ""): item for item in stages if str(item.get("stage_id") or "").strip()}
    edges = list_quality_lineage_edges(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=4000,
    )
    outcomes = list_quality_stage_row_outcomes(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=4000,
    )
    scoped_conn = resolve_quality_run_scoped_conn(settings, run_row)
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    final_dataset = get_quality_final_dataset_artifact(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id) or {}
    final_rows, basis_stage = fetch_final_dataset_rows_tool(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        stages=stages,
        final_dataset=final_dataset,
        limit=4000,
        offset=0,
    )
    final_members = {str(row.get("row_lineage_id") or "").strip() for row in final_rows if str(row.get("row_lineage_id") or "").strip()}

    lineage_ids: set[str] = set()
    lineage_ids.update(str(row.get("row_lineage_id") or "").strip() for row in edges)
    lineage_ids.update(str(row.get("row_lineage_id") or "").strip() for row in outcomes)
    lineage_ids.update(final_members)
    lineage_ids.discard("")

    rows: list[dict[str, Any]] = []
    for row_lineage_id in sorted(lineage_ids):
        parsed = parse_lineage_id(row_lineage_id)
        row_edges = [row for row in edges if str(row.get("row_lineage_id") or "") == row_lineage_id]
        row_outcomes = [row for row in outcomes if str(row.get("row_lineage_id") or "") == row_lineage_id]
        stage_trace: list[tuple[int, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for edge in row_edges:
            for stage_id_key, stage_name_key in (("from_stage_id", "from_stage_name"), ("to_stage_id", "to_stage_name")):
                stage_id = str(edge.get(stage_id_key) or "")
                if not stage_id:
                    continue
                stage = stage_by_id.get(stage_id) or {}
                stage_name = str(edge.get(stage_name_key) or stage.get("stage_name") or "").strip()
                marker = (stage_id, stage_name)
                if marker in seen:
                    continue
                seen.add(marker)
                stage_trace.append((int(stage.get("stage_seq") or 999999), stage_id, stage_name))
        for outcome in row_outcomes:
            stage_id = str(outcome.get("stage_id") or "")
            if not stage_id:
                continue
            stage = stage_by_id.get(stage_id) or {}
            stage_name = str(outcome.get("stage_name") or stage.get("stage_name") or "").strip()
            marker = (stage_id, stage_name)
            if marker in seen:
                continue
            seen.add(marker)
            stage_trace.append((int(stage.get("stage_seq") or 999999), stage_id, stage_name))
        latest_stage_name = None
        latest_stage_seq = None
        if stage_trace:
            latest_stage = sorted(stage_trace, key=lambda item: (item[0], item[2]))[-1]
            latest_stage_seq = latest_stage[0]
            latest_stage_name = latest_stage[2]
        if row_lineage_id in final_members and basis_stage:
            latest_stage_seq = basis_stage.get("stage_seq")
            latest_stage_name = basis_stage.get("stage_name")
        source_table = None
        source_row_ref = None
        decoded_label = None
        if parsed:
            parts = parsed.get("parts") or []
            decoded_label = " -> ".join(str(part) for part in parts if str(part).strip())
            if len(parts) >= 2:
                source_table = parts[0]
                source_row_ref = parts[1]
        outcome_types = [str(row.get("outcome_type") or "").strip() for row in row_outcomes if str(row.get("outcome_type") or "").strip()]
        reason_codes = [str(row.get("reason_code") or "").strip() for row in row_outcomes if str(row.get("reason_code") or "").strip()]
        if row_lineage_id in final_members:
            final_state = "final_dataset_member"
        elif reason_codes:
            final_state = reason_codes[-1]
        elif outcome_types:
            final_state = outcome_types[-1]
        elif row_edges:
            final_state = str(row_edges[-1].get("edge_type") or "transition")
        else:
            final_state = "tracked"
        rows.append(
            {
                "row_lineage_id": row_lineage_id,
                "source_table": source_table,
                "source_row_ref": source_row_ref,
                "decoded_lineage": decoded_label,
                "transition_count": len(row_edges),
                "stage_count": len(stage_trace),
                "rejected_count": sum(1 for row in row_outcomes if str(row.get("outcome_type") or "").strip() == "rejected"),
                "join_exception_count": sum(1 for row in row_outcomes if str(row.get("outcome_type") or "").strip() == "join_exception"),
                "latest_stage_seq": latest_stage_seq,
                "latest_stage_name": latest_stage_name,
                "final_state": final_state,
                "final_dataset_member": row_lineage_id in final_members,
                "evidence_path": f"/data-quality/lineage/{row_lineage_id}/journey?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row.get("final_dataset_member") else 1,
            -(int(row.get("rejected_count") or 0) + int(row.get("join_exception_count") or 0)),
            -(int(row.get("transition_count") or 0)),
            str(row.get("source_table") or ""),
            str(row.get("source_row_ref") or ""),
        )
    )
    safe_limit = _safe_limit(limit, default=1200, max_value=4000)
    return {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "summary": {
            "lineage_row_count": len(rows),
            "final_dataset_member_count": sum(1 for row in rows if row.get("final_dataset_member")),
            "rejected_row_count": sum(1 for row in rows if int(row.get("rejected_count") or 0) > 0),
            "join_exception_row_count": sum(1 for row in rows if int(row.get("join_exception_count") or 0) > 0),
        },
        "rows": rows[:safe_limit],
    }
