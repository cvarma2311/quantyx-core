# Phase 48: LLM-First SQL Conversation Mode

## Objective

When `CONVERSATION_LLM_SQL_MODE=true`, the LLM is a **PostgreSQL analytics agent** with full autonomy over SQL generation. It receives rich business context, compacted conversation memory, LLM-generated table descriptions, real column schemas, and the source chart SQL (if a follow-up) — and writes complete executable SQL from scratch. No metric catalog, no runtime synthesis, no query planner, no sql_builder. The LLM infers metric intent, FY date ranges, joins, and filters purely from analytical reasoning over table schemas and business context. Falls back transparently to the existing pipeline on any failure.

---

## Problem with the Current Pipeline

The existing pipeline requires metrics to be pre-defined in the catalog or synthesized via token-overlap heuristics before SQL can run. This breaks for:

- Metrics that are never named but analytically obvious ("actual vs history" when no catalog entry exists)
- Novel combinations the user invents in natural language ("FY-to-date achievement rate")
- Multi-table metrics where the model pruner drops non-fact tables
- Any domain where onboarding has not been run yet

The token-overlap synthesis (`runtime_metric_synthesis`) is deterministic but narrow — it cannot understand that `actual_tmt_sales` and `actual_history_tmt_sales` are the same column scoped to different fiscal years, or that `achievement_rate` is `actual / target * 100`.

---

## Target State

When `CONVERSATION_LLM_SQL_MODE=true`:

1. The LLM receives the full enriched context (7 layers, below) and writes complete PostgreSQL SQL
2. SQL is validated (destructive check + table scope + LIMIT injection + EXPLAIN) and executed directly
3. Results flow into `build_workspace_chart` → `_build_client_response` — **identical response shape** to the pipeline path
4. Any failure falls back silently to the existing interpret → validate → compile → query path

---

## Context Layers Sent to the LLM

### System Prompt (built dynamically per request)

Built by `_build_system_prompt(schema_name, business_context)` in `services/ai/llm_sql_direct.py`.

Contains:
- **Indian FY dates** — computed at call time from `_fy_dates()`:
  - Current FY: ISO dates + integer YYYYMMDD DAY_ID range
  - Prior FY: same format
- **Metric semantics** — `"actual"/"ytd"` → current FY, `"history"/"prior"` → prior FY, `"target"/"budget"` → target column, `"achievement"` → actual/target×100, multi-table → LEFT JOIN
- **SQL rules** — double-quote identifiers, schema-prefix tables, `ROUND(SUM(...)::numeric, 2)`, mandatory filters, always LIMIT, preserve source chart filters
- **Business context text** — from `_business_context_text` (tenant/domain onboarding context)

### User Message (built per request)

Built by `_build_user_message(...)` in `services/ai/llm_sql_direct.py`. Assembled in order:

**Layer 1 — Conversation history**
From `memory.get("summary_text")` (compacted by `upsert_workspace_memory`):
```
CONVERSATION HISTORY:
User has been exploring SBU-wise sales. Last question asked for actual vs target TMT sales for Lubes.
```

**Layer 2 — User question**
```
USER QUESTION:
break this down by zone for WZ
```

**Layer 3 — Table schemas**
Built by `_build_table_schemas(intelligence_bundle)` from `intelligence_bundle.table_profile_artifact`:
```json
{
  "tables": {
    "MOM_DAY_LEVEL_DATA": {
      "description": "Daily sales dispatch records with volume data by SBU, Zone, Region and Product.",
      "columns": {
        "DAY_ID":        "date/time key",
        "NETWEIGHT_TMT": "numeric measure",
        "SBU_Name":      "dimension",
        "Zone":          "dimension",
        "Region":        "dimension",
        "SalesArea":     "dimension",
        "ProductGroup":  "dimension"
      },
      "time_columns": [],
      "mandatory_filter": "\"SBU_Name\" IS NOT NULL AND \"SBU_Name\" != '0' AND \"SBU_Name\" NOT IN ('Common','Mumbai Ref','Renewable Energy','Visakh Ref')"
    },
    "M60_LEVEL_METADATA": {
      "description": "Monthly target and pace metadata by SBU, Zone and Region.",
      "columns": {
        "year_monthname":  "date/time key",
        "month_name":      "dimension",
        "TARGET_QTY_TMT":  "numeric measure",
        "PACE_QTY_TMT":    "numeric measure",
        "SBU_Name":        "dimension",
        "Zone":            "dimension"
      },
      "time_columns": ["year_monthname"],
      "mandatory_filter": "\"SBU_Name\" IS NOT NULL AND \"SBU_Name\" != '0' AND \"SBU_Name\" NOT IN ('Common','Mumbai Ref','Renewable Energy','Visakh Ref')"
    }
  },
  "join_hints": [
    {
      "left": "MOM_DAY_LEVEL_DATA",
      "right": "M60_LEVEL_METADATA",
      "on": "...",
      "type": "LEFT JOIN"
    }
  ]
}
```

