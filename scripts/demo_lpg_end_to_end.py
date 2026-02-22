#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
        _request(
            "PATCH",
            f"/hierarchies/{name}?tenant_id={TENANT_ID}&connection_id={CONNECTION_ID}&database={db_name}&schema={db_schema}",
            payload,
        )


def _certify_facts_dimensions() -> None:
    facts_resp = _request("GET", f"/facts?tenant_id={TENANT_ID}")
    for fact in facts_resp.get("facts", []):
        fact_id = fact.get("fact_id")
        if not fact_id:
            continue
        _request("PATCH", f"/facts/{fact_id}", {"status": "certified"})

    dims_resp = _request("GET", f"/dimensions?tenant_id={TENANT_ID}")
    for dim in dims_resp.get("dimensions", []):
        dim_id = dim.get("dimension_id")
        if not dim_id:
            continue
        _request("PATCH", f"/dimensions/{dim_id}", {"status": "certified"})


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
            _request("PATCH", f"/metrics/{metric_id}", {"tenant_id": TENANT_ID, "status": "certified"})
        cursor = resp.get("next_cursor")
        if not cursor:
            break


def _certify_glossary() -> None:
    _request("POST", "/glossary/certify", {"tenant_id": TENANT_ID, "domain_id": DOMAIN_ID})


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
        fact_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "table_name": fact_view,
            "grain": fact.get("grain") or "day",
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
    if should_run("ingest"):
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
    if should_run("extract"):
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
    if should_run("scan"):
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
    if should_run("apply"):
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
    if should_run("map"):
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
    if should_run("infer"):
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
    if should_run("metrics"):
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
        "sql": f"({{ ref('{fact_table}') }}.production_14_2kg * 14.2 + {{ ref('{fact_table}') }}.production_19kg * 19) / 1000",
        "grain": "day",
        "dimensions": ["sap_id", "plant_name"],
        "status": "suggested",
    }
    _log_request("POST", "/metrics", derived_metric)
    _log_response(_request("POST", "/metrics", derived_metric))

    # 9b) Certify artifacts (simulate UI review → certified)
    _certify_glossary()
    _certify_entities_hierarchies(db_name, db_schema)
    _certify_facts_dimensions()
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
