from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
import json
import uuid

import psycopg2
from psycopg2.extras import Json

from services.ai.config import Settings
from services.ai.db import execute_non_query, execute_returning_query, run_query


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _severity_from_score(score: Any) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if value < 50.0:
        return "critical"
    if value < 75.0:
        return "warning"
    return "good"


def quality_run_id_for(run_id: str) -> str:
    suffix = str(run_id or "").replace("run_", "").strip() or uuid.uuid4().hex[:12]
    return f"dqrun_{suffix[:32]}"


def create_or_update_quality_run(
    settings: Settings,
    *,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
    status: str = "running",
    overall_trust_score: float | None = None,
    summary_json: dict[str, Any] | None = None,
    completed: bool = False,
) -> str | None:
    quality_run_id = quality_run_id_for(run_id)
    sql = """
        INSERT INTO public.quantyx_data_quality_runs (
          quality_run_id, run_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          status, overall_trust_score, summary_json, created_at, completed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), CASE WHEN %s THEN now() ELSE NULL END)
        ON CONFLICT (quality_run_id)
        DO UPDATE SET
          status = EXCLUDED.status,
          overall_trust_score = EXCLUDED.overall_trust_score,
          summary_json = COALESCE(EXCLUDED.summary_json, public.quantyx_data_quality_runs.summary_json),
          connection_id = COALESCE(EXCLUDED.connection_id, public.quantyx_data_quality_runs.connection_id),
          database_name = COALESCE(EXCLUDED.database_name, public.quantyx_data_quality_runs.database_name),
          schema_name = COALESCE(EXCLUDED.schema_name, public.quantyx_data_quality_runs.schema_name),
          completed_at = CASE WHEN %s THEN now() ELSE public.quantyx_data_quality_runs.completed_at END
    """
    try:
        execute_non_query(
            settings,
            sql,
            [
                quality_run_id,
                run_id,
                tenant_id,
                domain_id,
                connection_id,
                database_name,
                schema_name,
                status,
                overall_trust_score,
                Json(summary_json or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                completed,
                completed,
            ],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return quality_run_id


def _table_summary(table: dict[str, Any]) -> dict[str, Any]:
    quality = table.get("quality_summary") or {}
    return {
        "quality_summary": quality,
        "candidate_keys": table.get("candidate_keys") or [],
        "fuzzy_duplicate_signals": table.get("fuzzy_duplicate_signals") or [],
    }


def _column_flags(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "is_sparse": bool(profile.get("is_sparse")),
        "is_very_sparse": bool(profile.get("is_very_sparse")),
        "semantic_role": profile.get("semantic_role"),
    }


def upsert_quality_artifacts_from_profiling(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
    profiling_json: dict[str, Any],
) -> dict[str, int]:
    tables = profiling_json.get("tables") or []
    table_count = 0
    column_count = 0
    table_sql = """
        INSERT INTO public.quantyx_data_quality_table_artifacts (
          artifact_id, quality_run_id, run_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          table_name, row_count, trust_score, completeness_score, freshness_score, duplicate_risk_score,
          severity, summary_json, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (quality_run_id, table_name)
        DO UPDATE SET
          row_count = EXCLUDED.row_count,
          trust_score = EXCLUDED.trust_score,
          completeness_score = EXCLUDED.completeness_score,
          freshness_score = EXCLUDED.freshness_score,
          duplicate_risk_score = EXCLUDED.duplicate_risk_score,
          severity = EXCLUDED.severity,
          summary_json = EXCLUDED.summary_json,
          updated_at = now()
    """
    column_sql = """
        INSERT INTO public.quantyx_data_quality_column_artifacts (
          artifact_id, quality_run_id, run_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          table_name, column_name, data_type, null_count, null_pct, blank_count, blank_pct,
          distinct_count, distinct_ratio, completeness_score, column_trust_score, quality_flags_json,
          created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (quality_run_id, table_name, column_name)
        DO UPDATE SET
          data_type = EXCLUDED.data_type,
          null_count = EXCLUDED.null_count,
          null_pct = EXCLUDED.null_pct,
          blank_count = EXCLUDED.blank_count,
          blank_pct = EXCLUDED.blank_pct,
          distinct_count = EXCLUDED.distinct_count,
          distinct_ratio = EXCLUDED.distinct_ratio,
          completeness_score = EXCLUDED.completeness_score,
          column_trust_score = EXCLUDED.column_trust_score,
          quality_flags_json = EXCLUDED.quality_flags_json,
          updated_at = now()
    """
    try:
        for table in tables:
            table_name = str(table.get("name") or "").strip()
            if not table_name:
                continue
            quality = table.get("quality_summary") or {}
            trust_score = quality.get("table_trust_score")
            completeness_score = quality.get("table_completeness_score")
            freshness_score = None
            if quality.get("freshness_lag_days") is not None:
                try:
                    freshness_score = max(0.0, 100.0 - min(float(quality.get("freshness_lag_days")), 20.0) * 5.0)
                except (TypeError, ValueError):
                    freshness_score = None
            duplicate_risk_score = None
            duplicate_count = int(quality.get("duplicate_risk_columns_count") or 0)
            if duplicate_count:
                duplicate_risk_score = max(0.0, 100.0 - min(float(duplicate_count) * 10.0, 100.0))
            execute_non_query(
                settings,
                table_sql,
                [
                    f"dqta_{uuid.uuid4().hex[:12]}",
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    connection_id,
                    database_name,
                    schema_name,
                    table_name,
                    quality.get("row_count") or table.get("row_count"),
                    trust_score,
                    completeness_score,
                    freshness_score,
                    duplicate_risk_score,
                    _severity_from_score(trust_score),
                    Json(_table_summary(table), dumps=lambda value: json.dumps(value, default=_json_default)),
                ],
            )
            table_count += 1
            for profile in table.get("column_profiles") or []:
                column_name = str(profile.get("name") or "").strip()
                if not column_name:
                    continue
                completeness = profile.get("completeness_score")
                execute_non_query(
                    settings,
                    column_sql,
                    [
                        f"dqca_{uuid.uuid4().hex[:12]}",
                        quality_run_id,
                        run_id,
                        tenant_id,
                        domain_id,
                        connection_id,
                        database_name,
                        schema_name,
                        table_name,
                        column_name,
                        profile.get("data_type"),
                        profile.get("null_count"),
                        profile.get("null_pct"),
                        profile.get("blank_count"),
                        profile.get("blank_pct"),
                        profile.get("distinct_count"),
                        profile.get("distinct_ratio"),
                        completeness,
                        completeness,
                        Json(_column_flags(profile), dumps=lambda value: json.dumps(value, default=_json_default)),
                    ],
                )
                column_count += 1
    except psycopg2.errors.UndefinedTable:
        return {"tables": 0, "columns": 0}
    return {"tables": table_count, "columns": column_count}


def replace_quality_rules(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None,
    database_name: str | None,
    schema_name: str | None,
    rules: list[dict[str, Any]],
    source: str = "context_text",
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_data_quality_rules
         WHERE quality_run_id = %s
           AND source = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_data_quality_rules (
          rule_id, quality_run_id, run_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          rule_type, severity, table_name, column_name, reference_table, reference_column, source_text,
          executor_kind, execution_plan_json, reviewed_by, reviewed_at, review_notes,
          condition_json, source, confidence, status, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s, %s, now(), now())
    """
    try:
        execute_non_query(settings, delete_sql, [quality_run_id, source])
        inserted = 0
        for rule in rules:
            table_name = str(rule.get("table_name") or "").strip()
            rule_type = str(rule.get("rule_type") or "").strip()
            if not table_name or not rule_type:
                continue
            rule_source = str(rule.get("source") or source).strip() or source
            rule_id = str(rule.get("rule_id") or "").strip() or f"dqr_{uuid.uuid4().hex[:12]}"
            rule["rule_id"] = rule_id
            rule["quality_run_id"] = quality_run_id
            rule["run_id"] = run_id
            rule["tenant_id"] = tenant_id
            rule["domain_id"] = domain_id
            execute_non_query(
                settings,
                insert_sql,
                [
                    rule_id,
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    connection_id,
                    database_name,
                    schema_name,
                    rule_type,
                    rule.get("severity") or "warning",
                    table_name,
                    rule.get("column_name"),
                    rule.get("reference_table"),
                    rule.get("reference_column"),
                    rule.get("source_text"),
                    rule.get("executor_kind"),
                    Json(rule.get("execution_plan_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                    rule.get("reviewed_by"),
                    rule.get("reviewed_at"),
                    rule.get("review_notes"),
                    Json(rule.get("condition_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                    rule_source,
                    rule.get("confidence"),
                    rule.get("status") or "active",
                ],
            )
            inserted += 1
    except psycopg2.errors.UndefinedTable:
        return 0
    return inserted


def get_quality_rule(
    settings: Settings,
    rule_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [rule_id]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND r.tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = run_query(
            settings,
            f"""
            SELECT r.*,
                   latest.result_id,
                   latest.status AS result_status,
                   latest.checked_row_count,
                   latest.violation_count,
                   latest.violation_pct,
                   latest.sample_rows_json,
                   latest.error_message,
                   latest.executed_at
              FROM public.quantyx_data_quality_rules r
              LEFT JOIN LATERAL (
                SELECT rr.*
                  FROM public.quantyx_data_quality_rule_results rr
                 WHERE rr.rule_id = r.rule_id
                 ORDER BY rr.executed_at DESC
                 LIMIT 1
              ) latest ON true
             WHERE r.rule_id = %s
               {tenant_filter}
             LIMIT 1
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def update_quality_rule_review(
    settings: Settings,
    *,
    rule_id: str,
    status: str,
    reviewed_by: str | None = None,
    review_notes: str | None = None,
    tenant_id: str | None = None,
    source_text: str | None = None,
    severity: str | None = None,
    table_name: str | None = None,
    column_name: str | None = None,
    reference_table: str | None = None,
    reference_column: str | None = None,
    condition_json: dict[str, Any] | None = None,
    executor_kind: str | None = None,
    execution_plan_json: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [
        status,
        reviewed_by,
        review_notes,
        source_text,
        severity,
        table_name,
        column_name,
        reference_table,
        reference_column,
        Json(condition_json, dumps=lambda value: json.dumps(value, default=_json_default)) if condition_json is not None else None,
        executor_kind,
        Json(execution_plan_json, dumps=lambda value: json.dumps(value, default=_json_default)) if execution_plan_json is not None else None,
        rule_id,
    ]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = execute_returning_query(
            settings,
            f"""
            UPDATE public.quantyx_data_quality_rules
               SET status = %s,
                   reviewed_by = COALESCE(%s, reviewed_by),
                   reviewed_at = now(),
                   review_notes = COALESCE(%s, review_notes),
                   source_text = COALESCE(%s, source_text),
                   severity = COALESCE(%s, severity),
                   table_name = COALESCE(%s, table_name),
                   column_name = COALESCE(%s, column_name),
                   reference_table = COALESCE(%s, reference_table),
                   reference_column = COALESCE(%s, reference_column),
                   condition_json = COALESCE(%s::jsonb, condition_json),
                   executor_kind = COALESCE(%s, executor_kind),
                   execution_plan_json = COALESCE(%s::jsonb, execution_plan_json),
                   updated_at = now()
             WHERE rule_id = %s
               {tenant_filter}
             RETURNING *
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def insert_quality_rule_result(
    settings: Settings,
    *,
    rule: dict[str, Any],
    status: str,
    checked_row_count: int | None = None,
    violation_count: int | None = None,
    violation_pct: float | None = None,
    sample_rows_json: list[dict[str, Any]] | None = None,
    error_message: str | None = None,
) -> str | None:
    result_id = f"dqrr_{uuid.uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_data_quality_rule_results (
          result_id, rule_id, quality_run_id, run_id, tenant_id, domain_id, status,
          checked_row_count, violation_count, violation_pct, sample_rows_json, error_message,
          executed_at, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now(), now())
    """
    try:
        execute_non_query(
            settings,
            sql,
            [
                result_id,
                rule.get("rule_id"),
                rule.get("quality_run_id"),
                rule.get("run_id"),
                rule.get("tenant_id"),
                rule.get("domain_id"),
                status,
                checked_row_count,
                violation_count,
                violation_pct,
                Json(sample_rows_json or [], dumps=lambda value: json.dumps(value, default=_json_default)),
                error_message,
            ],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return result_id


def replace_quality_duplicate_candidates(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    candidates: list[dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_data_quality_duplicate_candidates
         WHERE quality_run_id = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_data_quality_duplicate_candidates (
          candidate_id, quality_run_id, run_id, tenant_id, domain_id, table_name, duplicate_type,
          match_columns_json, confidence, candidate_record_count, sample_rows_json, cluster_json,
          review_status, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s, now(), now())
    """
    try:
        execute_non_query(settings, delete_sql, [quality_run_id])
        inserted = 0
        for candidate in candidates:
            table_name = str(candidate.get("table_name") or "").strip()
            duplicate_type = str(candidate.get("duplicate_type") or "").strip()
            if not table_name or not duplicate_type:
                continue
            execute_non_query(
                settings,
                insert_sql,
                [
                    candidate.get("candidate_id") or f"dqdup_{uuid.uuid4().hex[:12]}",
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    table_name,
                    duplicate_type,
                    Json(candidate.get("match_columns_json") or [], dumps=lambda value: json.dumps(value, default=_json_default)),
                    candidate.get("confidence"),
                    candidate.get("candidate_record_count"),
                    Json(candidate.get("sample_rows_json") or [], dumps=lambda value: json.dumps(value, default=_json_default)),
                    Json(candidate.get("cluster_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                    candidate.get("review_status") or "needs_review",
                ],
            )
            inserted += 1
    except psycopg2.errors.UndefinedTable:
        return 0
    return inserted


def get_previous_quality_run(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    current_run_id: str,
) -> dict[str, Any] | None:
    try:
        rows = run_query(
            settings,
            """
            SELECT *
              FROM public.quantyx_data_quality_runs
             WHERE tenant_id = %s
               AND domain_id = %s
               AND run_id <> %s
             ORDER BY COALESCE(completed_at, created_at) DESC
             LIMIT 1
            """,
            [tenant_id, domain_id, current_run_id],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def list_quality_tables_by_quality_run(
    settings: Settings,
    *,
    quality_run_id: str,
) -> list[dict[str, Any]]:
    try:
        return run_query(
            settings,
            """
            SELECT *
              FROM public.quantyx_data_quality_table_artifacts
             WHERE quality_run_id = %s
             ORDER BY table_name ASC
            """,
            [quality_run_id],
        )
    except psycopg2.errors.UndefinedTable:
        return []


def update_quality_table_monitoring(
    settings: Settings,
    *,
    quality_run_id: str,
    table_name: str,
    freshness_score: float | None,
    monitoring_json: dict[str, Any],
) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_data_quality_table_artifacts
           SET freshness_score = COALESCE(%s, freshness_score),
               summary_json = COALESCE(summary_json, '{}'::jsonb) || %s::jsonb,
               updated_at = now()
         WHERE quality_run_id = %s
           AND table_name = %s
        """,
        [
            freshness_score,
            Json(monitoring_json or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
            quality_run_id,
            table_name,
        ],
    )


def update_quality_table_trust_scores(
    settings: Settings,
    *,
    quality_run_id: str,
    table_scores: list[dict[str, Any]],
) -> None:
    sql = """
        UPDATE public.quantyx_data_quality_table_artifacts
           SET trust_score = %s,
               validity_score = %s,
               uniqueness_score = %s,
               referential_integrity_score = %s,
               freshness_score = COALESCE(%s, freshness_score),
               duplicate_risk_score = %s,
               severity = %s,
               summary_json = COALESCE(summary_json, '{}'::jsonb) || %s::jsonb,
               updated_at = now()
         WHERE quality_run_id = %s
           AND table_name = %s
    """
    for item in table_scores:
        execute_non_query(
            settings,
            sql,
            [
                item.get("trust_score"),
                item.get("validity_score"),
                item.get("uniqueness_score"),
                item.get("referential_integrity_score"),
                item.get("freshness_score"),
                item.get("duplicate_risk_score"),
                item.get("severity"),
                Json(
                    {
                        "trust_components": item.get("trust_components") or {},
                        "trust_component_explanations": item.get("trust_component_explanations") or {},
                    },
                    dumps=lambda value: json.dumps(value, default=_json_default),
                ),
                quality_run_id,
                item.get("table_name"),
            ],
        )


def create_quality_report_metadata(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    report_type: str,
    file_name: str,
    mime_type: str,
    storage_uri: str | None = None,
    summary_json: dict[str, Any] | None = None,
) -> str | None:
    report_id = f"dqreport_{uuid.uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_data_quality_reports (
          report_id, quality_run_id, run_id, tenant_id, domain_id, report_type,
          file_name, mime_type, storage_uri, summary_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
    """
    try:
        execute_non_query(
            settings,
            sql,
            [
                report_id,
                quality_run_id,
                run_id,
                tenant_id,
                domain_id,
                report_type,
                file_name,
                mime_type,
                storage_uri,
                Json(summary_json or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
            ],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return report_id


def replace_quality_enrichment_opportunities(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    opportunities: list[dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_data_quality_enrichment_opportunities
         WHERE quality_run_id = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_data_quality_enrichment_opportunities (
          opportunity_id, quality_run_id, run_id, tenant_id, domain_id, table_name, target_column,
          source_columns_json, missing_count, candidate_method, requires_external_lookup,
          requires_user_approval, confidence, question, status, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, now(), now())
    """
    try:
        execute_non_query(settings, delete_sql, [quality_run_id])
        inserted = 0
        for item in opportunities:
            table_name = str(item.get("table_name") or "").strip()
            target_column = str(item.get("target_column") or "").strip()
            if not table_name or not target_column:
                continue
            opportunity_id = str(item.get("opportunity_id") or "").strip() or f"dqeo_{uuid.uuid4().hex[:12]}"
            execute_non_query(
                settings,
                insert_sql,
                [
                    opportunity_id,
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    table_name,
                    target_column,
                    Json(item.get("source_columns_json") or [], dumps=lambda value: json.dumps(value, default=_json_default)),
                    item.get("missing_count"),
                    item.get("candidate_method"),
                    bool(item.get("requires_external_lookup")),
                    bool(item.get("requires_user_approval", True)),
                    item.get("confidence"),
                    item.get("question"),
                    item.get("status") or "needs_user_approval",
                ],
            )
            inserted += 1
    except psycopg2.errors.UndefinedTable:
        return 0
    return inserted


def list_quality_enrichment_opportunities(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    if status:
        filters += " AND status = %s"
        params.append(status)
    params.append(max(1, min(int(limit or 100), 500)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_enrichment_opportunities
             WHERE tenant_id = %s
               AND domain_id = %s
               {filters}
             ORDER BY missing_count DESC NULLS LAST, confidence DESC NULLS LAST, created_at DESC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def list_quality_duplicate_candidates(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    table_name: str | None = None,
    review_status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    if table_name:
        filters += " AND table_name = %s"
        params.append(table_name)
    if review_status:
        filters += " AND review_status = %s"
        params.append(review_status)
    params.append(max(1, min(int(limit or 100), 500)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_duplicate_candidates
             WHERE tenant_id = %s
               AND domain_id = %s
               {filters}
             ORDER BY table_name ASC, confidence DESC NULLS LAST, candidate_record_count DESC NULLS LAST, created_at DESC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def get_quality_enrichment_opportunity(
    settings: Settings,
    opportunity_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [opportunity_id]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_enrichment_opportunities
             WHERE opportunity_id = %s
               {tenant_filter}
             LIMIT 1
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def update_quality_enrichment_opportunity_status(
    settings: Settings,
    opportunity_id: str,
    *,
    tenant_id: str | None = None,
    status: str,
) -> dict[str, Any] | None:
    params: list[Any] = [status, opportunity_id]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = execute_returning_query(
            settings,
            f"""
            UPDATE public.quantyx_data_quality_enrichment_opportunities
               SET status = %s,
                   updated_at = now()
             WHERE opportunity_id = %s
               {tenant_filter}
             RETURNING *
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def create_quality_enrichment_proposal(
    settings: Settings,
    *,
    proposal: dict[str, Any],
) -> dict[str, Any] | None:
    sql = """
        INSERT INTO public.quantyx_data_quality_enrichment_proposals (
          proposal_id, opportunity_id, quality_run_id, run_id, tenant_id, domain_id, status,
          matched_count, unmatched_count, source_references_json, proposed_values_json,
          approved_by, approved_at, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, now(), now())
        RETURNING *
    """
    try:
        rows = execute_returning_query(
            settings,
            sql,
            [
                proposal.get("proposal_id") or f"dqep_{uuid.uuid4().hex[:12]}",
                proposal.get("opportunity_id"),
                proposal.get("quality_run_id"),
                proposal.get("run_id"),
                proposal.get("tenant_id"),
                proposal.get("domain_id"),
                proposal.get("status") or "proposed",
                proposal.get("matched_count"),
                proposal.get("unmatched_count"),
                Json(proposal.get("source_references_json") or [], dumps=lambda value: json.dumps(value, default=_json_default)),
                Json(proposal.get("proposed_values_json") or [], dumps=lambda value: json.dumps(value, default=_json_default)),
                proposal.get("approved_by"),
                proposal.get("approved_at"),
            ],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def get_quality_enrichment_proposal(
    settings: Settings,
    proposal_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [proposal_id]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_enrichment_proposals
             WHERE proposal_id = %s
               {tenant_filter}
             LIMIT 1
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def get_latest_quality_enrichment_proposal_for_opportunity(
    settings: Settings,
    opportunity_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [opportunity_id]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_enrichment_proposals
             WHERE opportunity_id = %s
               {tenant_filter}
             ORDER BY updated_at DESC, created_at DESC
             LIMIT 1
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def update_quality_enrichment_proposal(
    settings: Settings,
    proposal_id: str,
    *,
    tenant_id: str | None = None,
    status: str,
    approved_by: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [status, approved_by, proposal_id]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = execute_returning_query(
            settings,
            f"""
            UPDATE public.quantyx_data_quality_enrichment_proposals
               SET status = %s,
                   approved_by = COALESCE(%s, approved_by),
                   approved_at = CASE WHEN %s LIKE 'approved%%' THEN now() ELSE approved_at END,
                   updated_at = now()
             WHERE proposal_id = %s
               {tenant_filter}
             RETURNING *
            """,
            [status, approved_by, status, proposal_id, *([tenant_id] if tenant_id else [])],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def list_quality_rules(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    status: str | None = None,
    rule_status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND r.run_id = %s"
        params.append(run_id)
    if status:
        filters += " AND COALESCE(latest.status, r.status) = %s"
        params.append(status)
    if rule_status:
        filters += " AND r.status = %s"
        params.append(rule_status)
    params.append(max(1, min(int(limit or 100), 500)))
    try:
        return run_query(
            settings,
            f"""
            SELECT r.*,
                   latest.result_id,
                   latest.status AS result_status,
                   latest.checked_row_count,
                   latest.violation_count,
                   latest.violation_pct,
                   latest.sample_rows_json,
                   latest.error_message,
                   latest.executed_at
              FROM public.quantyx_data_quality_rules r
              LEFT JOIN LATERAL (
                SELECT rr.*
                  FROM public.quantyx_data_quality_rule_results rr
                 WHERE rr.rule_id = r.rule_id
                 ORDER BY rr.executed_at DESC
                 LIMIT 1
              ) latest ON true
             WHERE r.tenant_id = %s
               AND r.domain_id = %s
               {filters}
             ORDER BY r.severity ASC, r.created_at DESC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def get_quality_run_by_run_id(settings: Settings, run_id: str) -> dict[str, Any] | None:
    try:
        rows = run_query(
            settings,
            """
            SELECT *
              FROM public.quantyx_data_quality_runs
             WHERE run_id = %s
             ORDER BY created_at DESC
             LIMIT 1
            """,
            [run_id],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def list_quality_tables(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    run_filter = ""
    if run_id:
        run_filter = "AND run_id = %s"
        params.append(run_id)
    params.append(max(1, min(int(limit or 100), 500)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_table_artifacts
             WHERE tenant_id = %s
               AND domain_id = %s
               {run_filter}
             ORDER BY severity ASC, trust_score ASC NULLS LAST, table_name ASC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def get_quality_table_detail(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    table_name: str,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [tenant_id, domain_id, table_name]
    run_filter = ""
    if run_id:
        run_filter = "AND run_id = %s"
        params.append(run_id)
    try:
        rows = run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_table_artifacts
             WHERE tenant_id = %s
               AND domain_id = %s
               AND table_name = %s
               {run_filter}
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            params,
        )
        if not rows:
            return None
        table = rows[0]
        col_params: list[Any] = [table.get("quality_run_id"), table_name]
        columns = run_query(
            settings,
            """
            SELECT *
              FROM public.quantyx_data_quality_column_artifacts
             WHERE quality_run_id = %s
               AND table_name = %s
             ORDER BY null_pct DESC NULLS LAST, column_name ASC
            """,
            col_params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    table["columns"] = columns
    return table
