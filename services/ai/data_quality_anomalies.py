from __future__ import annotations

from hashlib import sha1
from typing import Any


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _severity(rank: str) -> str:
    return rank if rank in {"critical", "high", "warning", "info"} else "warning"


def _trend_evidence_path(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    object_type: str,
    object_key: str,
) -> str:
    if object_type == "table":
        return f"/data-quality/trends/tables/{object_key}?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
    if object_type == "rule":
        return f"/data-quality/trends/rules/{object_key}?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
    return (
        f"/data-quality/trends?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}"
        f"&object_type={object_type}&object_key={object_key}"
    )


def _make_anomaly(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    quality_run_id: str | None,
    trend_scope_key: str | None,
    baseline_run_id: str | None,
    object_type: str,
    object_key: str,
    object_name: str | None,
    anomaly_type: str,
    title: str,
    severity: str,
    current_value_num: float | None = None,
    current_value_text: str | None = None,
    previous_value_num: float | None = None,
    previous_value_text: str | None = None,
    delta_value: float | None = None,
    delta_pct: float | None = None,
    evidence_path: str | None = None,
    summary_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    anomaly_key = f"{tenant_id}|{domain_id}|{trend_scope_key or ''}|{object_type}|{object_key}|{anomaly_type}"
    return {
        "anomaly_key": anomaly_key,
        "quality_run_id": quality_run_id,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "trend_scope_key": trend_scope_key,
        "baseline_run_id": baseline_run_id,
        "object_type": object_type,
        "object_key": object_key,
        "object_name": object_name,
        "anomaly_type": anomaly_type,
        "title": title,
        "severity": _severity(severity),
        "evidence_path": evidence_path,
        "current_value_num": current_value_num,
        "current_value_text": current_value_text,
        "previous_value_num": previous_value_num,
        "previous_value_text": previous_value_text,
        "delta_value": delta_value,
        "delta_pct": delta_pct,
        "summary_json": summary_json or {},
    }


def derive_data_quality_anomalies(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    quality_run_id: str | None,
    trend_scope_key: str | None,
    baseline_run_id: str | None,
    trends: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trend in [item for item in (trends or []) if isinstance(item, dict)]:
        if str(trend.get("trend_status") or "").strip().lower() != "worsened":
            continue
        object_type = str(trend.get("object_type") or "run").strip() or "run"
        object_key = str(trend.get("object_key") or "__run__").strip() or "__run__"
        object_name = str(trend.get("object_name") or "").strip() or None
        metric_name = str(trend.get("metric_name") or "").strip()
        current_value_num = _as_float(trend.get("current_value_num"))
        previous_value_num = _as_float(trend.get("previous_value_num"))
        current_value_text = str(trend.get("current_value_text") or "").strip() or None
        previous_value_text = str(trend.get("previous_value_text") or "").strip() or None
        delta_value = _as_float(trend.get("delta_value"))
        delta_pct = _as_float(trend.get("delta_pct"))
        evidence_path = _trend_evidence_path(
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            object_type=object_type,
            object_key=object_key,
        )

        if object_type == "run" and metric_name == "overall_trust_score" and (delta_value or 0.0) <= -5.0:
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name="Run Summary",
                    anomaly_type="trust_score_drop",
                    title="Overall trust score dropped materially",
                    severity="critical" if (delta_value or 0.0) <= -10.0 else "high",
                    current_value_num=current_value_num,
                    previous_value_num=previous_value_num,
                    delta_value=delta_value,
                    delta_pct=delta_pct,
                    evidence_path=evidence_path,
                )
            )
        elif object_type == "run" and metric_name == "failed_rule_count" and ((delta_value or 0.0) >= 5.0 or (delta_pct or 0.0) >= 25.0):
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name="Run Summary",
                    anomaly_type="failed_rule_spike",
                    title="Failed rule count spiked",
                    severity="critical" if (delta_pct or 0.0) >= 50.0 else "high",
                    current_value_num=current_value_num,
                    previous_value_num=previous_value_num,
                    delta_value=delta_value,
                    delta_pct=delta_pct,
                    evidence_path=evidence_path,
                )
            )
        elif object_type == "run" and metric_name == "duplicate_candidate_count" and ((delta_value or 0.0) >= 5.0 or (delta_pct or 0.0) >= 25.0):
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name="Run Summary",
                    anomaly_type="duplicate_spike",
                    title="Duplicate candidates increased sharply",
                    severity="high",
                    current_value_num=current_value_num,
                    previous_value_num=previous_value_num,
                    delta_value=delta_value,
                    delta_pct=delta_pct,
                    evidence_path=evidence_path,
                )
            )
        elif object_type == "table" and metric_name == "row_count" and abs(delta_pct or 0.0) >= 20.0:
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name=object_name or object_key,
                    anomaly_type="row_count_drift",
                    title=f"Row count drift detected for {object_name or object_key}",
                    severity="critical" if abs(delta_pct or 0.0) >= 50.0 else "high",
                    current_value_num=current_value_num,
                    previous_value_num=previous_value_num,
                    delta_value=delta_value,
                    delta_pct=delta_pct,
                    evidence_path=evidence_path,
                )
            )
        elif object_type == "table" and metric_name == "trust_score" and (delta_value or 0.0) <= -8.0:
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name=object_name or object_key,
                    anomaly_type="table_trust_drop",
                    title=f"Table trust regressed for {object_name or object_key}",
                    severity="high",
                    current_value_num=current_value_num,
                    previous_value_num=previous_value_num,
                    delta_value=delta_value,
                    delta_pct=delta_pct,
                    evidence_path=evidence_path,
                )
            )
        elif object_type == "rule" and metric_name == "violation_count" and ((delta_value or 0.0) >= 10.0 or (delta_pct or 0.0) >= 25.0):
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name=object_name or object_key,
                    anomaly_type="rule_violation_spike",
                    title=f"Rule violations spiked for {object_name or object_key}",
                    severity="high",
                    current_value_num=current_value_num,
                    previous_value_num=previous_value_num,
                    delta_value=delta_value,
                    delta_pct=delta_pct,
                    evidence_path=evidence_path,
                )
            )
        elif object_type == "stage" and metric_name == "rejected_row_count" and ((delta_value or 0.0) >= 25.0 or (delta_pct or 0.0) >= 25.0):
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name=object_name or object_key,
                    anomaly_type="stage_rejection_spike",
                    title=f"Stage rejection spike in {object_name or object_key}",
                    severity="high",
                    current_value_num=current_value_num,
                    previous_value_num=previous_value_num,
                    delta_value=delta_value,
                    delta_pct=delta_pct,
                    evidence_path=evidence_path,
                )
            )
        elif object_type == "final_dataset" and metric_name == "final_row_count" and (delta_pct or 0.0) <= -20.0:
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name="Final Dataset",
                    anomaly_type="final_dataset_volume_drop",
                    title="Final dataset volume dropped materially",
                    severity="critical" if (delta_pct or 0.0) <= -50.0 else "high",
                    current_value_num=current_value_num,
                    previous_value_num=previous_value_num,
                    delta_value=delta_value,
                    delta_pct=delta_pct,
                    evidence_path=evidence_path,
                )
            )
        elif object_type == "final_dataset" and metric_name == "readiness_status":
            rows.append(
                _make_anomaly(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    run_id=run_id,
                    quality_run_id=quality_run_id,
                    trend_scope_key=trend_scope_key,
                    baseline_run_id=baseline_run_id,
                    object_type=object_type,
                    object_key=object_key,
                    object_name="Final Dataset",
                    anomaly_type="readiness_regression",
                    title="Final dataset readiness regressed",
                    severity="critical",
                    current_value_text=current_value_text,
                    previous_value_text=previous_value_text,
                    evidence_path=evidence_path,
                )
            )
    return rows


def summarize_data_quality_anomalies(rows: list[dict[str, Any]]) -> dict[str, Any]:
    anomaly_rows = [row for row in (rows or []) if isinstance(row, dict)]
    critical = [row for row in anomaly_rows if str(row.get("severity") or "").strip().lower() == "critical"]
    high = [row for row in anomaly_rows if str(row.get("severity") or "").strip().lower() == "high"]
    repeated = [row for row in anomaly_rows if row.get("baseline_run_id")]
    return {
        "anomaly_count": len(anomaly_rows),
        "critical_anomaly_count": len(critical),
        "high_anomaly_count": len(high),
        "repeated_anomaly_count": len(repeated),
    }


def build_quality_anomaly_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["severity"] = _severity(row.get("severity"))
    payload["summary"] = row.get("summary_json") or {}
    return payload
