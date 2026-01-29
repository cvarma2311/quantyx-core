#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


API_BASE = os.getenv("QUANTYX_API_BASE", "http://127.0.0.1:8787")
DOMAIN_ID = os.getenv("QUANTYX_DOMAIN", "manufacturing")
TENANT_ID = os.getenv("QUANTYX_TENANT", "x_mfg")
DEMO_TABLES = [t.strip() for t in os.getenv("DEMO_TABLES", "").split(",") if t.strip()]

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


def main() -> int:
    print("== Onboarding Demo ==")
    print(f"API_BASE={API_BASE}")
    print(f"DOMAIN_ID={DOMAIN_ID}")
    print(f"TENANT_ID={TENANT_ID}")
    print(f"DEMO_TABLES={DEMO_TABLES}")
    print("Log detail: verbose")

    if not DEMO_TABLES:
        print("DEMO_TABLES must be set (comma-separated table names).")
        return 1

    # 1) Schema scan via connection
    print("\n[1] Scan connection")
    print("Step 1 start")
    scan_payload = {
        "connections": [
            {
                "connection_id": "conn_demo",
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
    }
    map_path = f"/onboard/map?domain_id={DOMAIN_ID}&use_llm=false"
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
        "connection_id": "conn_demo",
        "database": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
    }
    infer_path = f"/onboard/infer-models?domain_id={DOMAIN_ID}"
    _log_request("POST", infer_path, infer_payload)
    infer_response = _request("POST", infer_path, infer_payload)
    _log_response(infer_response)
    print("Step 4 end")

    # 5) Suggested metrics (persist)
    print("\n[5] Suggested metrics (persist)")
    print("Step 5 start")
    metrics_payload = {
        "schema": schemas[0] if schemas else "public",
        "schemas": schemas or None,
        "tables": tables[:10] or None,
        "connection_id": "conn_demo",
        "database": os.getenv("DEMO_DB_NAME", "prod_warehouse"),
    }
    suggested_path = f"/metrics/suggested?domain_id={DOMAIN_ID}&persist=true"
    _log_request("POST", suggested_path, metrics_payload)
    suggested = _request("POST", suggested_path, metrics_payload)
    _log_response(suggested)
    print("Step 5 end")

    # 6) Promote first suggested metric (if present)
    print("\n[6] Promote a metric")
    print("Step 6 start")
    if suggested.get("measures"):
        measure = suggested["measures"][0]
        metric_id = f"{DOMAIN_ID}__{measure['table']}__{measure['column']}"
        patch_payload = {
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
    print("Step 6 end")

    # 7) Apply contracts
    print("\n[7] Apply contracts")
    print("Step 7 start")
    _log_request("POST", "/contracts/apply", {})
    apply_response = _request("POST", "/contracts/apply", {})
    _log_response(apply_response)
    print("Step 7 end")

    print("\n== Demo complete ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
