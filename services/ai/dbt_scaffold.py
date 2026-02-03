from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def infer_models_from_scan(tables: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts: list[dict[str, Any]] = []
    dims: list[dict[str, Any]] = []
    for table in tables:
        columns = table.get("columns", [])
        column_names = [col.get("name") for col in columns]
        numeric_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower()
            in {"integer", "bigint", "smallint", "numeric", "double precision", "real"}
        ]
        text_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower() in {"text", "character varying", "varchar"}
        ]
        date_cols = [
            col["name"]
            for col in columns
            if str(col.get("data_type", "")).lower()
            in {"date", "timestamp", "timestamp without time zone", "timestamp with time zone"}
        ]
        candidate_time = date_cols[0] if date_cols else None
        is_fact = bool(numeric_cols) and bool(candidate_time)
        if is_fact:
            facts.append(
                {
                    "name": table.get("table"),
                    "time_column": candidate_time,
                    "measures": numeric_cols[:10],
                    "dimensions": text_cols[:10],
                }
            )
        else:
            dim_keys = [col for col in column_names if col and (col.endswith("_id") or col.endswith("_code"))]
            dims.append(
                {
                    "name": table.get("table"),
                    "keys": dim_keys[:5],
                    "attributes": text_cols[:15],
                }
            )
    return facts, dims


def _llm_generate_scaffold(
    settings: Settings,
    database: str,
    schema: str,
    tables: list[dict[str, Any]],
    context_text: str | None,
) -> dict[str, Any] | None:
    if not settings.openai_api_key:
        return None
    system_prompt = (
        "You generate dbt model scaffolding from table metadata. "
        "Return JSON only. Include models with sql, descriptions, and columns."
    )
    table_payload = []
    for table in tables:
        cols = [
            {"name": col.get("name"), "type": col.get("data_type")}
            for col in table.get("columns", [])
            if col.get("name")
        ]
        table_payload.append({"table": table.get("table"), "columns": cols})
    user_payload = {
        "database": database,
        "schema": schema,
        "tables": table_payload,
        "context": context_text or "",
        "expected": {
            "models": [
                {
                    "name": "fact_sales",
                    "model_type": "fact",
                    "source_table": "fact_sales",
                    "sql": "select * from {{ source('raw', 'fact_sales') }}",
                    "description": "Auto-generated fact model",
                    "columns": [{"name": "sales_date", "description": "Date of sale"}],
                    "join_keys": ["customer_id"],
                }
            ]
        },
    }
    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or "models" not in parsed:
        return None
    return parsed


