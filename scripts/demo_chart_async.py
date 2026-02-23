#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.request


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8787")  # default
TENANT_ID = os.getenv("TENANT_ID", "VC_101")  # default
DOMAIN_ID = os.getenv("DOMAIN_ID", "lpg_production_distribution")  # default
QUESTION = os.getenv("QUESTION", "What is total LPG production by plant last week?")  # default
REQUEST_TIMEOUT_SEC = float(os.getenv("REQUEST_TIMEOUT_SEC", "12000"))  # default


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def main() -> int:
    print("== Chart Async Demo ==")
    print(f"API_BASE={API_BASE}")
    print(f"TENANT_ID={TENANT_ID}")
    print(f"DOMAIN_ID={DOMAIN_ID}")
    print(f"QUESTION={QUESTION}")

    create_payload = {
        "tenant_id": TENANT_ID,
        "domain_id": DOMAIN_ID,
        "question": QUESTION,
    }
    print("\n==> POST /query")
    print(json.dumps(create_payload, indent=2))
    query_resp = _request("POST", "/query", create_payload)
    print("<== response")
    print(json.dumps(query_resp, indent=2))

    chart_id = query_resp.get("chart_id")
    if not chart_id:
        print("No chart_id returned from /query.")
        return 1

    print(f"\nPolling /charts/{chart_id} ...")
    poll_delay = float(os.getenv("POLL_DELAY_SEC", "1.5"))  # default
    max_wait = float(os.getenv("POLL_MAX_SEC", "60"))  # default
    deadline = time.time() + max_wait

    while time.time() < deadline:
        resp = _request("GET", f"/charts/{chart_id}")
        status = resp.get("status")
        print(f"status={status}")
        if status == "ready":
            print("\n==> GET /charts/{chart_id} (ready)")
            print(json.dumps(resp, indent=2))
            return 0
        if status == "failed":
            print("\n==> GET /charts/{chart_id} (failed)")
            print(json.dumps(resp, indent=2))
            return 2
        time.sleep(poll_delay)

    print("Polling timed out.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
