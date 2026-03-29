#!/usr/bin/env python3
from __future__ import annotations

"""
End-to-end workspace deployment demo for Retail Fuel Monitoring (dry-out intelligence).

What it does:
1) Bootstraps tenant domain/scope for retail_fuel_monitoring.
2) Creates deployment via POST /workspace/deployments with alerts + location_master + loss_of_sales.
3) Streams run progress from /agentic/runs/{run_id}/stream (or polls events).
4) Prints final run status.
5) Prints anomaly debug + followup artifacts.
6) Prints Phase 43 correlation summary.

Usage examples:
  python3 scripts/demo_workspace_deployment_fuel.py

  python3 scripts/demo_workspace_deployment_fuel.py \\
    --api-base http://localhost:8787 \\
    --tenant-id FUEL_DEMO_001 \\
    --domain-id retail_fuel_monitoring \\
    --connection-id 2 \\
    --database hpcl_ceg \\
    --schema public

  python3 scripts/demo_workspace_deployment_fuel.py --mode poll

  # Pass a custom context file
  python3 scripts/demo_workspace_deployment_fuel.py \\
    --context-file docs/examples/fuel_business_context.txt

  # Skip correlation summary
  python3 scripts/demo_workspace_deployment_fuel.py --skip-correlation

  # Anomaly-only correlation with fewer forecast periods
  python3 scripts/demo_workspace_deployment_fuel.py \\
    --correlation-mode anomaly_only --forecast-periods 6
"""

import argparse
import json
from pathlib import Path
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

DEFAULT_TABLES = [
    "alerts",
    "location_master",
    "loss_of_sales",
]

# Default business context describing the retail fuel dry-out domain.
# Metric Definition sections are parsed by _extract_metric_overrides and injected
# as high-priority (5000) metric overrides, bypassing the LLM validator.
# Formulas use CASE WHEN to embed business filters inline.
_DEFAULT_CONTEXT_TEXT = """\
Domain: Retail Fuel Monitoring — Dry-Out Intelligence and Loss of Sale

Business Overview:
This domain tracks fuel dry-out events at retail outlets (petrol stations) across zones.
A dry-out means an outlet ran out of fuel (petrol/diesel/ethanol), leading to missed sales.

Key Tables:
- alerts: One row per dry-out alert event. Key columns: product_code, interlock_name,
  indent_status, mark_as_false, dry_out_in_days, dry_out_start_time, dry_out_end_time,
  created_at, alert_status, sap_id, bu, zone.
- location_master: Retail outlet master data. Columns: sap_id, zone, bu.
- loss_of_sales: Daily revenue loss estimates. Columns: stock_date, loss_of_sale, product_no.

Product Codes (alerts.product_code): 2811000 = MS (Petrol), 2812000 = HSD (Diesel), 2822000 = E20.
Product Codes (loss_of_sales.product_no): 1322000, 1683000, 1683100, 3672000, 2682000, 3373000.

Dry-Out Categories (field: dry_out_in_days):
- dry_out_in_days = 1 means short-term DryOut (single-day stockout)
- dry_out_in_days = 2 means extended IntraDryOut (intra-day or multi-shift stockout)
- alert_status = Open and unresolved for more than 5 days means permanent long-term dry-out

Valid Alert Filters (semantic hints):
- mark_as_false = true (text field) confirms a real dry-out event, not a false alarm
- interlock_name = Dry Out Each Indent Wise MainFlow identifies genuine dry-out alerts
- indent_status values to exclude: Cancelled, TempClosed, ProductLowLevel, OfflineOrFalseAlarm, NotAvailable
- bu = RO scopes to Retail Outlets
- zone is the geographic grouping; do NOT use sap_id as a chart category

Time columns: created_at is the canonical alert event time. dry_out_start_time (stored UTC, display Asia/Kolkata) for overlap range queries. stock_date for loss_of_sales.

Key Metrics:

Metric Definition:
- metric_name: dryout_count
- base_table: alerts
- formula: COUNT(CASE WHEN dry_out_in_days = '1' AND mark_as_false = 'true' THEN 1 END)
- time_column: created_at
- grain: day
- metric_type: count

Metric Definition:
- metric_name: intra_dryout_count
- base_table: alerts
- formula: COUNT(CASE WHEN dry_out_in_days = '2' AND mark_as_false = 'true' THEN 1 END)
- time_column: created_at
- grain: day
- metric_type: count

Metric Definition:
- metric_name: permanent_dryout_count
- base_table: alerts
- formula: COUNT(CASE WHEN alert_status = 'Open' AND mark_as_false = 'true' THEN 1 END)
- time_column: created_at
- grain: month
- metric_type: count

Metric Definition:
- metric_name: outlets_with_dryout
- base_table: alerts
- formula: COUNT(DISTINCT CASE WHEN mark_as_false = 'true' THEN sap_id END)
- time_column: created_at
- grain: day
- metric_type: count

Metric Definition:
- metric_name: loss_of_sale
- base_table: loss_of_sales
- formula: SUM(loss_of_sale)
- time_column: stock_date
- grain: day
- metric_type: sum

Dashboard Goals:
1. DryOut Trends by day and product (MS, HSD, E20) — line chart
2. IntraDryOut Trends by day and product — line chart
3. Permanent DryOut by month and product — bar chart
4. Zone-wise stockout distribution (outlets with vs without dry-out) — stacked bar or pie
5. Loss of Sale month-wise — bar chart
6. Loss of Sale day-wise (last 7 days) — line chart

Business Glossary:
- dry-out: fuel stock-out at a retail outlet
- intra-dryout: shorter duration stock-out (dry_out_in_days='2')
- permanent dryout: unresolved alert older than 5 days
- MS: Motor Spirit / Petrol
- HSD: High Speed Diesel
- E20: Ethanol 20% blend
- zone: geographic grouping of retail outlets
- sap_id: unique outlet identifier
- loss of sale: revenue lost due to stock-out
- indent: fuel supply order/request
"""


