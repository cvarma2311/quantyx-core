#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


API_BASE = os.getenv("QUANTYX_API_BASE", "http://127.0.0.1:8787")
DOMAIN_ID = os.getenv("QUANTYX_DOMAIN", "manufacturing")
TENANT_ID = os.getenv("QUANTYX_TENANT", "x_mfg")
CONNECTION_ID = os.getenv("DEMO_CONNECTION_ID", "conn_demo")
DEMO_TABLES = [t.strip() for t in os.getenv("DEMO_TABLES", "").split(",") if t.strip()]
DEMO_CONTEXT_TEXT = os.getenv("DEMO_CONTEXT_TEXT", "")
DEMO_CONTEXT_FILE = os.getenv("DEMO_CONTEXT_FILE", "")
DEMO_DBT_PROJECT = os.getenv("DEMO_DBT_PROJECT", "")
DEMO_DBT_PROFILE = os.getenv("DEMO_DBT_PROFILE", "default")
DEMO_DBT_TARGET = os.getenv("DEMO_DBT_TARGET", "dev")
DEMO_DBT_PROFILES_DIR = os.getenv("DEMO_DBT_PROFILES_DIR", "")

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
    print("== Onboarding Demo ==")
    print(f"API_BASE={API_BASE}")
    print(f"DOMAIN_ID={DOMAIN_ID}")
    print(f"TENANT_ID={TENANT_ID}")
    print(f"CONNECTION_ID={CONNECTION_ID}")
    print(f"DEMO_TABLES={DEMO_TABLES}")
    print(f"DEMO_CONTEXT_FILE={DEMO_CONTEXT_FILE}")
    print(f"DEMO_DBT_PROJECT={DEMO_DBT_PROJECT or '(auto)'}")
    print(f"DEMO_DBT_PROFILE={DEMO_DBT_PROFILE}")
    print(f"DEMO_DBT_TARGET={DEMO_DBT_TARGET}")
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
            "connection_id": CONNECTION_ID,
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
        f"/dbt/scaffold?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}&connection_id={CONNECTION_ID}"
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
                    "connection_id": CONNECTION_ID,
                    "database": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
                    "schema": os.getenv("DEMO_DB_SCHEMA", "public"),
                    "tables": DEMO_TABLES,
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

    if context_text or file_ids:
        context_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "source_type": "business_context",
            "source_title": "Demo business context",
            "raw_text": context_text,
            "file_ids": file_ids or None,
            "metadata": {
                "connection_id": CONNECTION_ID,
                "database": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
                "schema": os.getenv("DEMO_DB_SCHEMA", "public"),
                "tables": DEMO_TABLES,
            },
        }
        _log_request("POST", "/context/ingest", context_payload)
        context_response = _request("POST", "/context/ingest", context_payload)
        _log_response(context_response)
        context_id = context_response.get("context_id")

        if context_id:
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
            _log_request("POST", "/context/extract", extract_payload)
            extract_response = _request("POST", "/context/extract", extract_payload)
            _log_response(extract_response)
            extraction_types = sorted((extract_response.get("extractions") or {}).keys())
            if extraction_types:
                print(f"Extraction types: {extraction_types}")
            extraction_id = extract_response.get("extraction_id")
            list_path = (
                "/context"
                f"?tenant_id={TENANT_ID}"
                f"&domain_id={DOMAIN_ID}"
                f"&connection_id={CONNECTION_ID}"
                f"&database={os.getenv('DEMO_DB_NAME', 'prod_warehouse')}"
                f"&schema={os.getenv('DEMO_DB_SCHEMA', 'public')}"
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
                _log_request("POST", "/context/apply", apply_payload)
                apply_response = _request("POST", "/context/apply", apply_payload)
                _log_response(apply_response)
    else:
        print("No DEMO_CONTEXT_TEXT/DEMO_CONTEXT_FILE provided; skipping context ingestion.")

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

    # 2) Ontology mapping (rules + optional LLM)
    print("\n[2] Ontology mapping")
    print("Step 2 start")
    map_payload = {
        "schema": schemas[0] if schemas else "public",
        "schemas": schemas or None,
        "tables": tables[:10] or None,
                "connection_id": CONNECTION_ID,
        "database": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
    }
    map_path = f"/onboard/map?domain_id={DOMAIN_ID}&tenant_id={TENANT_ID}&use_llm=false"
    _log_request("POST", map_path, map_payload)
    map_response = _request("POST", map_path, map_payload)
    _log_response(map_response)
    print("Step 2 end")

    # 3) Entities + hierarchies (review / override)
    print("\n[3] Entities and hierarchies")
    print("Step 3 start")
    entities_path = f"/entities?domain_id={DOMAIN_ID}&tenant_id={TENANT_ID}&entity_limit=50"
    _log_request("GET", entities_path)
    entities_response = _request("GET", entities_path)
    _log_response(entities_response)
    print("Step 3 end")

    # 4) Infer facts/dims
    print("\n[4] Infer facts and dimensions")
    print("Step 4 start")
    infer_payload = {
        "schema": schemas[0] if schemas else "public",
        "schemas": schemas or None,
        "tables": tables[:10] or None,
        "time_column": None,
        "grain": "day",
        "use_llm": False,
        "connection_id": CONNECTION_ID,
        "database": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
    }
    infer_path = f"/onboard/infer-models?domain_id={DOMAIN_ID}"
    _log_request("POST", infer_path, infer_payload)
    infer_response = _request("POST", infer_path, infer_payload)
    _log_response(infer_response)
    print("Step 4 end")

    # 5) Generate dbt manifest
    print("\n[5] Generate dbt manifest")
    manifest_payload = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "connection_id": CONNECTION_ID,
        "profile_name": DEMO_DBT_PROFILE,
        "target_name": DEMO_DBT_TARGET,
        "profiles_dir": DEMO_DBT_PROFILES_DIR or None,
    }
    if DEMO_DBT_PROJECT:
        manifest_payload["dbt_project_path"] = DEMO_DBT_PROJECT
    _log_request("POST", "/dbt/manifest/generate", manifest_payload)
    manifest_response = _request("POST", "/dbt/manifest/generate", manifest_payload)
    _log_response(manifest_response)

    # 6) Suggested metrics (persist)
    print("\n[6] Suggested metrics (persist)")
    print("Step 5 start")
    metrics_payload = {
        "schema": schemas[0] if schemas else "public",
        "schemas": schemas or None,
        "tables": tables[:10] or None,
        "connection_id": CONNECTION_ID,
        "database": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
    }
    suggested_path = f"/metrics/suggested?domain_id={DOMAIN_ID}&persist=true"
    _log_request("POST", suggested_path, metrics_payload)
    suggested = _request("POST", suggested_path, metrics_payload)
    _log_response(suggested)
    print("Step 5 end")

    # 7) Promote first suggested metric (if present)
    print("\n[7] Promote a metric")
    print("Step 7 start")
    if suggested.get("measures"):
        measure = suggested["measures"][0]
        metric_id = f"{DOMAIN_ID}__{measure['table']}__{measure['column']}"
        patch_payload = {
            "display_name": measure["column"].replace("_", " ").title(),
            "description": f"Auto-promoted metric for {measure['table']}.{measure['column']}",
            "status": "certified",
            "connection_id": CONNECTION_ID,
            "database": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
            "schema": os.getenv("DEMO_DB_SCHEMA", "public"),
            "tables": [measure["table"]],
        }
        patch_path = f"/metrics/{metric_id}"
        _log_request("PATCH", patch_path, patch_payload)
        patch_response = _request("PATCH", patch_path, patch_payload)
        _log_response(patch_response)
    else:
        print("No measures found to promote.")
    print("Step 7 end")

    # 8) Apply contracts
    print("\n[8] Apply contracts")
    print("Step 8 start")
    _log_request("POST", "/contracts/apply", {})
    apply_response = _request("POST", "/contracts/apply", {})
    _log_response(apply_response)
    print("Step 8 end")

    print("\n== Demo complete ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