**Description fallback** — if no LLM description was generated during profiling, `_build_table_schemas` derives a plain hint from column names:
```
MOM_DAY_LEVEL_DATA — measures: NETWEIGHT_TMT; dimensions: SBU_Name, Zone, Region, SalesArea
```

**Layer 4 — Source chart SQL** (chart follow-ups only)
From `_resolve_chart_conversation_context` — the existing chart's SQL, metrics, dimensions:
```
SOURCE CHART (extend or refine — preserve FY filters and mandatory filters):
{
  "question": "comparison between actual_tmt_sales, actual_history_tmt_sales and target_tmt_sales for SBU_Name = Lubes",
  "sql": "SELECT \"SBU_Name\", SUM(CASE WHEN ...) AS actual_tmt_sales ...",
  "chart_type": "bar",
  "metrics": ["actual_tmt_sales", "actual_history_tmt_sales", "target_tmt_sales"],
  "dimensions": ["SBU_Name"]
}
```

**Layer 5 — Selected context** (if user clicked on chart)
From `_extract_chart_followup_context`:
```
SELECTED CONTEXT (user clicked on chart):
{ "selected_category": "WZ" }
```

---

## LLM Output Contract

OpenAI JSON mode (`response_format: {"type": "json_object"}`), temperature 0.1:

```json
{
  "sql":        "<complete executable PostgreSQL SELECT>",
  "chart_type": "grouped_bar",
  "title":      "Zone-wise TMT Sales Comparison — WZ",
  "metrics":    ["actual_tmt_sales", "actual_history_tmt_sales", "target_tmt_sales"],
  "dimensions": ["Zone"],
  "reasoning":  "Drilled into Zone for SBU_Name=WZ; preserved CASE WHEN FY filters and mandatory SBU_Name exclusions."
}
```

Fields:
- `sql` — full executable SQL including schema prefixes, FY CASE WHEN filters, mandatory filters, LIMIT
- `chart_type` — `bar | grouped_bar | line | pie | table` — used as `preferred_chart_type` in `build_workspace_chart`
- `title` — used as `chart_title` in response payload
- `metrics` — SELECT column aliases → populate `query_result.metrics` → drive chart series + follow-up requests
- `dimensions` — GROUP BY columns → populate `query_result.dimensions` → drive chart axis + drill-down
- `reasoning` — logged via `[llm_sql] validated` log line, not sent to client

---

## Flow

```
POST /workspace/conversations/{conversation_id}/messages
        ↓
[existing] _resolve_chart_conversation_context()    ← DB lookup for source chart SQL
[existing] _extract_chart_followup_context()        ← selected_category, selected_time_value
[existing] _load_run_scoped_intelligence(...)        ← loads intelligence_bundle (profiling, joins)
        ↓
[CONVERSATION_LLM_SQL_MODE=true?]
        ↓ YES
llm_direct_sql(                                     ← services/ai/llm_sql_direct.py
    user_query=raw_user_query,
    conversation_memory=memory.get("summary_text"),
    business_context=_business_context_text,
    intelligence_bundle=intelligence_bundle,
    chart_context=chart_context,
    chart_followup_context=chart_followup_context,
    schema_name=schema_name,
    settings=settings,
)
  internally:
    _build_system_prompt()        ← FY dates, metric semantics, SQL rules, business context
    _build_table_schemas()        ← columns + roles + descriptions + join hints
    _build_user_message()         ← conv memory + question + schemas + source chart + selected
    → OpenAI API call (JSON mode)
    _validate_and_clean()         ← destructive check + table scope + LIMIT injection + EXPLAIN
        ↓ returns validated sql dict  OR  None on any failure
        ↓ None → fall through to existing pipeline (silent)
        ↓ valid
run_query(sql, [])                                  ← direct DB execution
QueryResult(metrics, dimensions, sql, rows)
        ↓
[existing] build_workspace_chart(rows, metric_names, dimensions, preferred_chart_type)
[existing] _persist_workspace_chart_artifact(...)
[existing] _build_client_response(response_payload)
        ↓
return (response_payload, assistant_text, summary_json, inference_json)
```

