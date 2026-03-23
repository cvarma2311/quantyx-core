from __future__ import annotations

import json
import uuid

import psycopg2
from psycopg2 import sql
import urllib3
from minio import Minio
from minio.error import S3Error, InvalidResponseError
from fastapi import HTTPException, status
from psycopg2.extras import Json

from pyiceberg.catalog import load_catalog

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query

from collections import defaultdict


def get_minio_client(settings):
    """
    Initialize and return a MinIO client using configuration.
    Returns:
        Minio: Configured MinIO client object.
    Raises:
        ConnectionError: If client initialization fails (e.g., invalid endpoint or credentials).
    """
    try:

        host = settings.minio_host
        port = int(settings.minio_port)
        access_key = settings.minio_access_key_id
        secret_key = settings.minio_secret_access_key
        endpoint = f"{host}:{port}".replace("https://", "").replace("http://", "")

        http_client = urllib3.PoolManager(
            timeout=urllib3.Timeout(
                connect=3.0,
                read=5.0
            ),
            retries=False,
        )
        client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            region="us-east-1",
            secure=False,
            http_client=http_client
        )
        client.list_buckets()
        return client
    except S3Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MinIO client initialization failed: {e.message or e.code}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MinIO client initialization failed: {str(e)}",
        )


def get_flow_exec_details(
    settings: Settings,
    flow_id: str,
) -> dict | None:
    sql = """
        SELECT flow_name, flow_id, flow_run_id, flow_statement_date, job_status, error_msg
        FROM public.flow_exec_details_log 
        WHERE flow_id = %s and job_status in ('COMPLETED', 'RUNNING')
        ORDER BY created_at DESC
        LIMIT 1
    """
    params = [flow_id]
    try:
        rows = run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return None
    if not rows:
        return None
    return rows[0]


def get_minio_data_path(
    settings: Settings,
    table_namespace: str,
    table_name: str,
) -> tuple[str, str] | None:
    sql = """
        SELECT
            catalog_name,
            regexp_replace(metadata_location, '/metadata/.*$', '/data/') AS data_path
        FROM public.iceberg_tables
        WHERE table_namespace = %s
          AND table_name = %s
        LIMIT 1;
    """

    params = [table_namespace, table_name]
    try:
        rows = run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="iceberg_tables table not found",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Table not found: {table_namespace}.{table_name}",
        )
    row = rows[0]
    return row["catalog_name"], row["data_path"]


def get_schema_from_metadata(settings: Settings, metadata_path: str) -> list[dict] | None:
    """
    Reads Iceberg metadata.json from MinIO and extracts schema
    """

    if not metadata_path.startswith("s3a://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid metadata path format. Expected s3a:// scheme.",
        )

    path_without_scheme = metadata_path.replace("s3a://", "", 1)
    bucket, object_path = path_without_scheme.split("/", 1)

    try:
        client = get_minio_client(settings)
        response = client.get_object(bucket, object_path)
        metadata = json.loads(response.read())
        current_schema_id = metadata["current-schema-id"]
        schema_obj = next(
            s for s in metadata["schemas"]
            if s["schema-id"] == current_schema_id
        )
        if not schema_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schema not found in metadata",
            )

        fields = schema_obj["fields"]
        return [
            {
                "name": field["name"],
                "type": field["type"],
            }
            for field in fields
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing metadata: {str(e)}",
        )

def get_table_schema(
    settings: Settings,
    table_namespace: str,
    table_name: str,
) -> dict | None:
    sql = """
        SELECT metadata_location
        FROM public.iceberg_tables
        WHERE table_namespace = %s
          AND table_name = %s;
    """

    params = [table_namespace, table_name]
    try:
        rows = run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="iceberg_tables table not found",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Table not found: {table_namespace}.{table_name}",
        )

    metadata_path = rows[0]["metadata_location"]
    return get_schema_from_metadata(settings, metadata_path)


