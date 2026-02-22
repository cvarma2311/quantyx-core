#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


def _request(method: str, url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge all Quantyx data for a tenant via API.")
    parser.add_argument("--tenant-id", required=True, help="Tenant identifier to purge")
    parser.add_argument(
        "--api-base",
        default=os.getenv("API_BASE", "http://127.0.0.1:8787"),
        help="API base URL (default: env API_BASE or http://127.0.0.1:8787)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview deletion counts without deleting",
    )
    args = parser.parse_args()

    url = f"{args.api_base.rstrip('/')}/tenant/purge"
    payload = {"tenant_id": args.tenant_id, "dry_run": bool(args.dry_run), "confirm": True}
    print(f"==> POST {url}")
    print(json.dumps(payload, indent=2))
    try:
        response = _request("POST", url, payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        print(f"ERROR: {exc.code} {exc.reason} {body}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("<== response")
    print(json.dumps(response, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
