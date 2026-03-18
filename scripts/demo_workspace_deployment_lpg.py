#!/usr/bin/env python3
from __future__ import annotations

"""
End-to-end workspace deployment demo for LPG scope.

What it does:
1) Bootstraps tenant domain/scope.
2) Creates deployment via POST /workspace/deployments.
3) Streams run progress from /agentic/runs/{run_id}/stream (or polls events).
4) Prints final run status.

Usage examples:
  python3 scripts/demo_workspace_deployment_lpg.py

  python3 scripts/demo_workspace_deployment_lpg.py \
    --api-base http://localhost:8787 \
    --tenant-id DEBUG_LPG_001 \
    --domain-id lpg_production_distribution \
    --connection-id 2 \
    --database hpcl_ceg \
    --schema public

  python3 scripts/demo_workspace_deployment_lpg.py --mode poll

  python3 scripts/demo_workspace_deployment_lpg.py \
    --context-file docs/examples/lpg_business_context.txt

  python3 scripts/demo_workspace_deployment_lpg.py \
    --context-id ctx_ops_glossary \
    --context-ids ctx_kpi_formulas ctx_chart_guidance
"""

import argparse
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

DEFAULT_TABLES = [
    "lpg_plants",
    "lpg_plant_operations",
]


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
                            _print_event(event, print_full_payload=print_full_payload)
                    except json.JSONDecodeError:
                        print(f"SSE raw: {payload}")

            if now - last_status_check >= status_check_seconds:
                code, run = _request(api_base, "GET", f"/agentic/runs/{urllib.parse.quote(run_id)}")
                if code == 200 and isinstance(run, dict):
                    current_status = str(run.get("status") or "")
                    print(f"[run_status] {current_status}")
                    if _terminal_status(current_status):
                        if terminal_seen_at is None:
                            terminal_seen_at = now
                    else:
                        terminal_seen_at = None
                last_status_check = now

            if terminal_seen_at is not None and (now - terminal_seen_at) >= tail_seconds:
                break


def _poll_run_logs(
    api_base: str,
    run_id: str,
    *,
    print_full_payload: bool = True,
    interval_seconds: float = 2.0,
) -> None:
    seen_event_ids: set[str] = set()

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
            _print_event(event, print_full_payload=print_full_payload)

        run_code, run = _request(api_base, "GET", f"/agentic/runs/{urllib.parse.quote(run_id)}")
        if run_code == 200 and _terminal_status((run or {}).get("status")):
            print(f"[run_status] {(run or {}).get('status')}")
            break

        time.sleep(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a tenant deployment run and print agentic stream/logs end-to-end. "
            "This script auto-configures /tenant/domain and /tenant/scope first."
        )
    )
    parser.add_argument("--api-base", default="http://localhost:8787", help="API base URL")
    parser.add_argument("--tenant-id", default=None, help="Existing tenant_id. If omitted, a UUID is generated.")
    parser.add_argument("--domain-id", default="lpg_production_distribution")
    parser.add_argument("--connection-id", default="2")
    parser.add_argument("--database", default="hpcl_ceg")
    parser.add_argument("--schema", default="public")
    parser.add_argument(
        "--tables",
        nargs="*",
        default=DEFAULT_TABLES,
        help="List of tables for schema payload",
    )
    parser.add_argument(
        "--mode",
        choices=["stream", "poll"],
        default="stream",
        help="Use SSE stream or event polling logs",
    )
    parser.add_argument(
        "--context-text",
        default=None,
        help="Optional inline business context passed as context_text to /workspace/deployments",
    )
    parser.add_argument(
        "--context-file",
        default=None,
        help="Optional path to a text file whose contents are passed as context_text to /workspace/deployments",
    )
    parser.add_argument(
        "--context-id",
        action="append",
        default=[],
        help="Optional stored context_id to pass to /workspace/deployments. Can be repeated.",
    )
    parser.add_argument(
        "--context-ids",
        nargs="*",
        default=[],
        help="Optional list of stored context_ids to pass to /workspace/deployments",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print compact event summaries instead of full artifacts and metadata.",
    )
    args = parser.parse_args()

    tenant_id = args.tenant_id or str(uuid.uuid4())
    context_text = args.context_text
    if args.context_file:
        context_text = Path(args.context_file).read_text(encoding="utf-8")
    context_ids: list[str] = []
    seen_context_ids: set[str] = set()
    for value in list(args.context_id or []) + list(args.context_ids or []):
        context_id = str(value or "").strip()
        if not context_id or context_id in seen_context_ids:
            continue
        seen_context_ids.add(context_id)
        context_ids.append(context_id)
    schema_payload = {
        "connection_id": str(args.connection_id),
        "database": args.database,
        "schemas": [
            {
                "name": args.schema,
                "tables": list(args.tables),
            }
        ],
    }
    payload = {
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

    # Bootstrap tenant metadata required by /workspace/deployments.
    domain_payload = {"tenant_id": tenant_id, "domain_id": args.domain_id}
    scope_payload = {
        "tenant_id": tenant_id,
        "domain_id": args.domain_id,
        "connection_id": str(args.connection_id),
        "database": args.database,
        "schema": args.schema,
        "tables": list(args.tables),
    }
    print("Configuring tenant domain and scope:")
    print(_json_dump({"domain": domain_payload, "scope": scope_payload}))
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
                    "Hint: connection_id is not registered in backend scope registry. "
                    "Run /onboard/scan-connection once for this connection_id, then rerun this demo."
                )
        return 1

    print("Starting workspace deployment with payload:")
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

    code, final_run = _request(args.api_base, "GET", f"/agentic/runs/{urllib.parse.quote(run_id)}")
    print("\nFinal run status:")
    if code == 200:
        print(_json_dump(final_run))
    else:
        print(f"status={code} body={final_run}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
