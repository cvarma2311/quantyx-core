from __future__ import annotations

import re
from typing import Any


def extract_scope_from_metadata(metadata: dict | None) -> dict[str, Any]:
    metadata = metadata or {}
    return {
        "connection_id": metadata.get("connection_id"),
        "database": metadata.get("database") or metadata.get("database_name"),
        "schema": metadata.get("schema") or metadata.get("schema_name"),
        "tables": metadata.get("tables"),
    }


def validate_scope_fields(scope: dict | None) -> list[str]:
    scope = scope or {}
    missing = []
    for key in ("connection_id", "database", "schema"):
        if not scope.get(key):
            missing.append(key)
    tables = scope.get("tables")
    if not isinstance(tables, list) or not tables:
        missing.append("tables")
    return missing


def scopes_match(existing: dict | None, updated: dict | None) -> bool:
    if not updated:
        return True
    existing_scope = extract_scope_from_metadata(existing)
    updated_scope = extract_scope_from_metadata(updated)
    return existing_scope == updated_scope


def generate_source_title(raw_text: str | None, metadata: dict | None) -> str:
    if raw_text:
        words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", raw_text)
        if words:
            title = " ".join(words[:8])
            return title[:80]

    meta = metadata or {}
    fallback_parts = []
    for key in ("connection_id", "database", "schema"):
        value = meta.get(key)
        if value:
            fallback_parts.append(str(value))
    tables = meta.get("tables")
    if isinstance(tables, list) and tables:
        fallback_parts.append(",".join(tables[:2]))
    if fallback_parts:
        return " ".join(fallback_parts)[:80]
    return "Business context"