The entire `interpret_workspace_query → validate_workspace_query_plan → compile_workspace_query_plan → sql_builder.build_query → query(QueryRequest(...))` chain is **bypassed** in LLM-first mode.

---

## Table Description Generation (ProfilingAgent)

During every agentic run, `profile_tables` in `services/ai/agentic_agents.py` now calls `_generate_table_descriptions` after the main profiling loop.

**One batched LLM call** receives all tables with:
- Table name
- Column names + semantic roles (`measure_additive`, `dimension_attribute`, `time_dimension`, etc.)
- Row count
- Up to 5 sample categorical values per column

Returns `{"descriptions": {"TABLE_NAME": "one-sentence description", ...}}`.

Each description is stored in `profiling_json.tables[*].description` inside `quantyx_table_profile_artifacts`.

**Description resolution in `_build_table_schemas`:**
1. Use `tbl.get("description")` if non-empty (from profiling LLM call)
2. Fallback: derive from column names — `"TABLE — measures: COL1, COL2; dimensions: COL3, COL4"`

This means:
- Fresh profiling run → LLM descriptions stored and used
- Old artifacts without descriptions → fallback, no re-run needed
- No API key → `_generate_table_descriptions` returns `{}` immediately → fallback used

---

## Validation Layer (`_validate_and_clean`)

In `services/ai/llm_sql_direct.py`:

| Check | Action on Failure |
|-------|-------------------|
| `response.get("sql")` is non-empty | Return `None` → fallback |
| Matches `DROP\|DELETE\|INSERT\|UPDATE\|TRUNCATE\|ALTER\|CREATE` | Raise `LLMSqlValidationError` → fallback |
| All FROM/JOIN tables are in `known_tables` (case-insensitive) | Raise → fallback |
| `LIMIT` absent | Inject `LIMIT 200`, do not fallback |
| `EXPLAIN {sql}` on DB | Raise → fallback |

`known_tables` is derived from `table_schemas.get("tables", {}).keys()` — i.e. only tables that exist in the profiling artifact are allowed.

---

## Fallback Triggers

The existing pipeline runs if any of:
- `CONVERSATION_LLM_SQL_MODE=false` (default)
- No `openai_api_key` configured
- `intelligence_bundle.table_profile_artifact` is empty → `known_tables` is empty → early return `None`
- LLM call raises any exception (timeout, network, API error)
- LLM response fails JSON parse or has no `sql` field
- `_validate_and_clean` raises `LLMSqlValidationError`
- `run_query` raises after validation (DB error on generated SQL)

All fallback paths log a `[llm_sql]` warning and silently continue to the pipeline.

---

## Client Response Shape

`_build_client_response(response_payload)` in `services/api/main.py` — **identical output** regardless of which path ran:

```python
{
    "chart_id":      str,           # persisted chart artifact ID
    "chart_type":    str,           # bar, grouped_bar, line, pie, table
    "chart_title":   str,           # from LLM title or workspace_chart_title()
    "chart_payload": dict | None,   # chart rendering spec
    "sql":           str,           # executed SQL
    "metrics":       list[str],     # SELECT aliases
    "dimensions":    list[str],     # GROUP BY columns
    "rows":          list[dict],    # raw DB rows
    "chart_followup": {
        "source_chart_id":  str,
        "derived_chart_id": str,
        "follow_up_intent": str,    # "llm_agent" for LLM path
        "selected_context": dict,
    } | None,
}
```

Outer HTTP response:
```python
{
    "conversation_id": str,
    "message_id":      str,
    "response":        dict,    # slim response above
    "context_used":    { "resume_context": bool, "run_id": str },
}
```

Internal fields kept in `response_payload` for DB persistence but not sent to client: `conversation_plan` (contains `sql_mode: "llm_agent"` for LLM path), `lineage`, `artifact_lineage`, `dashboard_title`, `data`, `summary_json`, `inference_json`.

---

## What the LLM Handles Autonomously

| Scenario | LLM behaviour |
|----------|--------------|
| Metric exists in catalog | Copies or re-derives from source chart SQL |
| Metric not in catalog | Derives from column names + business context + FY semantics in system prompt |
| `actual` vs `history` disambiguation | Current FY vs prior FY BETWEEN ranges from system prompt |
| Multi-table metric (actual + target) | LEFT JOIN using join hints; CASE WHEN per metric |
| Novel computed metric ("achievement rate") | `ROUND(actual / NULLIF(target, 0) * 100, 2)` inline |
| Drill-down follow-up ("break by Zone for WZ") | Adds `WHERE SBU_Name = 'WZ'`, changes GROUP BY to Zone |
| Filter follow-up ("only show Lubes") | Adds filter, keeps GROUP BY and metrics unchanged |
| Mandatory filter | Applied per system prompt rule + validated by table scope check |

