#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import psycopg2
import uuid


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
CONTEXT_PATH = ROOT / "artifacts" / "LPG" / "LPG_Semantic_Context.md"
SCHEMA_PATH = ROOT / "artifacts" / "LPG" / "LPG_SCHEMAS_WITH_DESCRIPTION.json"

API_BASE = os.getenv("QUANTYX_API_BASE", "http://127.0.0.1:8787")
TENANT_ID = "VC_101"
DOMAIN_ID = os.getenv("QUANTYX_DOMAIN", "lpg_production_distribution")
CONNECTION_ID = os.getenv("DEMO_CONNECTION_ID", "conn_lpg")


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _log_request(method: str, path: str, payload: dict | None = None) -> None:
    print(f"\n==> {method} {path}")
    if payload is not None:
        print(json.dumps(payload, indent=2))


def _log_response(response: dict) -> None:
    print("<== response")
    print(json.dumps(response, indent=2))


def _log_step_ids(label: str, **ids: str | None) -> None:
    payload = {k: v for k, v in ids.items() if v}
    if not payload:
        return
    print(f"\n==> {label} IDs")
    print(json.dumps(payload, indent=2))


def _validate_metric_sql(metric_name: str, sql: str) -> None:
    if "{{ ref('fact_" not in sql and '{{ ref("fact_' not in sql:
        raise RuntimeError(
            f"Metric '{metric_name}' sql must include {{ ref('fact_*') }}; got: {sql}"
        )


def _rewrite_metric_sql_with_fact_ref(sql: str) -> str | None:
    if "{{ ref('fact_" in sql or '{{ ref("fact_' in sql:
        return sql
    pattern = re.compile(r"(?:(?P<schema>[A-Za-z0-9_]+)\.)?(?P<table>[A-Za-z0-9_]+)\.(?P<col>[A-Za-z0-9_]+)")
    tables = set()
    for match in pattern.finditer(sql):
        table = match.group("table")
        if table and not table.startswith("fact_"):
            tables.add(table)
    if not tables:
        return None

    def _replace(match: re.Match) -> str:
        table = match.group("table")
        col = match.group("col")
        if not table:
            return match.group(0)
        if table.startswith("fact_"):
            return match.group(0)
        fact_table = f"fact_{table}"
        return f"{{{{ ref('{fact_table}') }}}}.{col}"

    rewritten = pattern.sub(_replace, sql)
    if rewritten == sql:
        return None
    return rewritten


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def _request_with_logging(
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    allow_404: bool = False,
) -> dict:
    _log_request(method, path, payload)
    try:
        resp = _request(method, path, payload)
        _log_response(resp)
        return resp
    except RuntimeError as exc:
        print(f"REQUEST FAILED: {method} {path}")
        if payload is not None:
            print("Payload:")
            print(json.dumps(payload, indent=2))
        print(f"Error: {exc}")
        if allow_404 and (" 404 " in str(exc) or "404" in str(exc)):
            return {}
        raise


def _list_jobs(job_type: str, status: str = "completed", limit: int = 1) -> list[dict]:
    path = f"/jobs?tenant_id={TENANT_ID}&job_type={job_type}&status={status}&limit={limit}"
    _log_request("GET", path)
    resp = _request("GET", path)
    _log_response(resp)
    jobs = resp.get("jobs", []) or []
    filtered = []
    for job in jobs:
        domain_id = job.get("domain_id")
        if domain_id and domain_id != DOMAIN_ID:
            continue
        filtered.append(job)
    return filtered


def _get_job_result(job_id: str) -> dict:
    result_path = f"/jobs/{job_id}/result"
    _log_request("GET", result_path)
    result_payload = _request("GET", result_path)
    _log_response(result_payload)
    return result_payload.get("result") or {}


def _extraction_exists(extraction_id: str) -> bool:
    if not extraction_id:
        return False
    try:
        _log_request("GET", f"/context/extractions/{extraction_id}?tenant_id={TENANT_ID}")
        _log_response(_request("GET", f"/context/extractions/{extraction_id}?tenant_id={TENANT_ID}"))
        return True
    except RuntimeError:
        return False


