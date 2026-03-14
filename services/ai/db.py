from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings


def run_query(settings: Settings, sql: str, params: list[object]) -> list[dict]:
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def execute_returning_query(settings: Settings, sql: str, params: list[object]) -> list[dict]:
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.commit()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def execute_non_query(settings: Settings, sql: str, params: list[object]) -> None:
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()