---

## Environment Variables

```bash
CONVERSATION_LLM_SQL_MODE=true       # default: false — opt-in per deployment
CONVERSATION_LLM_SQL_MODEL=gpt-4o    # default: inherits OPENAI_MODEL
                                     # recommend gpt-4o for SQL correctness
CONVERSATION_LLM_SQL_TIMEOUT=20      # seconds, default: 20
```

---

## Token Budget

| Context block | Est. tokens | Source |
|---------------|------------|--------|
| System prompt (FY + semantics + SQL rules) | ~400 | `_build_system_prompt` |
| Business context text | ~200–500 | Onboarding context |
| Conversation memory | ~100–300 | `upsert_workspace_memory` compacted |
| Table schemas (columns + descriptions + join hints) | ~300–600 | `_build_table_schemas` |
| Source chart SQL | ~200–500 | `_resolve_chart_conversation_context` |
| User question + selected context | ~50–100 | Request payload |
| **Total** | **~1500–2500** | Response: ~400–700 tokens |

---

## Files Changed

| File | Change |
|------|--------|
| `services/ai/llm_sql_direct.py` | **New** — full LLM SQL agent module |
| `services/ai/agentic_agents.py` | Added `_generate_table_descriptions` + `description` field in profiling output |
| `services/api/main.py` | `_workspace_query_response`: new params + LLM branch; `_build_client_response`: slim response; both call sites updated; streaming path cleaned up |

### `services/ai/llm_sql_direct.py` (new)
- `is_llm_sql_mode_enabled()` — reads `CONVERSATION_LLM_SQL_MODE`
- `_fy_dates()` — current + prior Indian FY in YYYYMMDD and ISO
- `_build_system_prompt(schema_name, business_context)` — static prompt with FY, semantics, SQL rules
- `_build_table_schemas(intelligence_bundle)` — columns + semantic roles + descriptions + join hints
- `_build_user_message(...)` — assembles 5-layer user message
- `LLMSqlValidationError` — exception class
- `_validate_and_clean(response, known_tables, settings)` — destructive check + scope + LIMIT + EXPLAIN
- `llm_direct_sql(...)` — main entry point, returns validated dict or `None`

### `services/ai/agentic_agents.py` (modified)
- Added `json`, `urllib.request` imports
- `_generate_table_descriptions(settings, tables_data)` — one batched LLM call for all tables
- `profile_tables` — adds `"description": ""` to each table dict; calls `_generate_table_descriptions` after loop and injects results

### `services/api/main.py` (modified)
- `_workspace_query_response` — 4 new optional params: `chart_followup_context`, `raw_user_query`, `conversation_memory_text`, `business_context_text`
- LLM branch inserted before existing pipeline; on success executes SQL, builds `QueryResult`, calls `build_workspace_chart`, persists chart, returns early
- `_build_client_response(response_payload)` — new helper that strips internal fields; only 9 essential keys sent to client
- Both sync and streaming call sites pass new params
- Streaming `artifact` events trimmed to single `response` event with slim payload

---

## Success Criteria

- Metrics not in the catalog answered correctly without onboarding
- `actual_tmt_sales` and `actual_history_tmt_sales` produce different row values (correct FY scoping)
- Novel metrics like `achievement_rate` work without any catalog entry
- All mandatory filters present in 100% of LLM-generated queries
- Table descriptions generated and stored during profiling runs; fallback works for old artifacts
- Response payload shape identical to pipeline path — zero client changes needed
- Fallback rate < 10% in normal usage

---

## Dependencies

- **Phase 34** — Agent artifact persistence (`quantyx_table_profile_artifacts`; profiling artifact with table schemas, column semantics, descriptions)
- **Phase 39** — LLM-first workspace query interpretation (the pipeline this mode bypasses)
- **Phase 41** — Chart conversation and follow-up analytics (`_resolve_chart_conversation_context`, `_extract_chart_followup_context`, source chart SQL retrieval)
- **Phase 42** — Chart-based conversations (`quantyx_workspace_memory` for compacted conversation context)
- **Phase 47** — LLM chart discovery (established `CHART_DISCOVERY_MODE` env-flag architecture; this phase follows the same opt-in pattern with `CONVERSATION_LLM_SQL_MODE`)