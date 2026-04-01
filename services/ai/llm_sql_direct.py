"""
LLM-first SQL agent for workspace conversation messages.

When CONVERSATION_LLM_SQL_MODE=true this module replaces the entire
interpret → validate → compile → sql_builder pipeline with a single
LLM call that receives rich business context and writes complete
PostgreSQL SQL directly.

The LLM infers metric intent, FY date ranges, joins, and filters from:
  - Table schemas (actual column names + semantic roles from profiling artifact)
  - Source chart SQL (if a chart follow-up — highest-signal context)
  - Compacted conversation memory
  - Business context text
  - System prompt with Indian FY rules, mandatory filter conventions, SQL style
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.ai.config import Settings

logger = logging.getLogger(__name__)

_MODE_ENV = "CONVERSATION_LLM_SQL_MODE"
_MODEL_ENV = "CONVERSATION_LLM_SQL_MODEL"
_TIMEOUT_ENV = "CONVERSATION_LLM_SQL_TIMEOUT"


def is_llm_sql_mode_enabled() -> bool:
    return os.getenv(_MODE_ENV, "").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Fiscal year helpers
# ---------------------------------------------------------------------------

def _fy_dates() -> dict[str, str]:
    """Return current and prior Indian FY date strings (YYYYMMDD and ISO)."""
    today = date.today()
    y = today.year if today.month >= 4 else today.year - 1
    return {
        "cur_s": f"{y}0401",
        "cur_e": f"{y + 1}0331",
        "cur_s_iso": f"{y}-04-01",
        "cur_e_iso": f"{y + 1}-03-31",
        "pri_s": f"{y - 1}0401",
        "pri_e": f"{y}0331",
        "pri_s_iso": f"{y - 1}-04-01",
        "pri_e_iso": f"{y}-03-31",
    }


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_system_prompt(*, schema_name: str, business_context: str | None) -> str:
    f = _fy_dates()
    biz = f"\nBUSINESS CONTEXT:\n{business_context}\n" if business_context else ""
    return f"""You are a PostgreSQL analytics SQL agent. Given a user question and table schemas, write a single correct executable PostgreSQL SELECT query.

SCHEMA: {schema_name}

FISCAL YEAR (Indian FY — April 1 to March 31):
  Current FY : {f['cur_s_iso']} to {f['cur_e_iso']}
               DAY_ID integer range  : '{f['cur_s']}' to '{f['cur_e']}'
  Prior FY   : {f['pri_s_iso']} to {f['pri_e_iso']}
               DAY_ID integer range  : '{f['pri_s']}' to '{f['pri_e']}'
{biz}
METRIC SEMANTICS — infer from the question + column context:
  "actual" / "ytd" / "current"        → SUM(measure) filtered by current-FY DAY_ID range
  "history" / "prior" / "last year"   → SUM(measure) filtered by prior-FY DAY_ID range
  "target" / "budget" / "plan"        → SUM(target_measure) filtered by current-FY year_monthname range
  "achievement" / "attainment"        → ROUND(actual_expr / NULLIF(target_expr, 0) * 100, 2)
  Multiple metrics from same table    → CASE WHEN per metric in one query
  Multiple metrics from different tables → CTE per metric, then join (see CTE PATTERN below)

