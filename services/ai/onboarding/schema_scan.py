from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings


def scan_schema(settings: Settings, schema: str | None = None) -> list[dict[str, Any]]:
    target_schema = schema or settings.db_schema
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  c.table_name,
                  c.column_name,
                  c.data_type,
                  s.null_frac,
                  s.n_distinct
                FROM information_schema.columns c
                LEFT JOIN pg_stats s
                  ON s.schemaname = c.table_schema
                 AND s.tablename = c.table_name
                 AND s.attname = c.column_name
                WHERE c.table_schema = %s
                ORDER BY c.table_name, c.ordinal_position
                """,
                (target_schema,),
            )
            columns = cur.fetchall()

            cur.execute(
                """
                SELECT relname AS table_name, reltuples::BIGINT AS row_estimate
                FROM pg_class
                JOIN pg_namespace n ON n.oid = pg_class.relnamespace
                WHERE n.nspname = %s AND relkind = 'r'
                """,
                (target_schema,),
            )
            row_counts = {row["table_name"]: row["row_estimate"] for row in cur.fetchall()}

        tables: dict[str, dict[str, Any]] = {}
        for col in columns:
            table = tables.setdefault(
                col["table_name"],
                {
                    "table": col["table_name"],
                    "row_estimate": row_counts.get(col["table_name"]),
                    "columns": [],
                },
            )
            table["columns"].append(
                {
                    "name": col["column_name"],
                    "data_type": col["data_type"],
                    "null_frac": col.get("null_frac"),
                    "n_distinct": col.get("n_distinct"),
                }
            )

        return list(tables.values())
    finally:
        conn.close()
