# Phase 47 — LLM Chart Discovery: Data-Aware Dashboard Intelligence

## Overview

The current dashboard generation pipeline is **metric-first and schema-only**: it proposes
metrics from column names + formulas, picks breakdowns generically, and generates SQL without
ever seeing actual data values. This limits chart quality across all domains — the LLM cannot
leverage real data patterns, business filter semantics, or column value distributions.

Phase 47 introduces a **LLM Chart Discovery** mode with two key capabilities:

1. **Static context** — sample rows and distinct values are fetched upfront and sent to the LLM
2. **Agentic data queries** — the LLM can call a `query_data` tool to run exploratory SQL against
   the live database. The app executes the query and returns up to 50 rows. The LLM can make
   multiple tool calls before proposing its final charts.

All LLM-executed queries are enforced with `LIMIT 50`. All dates in proposed chart SQL must
be dynamic (using `CURRENT_DATE`, `INTERVAL`, `DATE_TRUNC` — never hardcoded dates).

The feature is **fully switchable** via `CHART_DISCOVERY_MODE` env variable.

---

## Problem Statement

### Current pipeline

```
Context → MetricAgent (formula from column names) → ChartPlannerAgent (generic breakdown)
       → SQL builder (formula + dimension) → chart
```

### What the LLM never sees today

| Missing input | Consequence |
|---|---|
| Actual row values | Cannot map codes to business labels or understand enum distributions |
| Distinct values per column | Picks low-cardinality columns as breakdowns without knowledge of actual values |
| Column value cardinality | Treats a column with 3 values the same as one with 5000 |
| Cross-table relationships | Cannot identify useful JOINs from schema alone |
| Business filter semantics | Doesn't know which column+value combinations define valid business events |
| Data date range | Doesn't know whether data spans 7 days or 3 years |

### What good charts look like (domain-agnostic examples)

For any domain with transactional data, the ideal charts include:

1. **Trend over time by category** — multi-series line grouped by a meaningful categorical column
2. **Monthly/weekly aggregation** — `DATE_TRUNC` + `SUM`/`COUNT` over the primary metric
3. **Status/category breakdown** — `GROUP BY` on a low-cardinality enum column with correct value filters
4. **Cross-table comparison** — JOIN between fact and dimension tables (e.g. events JOIN locations)
5. **Recent activity (last N days)** — short-window daily trend using `CURRENT_DATE - INTERVAL`
6. **Count of distinct entities by group** — `COUNT(DISTINCT id)` grouped by category

None of these can be reliably produced by the current formula→SQL pipeline without seeing real data.

---

## Design

### Feature flag

```
CHART_DISCOVERY_MODE=off            # existing ChartPlannerAgent only — default, current behaviour
CHART_DISCOVERY_MODE=discovery      # LLM discovery first, ChartPlannerAgent as fallback
CHART_DISCOVERY_MODE=discovery_only # LLM discovery only, skip ChartPlannerAgent entirely
```

All other env vars in this phase are ignored when `CHART_DISCOVERY_MODE=off`.

### New environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CHART_DISCOVERY_MODE` | `off` | Feature switch |
| `CHART_DISCOVERY_MODEL` | `gpt-4o-mini` | LLM model for chart discovery |
| `CHART_DISCOVERY_TIMEOUT_SEC` | `60` | Total wall-clock budget for the discovery loop |
| `CHART_DISCOVERY_SAMPLE_ROWS` | `40` | Rows fetched per table for static context |
| `CHART_DISCOVERY_DISTINCT_LIMIT` | `20` | Top-N distinct values per categorical column |
| `CHART_DISCOVERY_CHART_LIMIT` | `10` | Max charts the LLM may propose |
| `CHART_DISCOVERY_CAT_COLS_MAX` | `8` | Max categorical columns sent to LLM per table |
| `CHART_DISCOVERY_SQL_MAX_LEN` | `4000` | Reject LLM SQL longer than this (safety) |
| `CHART_DISCOVERY_TOOL_CALL_LIMIT` | `6` | Max `query_data` tool calls per discovery session |
| `CHART_DISCOVERY_TOOL_ROW_LIMIT` | `50` | Hard row cap enforced on every tool-call query |

---

## Agentic Tool-Calling Loop

