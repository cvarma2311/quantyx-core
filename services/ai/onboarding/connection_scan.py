from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor


def scan_connection(
    *,
    db_type: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    schema: str,
    tables: list[str] | None,
    limit: int,
    sample_rows: int,
    cursor_value: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    if db_type != "postgres":
        raise ValueError("Only postgres is supported for scan-connection")

    capped_samples = max(10, min(sample_rows, 100))
    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params: list[Any] = [schema]
            sql = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            """
            if tables:
                sql += " AND table_name = ANY(%s)"
                params.append(tables)
            sql += " ORDER BY table_name ASC"
            cur.execute(sql, params)
            table_rows = [row["table_name"] for row in cur.fetchall()]

            if cursor_value:
                table_rows = [name for name in table_rows if name > cursor_value]

            page_tables = table_rows[:limit]
            next_cursor = page_tables[-1] if len(page_tables) == limit else None

            if not page_tables:
                return [], next_cursor

            cur.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = ANY(%s)
                ORDER BY table_name, ordinal_position
                """,
                [schema, page_tables],
            )
            column_rows = cur.fetchall()

            cur.execute(
                """
                SELECT schemaname, tablename, attname, null_frac, n_distinct
                FROM pg_stats
                WHERE schemaname = %s AND tablename = ANY(%s)
                """,
                [schema, page_tables],
            )
            stats_rows = cur.fetchall()

        stats_map = {(row["tablename"], row["attname"]): row for row in stats_rows}

        tables_payload: dict[str, dict[str, Any]] = {}
        column_types: dict[tuple[str, str], str] = {}
        for row in column_rows:
            table_name = row["table_name"]
            column_name = row["column_name"]
            column_types[(table_name, column_name)] = row["data_type"]
            stats = stats_map.get((table_name, column_name), {})
            column_payload = {
                "name": column_name,
                "data_type": row["data_type"],
                "null_frac": stats.get("null_frac"),
                "distinct": stats.get("n_distinct"),
            }
            tables_payload.setdefault(table_name, {"table": table_name, "columns": []})
            tables_payload[table_name]["columns"].append(column_payload)

        with conn.cursor() as cur:
            for table_name in page_tables:
                cur.execute(
                    f'SELECT * FROM "{schema}"."{table_name}" LIMIT %s',
                    [capped_samples],
                )
                rows = cur.fetchall()
                if not rows:
                    continue
                columns = [desc[0] for desc in cur.description]
                for col_name in columns:
                    values = [row[columns.index(col_name)] for row in rows]
                    values = [val for val in values if val is not None]
                    if not values:
                        continue
                    data_type = column_types.get((table_name, col_name), "").lower()
                    profile = {}
                    if data_type in {"integer", "bigint", "smallint", "numeric", "double precision", "real"}:
                        try:
                            numeric_vals = [float(val) for val in values]
                            profile["mean"] = sum(numeric_vals) / len(numeric_vals)
                            profile["min"] = min(numeric_vals)
                            profile["max"] = max(numeric_vals)
                        except (TypeError, ValueError):
                            profile = {}
                    elif data_type in {"text", "character varying", "varchar"}:
                        sample_values = list(dict.fromkeys([str(val) for val in values]))[:5]
                        profile["sample_values"] = sample_values
                    elif data_type in {"date", "timestamp", "timestamp without time zone", "timestamp with time zone"}:
                        try:
                            profile["min"] = min(values)
                            profile["max"] = max(values)
                        except TypeError:
                            profile = {}
                    if profile:
                        for col in tables_payload.get(table_name, {}).get("columns", []):
                            if col["name"] == col_name:
                                col["profile"] = profile
                                break

        ordered_tables = [tables_payload[name] for name in page_tables if name in tables_payload]
        return ordered_tables, next_cursor
    finally:
        conn.close()
