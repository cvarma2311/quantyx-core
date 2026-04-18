from __future__ import annotations

from typing import Any
import uuid

from services.ai.config import Settings
from services.ai.db import ScopedConnection, run_query


def _qident(name: str | None) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def _nonnull_predicate(column_name: str) -> str:
    ident = _qident(column_name)
    return f"{ident} IS NOT NULL AND btrim({ident}::text) <> ''"


def _confidence_from_pressure(value: Any) -> float:
    try:
        pressure = max(0.0, min(float(value), 1.0))
    except Exception:
        pressure = 0.0
    return round(min(0.95, 0.7 + (pressure * 0.5)), 2)


def _composite_column_candidates(table: dict[str, Any]) -> list[list[str]]:
    profiles = [item for item in (table.get("column_profiles") or []) if isinstance(item, dict)]
    names = {str(item.get("name") or "").strip().lower(): str(item.get("name") or "").strip() for item in profiles if str(item.get("name") or "").strip()}

    def have(*columns: str) -> list[str] | None:
        resolved = [names.get(col.lower()) for col in columns]
        if all(resolved):
            return [str(item) for item in resolved if item]
        return None

    candidates: list[list[str]] = []
    for combo in (
        have("customer_name", "pincode"),
        have("name", "pincode"),
        have("full_name", "pincode"),
        have("customer_name", "postal_code"),
        have("name", "postal_code"),
        have("email", "country"),
        have("phone", "country"),
        have("city", "state", "country"),
        have("address_line1", "postal_code"),
    ):
        if combo and combo not in candidates:
            candidates.append(combo)
    return candidates[:3]


def _single_column_duplicate_candidate(
    settings: Settings,
    *,
    schema_name: str,
    table_name: str,
    column_name: str,
    scoped_conn: ScopedConnection | None,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    duplicate_count_hint: Any = None,
    uniqueness_ratio: Any = None,
) -> dict[str, Any] | None:
    schema = _qident(schema_name or "public")
    table = _qident(table_name)
    column = _qident(column_name)
    predicate = _nonnull_predicate(column_name)
    count_sql = f"""
        WITH dupes AS (
          SELECT {column} AS duplicate_value, COUNT(*) AS duplicate_count
            FROM {schema}.{table}
           WHERE {predicate}
           GROUP BY {column}
          HAVING COUNT(*) > 1
        )
        SELECT
          COUNT(*) AS duplicate_group_count,
          COALESCE(SUM(duplicate_count), 0) AS candidate_record_count,
          COALESCE(MAX(duplicate_count), 0) AS max_group_size
          FROM dupes
    """
    sample_sql = f"""
        SELECT {column} AS duplicate_value, COUNT(*) AS duplicate_count
          FROM {schema}.{table}
         WHERE {predicate}
         GROUP BY {column}
        HAVING COUNT(*) > 1
         ORDER BY duplicate_count DESC, duplicate_value::text ASC
         LIMIT 10
    """
    count_row = (run_query(settings, count_sql, [], scoped_conn=scoped_conn) or [{}])[0]
    duplicate_groups = int(count_row.get("duplicate_group_count") or 0)
    candidate_record_count = int(count_row.get("candidate_record_count") or 0)
    if duplicate_groups <= 0 or candidate_record_count <= 0:
        return None
    sample_rows = run_query(settings, sample_sql, [], scoped_conn=scoped_conn) or []
    return {
        "candidate_id": f"dqdup_{uuid.uuid4().hex[:12]}",
        "quality_run_id": quality_run_id,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "table_name": table_name,
        "duplicate_type": "exact_key_duplicate",
        "match_columns_json": [column_name],
        "confidence": 0.99,
        "candidate_record_count": candidate_record_count,
        "sample_rows_json": [dict(row) for row in sample_rows],
        "cluster_json": {
            "duplicate_group_count": duplicate_groups,
            "max_group_size": int(count_row.get("max_group_size") or 0),
            "duplicate_count_hint": duplicate_count_hint,
            "uniqueness_ratio": uniqueness_ratio,
        },
        "review_status": "needs_review",
    }


