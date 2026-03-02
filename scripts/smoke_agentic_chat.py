#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.request


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8787")
TENANT_ID = os.getenv("TENANT_ID", "VC_101")
DOMAIN_ID = os.getenv("DOMAIN_ID", "lpg_production_distribution")
QUESTION = os.getenv("QUESTION", "What is total LPG production by plant last week?")


def _request(method: str, path: str, payload: dict | None = None, timeout: int = 60):
    url = f"{API_BASE}{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else None


def main() -> int:
    print("== Smoke: /chat sync ==")
    status, body = _request(
        "POST",
        "/chat",
        {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "question": QUESTION,
            "mode": "sync",
        },
    )
    print(status)
    print(json.dumps(body, indent=2))

    print("\n== Smoke: /chat async ==")
    status, body = _request(
        "POST",
        "/chat",
        {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "question": QUESTION,
            "mode": "async",
        },
    )
    print(status)
    print(json.dumps(body, indent=2))
    chat_id = (body or {}).get("chat_id")

    if chat_id:
        print("\n== Poll /chat/{id} ==")
        for _ in range(10):
            status, poll_body = _request("GET", f"/chat/{chat_id}", None, timeout=30)
            print(status)
            print(json.dumps(poll_body, indent=2))
            if poll_body and poll_body.get("status") in {"complete", "failed"}:
                break
            time.sleep(1.5)
        print("\n== /chat/{id}/events ==")
        status, events = _request("GET", f"/chat/{chat_id}/events", None, timeout=30)
        print(status)
        print(json.dumps(events, indent=2))

    print("\n== Smoke: /views ==")
    status, body = _request(
        "GET",
        f"/views?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}",
        None,
        timeout=30,
    )
    print(status)
    print(json.dumps(body, indent=2))

    print("\n== Smoke: /rollups ==")
    status, body = _request(
        "GET",
        f"/rollups?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}",
        None,
        timeout=30,
    )
    print(status)
    print(json.dumps(body, indent=2))

    print("\n== Agentic run: /agentic/runs ==")
    status, body = _request(
        "POST",
        "/agentic/runs",
        {
            "tenant_id": TENANT_ID,
            "domain_id": DOMAIN_ID,
            "mode": "full",
        },
        timeout=60,
    )
    print(status)
    print(json.dumps(body, indent=2))
    run_id = (body or {}).get("run_id")

    if run_id:
        print("\n== /agentic/runs/{id} ==")
        status, run = _request("GET", f"/agentic/runs/{run_id}", None, timeout=30)
        print(status)
        print(json.dumps(run, indent=2))

        print("\n== /agentic/runs/{id}/events ==")
        status, events = _request("GET", f"/agentic/runs/{run_id}/events", None, timeout=30)
        print(status)
        print(json.dumps(events, indent=2))

        print("\n== /agentic/runs/{id}/chat ==")
        status, chat = _request("GET", f"/agentic/runs/{run_id}/chat", None, timeout=30)
        print(status)
        print(json.dumps(chat, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