CTE PATTERN for cross-table metrics (MANDATORY when metrics span multiple tables):
  Never JOIN tables of different grains directly — it causes row fan-out.
  Instead, aggregate each metric in its own CTE, then CROSS JOIN the scalar results.
  Do NOT add GROUP BY month or any time dimension unless the user explicitly asks for a trend or monthly breakdown.

  Default (scalar — one row of all metrics):
    WITH cte_actual AS (
      SELECT ROUND(SUM(m."NETWEIGHT_TMT")::numeric, 2) AS actual_tmt
      FROM {schema_name}."MOM_DAY_LEVEL_DATA" m
      WHERE m."DAY_ID"::varchar BETWEEN '...' AND '...'
    ),
    cte_history AS (
      SELECT ROUND(SUM(m."NETWEIGHT_TMT")::numeric, 2) AS history_tmt
      FROM {schema_name}."MOM_DAY_LEVEL_DATA" m
      WHERE m."DAY_ID"::varchar BETWEEN '...' AND '...'
    ),
    cte_target AS (
      SELECT ROUND(SUM(t."TARGET_QTY_TMT")::numeric, 2) AS target_tmt
      FROM {schema_name}."M60_LEVEL_METADATA" t
      WHERE t."year_monthname"::date BETWEEN '...' AND '...'
    )
    SELECT a.actual_tmt, h.history_tmt, t.target_tmt
    FROM cte_actual a CROSS JOIN cte_history h CROSS JOIN cte_target t

  Only use GROUP BY + FULL OUTER JOIN when the user explicitly requests a monthly trend, by-zone, or by-SBU breakdown.

SQL RULES:
  1. Always double-quote column and table identifiers: "SBU_Name", "NETWEIGHT_TMT"
  2. Always prefix tables with schema and use EXACTLY the table name as it appears in TABLE SCHEMAS (case-sensitive): {schema_name}."exact_table_name"
  3. Aggregations: ROUND(SUM("col")::numeric, 2) AS alias_name
  4. DAY_ID is a BIGINT storing YYYYMMDD — always cast to varchar before any date function:
     Filter  : "DAY_ID"::varchar BETWEEN '{f['cur_s']}' AND '{f['cur_e']}'
     To date : TO_DATE("DAY_ID"::varchar, 'YYYYMMDD')   ← REQUIRED cast, never TO_DATE("DAY_ID", ...)
     To month: DATE_TRUNC('month', TO_DATE("DAY_ID"::varchar, 'YYYYMMDD'))
  5. year_monthname is DATE-castable — filter: "year_monthname"::date BETWEEN '2025-04-01' AND '2026-03-31'
  6. Apply every mandatory_filter listed in the TABLE SCHEMAS block to every referenced table
  7. Always include LIMIT (default 200, max 500)
  8. If a SOURCE CHART is provided, extend or refine that SQL — do not discard its FY filters or mandatory filters
  9. Never use DROP, DELETE, INSERT, UPDATE, TRUNCATE