def get_upstream_path(edges: list[dict], node_id: str) -> list[str]:

    parts = node_id.split("_", 1)
    if len(parts) > 1 and parts[0] == parts[1].split("_")[0]:
        node_id = parts[1]

    reverse_graph = defaultdict(list)
    for edge in edges:
        reverse_graph[edge["target"]].append(edge["source"])
    visited = set()
    stack = [node_id]
    while stack:
        current = stack.pop()
        for parent in reverse_graph.get(current, []):
            if parent not in visited:
                visited.add(parent)
                stack.append(parent)
    return list(visited)


def get_source_node_ids(
    settings: Settings,
    flow_id: str,
    node_id: str
) -> list[str]:
    sql = """
        SELECT data
        FROM public.flow_builder
        WHERE flow_id = %s
    """
    params = [flow_id]
    try:
        rows = run_query(settings, sql, params)
    except psycopg2.errors.UndefinedTable:
        return []

    edges = rows[0]["data"].get("edges", [])
    source_node_ids = get_upstream_path(edges, node_id)
    return source_node_ids


def generate_custom_sql(minio_path: str, columns: list) -> str:
    """
    Generate SQL query for Iceberg table stored in MinIO.

    Args:
        minio_path: s3a://... path (can contain /data/)
        node_id: optional identifier (used as alias)

    Returns:
        SQL query string
    """

    table_path = minio_path.replace("s3a://", "s3://").rstrip("/")

    if table_path.endswith("/data"):
        table_path = table_path.rsplit("/data", 1)[0]

    column_string = ", ".join(columns) if columns else "*"

    sql_query = f"""
    SELECT {column_string}
    FROM iceberg_scan('{table_path}')
    """

    return sql_query.strip()


def store_flow_node_details(settings: Settings, payload: dict) -> None:
    row_id = str(uuid.uuid4())
    sql = """
        INSERT INTO public.quantyx_flow_node_data_registry (
          row_id,
          tenant_id,
          domain_id,
          flow_id,
          node_id,
          artifact_key,
          minio_path,
          iceberg_catalog,
          iceberg_namespace,
          iceberg_table,
          pyiceberg_table_fqn,
          data_schema,
          sample_records,
          row_count,
          source_node_ids,
          source_artifact_keys,
          transform_sql,
          node_type,
          compression,
          source_type,
          created_at,
          updated_at
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s,%s,%s, %s, %s, %s,
          now(), now()
        )
    """

    execute_non_query(
        settings,
        sql,
        [
            row_id,
            payload.get("tenant_id", ""),
            payload.get("domain_id", ""),
            payload.get("flow_id", ""),
            payload.get("node_id", ""),
            f"{payload.get('flow_id','')}::{payload.get('node_id','')}",
            payload.get("minio_path", ""),
            payload.get("catalog_name", ""),
            payload.get("table_namespace", ""),
            payload.get("table_name", ""),
            f"{payload.get('table_namespace','')}.{payload.get('table_name','')}",
            Json(payload.get("table_schema", [])),
            Json(payload.get("sample_records", [])),
            payload.get("row_count", 0),
            Json(payload.get("source_node_ids", [])),
            Json([f"{payload.get('flow_id','')}::{node_id}" for node_id in payload.get("source_node_ids", [])]),
            payload.get("transform_sql", ""),
            "source",
            "gzip",
            "system"
        ]
    )


def read_from_minio(settings: Settings, table_name: str, catalog_name: str, warehouse: str, namespace: str, limit: int = 0) -> dict:
    """
    Reads Iceberg table from MinIO
    Args:
        table_name (str): Name of the iceberg table
        catalog_name: Name of the Iceberg catalog registered in PostgreSQL.
        warehouse: Name of the MinIO bucket (warehouse).

    """
    catalog = load_catalog(
        catalog_name,
        **{
            "catalog_type": "sql",
            "uri": settings.catalog_db_uri,
            "s3.endpoint": settings.minio_endpoint,
            "s3.access-key-id": settings.minio_access_key_id,
            "s3.secret-access-key": settings.minio_secret_access_key,
            "warehouse": warehouse
        }
    )
    table = catalog.load_table(f"{namespace}.{table_name}")
    records = table.scan().to_pandas()
    record_count = len(records)
    if limit and limit > 0:
        records = records.head(limit)

    return {
        "row_count": record_count,
        "data": records.to_dict(orient="records")
    }