def _auto_resume_ids() -> dict[str, str]:
    ids: dict[str, str] = {}
    try:
        context_resp = _request("GET", f"/context?tenant_id={TENANT_ID}&limit=1")
        entries = context_resp.get("entries", []) or []
        if entries:
            context_id = entries[0].get("context_id")
            if context_id:
                ids["context_id"] = context_id
    except RuntimeError as exc:
        print(f"Auto-resume: unable to list context ({exc}); continuing without context_id.")

    try:
        extract_jobs = _list_jobs("context_extract")
        if extract_jobs:
            job_id = extract_jobs[0].get("job_id")
            if job_id:
                ids["extract_job_id"] = job_id
                result = _get_job_result(job_id)
                extraction_id = result.get("extraction_id")
                if extraction_id and _extraction_exists(extraction_id):
                    ids["extraction_id"] = extraction_id
                result_context_id = result.get("context_id")
                if result_context_id and "context_id" not in ids:
                    ids["context_id"] = result_context_id
    except RuntimeError as exc:
        print(f"Auto-resume: unable to list context_extract jobs ({exc}); continuing.")

    for job_type, key in [
        ("scan_connection", "scan_job_id"),
        ("context_apply", "apply_job_id"),
        ("map_entities", "map_job_id"),
        ("infer_models", "infer_job_id"),
        ("metrics_suggested", "metrics_job_id"),
    ]:
        try:
            jobs = _list_jobs(job_type)
            if jobs:
                job_id = jobs[0].get("job_id")
                if job_id:
                    ids[key] = job_id
        except RuntimeError as exc:
            print(f"Auto-resume: unable to list {job_type} jobs ({exc}); continuing.")

    return ids


def _certify_entities_hierarchies(db_name: str, db_schema: str) -> None:
    entities_resp = _request("GET", f"/entities?tenant_id={TENANT_ID}")
    for entity in entities_resp.get("entities", []):
        entity_id = entity.get("entity_id")
        if not entity_id:
            continue
        payload = {
            "description": entity.get("description"),
            "join_key": entity.get("join_key"),
            "examples": entity.get("examples"),
            "status": "certified",
        }
        _request(
            "PATCH",
            f"/entities/{entity_id}?tenant_id={TENANT_ID}&connection_id={CONNECTION_ID}&database={db_name}&schema={db_schema}",
            payload,
        )

    hier_resp = _request(
        "GET", f"/hierarchies?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}"
    )
    for hierarchy in hier_resp.get("hierarchies", []):
        name = hierarchy.get("name")
        if not name:
            continue
        payload = {
            "levels": hierarchy.get("levels", []),
            "description": hierarchy.get("description"),
            "context_id": hierarchy.get("context_id"),
            "hierarchy_group": hierarchy.get("hierarchy_group"),
            "status": "certified",
        }
        try:
            hierarchy_payload = {
                "tenant_id": TENANT_ID,
                "connection_id": CONNECTION_ID,
                "database": db_name,
                "schema": db_schema,
                "hierarchy_name": name,
                **payload,
            }
            _request_with_logging(
                "PATCH",
                "/hierarchies",
                hierarchy_payload,
            )
        except RuntimeError as exc:
            message = str(exc)
            if " 404 " in message or "404" in message:
                print(f"Skipping missing hierarchy: {name}")
                continue
            raise