def _request(api_base: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> tuple[int, Any]:
    url = f"{api_base.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(body) if body else {"detail": body}
        except Exception:
            parsed = {"detail": body}
        return exc.code, parsed
    except TimeoutError:
        return 599, {"detail": "request_timeout"}
    except socket.timeout:
        return 599, {"detail": "request_timeout"}


def _json_dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, default=str, sort_keys=True)


def _print_event(event: dict[str, Any], *, print_full_payload: bool = True) -> None:
    created_at = event.get("created_at") or "-"
    agent = event.get("agent_name") or "-"
    status = event.get("status") or "-"
    stage = event.get("stage_name") or "-"
    message = event.get("message") or ""
    print(f"[{created_at}] {agent} | {status} | stage={stage} | {message}")

    meta = {
        "event_id": event.get("event_id"),
        "logical_event_id": event.get("logical_event_id"),
        "payload_compacted": event.get("payload_compacted"),
    }
    print("  meta:")
    print(_json_dump(meta))

    artifacts = event.get("artifacts") or {}
    if print_full_payload and artifacts:
        print("  artifacts:")
        print(_json_dump(artifacts))
    elif isinstance(artifacts, dict):
        if artifacts.get("dashboard_id") or artifacts.get("dashboard_title"):
            print(
                "  dashboard:",
                _json_dump(
                    {
                        "dashboard_id": artifacts.get("dashboard_id"),
                        "dashboard_title": artifacts.get("dashboard_title"),
                    }
                ),
            )
        if artifacts.get("chart_ids"):
            print(f"  chart_ids: {artifacts.get('chart_ids')}")
        if artifacts.get("error_type") or artifacts.get("error_message"):
            print(
                "  error:",
                _json_dump(
                    {
                        "error_type": artifacts.get("error_type"),
                        "error_message": artifacts.get("error_message"),
                    }
                ),
            )
    print("")


def _terminal_status(status: str | None) -> bool:
    return str(status or "").lower() in {"completed", "failed", "cancelled"}


def _terminal_agent_status(status: str | None) -> bool:
    return str(status or "").lower() in {"completed", "failed", "cancelled", "skipped"}


def _stream_run(
    api_base: str,
    run_id: str,
    *,
    print_full_payload: bool = True,
    status_check_seconds: float = 3.0,
    tail_seconds: float = 3.0,
) -> None:
    url = f"{api_base.rstrip('/')}/agentic/runs/{urllib.parse.quote(run_id)}/stream"
    req = urllib.request.Request(url, method="GET")

    terminal_seen_at: float | None = None
    last_status_check = 0.0
    current_status: str | None = None
    anomaly_dashboard_started = False
    anomaly_dashboard_terminal = False

    with urllib.request.urlopen(req, timeout=120) as resp:
        while True:
            line = resp.readline().decode("utf-8", errors="ignore")
            if line == "":
                break
            line = line.strip()
            now = time.monotonic()

            if line.startswith("data: "):
                payload = line[6:].strip()
                if payload:
                    try:
                        event = json.loads(payload)
                        if isinstance(event, dict):
                            if str(event.get("agent_name") or "") == "AnomalyDashboardAgent":
                                anomaly_dashboard_started = True
                                if _terminal_agent_status(event.get("status")):
                                    anomaly_dashboard_terminal = True
                            _print_event(event, print_full_payload=print_full_payload)
                    except json.JSONDecodeError:
                        print(f"SSE raw: {payload}")

            if now - last_status_check >= status_check_seconds:
                code, run = _request(api_base, "GET", f"/agentic/runs/{urllib.parse.quote(run_id)}", timeout=15)
                if code == 200 and isinstance(run, dict):
                    current_status = str(run.get("status") or "")
                    print(f"[run_status] {current_status}")
                    if _terminal_status(current_status):
                        if terminal_seen_at is None:
                            terminal_seen_at = now
                    else:
                        terminal_seen_at = None
                last_status_check = now

            anomaly_safe_to_exit = (not anomaly_dashboard_started) or anomaly_dashboard_terminal
            if terminal_seen_at is not None and anomaly_safe_to_exit and (now - terminal_seen_at) >= tail_seconds:
                break