The LLM is given one tool: `query_data`. It can call this multiple times to explore the data
before proposing charts. The app always enforces `LIMIT {CHART_DISCOVERY_TOOL_ROW_LIMIT}` —
the LLM cannot bypass this regardless of what SQL it writes.

### Tool definition (OpenAI function calling format)

```json
{
  "name": "query_data",
  "description": "Execute a read-only SQL SELECT query against the database and return up to 50 rows. Use this to explore data before proposing charts — check date ranges, distinct values, sample records, counts. Always use LIMIT in your SQL; the system enforces LIMIT 50 regardless.",
  "parameters": {
    "type": "object",
    "properties": {
      "sql": {
        "type": "string",
        "description": "A valid PostgreSQL SELECT statement. Must not contain INSERT, UPDATE, DELETE, DROP, or any DDL."
      },
      "reason": {
        "type": "string",
        "description": "Brief explanation of what you are exploring and why."
      }
    },
    "required": ["sql", "reason"]
  }
}
```

### Loop flow

```
┌─────────────────────────────────────────────────────────────┐
│  LLM receives: system prompt + static context (schema,      │
│  sample rows, distinct values, business context)            │
└────────────────────────┬────────────────────────────────────┘
                         │
                ┌────────▼────────┐
                │ LLM responds    │
                └────────┬────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
┌─────────▼──────────┐      ┌──────────▼──────────┐
│  tool_call:        │      │  content: final      │
│  query_data(sql)   │      │  JSON chart specs    │
└─────────┬──────────┘      └──────────┬──────────┘
          │                            │
┌─────────▼──────────┐                 │
│  App:              │                 │
│  1. Validate SQL   │                 │
│  2. Enforce LIMIT  │                 │
│  3. Execute query  │                 │
│  4. Return rows    │                 │
└─────────┬──────────┘                 │
          │                            │
┌─────────▼──────────┐                 │
│  Append tool result│                 │
│  to message thread │                 │
└─────────┬──────────┘                 │
          │                            │
Loop (max CHART_DISCOVERY_TOOL_CALL_LIMIT times)
          │                            │
          └──────────────┬─────────────┘
                         │
                ┌────────▼────────┐
                │  Parse chart    │
                │  specs JSON     │
                └─────────────────┘
```

### Example LLM exploration session (generic)

```
[LLM] → query_data("SELECT MIN(created_at), MAX(created_at), COUNT(*) FROM events LIMIT 50",
                   reason="Check date range and data volume")
[App] → {"min": "2025-06-01", "max": "2026-03-26", "count": 120000}

[LLM] → query_data("SELECT DISTINCT status, COUNT(*) AS cnt FROM events
                    GROUP BY status ORDER BY cnt DESC LIMIT 50",
                   reason="Understand status distribution")
[App] → [{"status": "completed", "cnt": 88000}, {"status": "pending", "cnt": 24000}, ...]

[LLM] → query_data("SELECT DISTINCT category, COUNT(*) FROM events
                    GROUP BY category ORDER BY 2 DESC LIMIT 50",
                   reason="Identify high-value categorical breakdown columns")
[App] → [{"category": "A", "count": 52000}, {"category": "B", "count": 40000}, ...]

[LLM] → query_data("SELECT DATE_TRUNC('month', created_at) AS month, SUM(value) AS total
                    FROM events GROUP BY 1 ORDER BY 1 LIMIT 50",
                   reason="Verify monthly aggregation works and check scale")
[App] → [{"month": "2025-10-01", "total": 432100.5}, ...]

[LLM] → Final response: {"charts": [...domain-specific charts with dynamic SQL...]}
```

---

## Static Context Payload

Before the tool loop starts, the LLM receives an initial static context (schema + sample rows +
distinct values). This reduces the number of tool calls needed for basic orientation.

```json
{
  "domain_id": "<domain>",
  "context": "<context_text — first 6000 chars>",
  "tables": [
    {
      "name": "<table_name>",
      "schema": [{"name": "column_name", "type": "VARCHAR"}, ...],
      "sample_rows": [...up to CHART_DISCOVERY_SAMPLE_ROWS rows...],
      "distinct_values": {
        "<categorical_col>": [{"value": "A", "count": 52000}, ...],
        "<status_col>": [{"value": "active", "count": 88000}, ...]
      }
    }
  ]
}
```