def _certify_facts_dimensions() -> None:
    facts_resp = _request("GET", f"/facts?tenant_id={TENANT_ID}")
    for fact in facts_resp.get("facts", []):
        fact_id = fact.get("fact_id")
        if not fact_id:
            continue
        measures = fact.get("measures") or []
        if not measures:
            print(f"Skipping fact without measures: {fact_id}")
            continue
        try:
            _request_with_logging("PATCH", f"/facts/{fact_id}", {"status": "certified"})
        except RuntimeError as exc:
            print(f"Failed to certify fact {fact_id}: {exc}")

    dims_resp = _request("GET", f"/dimensions?tenant_id={TENANT_ID}")
    for dim in dims_resp.get("dimensions", []):
        dim_id = dim.get("dimension_id")
        if not dim_id:
            continue
        try:
            _request_with_logging("PATCH", f"/dimensions/{dim_id}", {"status": "certified"})
        except RuntimeError as exc:
            print(f"Failed to certify dimension {dim_id}: {exc}")


def _certify_metrics() -> None:
    cursor = None
    while True:
        path = f"/metrics?tenant_id={TENANT_ID}"
        if cursor:
            path += f"&cursor={cursor}"
        resp = _request("GET", path)
        for metric in resp.get("metrics", []):
            metric_id = metric.get("metric_id")
            if not metric_id:
                continue
            sql = (metric.get("sql") or "").strip()
            if not sql:
                print(f"Skipping metric with empty sql: {metric_id}")
                continue
            if "{{ ref('fact_" not in sql and '{{ ref("fact_' not in sql:
                rewritten = _rewrite_metric_sql_with_fact_ref(sql)
                if not rewritten:
                    print(f"Skipping metric without fact ref: {metric_id}")
                    continue
                print(f"Rewriting metric sql to use fact ref: {metric_id}")
                _request_with_logging(
                    "PATCH",
                    f"/metrics/{metric_id}",
                    {"tenant_id": TENANT_ID, "sql": rewritten},
                    allow_404=True,
                )
            resp = _request_with_logging(
                "PATCH",
                f"/metrics/{metric_id}",
                {"tenant_id": TENANT_ID, "status": "certified"},
                allow_404=True,
            )
            if not resp:
                print(f"Skipping missing metric: {metric_id}")
                continue
        cursor = resp.get("next_cursor")
        if not cursor:
            break


def _ensure_production_mt_dimensions() -> None:
    cursor = None
    while True:
        path = f"/metrics?tenant_id={TENANT_ID}"
        if cursor:
            path += f"&cursor={cursor}"
        resp = _request("GET", path)
        for metric in resp.get("metrics", []):
            metric_id = metric.get("metric_id")
            metric_name = (metric.get("metric_name") or "").lower()
            display_name = (metric.get("display_name") or "").lower()
            if metric_name != "production_mt" and display_name != "production (mt)":
                continue
            dimensions = metric.get("dimensions") or []
            if "process_date" in dimensions:
                continue
            new_dimensions = list(dict.fromkeys(dimensions + ["process_date"]))
            print(f"Updating production_mt dimensions: {metric_id}")
            _request_with_logging(
                "PATCH",
                f"/metrics/{metric_id}",
                {"tenant_id": TENANT_ID, "dimensions": new_dimensions},
                allow_404=True,
            )
        cursor = resp.get("next_cursor")
        if not cursor:
            break


def _deprecate_empty_sql_metrics() -> None:
    cursor = None
    while True:
        path = f"/metrics?tenant_id={TENANT_ID}"
        if cursor:
            path += f"&cursor={cursor}"
        resp = _request("GET", path)
        for metric in resp.get("metrics", []):
            metric_id = metric.get("metric_id")
            if not metric_id:
                continue
            sql = (metric.get("sql") or "").strip()
            if sql:
                continue
            print(f"Deprecating metric with empty sql: {metric_id}")
            _request_with_logging(
                "PATCH",
                f"/metrics/{metric_id}",
                {"tenant_id": TENANT_ID, "status": "deprecated"},
                allow_404=True,
            )
        cursor = resp.get("next_cursor")
        if not cursor:
            break


def _certify_glossary() -> None:
    _request_with_logging("POST", "/glossary/certify", {"tenant_id": TENANT_ID, "domain_id": DOMAIN_ID})


