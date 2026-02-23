#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


API_BASE = os.getenv("QUANTYX_API_BASE", "http://127.0.0.1:8787")
DOMAIN_ID = os.getenv("QUANTYX_DOMAIN", "manufacturing")
TENANT_ID = os.getenv("QUANTYX_TENANT", "x_mfg")
CONNECTION_ID = os.getenv("DEMO_CONNECTION_ID", "conn_demo")
DEMO_TABLES = [t.strip() for t in os.getenv("DEMO_TABLES", "").split(",") if t.strip()]
DEMO_CONTEXT_TEXT = os.getenv("DEMO_CONTEXT_TEXT", "")
DEMO_CONTEXT_TEXTS = os.getenv("DEMO_CONTEXT_TEXTS", "")
DEMO_CONTEXT_TITLES = os.getenv("DEMO_CONTEXT_TITLES", "")
DEMO_ACTIVE_CONTEXT_INDEX = int(os.getenv("DEMO_ACTIVE_CONTEXT_INDEX", "-1"))
DEMO_ACTIVE_CONTEXT_ALL = os.getenv("DEMO_ACTIVE_CONTEXT_ALL", "").lower() in {"1", "true", "yes"}
DEMO_CONTEXT_FILE = os.getenv("DEMO_CONTEXT_FILE", "")
DEMO_DBT_PROJECT = os.getenv("DEMO_DBT_PROJECT", "")
DEMO_DBT_PROFILE = os.getenv("DEMO_DBT_PROFILE", "default")
DEMO_DBT_TARGET = os.getenv("DEMO_DBT_TARGET", "dev")
DEMO_DBT_PROFILES_DIR = os.getenv("DEMO_DBT_PROFILES_DIR", "")
DEMO_SEMANTIC_CONTRACT = os.getenv("DEMO_SEMANTIC_CONTRACT", "false").lower() in {"1", "true", "yes"}