The distinct values payload covers only categorical columns (low-cardinality strings and enums),
up to `CHART_DISCOVERY_CAT_COLS_MAX` columns per table, `CHART_DISCOVERY_DISTINCT_LIMIT` values each.

---

## System Prompt

```
You are a senior data analyst building an operational intelligence dashboard.

You have access to a tool `query_data` — use it to explore the data before proposing charts.
Call it up to {CHART_DISCOVERY_TOOL_CALL_LIMIT} times. Each call returns up to 50 rows.

CHART PROPOSAL RULES:
1. Propose {CHART_DISCOVERY_CHART_LIMIT} charts maximum as a JSON object:
   {"charts": [...], "rationale": "..."}
2. Each chart must have: title, chart_type, metric_name, sql, x_axis, y_axis, series_by (or null).
3. chart_type: line | bar | stacked_bar | pie | area
4. sql must be a single valid PostgreSQL SELECT statement.
5. DATES MUST BE DYNAMIC — always use CURRENT_DATE, CURRENT_DATE - INTERVAL '30 days',
   DATE_TRUNC('month', ...) etc. NEVER hardcode specific dates.
6. Apply business filters inline using WHERE or CASE WHEN. Do not assume pre-filtered views.
7. ORDER BY time column ASC for time-series charts.
8. For multi-series (series_by): the series column must appear in SELECT.
9. x_axis and y_axis must match exact column aliases in the SELECT clause.
10. Always include LIMIT 500 at the end of chart SQL (the system enforces this anyway).

EXPLORATION GUIDANCE:
- First check data date ranges and row counts for each table.
- Check distinct values for key categorical columns if not already visible in static context.
- Verify a join works before using it in a chart SQL.
- Prioritise charts that show trends over time, breakdowns by business category, and comparisons.
- Use the business context provided to understand which columns carry operational significance.
```

---

## LIMIT Enforcement

The app **always** rewrites tool-call SQL to enforce the row cap before execution:

```python
def _enforce_tool_limit(sql: str, limit: int = 50) -> str:
    """Rewrite LLM query_data SQL to enforce LIMIT."""
    clean = sql.strip().rstrip(";")
    # If already has LIMIT clause, replace it
    if re.search(r'\bLIMIT\s+\d+', clean, re.IGNORECASE):
        clean = re.sub(r'\bLIMIT\s+\d+', f'LIMIT {limit}', clean, flags=re.IGNORECASE)
    else:
        clean = f"{clean} LIMIT {limit}"
    return clean
```

This is non-negotiable — the LLM cannot request more than `CHART_DISCOVERY_TOOL_ROW_LIMIT` rows
from a tool call regardless of what it writes.

Chart proposal SQL (the final SELECT for each chart) is **not** capped at 50 — it gets a
separate `LIMIT 500` appended for storage/rendering purposes.

---

## New Components

### `_chart_discovery_enabled() / _chart_discovery_only()`
(`agentic_agents.py`)

```python
def _chart_discovery_enabled() -> bool:
    return os.getenv("CHART_DISCOVERY_MODE", "off").lower() in {"discovery", "discovery_only"}

def _chart_discovery_only() -> bool:
    return os.getenv("CHART_DISCOVERY_MODE", "off").lower() == "discovery_only"
```

### `_fetch_table_samples(settings, table_names, schema) -> dict[str, TableSample]`
(`agentic_agents.py`)

```python
@dataclass
class TableSample:
    table_name: str
    rows: list[dict]               # up to CHART_DISCOVERY_SAMPLE_ROWS rows
    distinct_values: dict[str, list]  # col → [{value, count}, ...]
    row_count_estimate: int
```

- Fetches `SELECT * FROM schema.table LIMIT N` per table
- Fetches top-N distinct values for categorical columns (low-cardinality string/enum columns
  identified from profiling — not IDs, not free-text, not numeric)
- Runs in parallel using `ThreadPoolExecutor`, timeout = `CHART_DISCOVERY_TIMEOUT_SEC / 3`

### `_run_tool_call(sql, settings, schema) -> list[dict]`
(`agentic_orchestrator.py`)