def _poll_run_logs(
    api_base: str,
    run_id: str,
    *,
    print_full_payload: bool = True,
    interval_seconds: float = 2.0,
) -> None:
    seen_event_ids: set[str] = set()
    anomaly_dashboard_started = False
    anomaly_dashboard_terminal = False

    while True:
        code, resp = _request(
            api_base,
            "GET",
            f"/agentic/runs/{urllib.parse.quote(run_id)}/events?limit=2000",
        )
        if code != 200:
            print(f"Failed to fetch events: status={code} body={resp}")
            time.sleep(interval_seconds)
            continue

        events = (resp or {}).get("events") or []
        for event in events:
            event_id = str(event.get("event_id") or "")
            if not event_id or event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            if str(event.get("agent_name") or "") == "AnomalyDashboardAgent":
                anomaly_dashboard_started = True
                if _terminal_agent_status(event.get("status")):
                    anomaly_dashboard_terminal = True
            _print_event(event, print_full_payload=print_full_payload)

        run_code, run = _request(api_base, "GET", f"/agentic/runs/{urllib.parse.quote(run_id)}")
        anomaly_safe_to_exit = (not anomaly_dashboard_started) or anomaly_dashboard_terminal
        if run_code == 200 and _terminal_status((run or {}).get("status")) and anomaly_safe_to_exit:
            print(f"[run_status] {(run or {}).get('status')}")
            break

        time.sleep(interval_seconds)


