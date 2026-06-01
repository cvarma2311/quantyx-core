#!/usr/bin/env python3
from __future__ import annotations

"""
Demo runner for the Data Quality UI integration flow described in:
docs/implementation_plans/Phase_Agentic_Semantic_Platform/57_Data_Quality_UI_Integration_E2E_API_Flow.md

This script is intended for UI/backend integration testing. It calls the
implemented APIs, prints each request and response, and can optionally perform
review/enrichment state transitions.

Typical usage:

  python3 scripts/demo_data_quality_ui_api_flow.py --scenario reload --run-id run_123

  python3 scripts/demo_data_quality_ui_api_flow.py \
    --scenario review \
    --tenant-id VC_101 \
    --connection-id conn_lpg \
    --database analytics \
    --schema-name public \
    --review-action approve \
    --auto-resume

  python3 scripts/demo_data_quality_ui_api_flow.py \
    --scenario all \
    --tenant-id VC_101 \
    --connection-id conn_lpg \
    --database analytics \
    --schema-name public \
    --download-dir /tmp/dq_demo

  python3 scripts/demo_data_quality_ui_api_flow.py \
    --scenario all \
    --tenant-id VC_101 \
    --connection-id conn_lpg \
    --database analytics \
    --schema-name public \
    --include-rerun-monitor

Safe defaults:
- read-only where possible
- does not mutate rule review or enrichment state unless explicit action flags are set
- does not write back to source data; staging APIs only create overlay artifacts
"""

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_API_BASE = os.getenv("QUANTYX_API_BASE", "http://127.0.0.1:8787")
DEFAULT_DOMAIN_ID = "data_quality_observability"
DEFAULT_TABLES = ["customer_data"]
DEFAULT_DEPLOY_CONTEXT = (
    "Perform data quality checks on customer_data. "
    "customer_data.customer_id, customer_data.email, and customer_data.phone_number must be present. "
    "customer_data.customer_id must be unique. "
    "Each customer_data.account_number must map to only one customer_data.customer_id. "
    "customer_data.email must match a basic email pattern. "
    "Customer age must be between 18 and 80, calculated using customer_data.dob and customer_data.created_date. "
    "customer_data.account_type must be one of Savings, Current, or Business. "
    "customer_data.balance must not be negative."
)
DEFAULT_REVIEW_CONTEXT = (
    "Perform data quality checks on customer_data. "
    "customer_data.customer_id, customer_data.email, and customer_data.phone_number must be present. "
    "customer_data.customer_id must be unique. "
    "Each customer_data.account_number must map to only one customer_data.customer_id. "
    "customer_data.email must match a basic email pattern. "
    "Customer age must be between 18 and 80, calculated using customer_data.dob and customer_data.created_date. "
    "customer_data.account_type must be one of Savings, Current, or Business. "
    "customer_data.balance must not be negative."
)


class DemoLogger:
    def __init__(self, log_file: Path | None = None) -> None:
        self.log_file = log_file
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str = "") -> None:
        print(message)
        if self.log_file:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(message)
                handle.write("\n")

    def section(self, title: str) -> None:
        self.write("")
        self.write(f"===== {title} =====")

    def json(self, value: Any) -> None:
        self.write(json.dumps(value, indent=2, ensure_ascii=True, default=str, sort_keys=True))