```python
def _run_tool_call(sql: str, settings, schema: str) -> list[dict]:
    """Execute a validated, LIMIT-enforced LLM tool-call query. Returns rows as dicts."""
    limit = int(os.getenv("CHART_DISCOVERY_TOOL_ROW_LIMIT", "50"))
    enforced_sql = _enforce_tool_limit(sql, limit)
    valid, err = _validate_discovery_sql(enforced_sql)
    if not valid:
        return [{"_error": err}]
    try:
        with get_db_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(enforced_sql)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return rows
    except Exception as e:
        return [{"_error": str(e)[:300]}]
```

### `_llm_chart_discovery(settings, *, domain_id, context_text, schema_graph, profiling, table_samples) -> tuple[list[dict], dict]`
(`agentic_orchestrator.py`)

The main discovery loop:

```python
def _llm_chart_discovery(settings, *, domain_id, context_text, schema_graph,
                          profiling, table_samples) -> tuple[list[dict], dict]:
    model = os.getenv("CHART_DISCOVERY_MODEL", "gpt-4o-mini")
    timeout = int(os.getenv("CHART_DISCOVERY_TIMEOUT_SEC", "60"))
    max_tool_calls = int(os.getenv("CHART_DISCOVERY_TOOL_CALL_LIMIT", "6"))
    chart_limit = int(os.getenv("CHART_DISCOVERY_CHART_LIMIT", "10"))

    messages = [
        {"role": "system", "content": _build_discovery_system_prompt(chart_limit, max_tool_calls)},
        {"role": "user",   "content": json.dumps(_build_discovery_user_payload(
            domain_id, context_text, schema_graph, profiling, table_samples
        ))}
    ]
    tools = [_QUERY_DATA_TOOL_DEF]
    tool_calls_made = 0
    diagnostics = {"tool_calls": [], "model": model}

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = _openai_chat(settings, model=model, messages=messages, tools=tools,
                                timeout=max(5, int(deadline - time.monotonic())))
        choice = response["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason")

        # LLM wants to call a tool
        if finish_reason == "tool_calls" and tool_calls_made < max_tool_calls:
            tool_call = message["tool_calls"][0]
            args = json.loads(tool_call["function"]["arguments"])
            sql = args.get("sql", "")
            reason = args.get("reason", "")
            rows = _run_tool_call(sql, settings, schema=profiling.get("schema", "public"))
            diagnostics["tool_calls"].append({"sql": sql, "reason": reason, "rows_returned": len(rows)})
            tool_calls_made += 1
            messages.append({"role": "assistant", "content": None, "tool_calls": message["tool_calls"]})
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(rows, default=str)
            })
            continue

        # LLM has produced final chart specs (or hit tool call limit)
        content = message.get("content") or ""
        charts = _parse_discovery_charts(content)
        diagnostics["proposed"] = len(charts)
        return charts, diagnostics

    return [], {**diagnostics, "timeout": True}
```

### `_validate_discovery_sql(sql) -> tuple[bool, str | None]`
(`agentic_agents.py`)

```python
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)

def _validate_discovery_sql(sql: str) -> tuple[bool, str | None]:
    if not sql or not sql.strip().upper().startswith("SELECT"):
        return False, "not_a_select"
    if _FORBIDDEN_SQL.search(sql):
        return False, "forbidden_statement"
    max_len = int(os.getenv("CHART_DISCOVERY_SQL_MAX_LEN", "4000"))
    if len(sql) > max_len:
        return False, "sql_too_long"
    return True, None
```

Note: tool-call SQL uses lightweight validation (no EXPLAIN — keep latency low since this is
in the interactive loop). Final chart SQL goes through EXPLAIN dry-run before execution.

### `_execute_discovery_charts(settings, specs, schema, tenant_id, domain_id, run_id, dashboard_id) -> list[str]`
(`agentic_orchestrator.py`)

