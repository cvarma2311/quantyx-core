from __future__ import annotations

import re
def generate_source_title(raw_text: str | None, metadata: dict | None) -> str:
    if raw_text:
        words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", raw_text)
        if words:
            title = " ".join(words[:8])
            return title[:80]

    meta = metadata or {}
    fallback_parts = []
    columns = meta.get("columns")
    if isinstance(columns, list) and columns:
        fallback_parts.append(",".join(columns[:2]))
    tables = meta.get("tables")
    if isinstance(tables, list) and tables:
        fallback_parts.append(",".join(tables[:2]))
    if fallback_parts:
        return " ".join(fallback_parts)[:80]
    return "Business context"