def build_scaffold_payload(
    settings: Settings,
    database: str,
    schema: str,
    tables: list[dict[str, Any]],
    context_text: str | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    llm_payload = _llm_generate_scaffold(settings, database, schema, tables, context_text) if use_llm else None
    models: list[dict[str, Any]] = []
    if llm_payload and isinstance(llm_payload.get("models"), list):
        for model in llm_payload["models"]:
            if not model.get("name") or not model.get("sql"):
                continue
            model["status"] = "draft"
            models.append(model)
    if not models:
        facts, dims = infer_models_from_scan(tables)
        for fact in facts:
            table_name = fact["name"]
            model_name = table_name if str(table_name).startswith("fact_") else f"fact_{table_name}"
            sql = "select * from {{ source('raw', '" + str(table_name) + "') }}"
            models.append(
                {
                    "name": model_name,
                    "source_table": table_name,
                    "model_type": "fact",
                    "sql": sql,
                    "description": "Auto-generated fact model",
                    "columns": [],
                    "status": "draft",
                }
            )
        for dim in dims:
            table_name = dim["name"]
            model_name = table_name if str(table_name).startswith("dim_") else f"dim_{table_name}"
            sql = "select * from {{ source('raw', '" + str(table_name) + "') }}"
            models.append(
                {
                    "name": model_name,
                    "source_table": table_name,
                    "model_type": "dim",
                    "sql": sql,
                    "description": "Auto-generated dimension model",
                    "columns": [],
                    "status": "draft",
                }
            )

    columns_by_table: dict[str, list[str]] = {}
    for table in tables:
        columns_by_table[table.get("table")] = [col.get("name") for col in table.get("columns", []) if col.get("name")]

    schema_yaml_lines = ["version: 2", "", "sources:", "  - name: raw", f"    schema: {schema}", "    tables:"]
    for table_name, cols in columns_by_table.items():
        schema_yaml_lines.append(f"      - name: {table_name}")
        if cols:
            schema_yaml_lines.append("        columns:")
            for col in cols:
                schema_yaml_lines.append(f"          - name: {col}")
    schema_yaml_lines.append("")
    schema_yaml_lines.append("models:")
    for model in models:
        schema_yaml_lines.append(f"  - name: {model['name']}")
        schema_yaml_lines.append(
            f"    description: {model.get('description') or 'Auto-generated model'}"
        )
        if model.get("columns"):
            schema_yaml_lines.append("    columns:")
            for col in model.get("columns", []):
                col_name = col.get("name")
                if not col_name:
                    continue
                desc = col.get("description") or ""
                schema_yaml_lines.append(f"      - name: {col_name}")
                if desc:
                    schema_yaml_lines.append(f"        description: {desc}")
    schema_yaml = "\n".join(schema_yaml_lines)

    return {
        "database": database,
        "schema": schema,
        "models": models,
        "schema_yaml": schema_yaml,
        "review_checklist": [
            "Verify grain and primary keys",
            "Validate joins and filters",
            "Confirm column naming and descriptions",
        ],
    }


def write_scaffold_files(dbt_project_path: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    auto_dir = Path(dbt_project_path) / "models" / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for model in payload.get("models", []):
        filename = f"{model['name']}.sql"
        file_path = auto_dir / filename
        file_path.write_text(model.get("sql", "") + "\n")
        files.append({"path": str(file_path), "model": model["name"]})
    schema_path = auto_dir / "schema.yml"
    schema_path.write_text(payload.get("schema_yaml", "") + "\n")
    files.append({"path": str(schema_path), "model": "schema.yml"})
    return files


def persist_scaffold(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str,
    database: str,
    schema: str,
    tables: list[str],
    context_id: str | None,
    payload: dict[str, Any],
) -> str:
    scaffold_id = f"scaffold_{uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_dbt_scaffolds (
          scaffold_id,
          tenant_id,
          domain_id,
          connection_id,
          database_name,
          schema_name,
          tables,
          context_id,
          status,
          payload,
          created_at,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, now(), now())
    """
    execute_non_query(
        settings,
        sql,
        [
            scaffold_id,
            tenant_id,
            domain_id,
            connection_id,
            database,
            schema,
            json.dumps(tables),
            context_id,
            payload.get("status", "draft"),
            json.dumps(payload),
        ],
    )
    return scaffold_id


def list_scaffolds(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    connection_id: str | None = None,
) -> list[dict[str, Any]]:
    filters = ["tenant_id = %s", "domain_id = %s"]
    params: list[Any] = [tenant_id, domain_id]
    if connection_id:
        filters.append("connection_id = %s")
        params.append(connection_id)
    where_clause = " AND ".join(filters)
    sql = f"""
        SELECT scaffold_id,
               connection_id,
               database_name,
               schema_name,
               tables,
               context_id,
               status,
               created_at
          FROM public.quantyx_dbt_scaffolds
         WHERE {where_clause}
         ORDER BY created_at DESC
    """
    return run_query(settings, sql, params)


def get_scaffold(settings: Settings, scaffold_id: str) -> dict[str, Any] | None:
    sql = """
        SELECT scaffold_id,
               tenant_id,
               domain_id,
               connection_id,
               database_name,
               schema_name,
               tables,
               context_id,
               status,
               payload,
               created_at,
               updated_at
          FROM public.quantyx_dbt_scaffolds
         WHERE scaffold_id = %s
    """
    rows = run_query(settings, sql, [scaffold_id])
    return rows[0] if rows else None


def update_scaffold(
    settings: Settings,
    scaffold_id: str,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
    notes: str | None = None,
) -> None:
    updates = []
    params: list[Any] = []
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if payload is not None:
        updates.append("payload = %s::jsonb")
        payload["notes"] = notes
        params.append(json.dumps(payload))
    elif notes is not None:
        updates.append("payload = jsonb_set(payload, '{notes}', %s::jsonb, true)")
        params.append(json.dumps(notes))
    if not updates:
        return
    updates.append("updated_at = now()")
    params.append(scaffold_id)
    sql = f"UPDATE public.quantyx_dbt_scaffolds SET {', '.join(updates)} WHERE scaffold_id = %s"
    execute_non_query(settings, sql, params)