def _wait_for_terminal_run(api_base: str, run_id: str, *, timeout_seconds: float = 180.0, poll_seconds: float = 2.0) -> tuple[int, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_code = 0
    last_payload: Any = {}
    while time.monotonic() < deadline:
        code, payload = _request(api_base, "GET", f"/agentic/runs/{urllib.parse.quote(run_id)}")
        last_code = code
        last_payload = payload
        if code == 200 and _terminal_status((payload or {}).get("status")):
            return code, payload
        time.sleep(poll_seconds)
    return last_code, last_payload


def _anomaly_stage_summary(api_base: str, run_id: str) -> dict[str, Any]:
    code, resp = _request(
        api_base,
        "GET",
        f"/agentic/runs/{urllib.parse.quote(run_id)}/events?limit=2000",
        timeout=30,
    )
    if code != 200:
        return {
            "events_lookup_status": code,
            "events_lookup_error": resp,
            "anomaly_detection_seen": False,
            "anomaly_dashboard_seen": False,
        }

    events = (resp or {}).get("events") or []
    summary: dict[str, Any] = {
        "events_lookup_status": 200,
        "anomaly_detection_seen": False,
        "anomaly_dashboard_seen": False,
        "anomaly_detection_status": None,
        "anomaly_dashboard_status": None,
        "anomaly_detection_message": None,
        "anomaly_dashboard_message": None,
        "investigation_id": None,
        "anomaly_dashboard_id": None,
        "anomaly_ids": [],
        "hypothesis_ids": [],
        "action_ids": [],
        "executed_query_count": 0,
        "rejected_query_count": 0,
        "skip_reason": None,
        "failure": None,
    }

    for event in events:
        agent_name = str(event.get("agent_name") or "")
        artifacts = event.get("artifacts") or {}
        status = str(event.get("status") or "")
        message = str(event.get("message") or "")
        if agent_name == "AnomalyDetectionAgent":
            summary["anomaly_detection_seen"] = True
            summary["anomaly_detection_status"] = status
            summary["anomaly_detection_message"] = message
            if artifacts.get("investigation_id"):
                summary["investigation_id"] = artifacts.get("investigation_id")
            if artifacts.get("anomaly_ids"):
                summary["anomaly_ids"] = artifacts.get("anomaly_ids")
            if artifacts.get("hypothesis_ids"):
                summary["hypothesis_ids"] = artifacts.get("hypothesis_ids")
            if artifacts.get("action_ids"):
                summary["action_ids"] = artifacts.get("action_ids")
            if isinstance(artifacts.get("executed_queries"), list):
                summary["executed_query_count"] = len(artifacts.get("executed_queries") or [])
            if isinstance(artifacts.get("rejected_queries"), list):
                summary["rejected_query_count"] = len(artifacts.get("rejected_queries") or [])
            if artifacts.get("reason"):
                summary["skip_reason"] = artifacts.get("reason")
            if artifacts.get("error_type") or artifacts.get("error_message"):
                summary["failure"] = {
                    "agent": agent_name,
                    "error_type": artifacts.get("error_type"),
                    "error_message": artifacts.get("error_message"),
                }
        elif agent_name == "AnomalyDashboardAgent":
            summary["anomaly_dashboard_seen"] = True
            summary["anomaly_dashboard_status"] = status
            summary["anomaly_dashboard_message"] = message
            if artifacts.get("dashboard_id"):
                summary["anomaly_dashboard_id"] = artifacts.get("dashboard_id")
            if artifacts.get("reason") and not summary.get("skip_reason"):
                summary["skip_reason"] = artifacts.get("reason")
            if artifacts.get("error_type") or artifacts.get("error_message"):
                summary["failure"] = {
                    "agent": agent_name,
                    "error_type": artifacts.get("error_type"),
                    "error_message": artifacts.get("error_message"),
                }
    return summary


def _wait_for_anomaly_artifacts(
    api_base: str,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    timeout_seconds: float = 45.0,
    poll_seconds: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_summary: dict[str, Any] = {}
    while time.monotonic() < deadline:
        summary = _anomaly_stage_summary(api_base, run_id)
        last_summary = summary
        if summary.get("failure"):
            return summary
        dashboard_seen = bool(summary.get("anomaly_dashboard_seen"))
        dashboard_done = _terminal_agent_status(summary.get("anomaly_dashboard_status"))
        detection_seen = bool(summary.get("anomaly_detection_seen"))
        detection_done = _terminal_agent_status(summary.get("anomaly_detection_status"))
        if dashboard_seen and dashboard_done:
            return summary
        if detection_seen and detection_done and not dashboard_seen:
            return summary
        code, resp = _request(
            api_base,
            "GET",
            "/workspace/anomalies?"
            + urllib.parse.urlencode(
                {
                    "tenant_id": tenant_id,
                    "domain_id": domain_id,
                    "run_id": run_id,
                    "limit": 1,
                }
            ),
            timeout=20,
        )
        if code == 200 and ((resp or {}).get("investigations") or []):
            summary = dict(summary)
            latest = ((resp or {}).get("investigations") or [])[0]
            if latest.get("investigation_id") and not summary.get("investigation_id"):
                summary["investigation_id"] = latest.get("investigation_id")
            return summary
        time.sleep(poll_seconds)
    return last_summary


def _print_anomaly_debug(api_base: str, *, tenant_id: str, domain_id: str, run_id: str) -> None:
    summary = _wait_for_anomaly_artifacts(
        api_base,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
    )
    print("\nAnomaly readiness:")
    print(
        _json_dump(
            {
                "tenant_id": tenant_id,
                "domain_id": domain_id,
                "run_id": run_id,
                "anomaly_detection_seen": summary.get("anomaly_detection_seen"),
                "anomaly_detection_status": summary.get("anomaly_detection_status"),
                "anomaly_detection_message": summary.get("anomaly_detection_message"),
                "anomaly_dashboard_seen": summary.get("anomaly_dashboard_seen"),
                "anomaly_dashboard_status": summary.get("anomaly_dashboard_status"),
                "anomaly_dashboard_message": summary.get("anomaly_dashboard_message"),
                "investigation_id": summary.get("investigation_id"),
                "anomaly_dashboard_id": summary.get("anomaly_dashboard_id"),
                "anomaly_count": len(summary.get("anomaly_ids") or []),
                "hypothesis_count": len(summary.get("hypothesis_ids") or []),
                "action_count": len(summary.get("action_ids") or []),
                "executed_query_count": summary.get("executed_query_count"),
                "rejected_query_count": summary.get("rejected_query_count"),
                "skip_reason": summary.get("skip_reason"),
                "failure": summary.get("failure"),
            }
        )
    )
    if summary.get("failure"):
        print("Anomaly failure detected in run events.")
    elif summary.get("skip_reason"):
        print(f"Anomaly flow skipped or partially skipped: {summary.get('skip_reason')}")
    elif not summary.get("anomaly_detection_seen"):
        if summary.get("investigation_id"):
            print("Anomaly artifacts were found, but detailed stage events were not yet visible.")
        else:
            print("Anomaly stages were not observed in run events.")
    elif not summary.get("investigation_id"):
        print("Anomaly stages ran, but no investigation artifact was persisted.")


_CORRELATION_TERMINAL = {"done", "failed", "error"}


def _find_correlation_run(api_base: str, *, tenant_id: str, domain_id: str, run_id: str) -> dict[str, Any] | None:
    query = urllib.parse.urlencode({"tenant_id": tenant_id, "domain_id": domain_id, "limit": 10})
    code, resp = _request(api_base, "GET", f"/correlation/runs?{query}", timeout=20)
    if code != 200:
        return None
    runs: list[dict[str, Any]] = (resp or {}).get("runs") or []
    for r in runs:
        if str(r.get("run_id") or "") == run_id:
            return r
    return runs[0] if runs else None


def _trigger_correlation_run(
    api_base: str,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    analysis_mode: str = "full",
    forecast_periods: int = 12,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "analysis_mode": analysis_mode,
        "forecast_periods": forecast_periods,
        "triggered_by": "demo_workspace_deployment_fuel.py",
    }
    code, resp = _request(api_base, "POST", "/correlation/runs", payload, timeout=30)
    if code in {200, 201, 202}:
        return resp
    print(f"  [correlation] Trigger failed: status={code} body={resp}")
    return None


def _wait_for_correlation_run(
    api_base: str,
    correlation_run_id: str,
    *,
    timeout_seconds: float = 300.0,
    poll_seconds: float = 4.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    dots = 0
    while time.monotonic() < deadline:
        code, resp = _request(
            api_base,
            "GET",
            f"/correlation/runs/{urllib.parse.quote(correlation_run_id)}",
            timeout=20,
        )
        if code == 200 and isinstance(resp, dict):
            last = resp
            status = str(resp.get("status") or "").lower()
            dots += 1
            print(
                f"\r  [correlation] {correlation_run_id} status={status} "
                f"anomalies={resp.get('anomaly_count', '?')} "
                f"pairs={resp.get('correlation_pair_count', '?')} "
                f"threads={resp.get('thread_count', '?')} {'.' * (dots % 4)}   ",
                end="",
                flush=True,
            )
            if status in _CORRELATION_TERMINAL:
                print()
                return last
        time.sleep(poll_seconds)
    print()
    return last


def _print_correlation_summary(
    api_base: str,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    analysis_mode: str = "full",
    forecast_periods: int = 12,
    timeout_seconds: float = 300.0,
) -> None:
    print("\n" + "=" * 70)
    print("Phase 43 — Statistical Correlation Intelligence")
    print("=" * 70)

    print("  Looking for correlation run created during the agentic workflow...")
    time.sleep(2)

    corr_run = _find_correlation_run(api_base, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id)
    if corr_run:
        correlation_run_id = str(corr_run.get("correlation_run_id") or "")
        print(f"  Found correlation run: {correlation_run_id} (status={corr_run.get('status')})")
    else:
        print("  No inline correlation run found — manually triggering correlation run...")
        corr_run = _trigger_correlation_run(
            api_base,
            tenant_id=tenant_id,
            domain_id=domain_id,
            run_id=run_id,
            analysis_mode=analysis_mode,
            forecast_periods=forecast_periods,
        )
        if not corr_run:
            print("  Could not start correlation run. Skipping.")
            return
        correlation_run_id = str(corr_run.get("correlation_run_id") or "")
        print(f"  Started correlation run: {correlation_run_id}")

    if str(corr_run.get("status") or "").lower() not in _CORRELATION_TERMINAL:
        print(f"  Polling for completion (timeout={timeout_seconds:.0f}s)...")
        corr_run = _wait_for_correlation_run(api_base, correlation_run_id, timeout_seconds=timeout_seconds)

    final_status = str(corr_run.get("status") or "unknown")
    print(f"\nCorrelation run {correlation_run_id}")
    print(
        _json_dump(
            {
                "status": final_status,
                "analysis_mode": corr_run.get("analysis_mode"),
                "forecast_periods": corr_run.get("forecast_periods"),
                "metric_count": corr_run.get("metric_count"),
                "anomaly_count": corr_run.get("anomaly_count"),
                "correlation_pair_count": corr_run.get("correlation_pair_count"),
                "thread_count": corr_run.get("thread_count"),
                "started_at": corr_run.get("started_at"),
                "completed_at": corr_run.get("completed_at"),
                "error_message": corr_run.get("error_message"),
            }
        )
    )

    if corr_run.get("summary_text"):
        print("\nExecutive Summary:")
        print(f"  {corr_run['summary_text']}")

    if final_status == "failed":
        print("\nCorrelation run failed — skipping detail sections.")
        return

    print("\n--- Anomalies (top 10 by score) ---")
    q = urllib.parse.urlencode({"min_score": "0.0", "limit": "10"})
    code, resp = _request(api_base, "GET", f"/correlation/runs/{urllib.parse.quote(correlation_run_id)}/anomalies?{q}", timeout=20)
    if code == 200:
        anomalies: list[dict[str, Any]] = (resp or {}).get("anomalies") or []
        total = (resp or {}).get("total", 0)
        print(f"  Total: {total}")
        for a in anomalies[:10]:
            dim_note = ""
            if a.get("top_dimension") and a.get("top_dimension_value"):
                dim_note = f"  [{a['top_dimension']}={a['top_dimension_value']} {a.get('dimension_pct','?')}%]"
            print(
                f"  {a.get('metric_name','?')} | {a.get('anomaly_class','?')} | "
                f"score={a.get('anomaly_score','?')} z={a.get('z_score','?')} | "
                f"at={a.get('detected_at','?')} | dev={a.get('deviation_pct','?')}%{dim_note}"
            )
    else:
        print(f"  Anomaly lookup failed: status={code}")

    print("\n--- Top Correlation Pairs ---")
    q = urllib.parse.urlencode({"min_abs_r": "0.2", "limit": "10"})
    code, resp = _request(api_base, "GET", f"/correlation/runs/{urllib.parse.quote(correlation_run_id)}/pairs?{q}", timeout=20)
    if code == 200:
        pairs: list[dict[str, Any]] = (resp or {}).get("pairs") or []
        total = (resp or {}).get("total", 0)
        print(f"  Total (|r|≥0.2): {total}")
        for p in pairs[:10]:
            lag_note = ""
            if p.get("best_lag"):
                lag_note = f" lag={p['best_lag']} ({p.get('lag_direction','')})"
            print(
                f"  {p.get('metric_a','?')} ↔ {p.get('metric_b','?')} | "
                f"r={p.get('pearson_r','?')} | {p.get('strength_label','?')} {p.get('direction_label','?')}"
                f"{lag_note} | stable={p.get('is_stable','?')}"
            )
    else:
        print(f"  Pairs lookup failed: status={code}")

    print("\n--- Investigation Threads ---")
    q = urllib.parse.urlencode({"min_confidence": "0.0", "limit": "10"})
    code, resp = _request(api_base, "GET", f"/correlation/runs/{urllib.parse.quote(correlation_run_id)}/threads?{q}", timeout=20)
    if code == 200:
        threads: list[dict[str, Any]] = (resp or {}).get("threads") or []
        total = (resp or {}).get("total", 0)
        print(f"  Total: {total}")
        for t in threads[:5]:
            print(
                f"  trigger={t.get('trigger_metric','?')} | "
                f"confidence={t.get('confidence','?')} | "
                f"focus={t.get('suggested_focus','[]')}"
            )
            if t.get("narrative_text"):
                text = str(t["narrative_text"])
                print(f"    {text[:200]}{'...' if len(text) > 200 else ''}")
    else:
        print(f"  Threads lookup failed: status={code}")

    print("\n--- Forward Projections ---")
    code, resp = _request(api_base, "GET", f"/correlation/runs/{urllib.parse.quote(correlation_run_id)}/projections", timeout=20)
    if code == 200:
        projections: list[dict[str, Any]] = (resp or {}).get("projections") or []
        total = (resp or {}).get("total", 0)
        print(f"  Total: {total}")
        for proj in projections:
            inflection = f" | signal={proj['inflection_signal']}" if proj.get("inflection_signal") else ""
            seasonal = " | seasonal" if proj.get("seasonality_present") else ""
            next_pt = (proj.get("projection_json") or [{}])[0]
            forecast_note = ""
            if next_pt.get("forecast") is not None:
                forecast_note = (
                    f" | next={next_pt['forecast']:.2f} "
                    f"[{next_pt.get('lower_1sigma','?'):.2f}, {next_pt.get('upper_1sigma','?'):.2f}]"
                )
            print(
                f"  {proj.get('metric_name','?')} | trend={proj.get('trend_direction','?')}"
                f"{seasonal}{inflection}{forecast_note}"
            )
    else:
        print(f"  Projections lookup failed: status={code}")

    print(
        f"\nUseful endpoints:"
        f"\n  GET {api_base.rstrip('/')}/correlation/runs/{correlation_run_id}"
        f"\n  GET {api_base.rstrip('/')}/correlation/runs/{correlation_run_id}/anomalies"
        f"\n  GET {api_base.rstrip('/')}/correlation/runs/{correlation_run_id}/pairs"
        f"\n  GET {api_base.rstrip('/')}/correlation/runs/{correlation_run_id}/threads"
        f"\n  GET {api_base.rstrip('/')}/correlation/runs/{correlation_run_id}/projections"
    )
    print("=" * 70)


def _print_anomaly_followups(api_base: str, *, tenant_id: str, domain_id: str, run_id: str) -> None:
    query = urllib.parse.urlencode({"tenant_id": tenant_id, "domain_id": domain_id, "run_id": run_id, "limit": 10})
    code, resp = _request(api_base, "GET", f"/workspace/anomalies?{query}")
    if code != 200:
        print("\nAnomaly artifacts lookup failed:")
        print(f"status={code} body={resp}")
        return

    investigations = (resp or {}).get("investigations") or []
    print("\nAnomaly artifacts:")
    if not investigations:
        print("No anomaly investigations found for this run.")
        return

    latest = investigations[0]
    investigation_id = str(latest.get("investigation_id") or "").strip()
    print(_json_dump({"latest_investigation": latest}))
    if not investigation_id:
        return

    details_path = f"/workspace/anomalies/{urllib.parse.quote(investigation_id)}"
    dashboard_path = f"/workspace/anomalies/{urllib.parse.quote(investigation_id)}/dashboard"
    print("Useful endpoints:")
    print(f"- Investigation details: {api_base.rstrip('/')}{details_path}")
    print(f"- Investigation dashboard: {api_base.rstrip('/')}{dashboard_path}")

    details_code, details_resp = _request(api_base, "GET", details_path)
    if details_code == 200:
        summary = {
            "investigation_id": investigation_id,
            "anomaly_count": len((details_resp or {}).get("anomalies") or []),
            "hypothesis_count": len((details_resp or {}).get("hypotheses") or []),
            "action_count": len((details_resp or {}).get("actions") or []),
            "dashboard_links": (details_resp or {}).get("dashboard_links") or [],
        }
        print("Investigation summary:")
        print(_json_dump(summary))
    else:
        print(f"Investigation details lookup failed: status={details_code}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a retail fuel monitoring deployment run and stream agentic logs end-to-end. "
            "Targets the alerts, location_master, and loss_of_sales tables. "
            "Auto-configures /tenant/domain and /tenant/scope first."
        )
    )
    parser.add_argument("--api-base", default="http://localhost:8787")
    parser.add_argument("--tenant-id", default=None, help="Existing tenant_id. Defaults to a new UUID.")
    parser.add_argument("--domain-id", default="retail_fuel_monitoring")
    parser.add_argument("--connection-id", default="2")
    parser.add_argument("--database", default="hpcl_ceg")
    parser.add_argument("--schema", default="public")
    parser.add_argument(
        "--tables",
        nargs="*",
        default=DEFAULT_TABLES,
        help="Tables to deploy (default: alerts location_master loss_of_sales)",
    )
    parser.add_argument(
        "--mode",
        choices=["stream", "poll"],
        default="stream",
    )
    parser.add_argument(
        "--context-text",
        default=None,
        help="Inline business context string. Overrides built-in default context.",
    )
    parser.add_argument(
        "--context-file",
        default=None,
        help="Path to text file whose contents are used as context_text.",
    )
    parser.add_argument(
        "--no-default-context",
        action="store_true",
        help="Skip the built-in fuel monitoring context text (send no context_text).",
    )
    parser.add_argument(
        "--context-id",
        action="append",
        default=[],
        help="Stored context_id to pass to /workspace/deployments. Repeatable.",
    )
    parser.add_argument(
        "--context-ids",
        nargs="*",
        default=[],
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print compact event summaries instead of full artifacts.",
    )
    parser.add_argument(
        "--skip-correlation",
        action="store_true",
    )
    parser.add_argument(
        "--correlation-mode",
        choices=["full", "anomaly_only"],
        default="full",
    )
    parser.add_argument("--forecast-periods", type=int, default=12, metavar="N")
    parser.add_argument("--correlation-timeout", type=float, default=300.0, metavar="SECS")
    args = parser.parse_args()

    tenant_id = args.tenant_id or str(uuid.uuid4())

    # Resolve context text: CLI arg > context file > built-in default
    context_text: str | None = None
    if args.context_text:
        context_text = args.context_text
    elif args.context_file:
        context_text = Path(args.context_file).read_text(encoding="utf-8")
    elif not args.no_default_context:
        context_text = _DEFAULT_CONTEXT_TEXT

    context_ids: list[str] = []
    seen_context_ids: set[str] = set()
    for value in list(args.context_id or []) + list(args.context_ids or []):
        cid = str(value or "").strip()
        if not cid or cid in seen_context_ids:
            continue
        seen_context_ids.add(cid)
        context_ids.append(cid)

    schema_payload = {
        "connection_id": str(args.connection_id),
        "database": args.database,
        "schemas": [{"name": args.schema, "tables": list(args.tables)}],
    }
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "domain_id": args.domain_id,
        "connection_id": str(args.connection_id),
        "database": args.database,
        "schema_name": args.schema,
        "schema_payload": schema_payload,
    }
    if context_text:
        payload["context_text"] = context_text
    if context_ids:
        payload["context_ids"] = context_ids

    tenant_payload = {
        "tenant_id": tenant_id,
        "display_name": f"Fuel Demo — {tenant_id[:8]}",
        "status": "active",
        "domain_id": args.domain_id,
        "metadata": {
            "created_by": "demo_workspace_deployment_fuel.py",
            "connection_id": str(args.connection_id),
            "database": args.database,
            "schema": args.schema,
        },
    }
    domain_payload = {"tenant_id": tenant_id, "domain_id": args.domain_id}
    scope_payload = {
        "tenant_id": tenant_id,
        "domain_id": args.domain_id,
        "connection_id": str(args.connection_id),
        "database": args.database,
        "schema": args.schema,
        "tables": list(args.tables),
    }

    print("Configuring tenant, domain and scope:")
    print(_json_dump({"tenant": tenant_payload, "domain": domain_payload, "scope": scope_payload}))

    tenant_code, tenant_resp = _request(args.api_base, "POST", "/tenants", tenant_payload)
    if tenant_code not in {200, 201}:
        print(f"Failed to upsert tenant: status={tenant_code} body={tenant_resp}")
        return 1
    domain_code, domain_resp = _request(args.api_base, "POST", "/tenant/domain", domain_payload)
    if domain_code not in {200, 201}:
        print(f"Failed to set tenant domain: status={domain_code} body={domain_resp}")
        return 1
    scope_code, scope_resp = _request(args.api_base, "POST", "/tenant/scope", scope_payload)
    if scope_code not in {200, 201}:
        print(f"Failed to set tenant scope: status={scope_code} body={scope_resp}")
        if scope_code == 404 and isinstance(scope_resp, dict):
            detail = str(scope_resp.get("detail") or "")
            if "connection not registered" in detail:
                print(
                    "Hint: connection_id is not registered. "
                    "Run /onboard/scan-connection once for this connection_id, then rerun."
                )
        return 1

    print("\nStarting workspace deployment:")
    safe_payload = dict(payload)
    if safe_payload.get("context_text"):
        safe_payload["context_text"] = f"<{len(str(safe_payload['context_text']))} chars>"
    print(_json_dump(safe_payload))

    code, created = _request(args.api_base, "POST", "/workspace/deployments", payload)
    if code == 409:
        detail = (created or {}).get("detail") or {}
        run_id = detail.get("run_id")
        if not run_id:
            print(f"Deployment blocked (409) but no run_id returned: {created}")
            return 1
        print(f"Deployment already in progress. Attaching to existing run_id={run_id}")
    elif code in {200, 201}:
        run_id = (created or {}).get("run_id")
        if not run_id:
            print(f"Deployment creation returned no run_id: {created}")
            return 1
        print(f"Created deployment run_id={run_id}, tenant_id={tenant_id}")
    else:
        print(f"Failed to create deployment: status={code} body={created}")
        return 1

    print(f"\nStreaming logs for run_id={run_id} using mode={args.mode} ...\n")
    try:
        if args.mode == "stream":
            _stream_run(args.api_base, run_id, print_full_payload=not args.summary_only)
        else:
            _poll_run_logs(args.api_base, run_id, print_full_payload=not args.summary_only)
    except KeyboardInterrupt:
        print("Interrupted by user.")

    code, final_run = _wait_for_terminal_run(args.api_base, run_id)
    print("\nFinal run status:")
    if code == 200:
        print(_json_dump(final_run))
    else:
        print(f"status={code} body={final_run}")

    _print_anomaly_debug(args.api_base, tenant_id=tenant_id, domain_id=args.domain_id, run_id=run_id)
    _print_anomaly_followups(args.api_base, tenant_id=tenant_id, domain_id=args.domain_id, run_id=run_id)

    if not args.skip_correlation:
        _print_correlation_summary(
            args.api_base,
            tenant_id=tenant_id,
            domain_id=args.domain_id,
            run_id=run_id,
            analysis_mode=args.correlation_mode,
            forecast_periods=args.forecast_periods,
            timeout_seconds=args.correlation_timeout,
        )
    else:
        print("\n[correlation] Skipped (--skip-correlation).")

    return 0


if __name__ == "__main__":
    sys.exit(main())