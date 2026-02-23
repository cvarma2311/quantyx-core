#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

import psycopg2


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark Quantyx artifacts as certified for a tenant.")
    parser.add_argument("--tenant-id", required=True, help="Tenant identifier")
    parser.add_argument("--domain-id", default=None, help="Optional domain_id filter")
    args = parser.parse_args()

    db_host = os.getenv("DB_HOST")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    if not all([db_host, db_name, db_user, db_password]):
        raise SystemExit("Missing DB_* env vars (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD)")

    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
    )
    try:
        with conn.cursor() as cur:
            filters = "tenant_id = %s"
            params = [args.tenant_id]
            if args.domain_id:
                filters += " AND domain_id = %s"
                params.append(args.domain_id)

            def _exec(sql: str) -> None:
                cur.execute(sql, params)
                print(f"{sql.split()[1]}: {cur.rowcount} rows")

            _exec(f"UPDATE public.quantyx_entity_overrides SET lifecycle_status = 'certified' WHERE {filters}")
            _exec(f"UPDATE public.quantyx_hierarchy_overrides SET lifecycle_status = 'certified' WHERE {filters}")
            _exec(f"UPDATE public.quantyx_facts_registry SET lifecycle_status = 'certified' WHERE {filters}")
            _exec(f"UPDATE public.quantyx_dimensions_registry SET lifecycle_status = 'certified' WHERE {filters}")
            _exec(f"UPDATE public.quantyx_metrics_registry SET lifecycle_status = 'certified' WHERE {filters}")
            _exec(f\"UPDATE public.quantyx_glossary_terms SET lifecycle_status = 'certified' WHERE {filters}\")

        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