Return ONLY valid JSON (no markdown, no explanation outside the JSON):
{{
  "sql":        "<complete executable PostgreSQL SELECT or CTE>",
  "chart_type": "<bar|grouped_bar|line|pie|table>",
  "title":      "<concise chart title>",
  "metrics":    ["<select_alias1>", "<select_alias2>"],
  "dimensions": ["<group_by_col1>"],
  "reasoning":  "<one sentence: what you did and why>"
}}"""


def _build_table_schemas(
    intelligence_bundle: dict[str, Any],
) -> dict[str, Any]:
    """
    Build a lean table_schemas dict for the LLM user message:
      { "tables": { TABLE: { columns: {col: role}, mandatory_filter, time_columns } },
        "join_hints": [...] }
    """
    profiling: dict = (intelligence_bundle or {}).get("table_profile_artifact") or {}
    tables_raw: list[dict] = profiling.get("tables") or []

    tables_out: dict[str, Any] = {}
    for tbl in tables_raw:
        name = str(tbl.get("name") or "").strip()
        if not name:
            continue

        numeric: set[str] = set(
            (tbl.get("eligible_numeric_columns") or []) + (tbl.get("numeric_columns") or [])
        )
        time_cols: list[str] = tbl.get("time_columns") or []
        time_set: set[str] = set(time_cols)
        all_cols: list[str] = list(dict.fromkeys(
            (tbl.get("columns") or [])
            + list(numeric)
            + time_cols
            + (tbl.get("dimension_columns") or [])
        ))
        col_sem: dict[str, dict] = {
            s["name"]: s for s in (tbl.get("column_semantics") or []) if s.get("name")
        }

        # Pattern for integer YYYYMMDD date columns (e.g. DAY_ID, DATE_ID)
        _day_id_pat = re.compile(r"(?i)^(day[_\s]?id|date[_\s]?id|day|date[_\s]?key)$")

        annotated: dict[str, str] = {}
        for col in all_cols:
            if col in time_set:
                annotated[col] = "date/time key"
            elif _day_id_pat.match(col):
                annotated[col] = "integer date key (YYYYMMDD stored as bigint — always cast to varchar before date functions: \"DAY_ID\"::varchar)"
            elif col_sem.get(col, {}).get("eligible_measure") or col in numeric:
                annotated[col] = "numeric measure"
            else:
                annotated[col] = "dimension"

        # Description: use LLM-generated value from profiling if present,
        # otherwise derive a plain hint from column names so the LLM agent
        # still has something meaningful to reason over.
        description: str = (tbl.get("description") or "").strip()
        if not description:
            measure_cols = [c for c, r in annotated.items() if r == "numeric measure"]
            dim_cols = [c for c, r in annotated.items() if r == "dimension"]
            parts: list[str] = []
            if measure_cols:
                parts.append(f"measures: {', '.join(measure_cols[:4])}")
            if dim_cols:
                parts.append(f"dimensions: {', '.join(dim_cols[:4])}")
            description = f"{name} — " + "; ".join(parts) if parts else name

        tables_out[name] = {
            "description": description,
            "columns": annotated,
            "time_columns": time_cols,
            "mandatory_filter": tbl.get("mandatory_filter") or "",
        }

    # Join hints from the join registry
    join_hints: list[dict] = []
    for j in ((intelligence_bundle or {}).get("joins") or []):
        lft = str(j.get("left_table") or j.get("left") or "").strip()
        rgt = str(j.get("right_table") or j.get("right") or "").strip()
        on_clause = str(j.get("join_condition") or j.get("on") or "").strip()
        jtype = str(j.get("join_type") or j.get("type") or "LEFT JOIN").strip()
        if lft and rgt and on_clause:
            join_hints.append({"left": lft, "right": rgt, "on": on_clause, "type": jtype})

    return {"tables": tables_out, "join_hints": join_hints}


def _build_user_message(
    *,
    user_query: str,
    conversation_memory: str | None,
    table_schemas: dict[str, Any],
    chart_context: dict[str, Any] | None,
    chart_followup_context: dict[str, Any] | None,
) -> str:
    parts: list[str] = []

    if conversation_memory:
        parts.append(f"CONVERSATION HISTORY:\n{conversation_memory}")

    parts.append(f"USER QUESTION:\n{user_query}")

    parts.append(f"TABLE SCHEMAS:\n{json.dumps(table_schemas, indent=2, default=str)}")

    if chart_context and chart_context.get("sql"):
        source_block: dict[str, Any] = {
            "question":   chart_context.get("chart_title") or chart_context.get("source_chart_id"),
            "sql":        chart_context.get("sql"),
            "chart_type": chart_context.get("chart_type"),
            "metrics":    chart_context.get("metrics") or [],
            "dimensions": chart_context.get("dimensions") or [],
        }
        parts.append(
            "SOURCE CHART (extend or refine — preserve FY filters and mandatory filters):\n"
            + json.dumps(source_block, indent=2, default=str)
        )

    if chart_followup_context:
        selected = {k: v for k, v in chart_followup_context.items() if k != "chart_id" and v not in (None, "", [])}
        if selected:
            parts.append(f"SELECTED CONTEXT (user clicked on chart):\n{json.dumps(selected, indent=2, default=str)}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Multi-query merge
# ---------------------------------------------------------------------------

def _merge_query_rows(
    query_results: list[tuple[list[str], list[dict]]],
    dimensions: list[str],
) -> list[dict]:
    """
    Merge rows from multiple independent queries on shared dimension columns.

    Each entry in query_results is (metrics_list, rows). Rows from each query are
    keyed by the tuple of dimension values; metric columns are unioned into one row.
    Missing metric values for a dimension key are left as None.
    """
    merged: dict[tuple, dict] = {}
    for metrics, rows in query_results:
        for row in rows:
            key = tuple(row.get(d) for d in dimensions)
            if key not in merged:
                merged[key] = {d: row.get(d) for d in dimensions}
            for m in metrics:
                if m in row:
                    merged[key][m] = row[m]
    return list(merged.values())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class LLMSqlValidationError(Exception):
    pass


_TABLE_REF_RE = re.compile(
    r'(?:FROM|JOIN)\s+(?:"?[a-zA-Z_][a-zA-Z0-9_]*"?\.)?"?([a-zA-Z_][a-zA-Z0-9_]*)"?',
    re.IGNORECASE,
)
_DESTRUCTIVE_RE = re.compile(
    r'^\s*(DROP|DELETE|INSERT|UPDATE|TRUNCATE|ALTER|CREATE)\b',
    re.IGNORECASE,
)


def _validate_and_clean(
    response: dict[str, Any],
    *,
    known_tables: set[str],
    table_schemas: dict[str, Any],
    settings: "Settings",
    scoped_conn: Any = None,
) -> str:
    """Validate, sanitise, and return the cleaned SQL string."""
    from services.ai.db import run_query

    sql: str = str(response.get("sql") or "").strip().rstrip(";").strip()
    if not sql:
        raise LLMSqlValidationError("empty sql in LLM response")

    if _DESTRUCTIVE_RE.match(sql):
        raise LLMSqlValidationError("destructive statement rejected")

    # Table scope check + case correction
    # Build a lowercase→canonical map so we can fix wrong-case table refs the LLM wrote
    canonical_map: dict[str, str] = {t.lower(): t for t in known_tables}
    # Extract CTE names — any identifier immediately followed by AS ( is a virtual table,
    # not a real DB table, so exclude it from the unknown-table check.
    cte_names: set[str] = {
        m.group(1).lower()
        for m in re.finditer(r'\b(\w+)\s+AS\s*\(', sql, re.IGNORECASE)
    }
    referenced = {m.group(1).strip('"').lower() for m in _TABLE_REF_RE.finditer(sql)}
    # Exclude CTE names — they are virtual tables defined in the same query
    unknown = referenced - set(canonical_map.keys()) - cte_names
    if unknown:
        raise LLMSqlValidationError(f"unknown tables in SQL: {unknown}")
    # Replace any wrong-case table references with the canonical DB name (case-insensitive match)
    # This handles e.g. LLM writing "MOM_DAY_LEVEL_DATA" when the real table is "mom_day_level_data"
    # Only correct real table names — skip CTE names which are not in canonical_map.
    for ref_lower in referenced - cte_names:
        canonical = canonical_map[ref_lower]
        # Always replace: quoted form "ANY_CASE" → "canonical"
        sql = re.sub(
            r'"' + re.escape(ref_lower) + r'"',
            f'"{canonical}"',
            sql,
            flags=re.IGNORECASE,
        )
        # Also replace unquoted references that are not inside quotes
        sql = re.sub(
            r'(?<!["\w])' + re.escape(ref_lower) + r'(?!["\w])',
            f'"{canonical}"',
            sql,
            flags=re.IGNORECASE,
        )

    # Mandatory filter check — each referenced table's mandatory_filter must appear in SQL
    tables_meta: dict[str, Any] = table_schemas.get("tables") or {}
    for tbl_name, tbl_info in tables_meta.items():
        if tbl_name.lower() not in referenced:
            continue
        mf: str = (tbl_info.get("mandatory_filter") or "").strip()
        if not mf:
            continue
        # Extract the key condition token (e.g. column name) to check presence
        # Use the first identifier-like token from the filter string
        mf_token = re.split(r'[\s=<>!\'\"(]', mf)[0].strip('"').strip("'")
        if mf_token and mf_token.lower() not in sql.lower():
            logger.warning(
                "[llm_sql] mandatory_filter token '%s' missing from SQL for table %s — filter: %s",
                mf_token, tbl_name, mf,
            )
            raise LLMSqlValidationError(
                f"mandatory_filter not applied for table {tbl_name!r}: expected token {mf_token!r}"
            )

    # Inject LIMIT if absent
    if not re.search(r'\bLIMIT\b', sql, re.IGNORECASE):
        sql = sql + "\nLIMIT 200"

    # EXPLAIN check — catches syntax errors and bad column refs
    # Use scoped_conn so EXPLAIN runs against the tenant's actual database, not the metadata DB
    try:
        run_query(settings, f"EXPLAIN {sql}", [], scoped_conn=scoped_conn)
    except Exception as exc:
        logger.warning("[llm_sql] EXPLAIN failed — sql:\n%s\nerror: %s", sql, exc)
        raise LLMSqlValidationError(f"EXPLAIN failed: {exc}") from exc

    return sql


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def llm_direct_sql(
    *,
    user_query: str,
    conversation_memory: str | None,
    business_context: str | None,
    intelligence_bundle: dict[str, Any],
    chart_context: dict[str, Any] | None,
    chart_followup_context: dict[str, Any] | None,
    schema_name: str,
    settings: "Settings",
    scoped_conn: Any = None,
) -> dict[str, Any] | None:
    """
    Call the LLM SQL agent. Returns a validated dict:
      { sql, chart_type, title, metrics, dimensions, reasoning }
    or None if anything fails (caller falls back to the existing pipeline).
    """
    if not getattr(settings, "openai_api_key", None):
        return None

    model = os.getenv(_MODEL_ENV) or getattr(settings, "openai_model", "gpt-4o-mini")
    timeout_sec = int(os.getenv(_TIMEOUT_ENV, "20"))

    table_schemas = _build_table_schemas(intelligence_bundle)
    known_tables: set[str] = set(table_schemas.get("tables", {}).keys())

    if not known_tables:
        logger.warning("[llm_sql] no table schemas available — skipping LLM path")
        return None

    system_prompt = _build_system_prompt(
        schema_name=schema_name,
        business_context=business_context,
    )
    user_message = _build_user_message(
        user_query=user_query,
        conversation_memory=conversation_memory,
        table_schemas=table_schemas,
        chart_context=chart_context,
        chart_followup_context=chart_followup_context,
    )

    logger.info(
        "[llm_sql] REQUEST ▸ business_context_present=%s system_prompt_len=%d user_message_len=%d",
        bool(business_context),
        len(system_prompt),
        len(user_message),
    )
    logger.info("[llm_sql] SYSTEM PROMPT:\n%s", system_prompt)
    logger.info("[llm_sql] USER MESSAGE:\n%s", user_message)

    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        },
        default=str,
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    logger.info("[llm_sql] calling LLM model=%s timeout=%ds", model, timeout_sec)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        logger.info("[llm_sql] LLM RESPONSE (raw):\n%s", content)
        response = json.loads(content)
    except Exception as exc:
        logger.warning("[llm_sql] LLM call failed: %s", exc)
        return None

    if not isinstance(response, dict) or not response.get("sql"):
        logger.warning("[llm_sql] unexpected response shape: %s", str(response)[:300])
        return None

    logger.info("[llm_sql] parsed sql: %s", str(response.get("sql") or "")[:500])

    try:
        clean_sql = _validate_and_clean(
            response,
            known_tables=known_tables,
            table_schemas=table_schemas,
            settings=settings,
            scoped_conn=scoped_conn,
        )
    except LLMSqlValidationError as exc:
        logger.warning("[llm_sql] validation failed (%s) — falling back to pipeline", exc)
        return None

    response["sql"] = clean_sql
    logger.info(
        "[llm_sql] validated | model=%s metrics=%s dims=%s chart_type=%s reasoning=%s",
        model,
        response.get("metrics"),
        response.get("dimensions"),
        response.get("chart_type"),
        (response.get("reasoning") or "")[:120],
    )
    return response