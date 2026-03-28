from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings


class ScopedConnection:
    """Full connection credentials for a customer-scoped database."""

    __slots__ = ("connection_id", "host", "port", "user", "password", "database_name", "schema_name", "connection_type")

    def __init__(
        self,
        connection_id: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database_name: str,
        schema_name: str,
        connection_type: str = "postgresql",
    ) -> None:
        self.connection_id = connection_id
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database_name = database_name
        self.schema_name = schema_name
        self.connection_type = connection_type

    def __repr__(self) -> str:
        return (
            f"ScopedConnection(connection_id={self.connection_id!r}, "
            f"host={self.host!r}, port={self.port}, user={self.user!r}, "
            f"database_name={self.database_name!r}, schema_name={self.schema_name!r})"
        )

    def to_dict(self) -> dict:
        """Serialise to a plain dict (safe for JSON / LangGraph state storage).
        Password is intentionally included so the orchestrator can reconstruct
        the object from state — never log this dict directly."""
        return {
            "connection_id": self.connection_id,
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database_name": self.database_name,
            "schema_name": self.schema_name,
            "connection_type": self.connection_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScopedConnection":
        return cls(
            connection_id=str(d.get("connection_id") or ""),
            host=str(d.get("host") or ""),
            port=int(d.get("port") or 5432),
            user=str(d.get("user") or ""),
            password=str(d.get("password") or ""),
            database_name=str(d.get("database_name") or ""),
            schema_name=str(d.get("schema_name") or "public"),
            connection_type=str(d.get("connection_type") or "postgresql"),
        )


def run_query(
    settings: Settings,
    sql: str,
    params: list[object],
    scoped_conn: ScopedConnection | None = None,
) -> list[dict]:
    if scoped_conn:
        host     = scoped_conn.host
        port     = scoped_conn.port
        dbname   = scoped_conn.database_name
        user     = scoped_conn.user
        password = scoped_conn.password
    else:
        host     = settings.db_host
        port     = settings.db_port
        dbname   = settings.db_name
        user     = settings.db_user
        password = settings.db_password

    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.commit()
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