def _composite_duplicate_candidate(
    settings: Settings,
    *,
    schema_name: str,
    table_name: str,
    column_names: list[str],
    scoped_conn: ScopedConnection | None,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
) -> dict[str, Any] | None:
    if len(column_names) < 2:
        return None
    schema = _qident(schema_name or "public")
    table = _qident(table_name)
    group_cols = ", ".join(_qident(item) for item in column_names)
    predicate = " AND ".join(_nonnull_predicate(item) for item in column_names)
    count_sql = f"""
        WITH dupes AS (
          SELECT {group_cols}, COUNT(*) AS duplicate_count
            FROM {schema}.{table}
           WHERE {predicate}
           GROUP BY {group_cols}
          HAVING COUNT(*) > 1
        )
        SELECT
          COUNT(*) AS duplicate_group_count,
          COALESCE(SUM(duplicate_count), 0) AS candidate_record_count,
          COALESCE(MAX(duplicate_count), 0) AS max_group_size
          FROM dupes
    """
    sample_sql = f"""
        SELECT {group_cols}, COUNT(*) AS duplicate_count
          FROM {schema}.{table}
         WHERE {predicate}
         GROUP BY {group_cols}
        HAVING COUNT(*) > 1
         ORDER BY duplicate_count DESC
         LIMIT 10
    """
    count_row = (run_query(settings, count_sql, [], scoped_conn=scoped_conn) or [{}])[0]
    duplicate_groups = int(count_row.get("duplicate_group_count") or 0)
    candidate_record_count = int(count_row.get("candidate_record_count") or 0)
    if duplicate_groups <= 0 or candidate_record_count <= 0:
        return None
    sample_rows = run_query(settings, sample_sql, [], scoped_conn=scoped_conn) or []
    return {
        "candidate_id": f"dqdup_{uuid.uuid4().hex[:12]}",
        "quality_run_id": quality_run_id,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "table_name": table_name,
        "duplicate_type": "exact_composite_duplicate",
        "match_columns_json": list(column_names),
        "confidence": 0.95,
        "candidate_record_count": candidate_record_count,
        "sample_rows_json": [dict(row) for row in sample_rows],
        "cluster_json": {
            "duplicate_group_count": duplicate_groups,
            "max_group_size": int(count_row.get("max_group_size") or 0),
        },
        "review_status": "needs_review",
    }


def _fuzzy_signal_candidate(
    *,
    table: dict[str, Any],
    signal: dict[str, Any],
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
) -> dict[str, Any] | None:
    column_name = str(signal.get("column") or "").strip()
    if not column_name:
        return None
    samples = list((table.get("sample_values") or {}).get(column_name) or [])[:10]
    return {
        "candidate_id": f"dqdup_{uuid.uuid4().hex[:12]}",
        "quality_run_id": quality_run_id,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "table_name": str(table.get("name") or ""),
        "duplicate_type": "fuzzy_duplicate_signal",
        "match_columns_json": [column_name],
        "confidence": _confidence_from_pressure(signal.get("duplicate_pressure")),
        "candidate_record_count": max(
            0,
            int(signal.get("raw_unique_sample_count") or 0) - int(signal.get("normalized_unique_sample_count") or 0),
        ),
        "sample_rows_json": [{"sample_value": item} for item in samples],
        "cluster_json": {
            "risk_level": signal.get("risk_level"),
            "raw_unique_sample_count": signal.get("raw_unique_sample_count"),
            "normalized_unique_sample_count": signal.get("normalized_unique_sample_count"),
            "duplicate_pressure": signal.get("duplicate_pressure"),
        },
        "review_status": "needs_review",
    }


def detect_duplicate_candidates(
    settings: Settings,
    *,
    profiling: dict[str, Any],
    schema_name: str,
    scoped_conn: ScopedConnection | None,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for table in (profiling.get("tables") or []):
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        for key in (table.get("candidate_keys") or [])[:5]:
            column_name = str(key.get("column") or "").strip()
            duplicate_count = int(key.get("duplicate_count") or 0)
            if not column_name or duplicate_count <= 0:
                continue
            candidate = _single_column_duplicate_candidate(
                settings,
                schema_name=schema_name,
                table_name=table_name,
                column_name=column_name,
                scoped_conn=scoped_conn,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=tenant_id,
                domain_id=domain_id,
                duplicate_count_hint=duplicate_count,
                uniqueness_ratio=key.get("uniqueness_ratio"),
            )
            if candidate:
                candidates.append(candidate)
        for combo in _composite_column_candidates(table):
            candidate = _composite_duplicate_candidate(
                settings,
                schema_name=schema_name,
                table_name=table_name,
                column_names=combo,
                scoped_conn=scoped_conn,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=tenant_id,
                domain_id=domain_id,
            )
            if candidate:
                candidates.append(candidate)
        for signal in (table.get("fuzzy_duplicate_signals") or [])[:3]:
            if not isinstance(signal, dict):
                continue
            candidate = _fuzzy_signal_candidate(
                table=table,
                signal=signal,
                quality_run_id=quality_run_id,
                run_id=run_id,
                tenant_id=tenant_id,
                domain_id=domain_id,
            )
            if candidate:
                candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            str(item.get("table_name") or ""),
            str(item.get("duplicate_type") or ""),
            -(float(item.get("candidate_record_count") or 0)),
            -(float(item.get("confidence") or 0)),
        )
    )
    return candidates