def _ensure_fact_view(
    db_host: str,
    db_port: int,
    db_name: str,
    db_user: str,
    db_password: str,
    db_schema: str,
    source_table: str,
) -> str:
    fact_table = source_table if source_table.startswith("fact_") else f"fact_{source_table}"
    sql = f"""
        CREATE OR REPLACE VIEW {db_schema}.{fact_table} AS
        SELECT * FROM {db_schema}.{source_table}
    """
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                """
                INSERT INTO public.quantyx_fact_views_registry (
                  view_id,
                  tenant_id,
                  domain_id,
                  connection_id,
                  database_name,
                  schema_name,
                  view_name,
                  source_table
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [
                    f"fview_{uuid.uuid4().hex[:10]}",
                    TENANT_ID,
                    DOMAIN_ID,
                    CONNECTION_ID,
                    db_name,
                    db_schema,
                    fact_table,
                    source_table,
                ],
            )
        conn.commit()
    finally:
        conn.close()
    return fact_table


def _register_inferred_facts(
    infer_result: dict,
    db_host: str,
    db_port: int,
    db_name: str,
    db_user: str,
    db_password: str,
    db_schema: str,
) -> dict[str, str]:
    facts = infer_result.get("facts", []) or []
    table_to_fact: dict[str, str] = {}
    for fact in facts:
        table_name = fact.get("name") or fact.get("table_name")
        if not table_name:
            continue
        measures = fact.get("measures") or []
        if not measures:
            print(f"Skipping fact without measures: {table_name}")
            continue
        fact_view = _ensure_fact_view(
            db_host, db_port, db_name, db_user, db_password, db_schema, table_name
        )
        table_to_fact[table_name] = fact_view
        grain = fact.get("grain") or "day"
        if isinstance(grain, list):
            grain = ", ".join([str(item) for item in grain if item])
        fact_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "table_name": fact_view,
            "grain": grain,
            "time_column": fact.get("time_column"),
            "measures": measures,
            "dimensions": fact.get("dimensions", []),
            "description": fact.get("description"),
            "status": "certified",
        }
        _log_request("POST", "/facts", fact_payload)
        _log_response(_request("POST", "/facts", fact_payload))
    return table_to_fact


def _register_inferred_dimensions(infer_result: dict) -> None:
    dims = infer_result.get("dimensions", []) or []
    for dim in dims:
        name = dim.get("name")
        if not name:
            continue
        keys = dim.get("keys") or []
        attributes = dim.get("attributes") or []
        if not keys and attributes:
            keys = [attributes[0]]
        if not keys:
            continue
        payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "name": name,
            "keys": keys,
            "attributes": attributes,
            "description": dim.get("description"),
            "status": "certified",
        }
        _log_request("POST", "/dimensions", payload)
        _log_response(_request("POST", "/dimensions", payload))


def _wait_for_job(job_id: str, timeout_seconds: int | None = None, poll_seconds: int | None = None) -> dict:
    timeout_seconds = timeout_seconds or int(os.getenv("JOB_TIMEOUT_SEC", "12000"))
    poll_seconds = poll_seconds or int(os.getenv("JOB_POLL_SEC", "4"))
    start = time.time()
    while True:
        status_path = f"/jobs/{job_id}"
        _log_request("GET", status_path)
        status_payload = _request("GET", status_path)
        _log_response(status_payload)
        status = status_payload.get("status")
        if status in {"failed", "canceled"}:
            result_path = f"/jobs/{job_id}/result"
            _log_request("GET", result_path)
            result_payload = _request("GET", result_path)
            _log_response(result_payload)
            raise RuntimeError(f"Job {job_id} failed: {result_payload.get('error_message')}")
        if status == "completed":
            result_path = f"/jobs/{job_id}/result"
            _log_request("GET", result_path)
            result_payload = _request("GET", result_path)
            _log_response(result_payload)
            return result_payload.get("result") or {}
        if status == "queued":
            print(".. job still queued (worker may be offline or busy)")
        if time.time() - start > timeout_seconds:
            raise RuntimeError(f"Timed out waiting for job {job_id}")
        time.sleep(poll_seconds)


def _load_tables() -> list[str]:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    tables = []
    for entry in data:
        table_ctx = entry.get("table_context") or {}
        name = table_ctx.get("table_name")
        if name:
            tables.append(name)
    return tables


def main() -> int:
    parser = argparse.ArgumentParser(description="LPG demo end-to-end runner")
    parser.add_argument(
        "--resume-from",
        default="start",
        choices=["start", "ingest", "extract", "scan", "apply", "map", "infer", "metrics", "ask"],
        help="Resume from a specific phase (requires RESUME_* env vars for skipped steps).",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip async metrics suggestion step if already generated.",
    )
    parser.add_argument(
        "--auto-resume",
        action="store_true",
        help="Enable auto-resume by querying existing context/jobs.",
    )
    args = parser.parse_args()
    resume_from = args.resume_from
    phase_order = ["ingest", "extract", "scan", "apply", "map", "infer", "metrics", "ask"]
    resume_index = -1 if resume_from == "start" else phase_order.index(resume_from)

    def should_run(phase: str) -> bool:
        return resume_from == "start" or phase_order.index(phase) >= resume_index

    _load_env(ENV_PATH)
    if not CONTEXT_PATH.exists():
        print(f"Missing context file: {CONTEXT_PATH}")
        return 1

    tables = _load_tables()
    if not tables:
        print("No tables found in LPG_SCHEMAS_WITH_DESCRIPTION.json")
        return 1

    db_host = os.getenv("DEMO_DB_HOST", os.getenv("DB_HOST", "127.0.0.1"))
    db_port = int(os.getenv("DEMO_DB_PORT", os.getenv("DB_PORT", "5432")))
    db_name = os.getenv("DEMO_DB_NAME", os.getenv("DB_NAME", "prod_warehouse"))
    db_user = os.getenv("DEMO_DB_USER", os.getenv("DB_USER", "readonly_user"))
    db_password = os.getenv("DEMO_DB_PASSWORD", os.getenv("DB_PASSWORD", "password"))
    db_schema = os.getenv("DEMO_DB_SCHEMA", os.getenv("DB_SCHEMA", "public"))

    print("== LPG Demo End-to-End ==")
    print(f"API_BASE={API_BASE}")
    print(f"TENANT_ID={TENANT_ID}")
    print(f"DOMAIN_ID={DOMAIN_ID}")
    print(f"CONNECTION_ID={CONNECTION_ID}")
    print(f"DB_HOST={db_host}")
    print(f"DB_PORT={db_port}")
    print(f"DB_NAME={db_name}")
    print(f"DB_SCHEMA={db_schema}")
    print(f"Tables={tables}")

    context_text = CONTEXT_PATH.read_text(encoding="utf-8")

    # 1) Context ingest
    context_id = os.getenv("RESUME_CONTEXT_ID")
    extraction_id = os.getenv("RESUME_EXTRACTION_ID")
    scan_job_id = None
    apply_job_id = None
    map_job_id = None
    infer_job_id = None
    metrics_job_id = None
    auto_ids: dict[str, str] = {}
    if args.auto_resume:
        auto_ids = _auto_resume_ids()
        if not context_id:
            context_id = auto_ids.get("context_id")
        if not extraction_id:
            extraction_id = auto_ids.get("extraction_id")
        scan_job_id = auto_ids.get("scan_job_id")
        apply_job_id = auto_ids.get("apply_job_id")
        map_job_id = auto_ids.get("map_job_id")
        infer_job_id = auto_ids.get("infer_job_id")
        metrics_job_id = auto_ids.get("metrics_job_id")
    if should_run("ingest") and context_id and args.auto_resume:
        _log_step_ids("Context Ingest (auto-resume)", context_id=context_id)
    elif should_run("ingest"):
        ingest_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "source_type": "business_context",
            "source_title": "LPG Semantic Context v2",
            "raw_text": context_text,
            "metadata": {
                "connection_id": CONNECTION_ID,
                "database": db_name,
                "schema": db_schema,
                "tables": tables,
            },
        }
        _log_request("POST", "/context/ingest", ingest_payload)
        ingest_response = _request("POST", "/context/ingest", ingest_payload)
        _log_response(ingest_response)
        context_id = ingest_response.get("context_id")
        if not context_id:
            print("Missing context_id in ingest response")
            return 1
        _log_step_ids("Context Ingest", context_id=context_id)
    elif not context_id:
        raise RuntimeError("RESUME_CONTEXT_ID is required when resuming past ingest")
    else:
        _log_step_ids("Context Ingest (resumed)", context_id=context_id)

    # 1a) Set tenant domain + scope (required by context/apply and scoped APIs)
    _log_request("POST", "/tenant/domain", {"tenant_id": TENANT_ID, "domain_id": DOMAIN_ID})
    _log_response(_request("POST", "/tenant/domain", {"tenant_id": TENANT_ID, "domain_id": DOMAIN_ID}))

    scope_payload = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "connection_id": CONNECTION_ID,
        "database": db_name,
        "schema": db_schema,
        "tables": tables,
    }
    _log_request("POST", "/tenant/scope", scope_payload)
    _log_response(_request("POST", "/tenant/scope", scope_payload))

    # 2) Context extract (async)
    if should_run("extract") and extraction_id and args.auto_resume:
        _log_step_ids(
            "Context Extract (auto-resume)",
            context_id=context_id,
            extraction_id=extraction_id,
            extract_job_id=auto_ids.get("extract_job_id"),
        )
    elif should_run("extract"):
        extract_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "context_id": context_id,
            "extraction_types": [
                "abbreviations",
                "synonyms",
                "hierarchies",
                "metric_candidates",
                "question_intents",
            ],
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "mode": "parallel",
        }
        _log_request("POST", "/context/extract/async", extract_payload)
        extract_job = _request("POST", "/context/extract/async", extract_payload)
        _log_response(extract_job)
        extract_job_id = extract_job.get("job_id")
        if not extract_job_id:
            raise RuntimeError("context_extract job_id missing")
        extract_result = _wait_for_job(extract_job_id)
        extraction_id = extract_result.get("extraction_id")
        if not extraction_id:
            print("Missing extraction_id in extract job result")
            return 1
        _log_step_ids(
            "Context Extract",
            context_id=context_id,
            extract_job_id=extract_job_id,
            extraction_id=extraction_id,
        )
    elif not extraction_id:
        raise RuntimeError("RESUME_EXTRACTION_ID is required when resuming past extract")
    else:
        _log_step_ids(
            "Context Extract (resumed)",
            context_id=context_id,
            extraction_id=extraction_id,
        )

    # 3) Scan connection (async) - registers connection + scopes
    if should_run("scan") and scan_job_id and args.auto_resume:
        _log_step_ids(
            "Scan Connection (auto-resume)",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
        )
    elif should_run("scan"):
        scan_payload: dict[str, Any] = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
        "connections": [
            {
                "connection_id": CONNECTION_ID,
                "db_type": "postgres",
                "host": db_host,
                "port": db_port,
                "user": db_user,
                "password": db_password,
                "sample_rows": 100,
                "databases": [
                    {
                        "name": db_name,
                        "schemas": [
                            {
                                "name": db_schema,
                                "tables": tables,
                                "limit": 20,
                            }
                        ],
                    }
                ],
            }
        ],
    }
        _log_request("POST", "/onboard/scan-connection/async?generate_dbt=true", scan_payload)
        scan_job = _request("POST", "/onboard/scan-connection/async?generate_dbt=true", scan_payload)
        _log_response(scan_job)
        scan_job_id = scan_job.get("job_id")
        if not scan_job_id:
            raise RuntimeError("scan_connection job_id missing")
        _wait_for_job(scan_job_id)
        _log_step_ids(
            "Scan Connection",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
        )

    # 4) Set tenant domain + scope (required by context/apply and scoped APIs)
    _log_request("POST", "/tenant/domain", {"tenant_id": TENANT_ID, "domain_id": DOMAIN_ID})
    _log_response(_request("POST", "/tenant/domain", {"tenant_id": TENANT_ID, "domain_id": DOMAIN_ID}))

    scope_payload = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "connection_id": CONNECTION_ID,
        "database": db_name,
        "schema": db_schema,
        "tables": tables,
    }
    _log_request("POST", "/tenant/scope", scope_payload)
    _log_response(_request("POST", "/tenant/scope", scope_payload))

    # 5) Context apply (async)
    if should_run("apply") and apply_job_id and args.auto_resume:
        _log_step_ids(
            "Context Apply (auto-resume)",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
        )
    elif should_run("apply"):
        apply_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "extraction_id": extraction_id,
            "apply": {"entities": True, "hierarchies": True, "glossary": True, "metrics": True},
        }
        _log_request("POST", "/context/apply/async", apply_payload)
        apply_job = _request("POST", "/context/apply/async", apply_payload)
        _log_response(apply_job)
        apply_job_id = apply_job.get("job_id")
        if not apply_job_id:
            raise RuntimeError("context_apply job_id missing")
        _wait_for_job(apply_job_id)
        _log_step_ids(
            "Context Apply",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
        )

    # 6) Entity mapping (async)
    if should_run("map") and map_job_id and args.auto_resume:
        _log_step_ids(
            "Entity Map (auto-resume)",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
            map_job_id=map_job_id,
        )
    elif should_run("map"):
        map_path = f"/onboard/map/async?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}&use_llm=true"
        map_payload = {
            "tenant_id": TENANT_ID,
            "connection_id": CONNECTION_ID,
            "database": db_name,
            "schema": db_schema,
            "tables": tables,
        }
        _log_request("POST", map_path, map_payload)
        map_job = _request("POST", map_path, map_payload)
        _log_response(map_job)
        map_job_id = map_job.get("job_id")
        if not map_job_id:
            raise RuntimeError("map_entities job_id missing")
        _wait_for_job(map_job_id)
        _log_step_ids(
            "Entity Map",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
            map_job_id=map_job_id,
        )

    # 7) Infer models (async)
    infer_result: dict[str, Any] = {}
    resume_infer_job_id = os.getenv("RESUME_INFER_JOB_ID")
    if should_run("infer") and resume_infer_job_id:
        infer_job_id = resume_infer_job_id
        infer_result = _wait_for_job(infer_job_id)
        _log_step_ids(
            "Infer Models (resumed)",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
            map_job_id=map_job_id,
            infer_job_id=infer_job_id,
        )
    elif should_run("infer") and infer_job_id and args.auto_resume:
        infer_result = _get_job_result(infer_job_id)
        _log_step_ids(
            "Infer Models (auto-resume)",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
            map_job_id=map_job_id,
            infer_job_id=infer_job_id,
        )
    elif should_run("infer"):
        infer_path = f"/onboard/infer-models/async?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}"
        infer_payload = {
            "tenant_id": TENANT_ID,
            "connection_id": CONNECTION_ID,
            "database": db_name,
            "schema": db_schema,
            "tables": tables,
            "use_llm": True,
        }
        _log_request("POST", infer_path, infer_payload)
        infer_job = _request("POST", infer_path, infer_payload)
        _log_response(infer_job)
        infer_job_id = infer_job.get("job_id")
        if not infer_job_id:
            raise RuntimeError("infer_models job_id missing")
        infer_result = _wait_for_job(infer_job_id)
        _log_step_ids(
            "Infer Models",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
            map_job_id=map_job_id,
            infer_job_id=infer_job_id,
        )

    # 8) Suggested metrics (async)
    if should_run("metrics") and metrics_job_id and args.auto_resume:
        _log_step_ids(
            "Metrics Suggested (auto-resume)",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
            map_job_id=map_job_id,
            infer_job_id=infer_job_id,
            metrics_job_id=metrics_job_id,
        )
    elif should_run("metrics") and not args.skip_metrics:
        metrics_path = f"/metrics/suggested/async?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}&persist=true"
        metrics_payload = {
            "tenant_id": TENANT_ID,
            "connection_id": CONNECTION_ID,
            "database": db_name,
            "schema": db_schema,
            "tables": [
                "lpg_plant_operations",
                "lpg_todays_cdcms_sales_summary",
                "lpg_monthly_cdcms_sales_summary",
                "lpg_cdcms_subsidy_failure_statistics",
            ],
        }
        _log_request("POST", metrics_path, metrics_payload)
        metrics_job = _request("POST", metrics_path, metrics_payload)
        _log_response(metrics_job)
        metrics_job_id = metrics_job.get("job_id")
        if not metrics_job_id:
            raise RuntimeError("metrics_suggested job_id missing")
        _wait_for_job(metrics_job_id)
        _log_step_ids(
            "Metrics Suggested",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
            map_job_id=map_job_id,
            infer_job_id=infer_job_id,
            metrics_job_id=metrics_job_id,
        )
    elif should_run("metrics") and args.skip_metrics:
        _log_step_ids(
            "Metrics Suggested (skipped)",
            context_id=context_id,
            extraction_id=extraction_id,
            scan_job_id=scan_job_id,
            apply_job_id=apply_job_id,
            map_job_id=map_job_id,
            infer_job_id=infer_job_id,
            metrics_job_id=os.getenv("RESUME_METRICS_JOB_ID"),
        )

    # 9) Create fact views + register inferred facts (certified)
    table_to_fact = _register_inferred_facts(
        infer_result,
        db_host,
        db_port,
        db_name,
        db_user,
        db_password,
        db_schema,
    )
    _register_inferred_dimensions(infer_result)

    # 9b) Add derived metrics (suggested first; will certify later)
    production_fact = None
    for fact in (infer_result.get("facts") or []):
        measures = set(fact.get("measures") or [])
        if {"production_14_2kg", "production_19kg"}.issubset(measures):
            production_fact = fact.get("name") or fact.get("table_name")
            break
    fact_table = table_to_fact.get(production_fact or "", "fact_lpg_plant_operations")
    derived_metric = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "metric_name": "production_mt",
        "display_name": "Production (MT)",
        "type": "sum",
        "sql": f"({{{{ ref('{fact_table}') }}}}.production_14_2kg * 14.2 + {{{{ ref('{fact_table}') }}}}.production_19kg * 19) / 1000",
        "grain": "day",
        "dimensions": ["sap_id", "plant_name", "process_date"],
        "status": "suggested",
    }
    _validate_metric_sql(derived_metric["metric_name"], derived_metric["sql"])
    _log_request("POST", "/metrics", derived_metric)
    _log_response(_request("POST", "/metrics", derived_metric))

    # 9b) Certify artifacts (simulate UI review → certified)
    _certify_glossary()
    _certify_entities_hierarchies(db_name, db_schema)
    _certify_facts_dimensions()
    _ensure_production_mt_dimensions()
    _deprecate_empty_sql_metrics()
    _certify_metrics()

    # 9c) Reload contracts/catalog
    _log_request("POST", "/contracts/apply", {"tenant_id": TENANT_ID})
    _log_response(_request("POST", "/contracts/apply", {"tenant_id": TENANT_ID}))

    # 10) Ask What
    ask_what = {"tenant_id": TENANT_ID, "question": "What is total LPG production (MT) by plant last week?"}
    _log_request("POST", "/query", ask_what)
    ask_what_response = _request("POST", "/query", ask_what)
    _log_response(ask_what_response)

    # 11) Ask Why
    ask_why = {"tenant_id": TENANT_ID, "question": "Why is production down last week at Secunderabad plant?"}
    _log_request("POST", "/query", ask_why)
    ask_why_response = _request("POST", "/query", ask_why)
    _log_response(ask_why_response)

    print("\n== Demo complete ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
