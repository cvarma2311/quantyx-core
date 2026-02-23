#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request


def _request(method: str, url: str, payload: dict | None = None) -> dict:
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
        raise RuntimeError(f"{method} {url} failed: {exc.code} {body}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge all Quantyx data for a tenant.")
    parser.add_argument("--tenant-id", required=True, help="Tenant ID to purge")
    parser.add_argument("--dry-run", action="store_true", help="Only show counts per table")
    parser.add_argument(
        "--api-base",
        default=os.getenv("QUANTYX_API_BASE", "http://127.0.0.1:8787"),
        help="API base URL (default from QUANTYX_API_BASE)",
    )
    args = parser.parse_args()

    payload = {"tenant_id": args.tenant_id, "dry_run": args.dry_run}
    if not args.dry_run:
        payload["confirm"] = True

    url = f"{args.api_base}/tenant/purge"
    response = _request("POST", url, payload)
    print(json.dumps(response, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