For each proposed chart spec:
1. Validate SQL (SELECT-only, EXPLAIN dry-run)
2. Warn (don't reject) if hardcoded dates detected
3. Execute with LIMIT 500
4. Build amCharts payload via `build_discovery_chart_payload`
5. Run `build_chart_inference` for insight/narrative/stats
6. Store via `create_chart_request(..., source="llm_discovery")`
7. Add to dashboard via `_add_chart_to_dashboard`

### `build_discovery_chart_payload(spec, rows) -> dict`
(`charts.py`)

Converts a discovery spec + result rows into an amCharts 5 payload. Key difference from
existing `build_chart_payload`: respects `series_by` for multi-series line/bar charts.

```python
def build_discovery_chart_payload(spec: dict, rows: list[dict]) -> dict:
    chart_type = str(spec.get("chart_type") or "bar").lower()
    x_axis = spec.get("x_axis")
    y_axis = spec.get("y_axis")
    series_by = spec.get("series_by")  # None → single series; str → pivot by this column

    if series_by and series_by in {r.get(series_by) for r in rows if series_by in r}:
        # Pivot rows into multi-series format
        return _build_multi_series_payload(chart_type, rows, x_axis, y_axis, series_by, spec)
    else:
        return _build_single_series_payload(chart_type, rows, x_axis, y_axis, spec)
```

---

## Pipeline Integration

### Modified `dashboard_node`

```python
def dashboard_node(state):
    ...
    discovery_chart_ids = []
    discovery_titles = []

    if _chart_discovery_enabled():
        # 1. Fetch sample data
        table_samples = _fetch_table_samples(
            settings, table_names=profiled_table_names, schema=schema_name
        )
        _emit(settings, run_id, "ChartDiscoveryAgent", "running",
              f"Exploring data from {len(table_samples)} tables...")

        # 2. Run agentic discovery loop
        discovery_specs, discovery_diag = _llm_chart_discovery(
            settings,
            domain_id=domain_id,
            context_text=context_text,
            schema_graph=schema_graph,
            profiling=profiling,
            table_samples=table_samples,
        )
        state["chart_discovery_diagnostics"] = discovery_diag

        # 3. Execute validated charts
        if discovery_specs:
            discovery_chart_ids = _execute_discovery_charts(
                settings, discovery_specs, schema_name,
                tenant_id, domain_id, run_id, dashboard_id,
            )
            discovery_titles = [s["title"] for s in discovery_specs]

        _emit(settings, run_id, "ChartDiscoveryAgent", "completed",
              f"Discovery: {len(discovery_chart_ids)} charts generated",
              artifacts={
                  "mode": os.getenv("CHART_DISCOVERY_MODE"),
                  "tool_calls_made": len(discovery_diag.get("tool_calls") or []),
                  "llm_proposed": discovery_diag.get("proposed", 0),
                  "chart_ids": discovery_chart_ids,
              })

    # Existing ChartPlannerAgent — skip if discovery_only
    legacy_chart_ids = []
    legacy_titles = []
    if not _chart_discovery_only():
        legacy_chart_ids, legacy_titles = _run_legacy_chart_planner(state, ...)

    # Merge: discovery first, legacy fills remainder
    seen = set(discovery_chart_ids)
    all_chart_ids = discovery_chart_ids + [c for c in legacy_chart_ids if c not in seen]
    state["chart_ids"] = all_chart_ids
    state["chart_titles"] = discovery_titles + [t for t in legacy_titles if t not in discovery_titles]
```

---

## Diagnostic Events

```json
{
  "agent_name": "ChartDiscoveryAgent",
  "status": "completed",
  "artifacts": {
    "mode": "discovery",
    "tables_sampled": 3,
    "tool_calls_made": 4,
    "tool_call_log": [
      {"sql": "SELECT MIN(created_at), MAX(created_at), COUNT(*) FROM events ...", "reason": "Check date range", "rows_returned": 1},
      {"sql": "SELECT DISTINCT status, COUNT(*) ...", "reason": "Status distribution", "rows_returned": 4},
      {"sql": "SELECT DISTINCT category, COUNT(*) ...", "reason": "Category breakdown", "rows_returned": 8},
      {"sql": "SELECT DATE_TRUNC('month', ...) ...", "reason": "Verify monthly aggregation", "rows_returned": 6}
    ],
    "llm_proposed": 8,
    "validated": 8,
    "executed": 7,
    "rejected": 1,
    "rejected_reasons": [{"title": "Cross-Table CTE", "reason": "sql_too_long"}],
    "chart_ids": ["chart_abc", "chart_def", ...],
    "discovery_rationale": "Charts prioritise operational trends by time, category breakdowns, and cross-table comparisons."
  }
}
```

---

## Switchback / Rollback

| Scenario | Action |
|---|---|
| LLM discovery broken / slow | `CHART_DISCOVERY_MODE=off` — instant rollback |
| LLM generating bad SQL | `CHART_DISCOVERY_MODE=off` OR reduce `CHART_DISCOVERY_CHART_LIMIT=0` |
| Want both but limit LLM budget | `CHART_DISCOVERY_MODE=discovery` + `CHART_DISCOVERY_CHART_LIMIT=4` |
| LLM only, no generic charts | `CHART_DISCOVERY_MODE=discovery_only` |
| Reduce tool calls (cost/latency) | `CHART_DISCOVERY_TOOL_CALL_LIMIT=2` |
| Tune for larger data samples | `CHART_DISCOVERY_SAMPLE_ROWS=80` + `CHART_DISCOVERY_TOOL_ROW_LIMIT=100` |
| Use a stronger model | `CHART_DISCOVERY_MODEL=gpt-4o` |

---

## Quality Gates

| Gate | Where | Notes |
|---|---|---|
| SELECT-only check | `_validate_discovery_sql` | Both tool calls and chart SQL |
| LIMIT enforcement | `_enforce_tool_limit` | Tool calls capped at 50 rows always |
| SQL length guard | `_validate_discovery_sql` | Rejects SQL > `CHART_DISCOVERY_SQL_MAX_LEN` |
| EXPLAIN dry-run | `_execute_discovery_charts` | Chart SQL only — tool-call SQL skips this |
| Dynamic date check | `_execute_discovery_charts` | Warns (doesn't reject) if hardcoded dates detected |
| Empty result guard | `_execute_discovery_charts` | Skips charts returning 0 rows |
| Column presence check | `build_discovery_chart_payload` | x_axis/y_axis must exist in result columns |
| Max rows for storage | `_execute_discovery_charts` | Chart SQL results truncated to 500 rows |

---

## Files to Change

| File | Change |
|---|---|
| `services/ai/agentic_agents.py` | Add `TableSample` dataclass, `_chart_discovery_enabled()`, `_chart_discovery_only()`, `_fetch_table_samples()`, `_validate_discovery_sql()`, `_enforce_tool_limit()` |
| `services/ai/agentic_orchestrator.py` | Add `_build_discovery_system_prompt()`, `_build_discovery_user_payload()`, `_run_tool_call()`, `_llm_chart_discovery()`, `_execute_discovery_charts()`, wire into `dashboard_node` |
| `services/ai/charts.py` | Add `build_discovery_chart_payload()` with multi-series pivot support |
| `services/api/main.py` | Include `chart_discovery_diagnostics` in dashboard event payload |
| `.env.example` | Document all `CHART_DISCOVERY_*` variables |

No schema migrations required — discovery charts use the existing `quantyx_chart_requests`
table. A `source='llm_discovery'` tag distinguishes them from formula-generated charts.

---

## Implementation Sequence

```
Step 1  Feature flag helpers + env var resolution                  (20 min)
Step 2  TableSample dataclass + _fetch_table_samples()             (1 hr)
Step 3  _validate_discovery_sql() + _enforce_tool_limit()          (30 min)
Step 4  _run_tool_call() — execute + return rows as dicts          (30 min)
Step 5  _build_discovery_system_prompt() + user payload builder    (45 min)
Step 6  _llm_chart_discovery() — agentic tool-calling loop         (1.5 hr)
Step 7  _execute_discovery_charts() — validate → EXPLAIN → run    (1 hr)
Step 8  build_discovery_chart_payload() — multi-series pivot       (1 hr)
Step 9  Wire into dashboard_node with mode check + event emission  (45 min)
Step 10 .env.example documentation                                 (15 min)
Step 11 End-to-end test across at least two domains                (1 hr)
```

---

## Expected Outcome (any domain)

With `CHART_DISCOVERY_MODE=discovery`, the LLM will:

1. Orient itself by checking data date ranges and volumes per table
2. Discover meaningful categorical columns by querying distinct value distributions
3. Verify JOIN conditions work before using them in chart SQL
4. Propose domain-specific charts grounded in real data patterns — not generic formula permutations
5. Use business context text (from deployment) to label metrics and apply correct filters

The result is charts that reflect what the data actually contains, regardless of domain —
Manufacturing, Fuel Distribution, LPG, Logistics, or any future vertical.