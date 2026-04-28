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
    trend_mode: str | None = None,
    trend_scope_key: str | None = None,
    trend_scope_label: str | None = None,
    baseline_run_id: str | None = None,
    completed: bool = False,
) -> str | None:
    quality_run_id = quality_run_id_for(run_id)
    sql = """
        INSERT INTO public.quantyx_data_quality_runs (
          quality_run_id, run_id, tenant_id, domain_id, connection_id, database_name, schema_name,
          status, overall_trust_score, summary_json, trend_mode, trend_scope_key, trend_scope_label, baseline_run_id,
          created_at, completed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, now(), CASE WHEN %s THEN now() ELSE NULL END)
        ON CONFLICT (quality_run_id)
        DO UPDATE SET
          status = EXCLUDED.status,
          overall_trust_score = EXCLUDED.overall_trust_score,
          summary_json = COALESCE(EXCLUDED.summary_json, public.quantyx_data_quality_runs.summary_json),
          trend_mode = COALESCE(EXCLUDED.trend_mode, public.quantyx_data_quality_runs.trend_mode),
          trend_scope_key = COALESCE(EXCLUDED.trend_scope_key, public.quantyx_data_quality_runs.trend_scope_key),
          trend_scope_label = COALESCE(EXCLUDED.trend_scope_label, public.quantyx_data_quality_runs.trend_scope_label),
          baseline_run_id = COALESCE(EXCLUDED.baseline_run_id, public.quantyx_data_quality_runs.baseline_run_id),
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
                trend_mode,
                trend_scope_key,
                trend_scope_label,
                baseline_run_id,
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


def replace_quality_dataset_stages(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    stages: list[dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_data_quality_dataset_stages
         WHERE quality_run_id = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_data_quality_dataset_stages (
          stage_id, quality_run_id, run_id, tenant_id, domain_id,
          stage_seq, stage_name, stage_type, input_row_count, output_row_count,
          rejected_row_count, summary_json, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
    """
    try:
        execute_non_query(settings, delete_sql, [quality_run_id])
        inserted = 0
        for stage in stages:
            stage_name = str(stage.get("stage_name") or "").strip()
            stage_type = str(stage.get("stage_type") or "").strip()
            if not stage_name or not stage_type:
                continue
            execute_non_query(
                settings,
                insert_sql,
                [
                    str(stage.get("stage_id") or f"dqstage_{uuid.uuid4().hex[:12]}"),
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    stage.get("stage_seq"),
                    stage_name,
                    stage_type,
                    stage.get("input_row_count"),
                    stage.get("output_row_count"),
                    stage.get("rejected_row_count"),
                    Json(stage, dumps=lambda value: json.dumps(value, default=_json_default)),
                ],
            )
            inserted += 1
    except psycopg2.errors.UndefinedTable:
        return 0
    return inserted


