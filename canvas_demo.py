#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


API_BASE = os.getenv("QUANTYX_API_BASE", "http://127.0.0.1:8787")
DOMAIN_ID = os.getenv("QUANTYX_DOMAIN", "manufacturing")
TENANT_ID = os.getenv("QUANTYX_TENANT", "x_mfg")
CONNECTION_ID = os.getenv("DEMO_CONNECTION_ID", "conn_demo")
DEMO_TABLES = [t.strip() for t in os.getenv("DEMO_TABLES", "").split(",") if t.strip()]
DEMO_DB_HOST = os.getenv("DEMO_DB_HOST", "db.company.com")
DEMO_DB_PORT = int(os.getenv("DEMO_DB_PORT", "5432"))
DEMO_DB_USER = os.getenv("DEMO_DB_USER", "readonly_user")
DEMO_DB_PASSWORD = os.getenv("DEMO_DB_PASSWORD", "******")
DEMO_DB_NAME = os.getenv("DEMO_DB_NAME", "prod_warehouse")
DEMO_DB_SCHEMA = os.getenv("DEMO_DB_SCHEMA", "public")
DEMO_CANVAS_NAME = os.getenv("DEMO_CANVAS_NAME", "Demo Semantic Canvas")
DEMO_CANVAS_ID = os.getenv("DEMO_CANVAS_ID", "")
DEMO_USE_LLM = os.getenv("DEMO_USE_LLM", "true").lower() in {"1", "true", "yes"}
DEMO_USE_SEMANTIC_SUGGEST = os.getenv("DEMO_USE_SEMANTIC_SUGGEST", "true").lower() in {
    "1",
    "true",
    "yes",
}
DEMO_CONTEXT_FILE = os.getenv("DEMO_CONTEXT_FILE", "artifacts/analog_data.txt")

CONTEXT_TEXT = """S.N.\tTable Name\tQuestions\tRemarks
1\tHOST_BAYREASSIGNMENT\t"1. Identify repeated bay reassignments for the same TT within the last 7 days.
2. Identify repeated bay reassignments at a specific bay.
3. Identify repeated bay reassignments at a specific time of day.
4. Identify repeated bay reassignments for the same TT going to the same outlet.
5. Total number of bay reassignments per day across locations.
6. Identify repeated bay reassignments for a specific product."\tPoint 4 Refer IMS Table
2\tHOST_CANCELLEDTTS\t"1. Number of TTs cancelled per day.
2. Location-wise TT cancellation count.
3. Locations with the highest cancellation rate.
4. Outlets where TTs are cancelled most frequently.
5. Locations with maximum TT cancellations along with reasons.
6. Repeated TT cancellations associated with a specific transporter truck."\t"Point 4 Refer IMS Table
Point 6 Refer Transporter Table"
3\tHOST_KFACTORCHANGES\t"1. List of locations with the most recent K-Factor changes.
2. Repeated K-Factor changes in the last one year.
3. Repeated K-Factor changes for the same bay in the last one year across locations.
4. K-Factor change report across all locations or a specific location."\t
4\tHOST_LOCALLOADEDTTS\t"1. Identify TTs where local loading is performed repeatedly.
2. Identify time periods when local loading is frequently performed.
3. Identify products for which local loading is performed.
4. Identify bays where assigned TTs undergo local loading.
5. Identify outlets where assigned TTs undergo local loading.
6. Total local loading quantity during the last one week.
7. Local loading quantity for MS / HSD / Ethanol."\t"Point 4 Refer BayReassignment Table
Point 5 Refer IMS Table"
5\tHOST_MANUALFANPRINTED\t"1. Total count of manual FAN prints across locations.
2. Location-wise percentage of manual FAN prints.
3. Trucks that have manual FAN prints and also performed local loading.
4. Identify outlets where manual FAN printed trucks are dispatched.
5. Repeated manual FAN prints for the same truck."\t"Point 3 Refer LocalLoading table
Point 4 Refer IMS Table"
6\tHOST_MFMKFACTOR\t"1. List of locations with the most recent MFM-Factor changes.
2. Repeated MFM-Factor changes in the last one year.
3. Repeated MFM-Factor changes for the same bay in the last one year across locations.
4. MFM-Factor change report across all locations or a specific location."\t
7\tHOST_OVERLOADEDTTS\t"1. List of overloaded TTs per location.
2. List of overloaded TTs across all locations.
3. Identify bays with repeated overloading incidents.
4. Identify products frequently involved in overloading.
5. Verify whether overloaded TTs were cross-checked post loading (SAP validation)."\tPoint 5 Refer SAP Table
8\tHOST_SICKTTS\t"1. Total number of sick TTs across all locations.
2. Location-wise count of sick TTs.
3. Repeated sick TTs associated with a specific outlet truck.
4. Repeated sick TTs associated with a specific transporter truck."\t"Point 3 Refer IMS Table
Point 4 Refer Transporter Table"
9\tHOST_UNAUTHORIZEDFLOW\t"1. Repeated unauthorized flow occurrences at a specific bay.
2. Highest unauthorized quantity flow by location and bay.
3. Total unauthorized flow quantity (in liters) for a specific location."\t
10\tHOST_DAYENDDETAILS\t"1. Total invoiced quantity vs. total loaded quantity.
2. Total invoiced quantity vs. quantity delivered through BCU.
3. Total invoiced quantity vs. quantity delivered through MFM.
4. Bay-wise difference between BCU totalizer and invoice quantity.
5. Bay-wise difference between BCU totalizer and MFM totalizer.
6. List of bays where BCU totalizer and invoice quantity mismatch exceeds 0.05%.
7. List of bays where BCU totalizer and MFM totalizer mismatch exceeds 0.05%."\t"""


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


