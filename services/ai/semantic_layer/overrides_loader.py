from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings


def load_entity_overrides(settings: Settings, tenant_id: str, domain_id: str) -> list[dict]:
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
                SELECT entity_id, description, join_key, examples
                FROM public.quantyx_entity_overrides
                WHERE tenant_id = %s AND domain_id = %s
                """,
                (tenant_id, domain_id),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def load_hierarchy_overrides(settings: Settings, tenant_id: str, domain_id: str) -> list[dict]:
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
                SELECT hierarchy_name, levels, description
                FROM public.quantyx_hierarchy_overrides
                WHERE tenant_id = %s AND domain_id = %s
                """,
                (tenant_id, domain_id),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