def list_quality_dataset_stages(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    params.append(max(1, min(int(limit or 1200), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_dataset_stages
             WHERE tenant_id = %s
               AND domain_id = %s
               {filters}
             ORDER BY stage_seq ASC, created_at ASC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def get_quality_dataset_stage(
    settings: Settings,
    stage_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [stage_id]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_dataset_stages
             WHERE stage_id = %s
               {tenant_filter}
             LIMIT 1
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def replace_quality_join_artifacts(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    joins: list[dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_data_quality_join_artifacts
         WHERE quality_run_id = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_data_quality_join_artifacts (
          join_artifact_id, quality_run_id, run_id, tenant_id, domain_id,
          join_name, left_table, right_table, join_type, join_keys_json,
          matched_row_count, unmatched_left_row_count, unmatched_right_row_count,
          duplicate_match_count, summary_json, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, now(), now())
    """
    try:
        execute_non_query(settings, delete_sql, [quality_run_id])
        inserted = 0
        for join in joins:
            join_name = str(join.get("join_name") or "").strip()
            left_table = str(join.get("left_table") or "").strip()
            right_table = str(join.get("right_table") or "").strip()
            if not join_name or not left_table or not right_table:
                continue
            join_keys_json = [
                {
                    "left_key": join.get("left_key"),
                    "right_key": join.get("right_key"),
                }
            ]
            execute_non_query(
                settings,
                insert_sql,
                [
                    str(join.get("join_artifact_id") or f"dqjoin_{uuid.uuid4().hex[:12]}"),
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    join_name,
                    left_table,
                    right_table,
                    join.get("join_type"),
                    Json(join_keys_json, dumps=lambda value: json.dumps(value, default=_json_default)),
                    join.get("matched_row_count"),
                    join.get("unmatched_left_row_count"),
                    join.get("unmatched_right_row_count"),
                    join.get("duplicate_match_count"),
                    Json(join, dumps=lambda value: json.dumps(value, default=_json_default)),
                ],
            )
            inserted += 1
    except psycopg2.errors.UndefinedTable:
        return 0
    return inserted


def list_quality_join_artifacts(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    params.append(max(1, min(int(limit or 1200), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_join_artifacts
             WHERE tenant_id = %s
               AND domain_id = %s
               {filters}
             ORDER BY created_at ASC, join_name ASC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def get_quality_join_artifact(
    settings: Settings,
    join_artifact_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [join_artifact_id]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_join_artifacts
             WHERE join_artifact_id = %s
               {tenant_filter}
             LIMIT 1
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def replace_quality_stage_row_outcomes(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    row_outcomes: list[dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_data_quality_stage_row_outcomes
         WHERE quality_run_id = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_data_quality_stage_row_outcomes (
          outcome_id, quality_run_id, run_id, tenant_id, domain_id,
          stage_id, stage_name, outcome_type, row_lineage_id, row_ref, source_table,
          source_key_json, reason_code, reason_detail, row_data_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, now())
    """
    try:
        execute_non_query(settings, delete_sql, [quality_run_id])
        inserted = 0
        for item in row_outcomes:
            stage_id = str(item.get("stage_id") or "").strip()
            stage_name = str(item.get("stage_name") or "").strip()
            outcome_type = str(item.get("outcome_type") or "").strip()
            if not stage_id or not stage_name or not outcome_type:
                continue
            execute_non_query(
                settings,
                insert_sql,
                [
                    str(item.get("outcome_id") or f"dqout_{uuid.uuid4().hex[:12]}"),
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    stage_id,
                    stage_name,
                    outcome_type,
                    item.get("row_lineage_id"),
                    item.get("row_ref"),
                    item.get("source_table"),
                    Json(item.get("source_key_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                    item.get("reason_code"),
                    item.get("reason_detail"),
                    Json(item.get("row_data_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                ],
            )
            inserted += 1
    except psycopg2.errors.UndefinedTable:
        return 0
    return inserted


def replace_quality_lineage_edges(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    edges: list[dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM public.quantyx_data_quality_lineage_edges
         WHERE quality_run_id = %s
    """
    insert_sql = """
        INSERT INTO public.quantyx_data_quality_lineage_edges (
          edge_id, quality_run_id, run_id, tenant_id, domain_id,
          row_lineage_id, from_stage_id, from_stage_name, to_stage_id, to_stage_name,
          edge_type, summary_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
    """
    try:
        execute_non_query(settings, delete_sql, [quality_run_id])
        inserted = 0
        for item in edges:
            row_lineage_id = str(item.get("row_lineage_id") or "").strip()
            edge_type = str(item.get("edge_type") or "").strip()
            if not row_lineage_id or not edge_type:
                continue
            execute_non_query(
                settings,
                insert_sql,
                [
                    str(item.get("edge_id") or f"dqedge_{uuid.uuid4().hex[:12]}"),
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    row_lineage_id,
                    item.get("from_stage_id"),
                    item.get("from_stage_name"),
                    item.get("to_stage_id"),
                    item.get("to_stage_name"),
                    edge_type,
                    Json(item.get("summary_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                ],
            )
            inserted += 1
    except psycopg2.errors.UndefinedTable:
        return 0
    return inserted


def list_quality_lineage_edges(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    row_lineage_id: str | None = None,
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    if row_lineage_id:
        filters += " AND row_lineage_id = %s"
        params.append(row_lineage_id)
    params.append(max(1, min(int(limit or 1200), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_lineage_edges
             WHERE tenant_id = %s
               AND domain_id = %s
               {filters}
             ORDER BY created_at ASC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def list_quality_stage_row_outcomes(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    stage_id: str | None = None,
    outcome_type: str | None = None,
    row_lineage_id: str | None = None,
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    if stage_id:
        filters += " AND stage_id = %s"
        params.append(stage_id)
    if outcome_type:
        filters += " AND outcome_type = %s"
        params.append(outcome_type)
    if row_lineage_id:
        filters += " AND row_lineage_id = %s"
        params.append(row_lineage_id)
    params.append(max(1, min(int(limit or 1200), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_stage_row_outcomes
             WHERE tenant_id = %s
               AND domain_id = %s
               {filters}
             ORDER BY created_at ASC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def upsert_quality_final_dataset_artifact(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    artifact: dict[str, Any],
) -> str | None:
    artifact_id = str(artifact.get("artifact_id") or f"dqfinal_{uuid.uuid4().hex[:12]}")
    sql = """
        INSERT INTO public.quantyx_data_quality_final_dataset_artifacts (
          artifact_id, quality_run_id, run_id, tenant_id, domain_id,
          final_stage_name, final_row_count, total_rejected_row_count, readiness_status,
          summary_json, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (quality_run_id)
        DO UPDATE SET
          artifact_id = EXCLUDED.artifact_id,
          final_stage_name = EXCLUDED.final_stage_name,
          final_row_count = EXCLUDED.final_row_count,
          total_rejected_row_count = EXCLUDED.total_rejected_row_count,
          readiness_status = EXCLUDED.readiness_status,
          summary_json = EXCLUDED.summary_json,
          updated_at = now()
    """
    try:
        execute_non_query(
            settings,
            sql,
            [
                artifact_id,
                quality_run_id,
                run_id,
                tenant_id,
                domain_id,
                artifact.get("final_stage_name"),
                artifact.get("final_row_count"),
                artifact.get("total_rejected_row_count"),
                artifact.get("readiness_status"),
                Json(artifact.get("summary_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
            ],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return artifact_id


def get_quality_final_dataset_artifact(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    try:
        rows = run_query(
            settings,
            """
            SELECT *
              FROM public.quantyx_data_quality_final_dataset_artifacts
             WHERE tenant_id = %s
               AND domain_id = %s
               AND run_id = %s
             ORDER BY created_at DESC
             LIMIT 1
            """,
            [tenant_id, domain_id, run_id],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


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
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    if status:
        filters += " AND status = %s"
        params.append(status)
    params.append(max(1, min(int(limit or 1200), 4000)))
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
    limit: int = 1200,
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
    params.append(max(1, min(int(limit or 1200), 4000)))
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
    limit: int = 1200,
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
    params.append(max(1, min(int(limit or 1200), 4000)))
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
             WHERE r.tenant_id = %s
               AND r.domain_id = %s
               {filters}
             ORDER BY r.severity ASC, r.created_at DESC
             LIMIT %s
            """,
            params,
        )
        from services.ai.data_quality_rules import derive_quality_rule_label

        for row in rows:
            if not str(row.get("rule_label") or "").strip():
                row["rule_label"] = derive_quality_rule_label(row)
        return rows
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
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    run_filter = ""
    if run_id:
        run_filter = "AND run_id = %s"
        params.append(run_id)
    params.append(max(1, min(int(limit or 1200), 4000)))
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


def replace_quality_run_metric_snapshots(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    trend_scope_key: str | None,
    snapshots: list[dict[str, Any]],
) -> int:
    try:
        execute_non_query(
            settings,
            "DELETE FROM public.quantyx_data_quality_run_metric_snapshots WHERE quality_run_id = %s",
            [quality_run_id],
        )
        inserted = 0
        for item in snapshots:
            execute_non_query(
                settings,
                """
                INSERT INTO public.quantyx_data_quality_run_metric_snapshots (
                  snapshot_id, quality_run_id, run_id, tenant_id, domain_id, trend_scope_key,
                  metric_name, metric_value_num, metric_value_text, metric_unit, captured_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                [
                    f"dqrsnap_{uuid.uuid4().hex[:12]}",
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    trend_scope_key,
                    item.get("metric_name"),
                    item.get("metric_value_num"),
                    item.get("metric_value_text"),
                    item.get("metric_unit"),
                ],
            )
            inserted += 1
        return inserted
    except psycopg2.errors.UndefinedTable:
        return 0


def replace_quality_object_metric_snapshots(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    trend_scope_key: str | None,
    snapshots: list[dict[str, Any]],
) -> int:
    try:
        execute_non_query(
            settings,
            "DELETE FROM public.quantyx_data_quality_object_metric_snapshots WHERE quality_run_id = %s",
            [quality_run_id],
        )
        inserted = 0
        for item in snapshots:
            execute_non_query(
                settings,
                """
                INSERT INTO public.quantyx_data_quality_object_metric_snapshots (
                  object_snapshot_id, quality_run_id, run_id, tenant_id, domain_id, trend_scope_key,
                  object_type, object_key, object_name, metric_name, metric_value_num, metric_value_text, metric_unit, captured_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                [
                    f"dqosnap_{uuid.uuid4().hex[:12]}",
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    trend_scope_key,
                    item.get("object_type"),
                    item.get("object_key"),
                    item.get("object_name"),
                    item.get("metric_name"),
                    item.get("metric_value_num"),
                    item.get("metric_value_text"),
                    item.get("metric_unit"),
                ],
            )
            inserted += 1
        return inserted
    except psycopg2.errors.UndefinedTable:
        return 0


def replace_quality_trends(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    trend_scope_key: str | None,
    baseline_run_id: str | None,
    trends: list[dict[str, Any]],
) -> int:
    try:
        execute_non_query(
            settings,
            "DELETE FROM public.quantyx_data_quality_trends WHERE quality_run_id = %s",
            [quality_run_id],
        )
        inserted = 0
        for item in trends:
            execute_non_query(
                settings,
                """
                INSERT INTO public.quantyx_data_quality_trends (
                  trend_id, quality_run_id, run_id, tenant_id, domain_id, trend_scope_key, baseline_run_id,
                  object_type, object_key, object_name, metric_name,
                  previous_value_num, previous_value_text, current_value_num, current_value_text,
                  delta_value, delta_pct, trend_status, directionality, summary_json, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                """,
                [
                    f"dqtrend_{uuid.uuid4().hex[:12]}",
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    trend_scope_key,
                    item.get("baseline_run_id") or baseline_run_id,
                    item.get("object_type"),
                    item.get("object_key"),
                    item.get("object_name"),
                    item.get("metric_name"),
                    item.get("previous_value_num"),
                    item.get("previous_value_text"),
                    item.get("current_value_num"),
                    item.get("current_value_text"),
                    item.get("delta_value"),
                    item.get("delta_pct"),
                    item.get("trend_status"),
                    item.get("directionality"),
                    Json(item.get("summary_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                ],
            )
            inserted += 1
        return inserted
    except psycopg2.errors.UndefinedTable:
        return 0


def replace_quality_anomalies(
    settings: Settings,
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    trend_scope_key: str | None,
    anomalies: list[dict[str, Any]],
) -> int:
    try:
        execute_non_query(
            settings,
            "DELETE FROM public.quantyx_data_quality_anomalies WHERE quality_run_id = %s",
            [quality_run_id],
        )
        inserted = 0
        for item in anomalies:
            execute_non_query(
                settings,
                """
                INSERT INTO public.quantyx_data_quality_anomalies (
                  anomaly_id, anomaly_key, quality_run_id, run_id, tenant_id, domain_id, trend_scope_key, baseline_run_id,
                  object_type, object_key, object_name, anomaly_type, title, severity, evidence_path,
                  current_value_num, current_value_text, previous_value_num, previous_value_text, delta_value, delta_pct,
                  summary_json, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                """,
                [
                    f"dqanom_{uuid.uuid4().hex[:12]}",
                    item.get("anomaly_key"),
                    quality_run_id,
                    run_id,
                    tenant_id,
                    domain_id,
                    trend_scope_key,
                    item.get("baseline_run_id"),
                    item.get("object_type"),
                    item.get("object_key"),
                    item.get("object_name"),
                    item.get("anomaly_type"),
                    item.get("title"),
                    item.get("severity"),
                    item.get("evidence_path"),
                    item.get("current_value_num"),
                    item.get("current_value_text"),
                    item.get("previous_value_num"),
                    item.get("previous_value_text"),
                    item.get("delta_value"),
                    item.get("delta_pct"),
                    Json(item.get("summary_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                ],
            )
            inserted += 1
        return inserted
    except psycopg2.errors.UndefinedTable:
        return 0


def list_quality_run_metric_snapshots(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    params.append(max(1, min(int(limit or 1200), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_run_metric_snapshots
             WHERE tenant_id = %s
               AND domain_id = %s
               {filters}
             ORDER BY created_at ASC, metric_name ASC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def list_quality_trends(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    object_type: str | None = None,
    object_key: str | None = None,
    trend_status: str | None = None,
    metric_name: str | None = None,
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id, run_id]
    filters = ""
    if object_type:
        filters += " AND object_type = %s"
        params.append(object_type)
    if object_key:
        filters += " AND object_key = %s"
        params.append(object_key)
    if trend_status:
        filters += " AND trend_status = %s"
        params.append(trend_status)
    if metric_name:
        filters += " AND metric_name = %s"
        params.append(metric_name)
    params.append(max(1, min(int(limit or 1200), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_trends
             WHERE tenant_id = %s
               AND domain_id = %s
               AND run_id = %s
               {filters}
             ORDER BY object_type ASC, object_key ASC, metric_name ASC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def list_quality_anomalies(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    severity: str | None = None,
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id, run_id]
    filters = ""
    if severity:
        filters += " AND severity = %s"
        params.append(severity)
    params.append(max(1, min(int(limit or 1200), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_anomalies
             WHERE tenant_id = %s
               AND domain_id = %s
               AND run_id = %s
               {filters}
             ORDER BY
               CASE severity
                 WHEN 'critical' THEN 0
                 WHEN 'high' THEN 1
                 WHEN 'warning' THEN 2
                 ELSE 3
               END ASC,
               created_at DESC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def get_quality_anomaly(
    settings: Settings,
    *,
    anomaly_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [anomaly_id]
    filters = ""
    if tenant_id:
        filters += " AND tenant_id = %s"
        params.append(tenant_id)
    try:
        rows = run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_anomalies
             WHERE anomaly_id = %s
               {filters}
             LIMIT 1
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def list_quality_object_metric_snapshots(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    trend_scope_key: str,
    object_type: str | None = None,
    object_key: str | None = None,
    run_id: str | None = None,
    limit: int = 4000,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id, trend_scope_key]
    filters = ""
    if object_type:
        filters += " AND object_type = %s"
        params.append(object_type)
    if object_key:
        filters += " AND object_key = %s"
        params.append(object_key)
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    params.append(max(1, min(int(limit or 4000), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_object_metric_snapshots
             WHERE tenant_id = %s
               AND domain_id = %s
               AND trend_scope_key = %s
               {filters}
             ORDER BY captured_at DESC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def upsert_quality_issues(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    trend_scope_key: str | None,
    run_id: str,
    quality_run_id: str,
    issues: list[dict[str, Any]],
) -> dict[str, int]:
    try:
        existing_rows = run_query(
            settings,
            """
            SELECT *
              FROM public.quantyx_data_quality_issues
             WHERE tenant_id = %s
               AND domain_id = %s
               AND COALESCE(trend_scope_key, '') = COALESCE(%s, '')
            """,
            [tenant_id, domain_id, trend_scope_key],
        )
    except psycopg2.errors.UndefinedTable:
        return {"issue_count": 0, "open_issue_count": 0, "overdue_issue_count": 0}
    existing_by_key = {str(row.get("issue_key") or ""): row for row in existing_rows}
    current_keys: set[str] = set()
    for issue in issues:
        issue_key = str(issue.get("issue_key") or "").strip()
        if not issue_key:
            continue
        current_keys.add(issue_key)
        existing = existing_by_key.get(issue_key)
        existing_status = str((existing or {}).get("status") or "").strip().lower()
        related_run_ids = list((existing or {}).get("related_run_ids_json") or [])
        if run_id not in related_run_ids:
            related_run_ids.append(run_id)
        if existing:
            owner_id = str((existing or {}).get("owner_id") or "").strip() or issue.get("owner_id")
            due_at = (existing or {}).get("due_at") or issue.get("due_at")
            if existing_status in {"in_progress", "deferred", "accepted_risk"}:
                status = existing_status
            else:
                status = "open"
            execute_non_query(
                settings,
                """
                UPDATE public.quantyx_data_quality_issues
                   SET trend_scope_key = %s,
                       run_id = %s,
                       quality_run_id = %s,
                       last_seen_run_id = %s,
                       issue_type = %s,
                       title = %s,
                       severity = %s,
                       object_type = %s,
                       object_key = %s,
                       table_name = %s,
                       column_name = %s,
                       stage_id = %s,
                       owner_id = %s,
                       status = %s,
                       due_at = COALESCE(%s, due_at),
                       last_seen_at = now(),
                       evidence_path = %s,
                       recommendation_json = %s::jsonb,
                       summary_json = %s::jsonb,
                       related_run_ids_json = %s::jsonb,
                       updated_at = now()
                 WHERE issue_id = %s
                """,
                [
                    trend_scope_key,
                    run_id,
                    quality_run_id,
                    run_id,
                    issue.get("issue_type"),
                    issue.get("title"),
                    issue.get("severity"),
                    issue.get("object_type"),
                    issue.get("object_key"),
                    issue.get("table_name"),
                    issue.get("column_name"),
                    issue.get("stage_id"),
                    owner_id,
                    status,
                    due_at,
                    issue.get("evidence_path"),
                    Json(issue.get("recommendation_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                    Json(issue.get("summary_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                    Json(related_run_ids, dumps=lambda value: json.dumps(value, default=_json_default)),
                    existing.get("issue_id"),
                ],
            )
        else:
            execute_non_query(
                settings,
                """
                INSERT INTO public.quantyx_data_quality_issues (
                  issue_id, issue_key, tenant_id, domain_id, trend_scope_key, run_id, quality_run_id,
                  first_seen_run_id, last_seen_run_id, issue_type, title, severity, object_type, object_key,
                  table_name, column_name, stage_id, owner_id, status, due_at, first_seen_at, last_seen_at,
                  evidence_path, recommendation_json, summary_json, related_run_ids_json, created_at, updated_at
                )
                VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  now(), now(), %s, %s::jsonb, %s::jsonb, %s::jsonb, now(), now()
                )
                """,
                [
                    f"dqissue_{uuid.uuid4().hex[:12]}",
                    issue_key,
                    tenant_id,
                    domain_id,
                    trend_scope_key,
                    run_id,
                    quality_run_id,
                    run_id,
                    run_id,
                    issue.get("issue_type"),
                    issue.get("title"),
                    issue.get("severity"),
                    issue.get("object_type"),
                    issue.get("object_key"),
                    issue.get("table_name"),
                    issue.get("column_name"),
                    issue.get("stage_id"),
                    issue.get("owner_id"),
                    issue.get("status") or "open",
                    issue.get("due_at"),
                    issue.get("evidence_path"),
                    Json(issue.get("recommendation_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                    Json(issue.get("summary_json") or {}, dumps=lambda value: json.dumps(value, default=_json_default)),
                    Json([run_id], dumps=lambda value: json.dumps(value, default=_json_default)),
                ],
            )
    for row in existing_rows:
        issue_key = str(row.get("issue_key") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        if not issue_key or issue_key in current_keys or status in {"resolved", "accepted_risk"}:
            continue
        summary = dict(row.get("summary_json") or {})
        summary["resolution_source"] = "auto_not_present_in_current_run"
        execute_non_query(
            settings,
            """
            UPDATE public.quantyx_data_quality_issues
               SET status = 'resolved',
                   summary_json = %s::jsonb,
                   updated_at = now()
             WHERE issue_id = %s
            """,
            [
                Json(summary, dumps=lambda value: json.dumps(value, default=_json_default)),
                row.get("issue_id"),
            ],
        )
    current_rows = list_quality_issues(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        limit=4000,
    )
    open_rows = [row for row in current_rows if str(row.get("status") or "").strip().lower() in {"open", "in_progress", "deferred"}]
    overdue_count = 0
    now = datetime.utcnow()
    for row in open_rows:
        due_at = row.get("due_at")
        if isinstance(due_at, datetime):
            due_dt = due_at
        else:
            try:
                due_dt = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
        if due_dt.tzinfo is not None:
            due_dt = due_dt.astimezone().replace(tzinfo=None)
        if due_dt < now:
            overdue_count += 1
    return {
        "issue_count": len(current_rows),
        "open_issue_count": len(open_rows),
        "overdue_issue_count": overdue_count,
    }


def list_quality_issues(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    status: str | None = None,
    owner_id: str | None = None,
    limit: int = 1200,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_id, domain_id]
    filters = ""
    if run_id:
        filters += " AND run_id = %s"
        params.append(run_id)
    if status:
        filters += " AND status = %s"
        params.append(status)
    if owner_id:
        filters += " AND owner_id = %s"
        params.append(owner_id)
    params.append(max(1, min(int(limit or 1200), 4000)))
    try:
        return run_query(
            settings,
            f"""
            SELECT *
              FROM public.quantyx_data_quality_issues
             WHERE tenant_id = %s
               AND domain_id = %s
               {filters}
             ORDER BY
               CASE severity
                 WHEN 'critical' THEN 0
                 WHEN 'high' THEN 1
                 WHEN 'medium' THEN 2
                 WHEN 'low' THEN 3
                 ELSE 9
               END ASC,
               updated_at DESC
             LIMIT %s
            """,
            params,
        )
    except psycopg2.errors.UndefinedTable:
        return []


def get_quality_issue(
    settings: Settings,
    *,
    issue_id: str,
) -> dict[str, Any] | None:
    try:
        rows = run_query(
            settings,
            """
            SELECT *
              FROM public.quantyx_data_quality_issues
             WHERE issue_id = %s
             LIMIT 1
            """,
            [issue_id],
        )
    except psycopg2.errors.UndefinedTable:
        return None
    return rows[0] if rows else None


def assign_quality_issue(
    settings: Settings,
    *,
    issue_id: str,
    owner_id: str | None,
) -> dict[str, Any] | None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_data_quality_issues
           SET owner_id = %s,
               updated_at = now()
         WHERE issue_id = %s
        """,
        [owner_id, issue_id],
    )
    return get_quality_issue(settings, issue_id=issue_id)


def update_quality_issue_status(
    settings: Settings,
    *,
    issue_id: str,
    status: str,
    note: str | None = None,
) -> dict[str, Any] | None:
    next_status = str(status or "").strip().lower()
    if next_status not in {"open", "in_progress", "deferred", "resolved", "accepted_risk"}:
        raise ValueError("Unsupported issue status")
    issue = get_quality_issue(settings, issue_id=issue_id)
    if not issue:
        return None
    summary = dict(issue.get("summary_json") or {})
    if note:
        summary["status_note"] = note
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_data_quality_issues
           SET status = %s,
               summary_json = %s::jsonb,
               updated_at = now()
         WHERE issue_id = %s
        """,
        [
            next_status,
            Json(summary, dumps=lambda value: json.dumps(value, default=_json_default)),
            issue_id,
        ],
    )
    return get_quality_issue(settings, issue_id=issue_id)