def _mask_payload(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    masked = json.loads(json.dumps(payload))
    for connection in masked.get("connections", []):
        if "password" in connection:
            connection["password"] = "******"
    return masked


def _log_request(method: str, path: str, payload: dict | None = None) -> None:
    print(f"Request start: {method} {path}")
    if payload is not None:
        print("Request payload:")
        print(json.dumps(_mask_payload(payload), indent=2))


def _log_response(response: dict) -> None:
    print("Response payload:")
    print(json.dumps(response, indent=2))
    print("Response end")


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
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def _wait_for_job_result(job_id: str, timeout_seconds: int = 180, poll_seconds: int = 3) -> dict:
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
            raise RuntimeError(
                f"Job {job_id} ended with status={status}: {result_payload.get('error_message')}"
            )
        if status == "completed":
            result_path = f"/jobs/{job_id}/result"
            _log_request("GET", result_path)
            result_payload = _request("GET", result_path)
            _log_response(result_payload)
            return result_payload.get("result") or {}
        if time.time() - start > timeout_seconds:
            raise RuntimeError(f"Timed out waiting for job {job_id}")
        time.sleep(poll_seconds)


def run_onboarding(
    *,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    db_name: str,
    db_schema: str,
    tables: list[str],
    context_text: str = "",
    context_file: str = "",
    dbt_project_path: str = "",
    dbt_profile: str = "default",
    dbt_target: str = "dev",
    dbt_profiles_dir: str = "",
) -> int:
    """
    Run the full onboarding flow for a tenant.
    context_file should be a local file path to a .txt or .docx file.
    """
    global TENANT_ID, DOMAIN_ID, DEMO_TABLES, DEMO_CONTEXT_TEXT, DEMO_CONTEXT_FILE
    global DEMO_DBT_PROJECT, DEMO_DBT_PROFILE, DEMO_DBT_TARGET, DEMO_DBT_PROFILES_DIR
    global CONNECTION_ID

    TENANT_ID = tenant_id
    DOMAIN_ID = domain_id
    CONNECTION_ID = connection_id
    DEMO_TABLES = tables
    DEMO_CONTEXT_TEXT = context_text
    DEMO_CONTEXT_FILE = context_file
    DEMO_DBT_PROJECT = dbt_project_path
    DEMO_DBT_PROFILE = dbt_profile
    DEMO_DBT_TARGET = dbt_target
    DEMO_DBT_PROFILES_DIR = dbt_profiles_dir

    os.environ["DEMO_DB_HOST"] = db_host
    os.environ["DEMO_DB_PORT"] = str(db_port)
    os.environ["DEMO_DB_USER"] = db_user
    os.environ["DEMO_DB_PASSWORD"] = db_password
    os.environ["DEMO_DB_NAME"] = db_name
    os.environ["DEMO_DB_SCHEMA"] = db_schema
    os.environ["DEMO_CONNECTION_ID"] = connection_id

    if DEMO_CONTEXT_FILE and not os.path.isfile(DEMO_CONTEXT_FILE):
        raise FileNotFoundError(f"context_file not found: {DEMO_CONTEXT_FILE}")

    return main()


def main() -> int:
    print("Usage:")
    print("  DEMO_SEMANTIC_CONTRACT=true to run semantic contract extraction")
    print("  DEMO_CONTEXT_TEXT/DEMO_CONTEXT_FILE for context ingestion")
    print("  DEMO_CONTEXT_TEXTS (use '||' to separate multiple contexts)")
    print("  DEMO_TABLES is required")
    print("== Onboarding Demo ==")
    print(f"API_BASE={API_BASE}")
    print(f"DOMAIN_ID={DOMAIN_ID}")
    print(f"TENANT_ID={TENANT_ID}")
    print(f"CONNECTION_ID={CONNECTION_ID}")
    print(f"DEMO_TABLES={DEMO_TABLES}")
    print(f"DEMO_CONTEXT_FILE={DEMO_CONTEXT_FILE}")
    print(f"DEMO_CONTEXT_TEXTS={DEMO_CONTEXT_TEXTS}")
    print(f"DEMO_CONTEXT_TITLES={DEMO_CONTEXT_TITLES}")
    print(f"DEMO_ACTIVE_CONTEXT_INDEX={DEMO_ACTIVE_CONTEXT_INDEX}")
    print(f"DEMO_ACTIVE_CONTEXT_ALL={DEMO_ACTIVE_CONTEXT_ALL}")
    print(f"DEMO_DBT_PROJECT={DEMO_DBT_PROJECT or '(auto)'}")
    print(f"DEMO_DBT_PROFILE={DEMO_DBT_PROFILE}")
    print(f"DEMO_DBT_TARGET={DEMO_DBT_TARGET}")
    print(f"DEMO_SEMANTIC_CONTRACT={DEMO_SEMANTIC_CONTRACT}")
    print("Log detail: verbose")

    if not DEMO_TABLES:
        print("DEMO_TABLES must be set (comma-separated table names).")
        return 1

    # 0) Optional admin dbt config seed
    if DEMO_DBT_PROJECT or DEMO_DBT_PROFILES_DIR:
        print("\n[0] Seed dbt config (admin)")
        dbt_config_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "dbt_project_path": DEMO_DBT_PROJECT or None,
            "profile_name": DEMO_DBT_PROFILE,
            "target_name": DEMO_DBT_TARGET,
            "profiles_dir": DEMO_DBT_PROFILES_DIR or None,
        }
        _log_request("POST", "/dbt/config", dbt_config_payload)
        dbt_config_response = _request("POST", "/dbt/config", dbt_config_payload)
        _log_response(dbt_config_response)

    # 1) Schema scan via connection
    print("\n[1] Scan connection")
    print("Step 1 start")
    scan_payload: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "connections": [
                {
                    "connection_id": CONNECTION_ID,
                    "db_type": "postgres",
                "host": os.getenv("DEMO_DB_HOST", "db.company.com"),
                "port": int(os.getenv("DEMO_DB_PORT", "5432")),
                "user": os.getenv("DEMO_DB_USER", "readonly_user"),
                "password": os.getenv("DEMO_DB_PASSWORD", "******"),
                "sample_rows": 100,
                "databases": [
                    {
                        "name": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
                        "schemas": [
                            {
                                "name": os.getenv("DEMO_DB_SCHEMA", "public"),
                                "tables": DEMO_TABLES,
                                "limit": 20,
                                "cursor": None,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    _log_request("POST", "/onboard/scan-connection", scan_payload)
    scan_response = _request("POST", "/onboard/scan-connection", scan_payload)
    _log_response(scan_response)
    print("Step 1 end")

    # 1c) List dbt scaffolds (auto-generated)
    print("\n[1c] List dbt scaffolds")
    scaffold_list_path = (
        f"/dbt/scaffold?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}"
    )
    _log_request("GET", scaffold_list_path)
    scaffold_list_response = _request("GET", scaffold_list_path)
    _log_response(scaffold_list_response)

    # 1b) Optional business context
    print("\n[1b] Business context ingestion")
    context_text = DEMO_CONTEXT_TEXT
    file_ids = []
    if DEMO_CONTEXT_FILE:
        print("DEMO_CONTEXT_FILE set; file content will be uploaded and linked.")

    if DEMO_CONTEXT_FILE:
        print("\n[1b-1] Upload context file")
        file_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "source_type": "business_context",
            "source_title": "Demo business context",
            "metadata": json.dumps(
                {
                    "columns": ["plant_name", "region_name"],
                }
            ),
        }
        boundary = "----quantyx-boundary"
        file_path = DEMO_CONTEXT_FILE
        try:
            with open(file_path, "rb") as fh:
                file_bytes = fh.read()
        except OSError as exc:
            print(f"Failed to read DEMO_CONTEXT_FILE: {exc}")
            return 1
        parts = []
        for key, value in file_payload.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n")
        filename = os.path.basename(file_path)
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        )
        body = "".join(parts).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            f"{API_BASE}/context/ingest-file",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        print("Request: POST /context/ingest-file")
        with urllib.request.urlopen(request, timeout=60) as resp:
            upload_response = json.loads(resp.read().decode("utf-8"))
        print("Response payload:")
        print(json.dumps(upload_response, indent=2))
        if upload_response.get("file_id"):
            file_ids.append(upload_response["file_id"])

    context_entries: list[dict[str, str]] = []
    if DEMO_CONTEXT_TEXTS:
        texts = [chunk.strip() for chunk in DEMO_CONTEXT_TEXTS.split("||") if chunk.strip()]
        titles = [chunk.strip() for chunk in DEMO_CONTEXT_TITLES.split("||") if chunk.strip()]
        for idx, text in enumerate(texts):
            title = titles[idx] if idx < len(titles) else f"Demo business context {idx + 1}"
            context_entries.append({"title": title, "text": text})
    elif context_text or file_ids:
        context_entries.append({"title": "Demo business context", "text": context_text})

    context_ids: list[str] = []
    for entry in context_entries:
        context_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "source_type": "business_context",
            "source_title": entry["title"],
            "raw_text": entry["text"],
            "file_ids": file_ids or None,
            "metadata": {
                "columns": ["plant_name", "region_name"],
            },
        }
        _log_request("POST", "/context/ingest", context_payload)
        context_response = _request("POST", "/context/ingest", context_payload)
        _log_response(context_response)
        context_id = context_response.get("context_id")
        if not context_id:
            continue
        context_ids.append(context_id)

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
        }
        _log_request("POST", "/context/extract/async", extract_payload)
        extract_job = _request("POST", "/context/extract/async", extract_payload)
        _log_response(extract_job)
        extract_job_id = extract_job.get("job_id")
        if not extract_job_id:
            raise RuntimeError("Context extract async job_id missing in response")
        extract_response = _wait_for_job_result(extract_job_id)
        extraction_types = sorted((extract_response.get("extractions") or {}).keys())
        if extraction_types:
            print(f"Extraction types: {extraction_types}")
        extraction_id = extract_response.get("extraction_id")
        list_path = (
            "/context"
            f"?tenant_id={TENANT_ID}"
        )
        _log_request("GET", list_path)
        list_response = _request("GET", list_path)
        _log_response(list_response)
        if extraction_id:
            extraction_path = (
                f"/context/extractions/{extraction_id}"
                f"?tenant_id={TENANT_ID}"
                f"&domain_id={DOMAIN_ID}"
            )
            _log_request("GET", extraction_path)
            extraction_response = _request("GET", extraction_path)
            _log_response(extraction_response)

            if extraction_id:
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
                    raise RuntimeError("Context apply async job_id missing in response")
                apply_response = _wait_for_job_result(apply_job_id)
                _log_response(apply_response)

    if context_ids:
        if DEMO_ACTIVE_CONTEXT_ALL:
            for context_id in context_ids:
                patch_path = f"/context/{context_id}?tenant_id={TENANT_ID}"
                patch_payload = {"status": "active"}
                _log_request("PATCH", patch_path, patch_payload)
                patch_response = _request("PATCH", patch_path, patch_payload)
                _log_response(patch_response)
        else:
            active_index = DEMO_ACTIVE_CONTEXT_INDEX
            if active_index < 0:
                active_index = len(context_ids) - 1
            if 0 <= active_index < len(context_ids):
                active_context_id = context_ids[active_index]
                patch_path = f"/context/{active_context_id}?tenant_id={TENANT_ID}"
                patch_payload = {"status": "active"}
                _log_request("PATCH", patch_path, patch_payload)
                patch_response = _request("PATCH", patch_path, patch_payload)
                _log_response(patch_response)
    else:
        print("No DEMO_CONTEXT_TEXT/DEMO_CONTEXT_FILE provided; skipping context ingestion.")

    # 1d) Optional semantic contract extraction + apply
    if DEMO_SEMANTIC_CONTRACT:
        print("\n[1d] Semantic contract extraction")
        semantic_payload = {
            "tenant_id": TENANT_ID,
            "industry": DOMAIN_ID,
            "inputs": {
                "raw_text": DEMO_CONTEXT_TEXT or "MFM = mass flow meter.",
                "tables_and_columns": "fact_dispatch: [bay_name, mfm_id, product_name]",
                "entity_types": ["organizational_unit", "mass_flow_meter", "product"],
                "metric_candidate": "metric_name=throughput_volume, columns=[mfm_volume, product_name]",
            },
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        }
        _log_request("POST", "/contracts/semantic/extract", semantic_payload)
        semantic_response = _request("POST", "/contracts/semantic/extract", semantic_payload)
        _log_response(semantic_response)
        contract_id = semantic_response.get("contract_id")
        if contract_id:
            apply_payload = {"tenant_id": TENANT_ID, "contract_id": contract_id}
            _log_request("POST", "/contracts/semantic/apply", apply_payload)
            apply_response = _request("POST", "/contracts/semantic/apply", apply_payload)
            _log_response(apply_response)
    else:
        print("DEMO_SEMANTIC_CONTRACT not enabled; skipping semantic contract extraction.")

    # Pull a schema/table set for downstream steps
    print("\n[1a] Extract schema/table list from scan")
    schemas = []
    tables = []
    for connection in scan_response.get("connections", []):
        print(f"Scan connection_id={connection.get('connection_id')}")
        for database in connection.get("databases", []):
            print(f"Scan database={database.get('name')}")
            for schema in database.get("schemas", []):
                print(f"Scan schema={schema.get('name')}")
                schemas.append(schema.get("name"))
                for table in schema.get("tables", []):
                    if table.get("table"):
                        tables.append(table["table"])
    print(f"Schemas extracted={len(schemas)}")
    print(f"Tables extracted={len(tables)}")
    if schemas:
        print(f"Schemas={schemas}")
    if tables:
        print(f"Tables (sample)={tables[:10]}")

    # 2) Ontology mapping (async)
    print("\n[2] Ontology mapping (async)")
    print("Step 2 start")
    map_payload = {
        "tenant_id": TENANT_ID,
    }
    map_path = "/onboard/map/async?use_llm=false"
    _log_request("POST", map_path, map_payload)
    map_job = _request("POST", map_path, map_payload)
    _log_response(map_job)
    map_job_id = map_job.get("job_id")
    if not map_job_id:
        raise RuntimeError("Map async job_id missing in response")
    map_response = _wait_for_job_result(map_job_id)
    map_tenant_id = map_response.get("tenant_id")
    if not map_tenant_id:
        raise RuntimeError("Map async result missing tenant_id")
    if map_tenant_id != TENANT_ID:
        raise RuntimeError(f"Map async tenant_id mismatch: expected={TENANT_ID}, got={map_tenant_id}")
    for idx, candidate in enumerate(map_response.get("candidates", []) or []):
        if not candidate.get("entity_id"):
            raise RuntimeError(f"Map async candidate missing entity_id at index={idx}")
    for idx, candidate in enumerate(map_response.get("low_confidence_candidates", []) or []):
        if not candidate.get("entity_id"):
            raise RuntimeError(f"Map async low_confidence_candidate missing entity_id at index={idx}")
    print(
        "Map async result validated: tenant_id + entity_id present in candidates and low_confidence_candidates"
    )

    # 2a) Fetch mapping run details
    mapping_id = map_response.get("mapping_id")
    if mapping_id:
        print("\n[2a] Mapping run details")
        mapping_path = f"/onboard/map/{mapping_id}?tenant_id={TENANT_ID}"
        _log_request("GET", mapping_path)
        mapping_response = _request("GET", mapping_path)
        _log_response(mapping_response)

    # 2b) Apply mapping run to canonical entity overrides
    if mapping_id:
        print("\n[2b] Apply mapping run")
        apply_payload = {
            "tenant_id": TENANT_ID,
            "selection_mode": "all",
            "status": "draft",
            "notes": "Applied by onboarding demo",
        }
        apply_path = f"/onboard/map/{mapping_id}/apply"
        _log_request("POST", apply_path, apply_payload)
        apply_response = _request("POST", apply_path, apply_payload)
        _log_response(apply_response)
    else:
        print("Mapping result has no mapping_id; skipping apply step.")

    # 2c) Mapping history
    print("\n[2c] Mapping history")
    map_history_path = f"/onboard/map/history?tenant_id={TENANT_ID}&limit=20"
    _log_request("GET", map_history_path)
    map_history_response = _request("GET", map_history_path)
    _log_response(map_history_response)
    print("Step 2 end")

    # 3) Entities + hierarchies (review / override)
    print("\n[3] Entities and hierarchies")
    print("Step 3 start")
    entities_path = f"/entities?tenant_id={TENANT_ID}"
    _log_request("GET", entities_path)
    entities_response = _request("GET", entities_path)
    _log_response(entities_response)

    # Optional: update hierarchy override using payload-based API
    if os.getenv("DEMO_UPDATE_HIERARCHY", "").lower() in {"1", "true", "yes"}:
        hierarchies = entities_response.get("hierarchies", []) or []
        if hierarchies:
            hierarchy_name = hierarchies[0].get("name")
            if hierarchy_name:
                hierarchy_payload = {
                    "tenant_id": TENANT_ID,
                    "connection_id": CONNECTION_ID,
                    "database": DB_NAME,
                    "schema": DB_SCHEMA,
                    "hierarchy_name": hierarchy_name,
                    "levels": hierarchies[0].get("levels", []),
                    "description": hierarchies[0].get("description"),
                    "status": "certified",
                }
                _log_request("PATCH", "/hierarchies", hierarchy_payload)
                _log_response(_request("PATCH", "/hierarchies", hierarchy_payload))
        else:
            print("No hierarchies available to update.")
    print("Step 3 end")

    # 4) Infer facts/dims (async)
    print("\n[4] Infer facts and dimensions (async)")
    print("Step 4 start")
    infer_payload = {
        "tenant_id": TENANT_ID,
        "time_column": None,
        "grain": "day",
        "use_llm": False,
    }
    infer_path = f"/onboard/infer-models/async?domain_id={DOMAIN_ID}"
    _log_request("POST", infer_path, infer_payload)
    infer_job = _request("POST", infer_path, infer_payload)
    _log_response(infer_job)
    infer_job_id = infer_job.get("job_id")
    if not infer_job_id:
        raise RuntimeError("Infer async job_id missing in response")
    infer_result = _wait_for_job_result(infer_job_id)
    print("Infer async result summary:")
    print(json.dumps(infer_result, indent=2))
    facts_path = f"/facts?tenant_id={TENANT_ID}"
    _log_request("GET", facts_path)
    facts_response = _request("GET", facts_path)
    _log_response(facts_response)
    dimensions_path = f"/dimensions?tenant_id={TENANT_ID}"
    _log_request("GET", dimensions_path)
    dimensions_response = _request("GET", dimensions_path)
    _log_response(dimensions_response)
    print("Step 4 end")

    # 5) Generate dbt manifest
    print("\n[5] Generate dbt manifest")
    manifest_payload = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "profile_name": DEMO_DBT_PROFILE,
        "target_name": DEMO_DBT_TARGET,
        "profiles_dir": DEMO_DBT_PROFILES_DIR or None,
    }
    if DEMO_DBT_PROJECT:
        manifest_payload["dbt_project_path"] = DEMO_DBT_PROJECT
    _log_request("POST", "/dbt/manifest/generate", manifest_payload)
    manifest_response = _request("POST", "/dbt/manifest/generate", manifest_payload)
    _log_response(manifest_response)

    # 6) Suggested metrics (persist, async)
    print("\n[6] Suggested metrics (persist, async)")
    print("Step 6 start")
    metrics_payload = {
        "tenant_id": TENANT_ID,
    }
    suggested_path = f"/metrics/suggested/async?domain_id={DOMAIN_ID}&persist=true"
    _log_request("POST", suggested_path, metrics_payload)
    metrics_job = _request("POST", suggested_path, metrics_payload)
    _log_response(metrics_job)
    metrics_job_id = metrics_job.get("job_id")
    if not metrics_job_id:
        raise RuntimeError("Metrics async job_id missing in response")
    suggested = _wait_for_job_result(metrics_job_id)
    print("Suggested metrics async result summary:")
    print(json.dumps(suggested, indent=2))
    print("Step 6 end")

    # 7) Metrics catalog (review)
    print("\n[7] Metrics catalog (review)")
    print("Step 7 start")
    metrics_path = (
        f"/metrics?tenant_id={TENANT_ID}"
        f"&domain_id={DOMAIN_ID}"
    )
    _log_request("GET", metrics_path)
    metrics_response = _request("GET", metrics_path)
    _log_response(metrics_response)
    print("Step 7 end")

    # 8) Promote first suggested metric (if present)
    print("\n[8] Promote a metric")
    print("Step 8 start")
    if suggested.get("measures"):
        measure = suggested["measures"][0]
        metric_id = f"{DOMAIN_ID}__{measure['table']}__{measure['column']}"
        patch_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "display_name": measure["column"].replace("_", " ").title(),
            "description": f"Auto-promoted metric for {measure['table']}.{measure['column']}",
            "status": "certified",
        }
        patch_path = f"/metrics/{metric_id}"
        _log_request("PATCH", patch_path, patch_payload)
        patch_response = _request("PATCH", patch_path, patch_payload)
        _log_response(patch_response)
    else:
        print("No measures found to promote.")
    print("Step 8 end")

    # 9) Apply contracts
    print("\n[9] Apply contracts")
    print("Step 9 start")
    _log_request("POST", "/contracts/apply", {})
    apply_response = _request("POST", "/contracts/apply", {})
    _log_response(apply_response)
    print("Step 9 end")

    # 10) Review summary
    print("\n[10] Review summary")
    print("Step 10 start")
    review_path = (
        f"/review/summary?tenant_id={TENANT_ID}"
        f"&domain_id={DOMAIN_ID}"
    )
    _log_request("GET", review_path)
    review_response = _request("GET", review_path)
    _log_response(review_response)
    print("Step 10 end")

    print("\n== Demo complete ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