class ApiClient:
    def __init__(self, api_base: str, logger: DemoLogger) -> None:
        self.api_base = api_base.rstrip("/")
        self.logger = logger

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.api_base}{path}"

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: int = 120,
        expected: set[int] | None = None,
    ) -> tuple[int, Any]:
        url = self._url(path)
        self.logger.write(f"==> {method} {path}")
        if payload is not None:
            self.logger.json(payload)
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
                parsed = json.loads(raw) if raw else {}
                self.logger.write(f"<== {resp.status}")
                self.logger.json(parsed)
                if expected and resp.status not in expected:
                    raise RuntimeError(f"Unexpected status {resp.status} for {method} {path}")
                return resp.status, parsed
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(body) if body else {"detail": body}
            except Exception:
                parsed = {"detail": body}
            self.logger.write(f"<== {exc.code}")
            self.logger.json(parsed)
            if expected and exc.code not in expected:
                raise
            return exc.code, parsed
        except TimeoutError:
            parsed = {"detail": "request_timeout"}
            self.logger.write("<== 599")
            self.logger.json(parsed)
            return 599, parsed
        except socket.timeout:
            parsed = {"detail": "request_timeout"}
            self.logger.write("<== 599")
            self.logger.json(parsed)
            return 599, parsed

    def request_binary(
        self,
        method: str,
        path: str,
        *,
        timeout: int = 120,
        expected: set[int] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        url = self._url(path)
        self.logger.write(f"==> {method} {path}")
        req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                headers = {k: v for k, v in resp.headers.items()}
                meta = {
                    "status": resp.status,
                    "content_type": headers.get("Content-Type"),
                    "content_disposition": headers.get("Content-Disposition"),
                    "byte_count": len(data),
                }
                self.logger.write(f"<== {resp.status}")
                self.logger.json(meta)
                if expected and resp.status not in expected:
                    raise RuntimeError(f"Unexpected status {resp.status} for {method} {path}")
                return resp.status, data, headers
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(body) if body else {"detail": body}
            except Exception:
                parsed = {"detail": body}
            self.logger.write(f"<== {exc.code}")
            self.logger.json(parsed)
            if expected and exc.code not in expected:
                raise
            return exc.code, b"", {}


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _parse_query_path(raw_path: str) -> str:
    return raw_path if raw_path.startswith("/") else f"/{raw_path}"


def _load_text_file(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8")


def _load_json_file(path: str | None) -> dict[str, Any] | list[Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_inline_schema_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "connection_id": str(args.connection_id or ""),
        "database": args.database,
        "schemas": [
            {
                "name": args.schema_name,
                "tables": list(args.tables or []),
            }
        ],
    }


def _path_from_evidence_link(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        parsed = urllib.parse.urlparse(path)
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return path


def _build_deployment_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_id": args.tenant_id,
        "domain_id": args.domain_id,
        "mode": "full",
        "pause_for_rule_review": bool(args.pause_for_rule_review),
        "context_text": args.context_text,
    }
    if args.connection_id:
        payload["connection_id"] = args.connection_id
    if args.database:
        payload["database"] = args.database
    if args.schema_name:
        payload["schema_name"] = args.schema_name
    if args.context_ids:
        payload["context_ids"] = list(args.context_ids)
    schema_payload = _load_json_file(args.schema_payload_file)
    if schema_payload is None:
        schema_payload = _build_inline_schema_payload(args)
    payload["schema_payload"] = schema_payload
    return payload


def bootstrap_scope(client: ApiClient, args: argparse.Namespace) -> None:
    tenant_payload = {
        "tenant_id": args.tenant_id,
        "display_name": args.tenant_id,
        "status": "active",
        "domain_id": args.domain_id,
        "metadata": {
            "created_by": "demo_data_quality_ui_api_flow.py",
            "connection_id": str(args.connection_id or ""),
            "database": args.database,
            "schema": args.schema_name,
            "tables": list(args.tables or []),
        },
    }
    domain_payload = {
        "tenant_id": args.tenant_id,
        "domain_id": args.domain_id,
    }
    scope_payload = {
        "tenant_id": args.tenant_id,
        "domain_id": args.domain_id,
        "connection_id": str(args.connection_id or ""),
        "database": args.database,
        "schema": args.schema_name,
        "tables": list(args.tables or []),
    }
    client.logger.section("BOOTSTRAP TENANT / DOMAIN / SCOPE")
    client.request_json("POST", "/tenants", payload=tenant_payload, expected={200, 201})
    client.request_json("POST", "/tenant/domain", payload=domain_payload, expected={200, 201})
    client.request_json("POST", "/tenant/scope", payload=scope_payload, expected={200, 201})


def wait_for_agentic_run_state(
    client: ApiClient,
    run_id: str,
    *,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        code, payload = client.request_json("GET", f"/agentic/runs/{_quote(run_id)}", expected={200, 404})
        if code == 200 and isinstance(payload, dict):
            last = payload
            status = str(payload.get("status") or "").strip().lower()
            if status in {"completed", "failed", "cancelled", "awaiting_rule_review"}:
                return payload
        time.sleep(poll_seconds)
    return last


def log_recent_run_events(client: ApiClient, run_id: str, *, limit: int = 20) -> dict[str, Any]:
    client.logger.section("RECENT RUN EVENTS")
    _, payload = client.request_json("GET", f"/agentic/runs/{_quote(run_id)}/events?limit={limit}", expected={200, 404})
    return payload if isinstance(payload, dict) else {}


def wait_for_data_quality_run_visibility(
    client: ApiClient,
    run_id: str,
    *,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        code, payload = client.request_json("GET", f"/data-quality/runs/{_quote(run_id)}", expected={200, 404})
        if code == 200 and isinstance(payload, dict):
            return payload
        if isinstance(payload, dict):
            last = payload
        time.sleep(poll_seconds)
    return last


def wait_for_job_state(
    client: ApiClient,
    job_id: str,
    *,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        code, payload = client.request_json("GET", f"/jobs/{_quote(job_id)}", expected={200, 404})
        if code == 200 and isinstance(payload, dict):
            last = payload
            status = str(payload.get("status") or "").strip().lower()
            if status in {"completed", "failed", "canceled", "cancelled"}:
                return payload
        time.sleep(poll_seconds)
    return last


def log_job_result(client: ApiClient, job_id: str) -> dict[str, Any]:
    client.logger.section("JOB RESULT")
    _, payload = client.request_json("GET", f"/jobs/{_quote(job_id)}/result", expected={200, 202, 404})
    return payload if isinstance(payload, dict) else {}


def start_or_reuse_run(client: ApiClient, args: argparse.Namespace) -> str:
    if args.run_id:
        return args.run_id
    if args.auto_bootstrap:
        bootstrap_scope(client, args)
    payload = _build_deployment_payload(args)
    code, response = client.request_json("POST", "/workspace/deployments", payload=payload, expected={200, 409})
    if code == 200:
        run_id = str(response.get("run_id") or "").strip()
        if not run_id:
            raise RuntimeError("Deployment response did not contain run_id")
        return run_id
    detail = response.get("detail") if isinstance(response, dict) else None
    if isinstance(detail, dict) and detail.get("run_id"):
        return str(detail["run_id"])
    raise RuntimeError("Unable to determine run_id from deployment response")


def scenario_run_history(
    client: ApiClient,
    args: argparse.Namespace,
    *,
    tenant_id: str,
    domain_id: str,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    _, payload = client.request_json(
        "GET",
        f"/workspace/deployments?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'limit': args.run_history_limit})}",
        expected={200},
    )
    outputs["run_history"] = payload
    return outputs


def start_rerun_monitor(
    client: ApiClient,
    args: argparse.Namespace,
    *,
    source_run_id: str,
) -> tuple[str, dict[str, Any]]:
    payload = {"trend_mode": "monitor"}
    code, response = client.request_json(
        "POST",
        f"/workspace/deployments/{_quote(source_run_id)}/rerun",
        payload=payload,
        expected={200, 409},
    )
    if code == 200:
        rerun_id = str(response.get("run_id") or "").strip()
        if not rerun_id:
            raise RuntimeError("Rerun response did not contain run_id")
        return rerun_id, response
    detail = response.get("detail") if isinstance(response, dict) else None
    if isinstance(detail, dict) and detail.get("run_id"):
        return str(detail["run_id"]), response
    raise RuntimeError("Unable to determine rerun run_id from rerun response")


def scenario_reload(client: ApiClient, args: argparse.Namespace, run_id: str) -> dict[str, Any]:
    client.request_json("GET", f"/agentic/runs/{_quote(run_id)}/events?limit={args.events_limit}", expected={200})
    client.request_json("GET", f"/agentic/runs/{_quote(run_id)}/chat?limit={args.chat_limit}", expected={200})
    code, hydration = client.request_json("GET", f"/data-quality/runs/{_quote(run_id)}/hydration", expected={200, 404})
    if code != 200:
        return {}
    return hydration if isinstance(hydration, dict) else {}


def scenario_summary_and_surfaces(
    client: ApiClient,
    args: argparse.Namespace,
    run_id: str,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    code, summary = client.request_json("GET", f"/data-quality/runs/{_quote(run_id)}", expected={200, 404})
    if code != 200 or not isinstance(summary, dict):
        return outputs
    outputs["summary"] = summary
    tenant_id = str(summary.get("tenant_id") or args.tenant_id)
    domain_id = str(summary.get("domain_id") or args.domain_id)

    q = urllib.parse.urlencode({"tenant_id": tenant_id, "domain_id": domain_id, "run_id": run_id})
    _, tables = client.request_json("GET", f"/data-quality/tables?{q}", expected={200})
    outputs["tables"] = tables

    first_table = None
    if isinstance(tables, dict):
        table_rows = tables.get("tables") or []
        if table_rows:
            first_table = table_rows[0]
            table_name = str(first_table.get("table_name") or "")
            if table_name:
                table_q = urllib.parse.urlencode({"tenant_id": tenant_id, "domain_id": domain_id, "run_id": run_id})
                _, detail = client.request_json(
                    "GET",
                    f"/data-quality/tables/{_quote(table_name)}?{table_q}",
                    expected={200, 404},
                )
                outputs["table_detail"] = detail

    _, rules = client.request_json(
        "GET",
        f"/data-quality/rules?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["rules"] = rules

    _, duplicates = client.request_json(
        "GET",
        f"/data-quality/duplicates?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["duplicates"] = duplicates

    _, freshness = client.request_json(
        "GET",
        f"/data-quality/freshness?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["freshness"] = freshness

    _, stages = client.request_json(
        "GET",
        f"/data-quality/stages?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["stages"] = stages

    stage_rows = (stages or {}).get("stages") or []
    first_stage = stage_rows[0] if stage_rows else None
    if first_stage:
        stage_id = str(first_stage.get("stage_id") or "")
        if stage_id:
            _, stage_detail = client.request_json(
                "GET",
                f"/data-quality/stages/{_quote(stage_id)}?{urllib.parse.urlencode({'tenant_id': tenant_id})}",
                expected={200, 404},
            )
            outputs["stage_detail"] = stage_detail
            _, stage_evidence = client.request_json(
                "GET",
                f"/data-quality/evidence/stages/{_quote(stage_id)}?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'limit': args.list_limit})}",
                expected={200, 404},
            )
            outputs["stage_evidence"] = stage_evidence

    _, joins = client.request_json(
        "GET",
        f"/data-quality/joins?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["joins"] = joins

    join_rows = (joins or {}).get("joins") or []
    first_join = join_rows[0] if join_rows else None
    if first_join:
        join_artifact_id = str(first_join.get("join_artifact_id") or "")
        if join_artifact_id:
            _, join_detail = client.request_json(
                "GET",
                f"/data-quality/joins/{_quote(join_artifact_id)}?{urllib.parse.urlencode({'tenant_id': tenant_id})}",
                expected={200, 404},
            )
            outputs["join_detail"] = join_detail
            _, join_evidence = client.request_json(
                "GET",
                f"/data-quality/evidence/joins/{_quote(join_artifact_id)}?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'limit': args.list_limit})}",
                expected={200, 404},
            )
            outputs["join_evidence"] = join_evidence

    _, rejected_records = client.request_json(
        "GET",
        f"/data-quality/rejected-records?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["rejected_records"] = rejected_records

    _, final_dataset = client.request_json(
        "GET",
        f"/data-quality/final-dataset?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id})}",
        expected={200, 404},
    )
    outputs["final_dataset"] = final_dataset

    _, final_dataset_rows = client.request_json(
        "GET",
        f"/data-quality/final-dataset/rows?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit, 'offset': 0})}",
        expected={200, 404},
    )
    outputs["final_dataset_rows"] = final_dataset_rows

    _, lineage = client.request_json(
        "GET",
        f"/data-quality/lineage?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200, 404},
    )
    outputs["lineage"] = lineage

    lineage_rows = (lineage or {}).get("rows") or []
    first_lineage = lineage_rows[0] if lineage_rows else None
    if first_lineage:
        row_lineage_id = str(first_lineage.get("row_lineage_id") or "")
        if row_lineage_id:
            base_q = urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id})
            _, lineage_journey = client.request_json(
                "GET",
                f"/data-quality/lineage/{_quote(row_lineage_id)}/journey?{base_q}",
                expected={200, 404},
            )
            outputs["lineage_journey"] = lineage_journey
            _, lineage_trace = client.request_json(
                "GET",
                f"/data-quality/lineage/{_quote(row_lineage_id)}?{base_q}",
                expected={200, 404},
            )
            outputs["lineage_trace"] = lineage_trace

    _, remediation = client.request_json(
        "GET",
        f"/data-quality/remediation?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["remediation"] = remediation

    _, trends = client.request_json(
        "GET",
        f"/data-quality/trends?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["trends"] = trends

    _, business_term_trends = client.request_json(
        "GET",
        f"/data-quality/trends/business-terms?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id})}",
        expected={200},
    )
    outputs["business_term_trends"] = business_term_trends

    _, anomalies = client.request_json(
        "GET",
        f"/data-quality/anomalies?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["anomalies"] = anomalies

    _, issues = client.request_json(
        "GET",
        f"/data-quality/issues?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'run_id': run_id, 'limit': args.list_limit})}",
        expected={200},
    )
    outputs["issues"] = issues

    _, dashboard = client.request_json(
        "GET",
        f"/data-quality/runs/{_quote(run_id)}/dashboard",
        expected={200, 404},
    )
    outputs["dashboard"] = dashboard

    excel_path = f"/data-quality/reports/{_quote(run_id)}/excel?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id})}"
    status, binary, headers = client.request_binary("GET", excel_path, expected={200, 404})
    if status == 200 and binary:
        download_dir = Path(args.download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)
        filename = _extract_filename(headers) or f"data_quality_{run_id}.xlsx"
        target = download_dir / filename
        target.write_bytes(binary)
        client.logger.write(f"Saved Excel report to {target}")
        outputs["excel_report_path"] = str(target)

    return outputs


def scenario_rule_review(
    client: ApiClient,
    args: argparse.Namespace,
    run_id: str,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    tenant_id = str((summary or {}).get("tenant_id") or args.tenant_id)
    domain_id = str((summary or {}).get("domain_id") or args.domain_id)
    queue_q = urllib.parse.urlencode({"tenant_id": tenant_id, "domain_id": domain_id, "run_id": run_id})
    _, queue = client.request_json("GET", f"/data-quality/rules/review-queue?{queue_q}", expected={200})
    outputs["review_queue"] = queue

    rules = (queue or {}).get("rules") or []
    if not rules:
        return outputs

    review_action = args.review_action
    if args.auto_approve_review_rules and review_action == "none":
        review_action = "approve"

    outputs["rule_details"] = []
    outputs["review_results"] = []

    for index, rule in enumerate(rules):
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            continue
        _, detail = client.request_json(
            "GET",
            f"/data-quality/rules/{_quote(rule_id)}/review?{urllib.parse.urlencode({'tenant_id': tenant_id})}",
            expected={200},
        )
        outputs["rule_details"].append(detail)
        if review_action == "none":
            if index == 0:
                outputs["rule_detail"] = detail
            continue

        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "reviewed_by": args.reviewed_by,
            "action": review_action,
            "review_notes": args.review_notes or f"Demo review action: {review_action}",
        }
        if review_action == "approve" and args.rule_condition_json_file and index == 0:
            payload["condition_json"] = _load_json_file(args.rule_condition_json_file)
        if args.rule_source_text and index == 0:
            payload["source_text"] = args.rule_source_text
        if args.rule_severity and index == 0:
            payload["severity"] = args.rule_severity

        _, review_result = client.request_json(
            "POST",
            f"/data-quality/rules/{_quote(rule_id)}/review",
            payload=payload,
            expected={200},
        )
        outputs["review_results"].append(review_result)
        if index == 0:
            outputs["rule_detail"] = detail
            outputs["review_result"] = review_result

    _, refreshed_queue = client.request_json("GET", f"/data-quality/rules/review-queue?{queue_q}", expected={200})
    outputs["review_queue_after"] = refreshed_queue
    remaining = (refreshed_queue or {}).get("rules") or []

    if (args.auto_resume or args.auto_approve_review_rules) and not remaining:
        _, resume = client.request_json(
            "POST",
            f"/data-quality/runs/{_quote(run_id)}/resume-after-rule-review",
            payload={"requested_by": args.reviewed_by},
            expected={200, 409},
        )
        outputs["resume"] = resume

    return outputs


def scenario_enrichment(
    client: ApiClient,
    args: argparse.Namespace,
    run_id: str,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    tenant_id = str((summary or {}).get("tenant_id") or args.tenant_id)
    domain_id = str((summary or {}).get("domain_id") or args.domain_id)

    base_q = urllib.parse.urlencode({"tenant_id": tenant_id, "domain_id": domain_id, "run_id": run_id, "limit": args.list_limit})
    _, opportunities = client.request_json("GET", f"/data-quality/enrichment/opportunities?{base_q}", expected={200})
    outputs["opportunities"] = opportunities

    _, questions = client.request_json("GET", f"/data-quality/enrichment/questions?{base_q}", expected={200})
    outputs["questions"] = questions

    question_rows = (questions or {}).get("questions") or []
    opportunity_rows = (opportunities or {}).get("opportunities") or []

    proposal_id = args.proposal_id
    opportunity_id = args.opportunity_id
    if not opportunity_id and question_rows:
        opportunity_id = str(question_rows[0].get("opportunity_id") or "")
    if not opportunity_id and opportunity_rows:
        opportunity_id = str(opportunity_rows[0].get("opportunity_id") or "")

    if args.enrichment_answer != "none" and opportunity_id:
        answer_payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "answer": args.enrichment_answer,
        }
        if args.enrichment_answer == "approve":
            answer_payload["approved_by"] = args.reviewed_by
            answer_payload["max_records"] = args.max_records
        _, answer_result = client.request_json(
            "POST",
            f"/data-quality/enrichment/questions/{_quote(opportunity_id)}/answer",
            payload=answer_payload,
            expected={200},
        )
        outputs["question_answer"] = answer_result
        proposal_id = str(answer_result.get("proposal_id") or proposal_id or "")
    elif args.legacy_approve_research and opportunity_id:
        _, legacy_result = client.request_json(
            "POST",
            f"/data-quality/enrichment/opportunities/{_quote(opportunity_id)}/approve-research",
            payload={"tenant_id": tenant_id, "approved_by": args.reviewed_by, "max_records": args.max_records},
            expected={200},
        )
        outputs["legacy_approve_research"] = legacy_result
        proposal_id = str(legacy_result.get("proposal_id") or proposal_id or "")

    if not proposal_id:
        for question in question_rows:
            if question.get("proposal_id"):
                proposal_id = str(question["proposal_id"])
                break

    if proposal_id:
        _, proposal = client.request_json(
            "GET",
            f"/data-quality/enrichment/proposals/{_quote(proposal_id)}?{urllib.parse.urlencode({'tenant_id': tenant_id})}",
            expected={200},
        )
        outputs["proposal"] = proposal

        if args.apply_staging:
            apply_payload = {
                "tenant_id": tenant_id,
                "approved_by": args.reviewed_by,
                "application_mode": "staged_overlay",
                "approval_scope": args.approval_scope,
                "min_confidence": args.min_confidence,
                "reason": args.staging_reason or "Demo staged overlay approval",
            }
            _, apply_result = client.request_json(
                "POST",
                f"/data-quality/enrichment/proposals/{_quote(proposal_id)}/approve-application",
                payload=apply_payload,
                expected={200},
            )
            outputs["proposal_application"] = apply_result

        _, staged = client.request_json(
            "GET",
            f"/data-quality/enrichment/proposals/{_quote(proposal_id)}/staged-artifact?{urllib.parse.urlencode({'tenant_id': tenant_id})}",
            expected={200, 404},
        )
        outputs["staged_artifact"] = staged

    return outputs


def scenario_evidence(
    client: ApiClient,
    args: argparse.Namespace,
    run_id: str,
    summary_outputs: dict[str, Any],
    enrichment_outputs: dict[str, Any],
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    summary = summary_outputs.get("summary") or {}
    tenant_id = str(summary.get("tenant_id") or args.tenant_id)
    domain_id = str(summary.get("domain_id") or args.domain_id)

    remediation = summary_outputs.get("remediation") or {}
    actions = remediation.get("actions") or []
    missingness_path = None
    for action in actions:
        if str(action.get("evidence_type") or "") == "missingness":
            missingness_path = _path_from_evidence_link(action.get("evidence_path"))
            break
    if missingness_path:
        _, missingness = client.request_json("GET", missingness_path, expected={200, 404})
        outputs["missingness"] = missingness

    rules = (summary_outputs.get("rules") or {}).get("rules") or []
    if rules:
        rule_id = str(rules[0].get("rule_id") or "")
        if rule_id:
            _, rule_evidence = client.request_json(
                "GET",
                f"/data-quality/evidence/rules/{_quote(rule_id)}?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'limit': args.list_limit})}",
                expected={200, 404},
            )
            outputs["rule"] = rule_evidence

    duplicates = (summary_outputs.get("duplicates") or {}).get("duplicates") or []
    if duplicates:
        candidate_id = str(duplicates[0].get("candidate_id") or "")
        if candidate_id:
            _, duplicate_evidence = client.request_json(
                "GET",
                f"/data-quality/evidence/duplicates/{_quote(candidate_id)}?{urllib.parse.urlencode({'tenant_id': tenant_id, 'domain_id': domain_id, 'limit': args.list_limit})}",
                expected={200, 404},
            )
            outputs["duplicates"] = duplicate_evidence

    freshness_rows = (summary_outputs.get("freshness") or {}).get("freshness") or []
    if freshness_rows:
        table_name = str(freshness_rows[0].get("table_name") or "")
        if table_name:
            _, freshness_evidence = client.request_json(
                "GET",
                f"/data-quality/evidence/freshness/{_quote(table_name)}?{urllib.parse.urlencode({'tenant_id': tenant_id, 'run_id': run_id, 'domain_id': domain_id})}",
                expected={200, 404},
            )
            outputs["freshness"] = freshness_evidence

    proposal = enrichment_outputs.get("proposal") or {}
    proposal_id = str(proposal.get("proposal_id") or args.proposal_id or "")
    if proposal_id:
        _, enrichment_evidence = client.request_json(
            "GET",
            f"/data-quality/evidence/enrichment/{_quote(proposal_id)}?{urllib.parse.urlencode({'tenant_id': tenant_id, 'limit': args.list_limit})}",
            expected={200, 404},
        )
        outputs["enrichment"] = enrichment_evidence

    return outputs


def _extract_filename(headers: dict[str, str]) -> str | None:
    content_disposition = headers.get("Content-Disposition") or headers.get("content-disposition")
    if not content_disposition:
        return None
    parts = [part.strip() for part in content_disposition.split(";")]
    for part in parts:
        if part.lower().startswith("filename="):
            return part.split("=", 1)[1].strip().strip('"')
    return None


def run_scenario(client: ApiClient, args: argparse.Namespace) -> int:
    run_id = start_or_reuse_run(client, args)
    client.logger.section("RUN IDENTIFIER")
    client.logger.json({"run_id": run_id})

    if args.wait_for_state:
        client.logger.section("WAIT FOR RUN STATE")
        initial_agentic_state = wait_for_agentic_run_state(
            client,
            run_id,
            timeout_seconds=args.wait_timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        initial_status = str((initial_agentic_state or {}).get("status") or "").strip().lower()
        if initial_status in {"failed", "cancelled", "canceled"}:
            log_recent_run_events(client, run_id, limit=args.events_limit)
            return 1
        wait_for_data_quality_run_visibility(
            client,
            run_id,
            timeout_seconds=args.wait_timeout_seconds,
            poll_seconds=args.poll_seconds,
        )

    hydration: dict[str, Any] = {}
    summary_outputs: dict[str, Any] = {}
    enrichment_outputs: dict[str, Any] = {}
    history_outputs: dict[str, Any] = {}

    if args.scenario in {"reload", "all", "completed", "review", "enrichment", "evidence"}:
        client.logger.section("RELOAD FLOW")
        hydration = scenario_reload(client, args, run_id)

    if args.scenario in {"review", "all"}:
        client.logger.section("RULE REVIEW FLOW")
        review_outputs = scenario_rule_review(
            client,
            args,
            run_id,
            summary=summary_outputs.get("summary") or (hydration.get("run") if isinstance(hydration, dict) else None),
        )
        if args.auto_resume and args.wait_after_resume:
            resume_job_id = str((review_outputs.get("resume") or {}).get("job_id") or "").strip()
            if resume_job_id:
                client.logger.section("WAIT FOR RESUME JOB")
                job_state = wait_for_job_state(
                    client,
                    resume_job_id,
                    timeout_seconds=args.wait_timeout_seconds,
                    poll_seconds=args.poll_seconds,
                )
                job_status = str((job_state or {}).get("status") or "").strip().lower()
                if job_status not in {"completed", "failed", "canceled", "cancelled"}:
                    client.logger.section("JOB WAIT RESULT")
                    client.logger.json(
                        {
                            "detail": "resume_job_did_not_reach_terminal_state_before_timeout",
                            "job_id": resume_job_id,
                            "status": job_status or None,
                            "updated_at": (job_state or {}).get("updated_at"),
                            "progress_stage": (job_state or {}).get("progress_stage"),
                            "progress_pct": (job_state or {}).get("progress_pct"),
                        }
                    )
                    log_job_result(client, resume_job_id)
                    log_recent_run_events(client, run_id)
                    return 1
                log_job_result(client, resume_job_id)
                if job_status in {"failed", "canceled", "cancelled"}:
                    log_recent_run_events(client, run_id)
                    return 1
            client.logger.section("WAIT AFTER RESUME")
            resumed = wait_for_agentic_run_state(
                client,
                run_id,
                timeout_seconds=args.wait_timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
            resumed_status = str((resumed or {}).get("status") or "").strip().lower()
            if resumed_status not in {"completed", "failed", "cancelled"}:
                client.logger.section("WAIT RESULT")
                client.logger.json(
                    {
                        "detail": "resume_did_not_reach_terminal_state_before_timeout",
                        "run_id": run_id,
                        "status": resumed_status or None,
                        "updated_at": (resumed or {}).get("updated_at"),
                    }
                )
                log_recent_run_events(client, run_id)
                return 1
            if resumed_status in {"failed", "cancelled"}:
                log_recent_run_events(client, run_id)
                return 1
            log_recent_run_events(client, run_id, limit=args.events_limit)

    if args.scenario in {"completed", "all", "review", "enrichment", "evidence"}:
        client.logger.section("SUMMARY AND SURFACES")
        summary_outputs = scenario_summary_and_surfaces(client, args, run_id)

    summary = summary_outputs.get("summary") or (hydration.get("run") if isinstance(hydration, dict) else {}) or {}
    tenant_id = str(summary.get("tenant_id") or args.tenant_id)
    domain_id = str(summary.get("domain_id") or args.domain_id)

    if args.scenario in {"completed", "all"}:
        client.logger.section("RUN HISTORY")
        history_outputs = scenario_run_history(client, args, tenant_id=tenant_id, domain_id=domain_id)

    if args.scenario in {"enrichment", "all"}:
        client.logger.section("ENRICHMENT FLOW")
        enrichment_outputs = scenario_enrichment(
            client,
            args,
            run_id,
            summary=summary,
        )

    if args.scenario in {"evidence", "all"}:
        client.logger.section("EVIDENCE FLOW")
        scenario_evidence(client, args, run_id, summary_outputs, enrichment_outputs)

    if args.include_rerun_monitor:
        client.logger.section("RERUN AS MONITOR FLOW")
        history = history_outputs.get("run_history") or {}
        runs = (history.get("runs") or history.get("deployments") or [])
        source_run_id = str(args.rerun_source_run_id or run_id).strip()
        if not args.rerun_source_run_id and runs:
            latest = runs[0]
            latest_run_id = str(latest.get("run_id") or "").strip()
            if latest_run_id:
                source_run_id = latest_run_id
        client.logger.json({"source_run_id": source_run_id})
        rerun_id, rerun_response = start_rerun_monitor(client, args, source_run_id=source_run_id)
        client.logger.section("RERUN IDENTIFIER")
        client.logger.json({"run_id": rerun_id, "response": rerun_response})
        if args.wait_for_state:
            client.logger.section("WAIT FOR RERUN STATE")
            rerun_agentic_state = wait_for_agentic_run_state(
                client,
                rerun_id,
                timeout_seconds=args.wait_timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
            rerun_status = str((rerun_agentic_state or {}).get("status") or "").strip().lower()
            if rerun_status in {"failed", "cancelled", "canceled"}:
                log_recent_run_events(client, rerun_id, limit=args.events_limit)
                return 1
            wait_for_data_quality_run_visibility(
                client,
                rerun_id,
                timeout_seconds=args.wait_timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
        client.logger.section("RERUN RELOAD FLOW")
        rerun_hydration = scenario_reload(client, args, rerun_id)
        rerun_review_outputs: dict[str, Any] = {}
        if args.auto_handle_rerun_review:
            client.logger.section("RERUN RULE REVIEW FLOW")
            rerun_review_outputs = scenario_rule_review(
                client,
                args,
                rerun_id,
                summary=(rerun_hydration.get("run") if isinstance(rerun_hydration, dict) else None),
            )
            if args.auto_resume and args.wait_after_resume:
                resume_job_id = str((rerun_review_outputs.get("resume") or {}).get("job_id") or "").strip()
                if resume_job_id:
                    client.logger.section("WAIT FOR RERUN RESUME JOB")
                    rerun_job_state = wait_for_job_state(
                        client,
                        resume_job_id,
                        timeout_seconds=args.wait_timeout_seconds,
                        poll_seconds=args.poll_seconds,
                    )
                    rerun_job_status = str((rerun_job_state or {}).get("status") or "").strip().lower()
                    log_job_result(client, resume_job_id)
                    if rerun_job_status in {"failed", "canceled", "cancelled"}:
                        log_recent_run_events(client, rerun_id)
                        return 1
                client.logger.section("WAIT AFTER RERUN RESUME")
                rerun_completed_state = wait_for_agentic_run_state(
                    client,
                    rerun_id,
                    timeout_seconds=args.wait_timeout_seconds,
                    poll_seconds=args.poll_seconds,
                )
                rerun_completed_status = str((rerun_completed_state or {}).get("status") or "").strip().lower()
                if rerun_completed_status not in {"completed", "failed", "cancelled"}:
                    log_recent_run_events(client, rerun_id)
                    return 1
                if rerun_completed_status in {"failed", "cancelled"}:
                    log_recent_run_events(client, rerun_id)
                    return 1
                log_recent_run_events(client, rerun_id, limit=args.events_limit)
        client.logger.section("RERUN SUMMARY AND SURFACES")
        rerun_summary_outputs = scenario_summary_and_surfaces(client, args, rerun_id)
        client.logger.section("RERUN LINEAGE GRAPH")
        client.request_json("GET", f"/agentic/runs/{_quote(rerun_id)}/lineage", expected={200})
        client.logger.section("RERUN HISTORY AFTER MONITOR")
        scenario_run_history(client, args, tenant_id=tenant_id, domain_id=domain_id)
        rerun_summary = rerun_summary_outputs.get("summary") or {}
        rerun_tenant_id = str(rerun_summary.get("tenant_id") or tenant_id)
        rerun_domain_id = str(rerun_summary.get("domain_id") or domain_id)
        client.logger.section("RERUN TREND SURFACES")
        client.request_json(
            "GET",
            f"/data-quality/trends?{urllib.parse.urlencode({'tenant_id': rerun_tenant_id, 'domain_id': rerun_domain_id, 'run_id': rerun_id, 'limit': args.list_limit})}",
            expected={200},
        )
        client.request_json(
            "GET",
            f"/data-quality/trends/business-terms?{urllib.parse.urlencode({'tenant_id': rerun_tenant_id, 'domain_id': rerun_domain_id, 'run_id': rerun_id})}",
            expected={200},
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Demo runner for the Data Quality UI E2E API flow.",
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="API base URL.")
    parser.add_argument("--scenario", choices=["reload", "review", "completed", "enrichment", "evidence", "all"], default="all")
    parser.add_argument("--tenant-id", required=True, help="Tenant id.")
    parser.add_argument("--domain-id", default=DEFAULT_DOMAIN_ID, help="Domain id.")
    parser.add_argument("--run-id", help="Existing run id. If omitted, the script starts a deployment.")
    parser.add_argument("--connection-id", help="Connection id for new deployment.")
    parser.add_argument("--database", help="Database name for new deployment.")
    parser.add_argument("--schema-name", default="public", help="Schema name for new deployment.")
    parser.add_argument("--tables", nargs="*", default=list(DEFAULT_TABLES), help="Tables in scope for inline schema payload and tenant scope bootstrap.")
    parser.add_argument("--schema-payload-file", help="Optional schema payload JSON file for deployment if no saved scan exists.")
    parser.add_argument("--context-text", help="Inline deployment context text.")
    parser.add_argument("--context-file", help="Load deployment context text from file.")
    parser.add_argument("--context-ids", nargs="*", default=[], help="Optional stored context ids to activate during deployment.")
    parser.add_argument("--auto-bootstrap", action="store_true", help="Create/update tenant, tenant-domain binding, and tenant scope before starting a fresh deployment.")
    parser.add_argument("--pause-for-rule-review", action="store_true", help="Pause the deployment before rule execution when review is required.")
    parser.add_argument("--wait-for-state", action="store_true", help="Wait for queued/running deployment to reach completed/failed/awaiting_rule_review before continuing.")
    parser.add_argument("--wait-timeout-seconds", type=int, default=600, help="Maximum wait time for run status polling.")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="Polling interval for run status waits.")
    parser.add_argument("--events-limit", type=int, default=200, help="Event replay limit for reload flow.")
    parser.add_argument("--chat-limit", type=int, default=50, help="Chat replay limit for reload flow.")
    parser.add_argument("--list-limit", type=int, default=25, help="List API limit for summary/evidence/enrichment APIs.")
    parser.add_argument("--run-history-limit", type=int, default=100, help="Run history limit for /workspace/deployments.")
    parser.add_argument("--download-dir", default="/tmp/dq_ui_demo", help="Directory for downloaded Excel reports.")
    parser.add_argument("--log-file", help="Optional file to also write all logs to.")

    parser.add_argument("--review-action", choices=["none", "approve", "reject"], default="none", help="Optional rule-review action to apply to the first review item.")
    parser.add_argument(
        "--auto-approve-review-rules",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When review items exist, approve the whole queue and continue the run.",
    )
    parser.add_argument("--reviewed-by", default="ui:demo_user", help="Reviewer or approver identity for mutable calls.")
    parser.add_argument("--review-notes", help="Optional review notes.")
    parser.add_argument("--rule-condition-json-file", help="Optional condition_json patch file when approving a rule.")
    parser.add_argument("--rule-source-text", help="Optional edited rule source text.")
    parser.add_argument("--rule-severity", help="Optional severity patch for rule review.")
    parser.add_argument("--auto-resume", action="store_true", help="Call resume-after-rule-review after the review queue is resolved.")
    parser.add_argument("--wait-after-resume", action="store_true", help="Wait for resumed run to progress after auto-resume.")

    parser.add_argument("--opportunity-id", help="Specific enrichment opportunity id to use.")
    parser.add_argument("--proposal-id", help="Specific enrichment proposal id to use.")
    parser.add_argument("--enrichment-answer", choices=["none", "approve", "defer", "reject", "reopen"], default="none", help="Optional answer to apply to the first enrichment question.")
    parser.add_argument("--legacy-approve-research", action="store_true", help="Call the legacy approve-research endpoint instead of question-centric answer.")
    parser.add_argument("--max-records", type=int, default=500, help="Max records for enrichment proposal generation.")
    parser.add_argument("--apply-staging", action="store_true", help="Approve the selected proposal for staged overlay application.")
    parser.add_argument("--approval-scope", choices=["deterministic_only", "high_confidence", "all"], default="high_confidence")
    parser.add_argument("--min-confidence", type=float, default=0.85, help="Confidence threshold for staged application.")
    parser.add_argument("--staging-reason", help="Optional reason for staged overlay approval.")
    parser.add_argument("--include-rerun-monitor", action="store_true", help="After the fresh run flow, fetch run history and rerun an existing run with trend_mode=monitor.")
    parser.add_argument("--rerun-source-run-id", help="Optional source run id for rerun-as-monitor. Defaults to the latest run from run history, or the current run.")
    parser.add_argument(
        "--auto-handle-rerun-review",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When the rerun pauses for rule review, auto-approve and resume it using the same review flow.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.context_file:
        args.context_text = _load_text_file(args.context_file)
    if not args.context_text:
        args.context_text = DEFAULT_REVIEW_CONTEXT if args.scenario == "review" else DEFAULT_DEPLOY_CONTEXT
    if args.auto_approve_review_rules and args.scenario in {"review", "all"}:
        args.auto_resume = True
        args.wait_after_resume = True

    logger = DemoLogger(log_file=Path(args.log_file) if args.log_file else None)
    client = ApiClient(args.api_base, logger)
    try:
        return run_scenario(client, args)
    except KeyboardInterrupt:
        logger.write("Interrupted.")
        return 130
    except Exception as exc:
        logger.write(f"FAILED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