def _request_multipart(path: str, fields: dict[str, str], file_field: str, file_path: str) -> dict:
    boundary = "----quantyx-demo-boundary"
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.append(f"--{boundary}".encode("utf-8"))
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))

    filename = os.path.basename(file_path)
    with open(file_path, "rb") as handle:
        file_bytes = handle.read()
    lines.append(f"--{boundary}".encode("utf-8"))
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"'.encode("utf-8")
    )
    lines.append(b"Content-Type: text/plain")
    lines.append(b"")
    lines.append(file_bytes)
    lines.append(f"--{boundary}--".encode("utf-8"))

    body = b"\r\n".join(lines)
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"POST {path} failed: {exc.code} {body}") from exc


def _get_first(items: list[dict], key: str) -> str | None:
    for item in items:
        value = item.get(key)
        if value:
            return value
    return None


def main() -> int:
    print("== Canvas Demo ==")
    print(f"API_BASE={API_BASE}")
    print(f"DOMAIN_ID={DOMAIN_ID}")
    print(f"TENANT_ID={TENANT_ID}")
    print(f"CONNECTION_ID={CONNECTION_ID}")
    print(f"DEMO_TABLES={DEMO_TABLES}")
    print(f"DEMO_USE_LLM={DEMO_USE_LLM}")
    print(f"DEMO_USE_SEMANTIC_SUGGEST={DEMO_USE_SEMANTIC_SUGGEST}")
    print(f"DEMO_CANVAS_ID={DEMO_CANVAS_ID or '(new)'}")
    print(f"DEMO_CONTEXT_FILE={DEMO_CONTEXT_FILE}")
    print("Log detail: verbose")

    if not DEMO_TABLES:
        print("DEMO_TABLES must be set (comma-separated table names).")
        return 1

    # 0) Set tenant domain
    print("\n[0] Set tenant domain")
    domain_payload = {"tenant_id": TENANT_ID, "domain_id": DOMAIN_ID}
    _log_request("POST", "/tenant/domain", domain_payload)
    domain_response = _request("POST", "/tenant/domain", domain_payload)
    _log_response(domain_response)

    # 1) Scan connection
    print("\n[1] Scan connection")
    scan_payload: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "connections": [
            {
                "connection_id": CONNECTION_ID,
                "db_type": "postgres",
                "host": DEMO_DB_HOST,
                "port": DEMO_DB_PORT,
                "user": DEMO_DB_USER,
                "password": DEMO_DB_PASSWORD,
                "sample_rows": 100,
                "databases": [
                    {
                        "name": DEMO_DB_NAME,
                        "schemas": [
                            {
                                "name": DEMO_DB_SCHEMA,
                                "tables": DEMO_TABLES,
                                "limit": 50,
                                "cursor": None,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    _log_request("POST", "/onboard/scan-connection", scan_payload)
    scan_response = _request("POST", "/onboard/scan-connection", scan_payload)
    _log_response(scan_response)

    # 2) Set tenant scope
    print("\n[2] Set tenant scope")
    scope_payload = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "connection_id": CONNECTION_ID,
        "database": DEMO_DB_NAME,
        "schema": DEMO_DB_SCHEMA,
        "tables": DEMO_TABLES,
    }
    _log_request("POST", "/tenant/scope", scope_payload)
    scope_response = _request("POST", "/tenant/scope", scope_payload)
    _log_response(scope_response)

    file_id = None
    # 2b) Ingest context text
    print("\n[2b] Ingest context text")
    context_payload = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "source_type": "business_context",
        "source_title": "Analog questions context",
        "raw_text": CONTEXT_TEXT,
        "metadata": {
            "tables": DEMO_TABLES,
            "notes": "Analog context from onboarding questions.",
        },
    }
    _log_request("POST", "/context/ingest", context_payload)
    context_response = _request("POST", "/context/ingest", context_payload)
    _log_response(context_response)

    # 2c) Ingest context file
    if DEMO_CONTEXT_FILE and os.path.isfile(DEMO_CONTEXT_FILE):
        print("\n[2c] Ingest context file")
        fields = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "source_type": "business_context",
            "source_title": "Analog data file",
            "metadata": json.dumps({"tables": DEMO_TABLES}),
        }
        _log_request("POST", "/context/ingest-file", {"file": DEMO_CONTEXT_FILE, **fields})
        file_response = _request_multipart(
            "/context/ingest-file",
            fields=fields,
            file_field="file",
            file_path=DEMO_CONTEXT_FILE,
        )
        _log_response(file_response)
        file_id = file_response.get("file_id")
    else:
        print("\n[2c] Skipping context file (file not found)")

    # 2d) Link context to file
    if file_id and context_response.get("context_id"):
        print("\n[2d] Link context to file")
        link_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "source_type": "business_context",
            "source_title": "Analog questions context (linked file)",
            "raw_text": CONTEXT_TEXT,
            "file_ids": [file_id],
            "metadata": {
                "tables": DEMO_TABLES,
                "notes": "Analog context with file link.",
            },
        }
        _log_request("POST", "/context/ingest", link_payload)
        link_response = _request("POST", "/context/ingest", link_payload)
        _log_response(link_response)

    # 3) Map entities
    print("\n[3] Map entities")
    map_payload = {"tenant_id": TENANT_ID}
    _log_request("POST", "/onboard/map", map_payload)
    map_response = _request("POST", "/onboard/map", map_payload)
    _log_response(map_response)

    # 4) List entities and hierarchies
    print("\n[4] List entities and hierarchies")
    entities_path = f"/entities?tenant_id={TENANT_ID}"
    _log_request("GET", entities_path)
    entities_response = _request("GET", entities_path)
    _log_response(entities_response)

    # 5) Infer facts and dimensions
    print("\n[5] Infer facts and dimensions")
    infer_payload = {"tenant_id": TENANT_ID, "grain": "day", "use_llm": DEMO_USE_LLM}
    _log_request("POST", "/onboard/infer-models", infer_payload)
    infer_response = _request("POST", "/onboard/infer-models", infer_payload)
    _log_response(infer_response)

    # 6) Suggest metrics
    print("\n[6] Suggest metrics")
    metrics_payload = {"tenant_id": TENANT_ID}
    _log_request("POST", "/metrics/suggested", metrics_payload)
    metrics_response = _request("POST", "/metrics/suggested", metrics_payload)
    _log_response(metrics_response)

    # 7) List facts and dimensions
    print("\n[7] List facts")
    facts_path = f"/facts?tenant_id={TENANT_ID}"
    _log_request("GET", facts_path)
    facts_response = _request("GET", facts_path)
    _log_response(facts_response)

    print("\n[8] List dimensions")
    dims_path = f"/dimensions?tenant_id={TENANT_ID}"
    _log_request("GET", dims_path)
    dims_response = _request("GET", dims_path)
    _log_response(dims_response)

    # 9) Semantic suggest + apply (optional)
    suggest_response = None
    if DEMO_USE_SEMANTIC_SUGGEST:
        print("\n[9] Semantic suggest (LLM)")
        suggest_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "inputs": {
                "questions": [
                    "Top 5 plants by dispatch volume this month",
                    "Which products are trending down YoY?",
                ],
                "glossary": "MFM=Mass Flow Meter, bay=loading bay",
            },
        }
        _log_request("POST", "/semantic/suggest", suggest_payload)
        suggest_response = _request("POST", "/semantic/suggest", suggest_payload)
        _log_response(suggest_response)

        print("\n[10] Apply semantic suggestions (persist + canvas)")
        apply_payload = {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "canvas_id": DEMO_CANVAS_ID or None,
            "facts": suggest_response.get("facts", []),
            "dimensions": suggest_response.get("dimensions", []),
            "metrics": suggest_response.get("metrics", []),
            "lineage": suggest_response.get("lineage", {}),
            "idempotency_key": "semantic-apply-001",
        }
        _log_request("POST", "/semantic/suggest/apply", apply_payload)
        apply_response = _request("POST", "/semantic/suggest/apply", apply_payload)
        _log_response(apply_response)
        if apply_response.get("canvas_id"):
            DEMO_CANVAS_ID = apply_response["canvas_id"]

    # 11) Save a manual canvas example
    print("\n[11] Save manual canvas")
    facts = facts_response.get("facts", [])
    dims = dims_response.get("dimensions", [])
    fact_name = _get_first(facts, "table_name")
    dim_name = _get_first(dims, "name")
    nodes = []
    edges = []
    if dim_name:
        nodes.append({"type": "dimension", "payload": {"name": dim_name}})
    if fact_name:
        nodes.append({"type": "fact", "payload": {"table_name": fact_name}})
    if dim_name and fact_name:
        edges.append(
            {
                "from_id": dim_name,
                "to_id": fact_name,
                "edge_type": "dimension_to_fact",
            }
        )
    canvas_payload = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "name": DEMO_CANVAS_NAME,
        "description": "Manual canvas demo",
        "nodes": nodes,
        "edges": edges,
        "idempotency_key": "canvas-001",
    }
    _log_request("POST", "/canvas/save", canvas_payload)
    canvas_response = _request("POST", "/canvas/save", canvas_payload)
    _log_response(canvas_response)
    canvas_id = canvas_response.get("canvas_id") or DEMO_CANVAS_ID

    # 12) Fetch canvas + lineage
    if canvas_id:
        print("\n[12] Get canvas by id")
        get_canvas_path = f"/canvas/{canvas_id}?tenant_id={TENANT_ID}"
        _log_request("GET", get_canvas_path)
        get_canvas_response = _request("GET", get_canvas_path)
        _log_response(get_canvas_response)

    print("\n[13] List canvases")
    list_canvas_path = f"/canvas?tenant_id={TENANT_ID}"
    _log_request("GET", list_canvas_path)
    list_canvas_response = _request("GET", list_canvas_path)
    _log_response(list_canvas_response)

    print("\n[14] Canvas tree")
    tree_path = f"/canvas/tree?tenant_id={TENANT_ID}"
    _log_request("GET", tree_path)
    tree_response = _request("GET", tree_path)
    _log_response(tree_response)

    print("\n[15] Semantic lineage")
    lineage_path = f"/lineage?tenant_id={TENANT_ID}"
    _log_request("GET", lineage_path)
    lineage_response = _request("GET", lineage_path)
    _log_response(lineage_response)

    print("\nCanvas demo complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
