# Phase 49: Chart SQL Editor — Execute, Save as New, and Overwrite

## Objective

Allow users to view, edit, and re-execute the SQL behind any existing `chart_id`. The result can be:

1. **Preview** — run the edited SQL, see rows + chart artifacts, nothing persisted.
2. **Save as New** — original untouched; new `chart_id` created with edited SQL, fresh data, narrative, and stats.
3. **Overwrite** — existing `chart_id` updated in-place: SQL, rows, chart artifacts, narrative, and stats all replaced. Full SQL history preserved. Dashboard refresh event emitted.

This gives analysts a "power user" escape hatch — the LLM or pipeline produced a chart that is close but not quite right, and the user corrects the SQL without starting a new conversation from scratch.

---

## Decisions Made

| Question | Decision |
|---|---|
| Full SQL history | **Yes** — dedicated `quantyx_chart_sql_history` table, one row per save/overwrite |
| Overwrite restricted to `created_by` | **No** — any authenticated user in the tenant may overwrite |
| Auto-infer metric/dimension from SELECT aliases | **Yes** — if not supplied, parse SELECT clause to extract column aliases as metric_names and GROUP BY columns as dimensions |
| Dashboard sync on overwrite | **Yes** — emit a dashboard refresh event for every user dashboard that contains the overwritten `chart_id` |

---

## Current State

`GET /charts/{chart_id}` already returns:

```json
{
  "chart_id": "chart_abc123",
  "status": "ready",
  "sql": "SELECT ...",
  "params": [],
  "rows_json": [...],
  "chart_type": "bar",
  "chart_payload": {...},
  "insight_text": "...",
  "narrative_text": "...",
  "stats_json": {...},
  "conversation_ids": ["conv_xxx"]
}
```

`update_chart_request` in `charts_store.py` already accepts all updatable fields.
`build_chart_inference` already regenerates insight/narrative/stats from rows.
`quantyx_user_dashboard_charts` already maps `dashboard_id → chart_id` — queryable to find affected dashboards on overwrite.

---

## Design: What Gets Regenerated vs Preserved

### Regenerated on every execute (preview, save-as-new, overwrite)

- `rows_json` — fresh query result
- `chart_type` — re-inferred from new rows + dimensions
- `chart_payload` — re-built chart spec
- `chart_data` — formatted for chart renderer
- `insight_text` — re-generated from new rows
- `narrative_text` — re-generated from new rows
- `stats_json` — recomputed (min, max, avg, total, count)

### Preserved in overwrite mode

- `chart_id` — identity unchanged
- `tenant_id`, `domain_id`, `run_id` — scope unchanged
- `question` — original NL question unchanged
- `query_payload` — original query intent preserved
- `chart_source` — unchanged
- `conversation_ids` — link history not broken
- `created_at` — creation timestamp unchanged

### Copied from source in save-as-new mode

- `tenant_id`, `domain_id`, `run_id`
- `question` (overridable via request `title`)
- `query_payload`
- `chart_source = "sql_editor"`
- `editor_source_chart_id` = original `chart_id`

---

## Auto-Inference of Metric Names and Dimensions

When `metric_names` and/or `dimension` are not supplied in the request, the system parses the SQL SELECT clause:

### Metric name inference
Extracts non-grouped numeric aliases from the SELECT list:
```sql
-- Input SQL
SELECT Zone, SUM(NETWEIGHT_TMT) AS actual_tmt, COUNT(*) AS txn_count FROM ...
GROUP BY Zone
```
→ `metric_names = ["actual_tmt", "txn_count"]` (aggregated columns)

### Dimension inference
Extracts GROUP BY columns (after stripping schema/table prefix and quotes):
```sql
GROUP BY m."Zone", m."Region"
```
→ `dimensions = ["Zone", "Region"]`

### Inference logic (`_infer_metrics_and_dimensions`)

```python
def _infer_metrics_and_dimensions(sql: str) -> tuple[list[str], list[str]]:
    # 1. Extract GROUP BY columns → dimensions
    # 2. Extract SELECT aliases that are NOT in GROUP BY → metric_names
    # Uses regex over normalised SQL; falls back to empty lists on parse failure
```

Rules:
- `SELECT *` → metrics = [], dimensions = [] (user must supply explicitly)
- No GROUP BY → all SELECT aliases treated as metrics, dimensions = []
- CTE aliases resolved: the final SELECT is used, not intermediate CTEs

---

## SQL History Table

Every save (save-as-new and overwrite) writes one row to `quantyx_chart_sql_history`. Preview runs do **not** write history.

### Schema

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_chart_sql_history (
  history_id      TEXT PRIMARY KEY,
  chart_id        TEXT NOT NULL,
  tenant_id       TEXT NOT NULL,
  sql             TEXT NOT NULL,
  metric_names    JSONB NULL,
  dimensions      JSONB NULL,
  row_count       INT  NULL,
  save_mode       TEXT NOT NULL,          -- 'save_as_new' | 'overwrite'
  saved_by        TEXT NULL,
  stats_json      JSONB NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chart_sql_history_chart
  ON public.quantyx_chart_sql_history (chart_id, created_at DESC);

COMMENT ON TABLE public.quantyx_chart_sql_history IS
  'Full SQL edit history for every save-as-new and overwrite on quantyx_chart_requests.';
COMMENT ON COLUMN public.quantyx_chart_sql_history.save_mode IS
  'save_as_new: new chart_id was created. overwrite: existing chart_id was updated in-place.';
```

### History record written on overwrite

```json
{
  "history_id": "sqlhist_abc123",
  "chart_id": "chart_abc123",
  "tenant_id": "VC_101",
  "sql": "SELECT Zone, SUM(...) ...",
  "metric_names": ["actual_tmt"],
  "dimensions": ["Zone"],
  "row_count": 12,
  "save_mode": "overwrite",
  "saved_by": "user_789",
  "stats_json": { "count": 12, "min": 1.2, "max": 44.5, "avg": 18.3, "total": 219.6 }
}
```

### History record written on save-as-new

```json
{
  "history_id": "sqlhist_def456",
  "chart_id": "chart_new999",      ← new chart_id, not the source
  "tenant_id": "VC_101",
  "sql": "SELECT Zone, SUM(...) ...",
  "metric_names": ["actual_tmt"],
  "dimensions": ["Zone"],
  "row_count": 12,
  "save_mode": "save_as_new",
  "saved_by": "user_789",
  "stats_json": {...}
}
```

### `GET /charts/{chart_id}/sql-history` endpoint

Returns the full edit history for a chart ordered newest-first:

```json
{
  "chart_id": "chart_abc123",
  "history": [
    {
      "history_id": "sqlhist_abc123",
      "sql": "SELECT ...",
      "save_mode": "overwrite",
      "saved_by": "user_789",
      "row_count": 12,
      "created_at": "2026-04-02T10:30:00Z"
    }
  ]
}
```

---

## Dashboard Sync on Overwrite

When `PUT /charts/{chart_id}/overwrite` completes successfully:

1. Query `quantyx_user_dashboard_charts` for all `dashboard_id` values containing this `chart_id`
2. For each affected dashboard, insert a row into `quantyx_dashboard_refresh_events` with:
   - `stage_name = "chart_overwritten"`
   - `message = "Chart {chart_id} was overwritten via SQL editor"`
   - `artifacts = { "chart_id": ..., "previous_row_count": ..., "new_row_count": ... }`

This means:
- The dashboard does **not** need a full re-render — it already queries `chart_id` live, so the new data appears automatically on next load
- The refresh event serves as a notification/audit trail that the dashboard's underlying data changed
- No separate background job triggered — the event is informational, not a trigger for recomputation

```python
def _emit_dashboard_chart_overwrite_events(
    settings: Settings,
    chart_id: str,
    tenant_id: str,
    previous_row_count: int,
    new_row_count: int,
) -> None:
    # Find all user dashboards containing this chart_id
    # Insert a dashboard refresh event for each
```

---

## API Design

### 1. `POST /charts/{chart_id}/execute` — Preview

Validate and run edited SQL. Returns rows and regenerated artifacts **without saving**.

**Request:**
```json
{
  "sql": "SELECT Zone, SUM(NETWEIGHT_TMT) AS actual_tmt FROM public.\"MOM_DAY_LEVEL_DATA\" WHERE ...",
  "metric_names": ["actual_tmt"],
  "dimension": "Zone"
}
```

`metric_names` and `dimension` are optional — auto-inferred from SQL if absent.

**Response:**
```json
{
  "chart_id": "chart_abc123",
  "sql": "SELECT ...",
  "rows": [...],
  "row_count": 12,
  "chart_type": "bar",
  "chart_payload": {...},
  "insight_text": "North zone leads with 44.5 TMT",
  "narrative_text": "North zone outperforms South by 2.4×",
  "stats_json": { "count": 12, "min": 1.2, "max": 44.5, "avg": 18.3, "total": 219.6 },
  "inferred_metrics": ["actual_tmt"],
  "inferred_dimensions": ["Zone"],
  "status": "preview"
}
```

`inferred_metrics` and `inferred_dimensions` are included when auto-inference was used, so the UI can display them and let the user confirm before saving.

---

### 2. `POST /charts/{chart_id}/save-as-new` — Fork

Execute edited SQL, regenerate artifacts, persist as a **new** `chart_id`. Original untouched.

**Request:**
```json
{
  "sql": "SELECT Zone, SUM(NETWEIGHT_TMT) AS actual_tmt FROM ...",
  "metric_names": ["actual_tmt"],
  "dimension": "Zone",
  "title": "North Zone Actuals — Corrected Filter",
  "conversation_id": "conv_xxx",
  "saved_by": "user_789"
}
```

**Response:**
```json
{
  "source_chart_id": "chart_abc123",
  "chart_id": "chart_new999",
  "status": "ready",
  "sql": "SELECT ...",
  "rows_json": [...],
  "chart_type": "bar",
  "chart_payload": {...},
  "insight_text": "...",
  "narrative_text": "...",
  "stats_json": {...},
  "inferred_metrics": ["actual_tmt"],
  "inferred_dimensions": ["Zone"]
}
```

**Side effects:**
- New row in `quantyx_chart_requests` (`chart_source = "sql_editor"`, `editor_source_chart_id = "chart_abc123"`)
- Row in `quantyx_chart_sql_history` (`save_mode = "save_as_new"`)
- `append_chart_conversation_id` called if `conversation_id` provided
- `create_chart_event` (`event_type = "sql_editor_save_new"`)

---

### 3. `PUT /charts/{chart_id}/overwrite` — Update in Place

Execute edited SQL, regenerate artifacts, write everything back onto the **same** `chart_id`.

**Request:**
```json
{
  "sql": "SELECT Zone, SUM(NETWEIGHT_TMT) AS actual_tmt FROM ...",
  "metric_names": ["actual_tmt"],
  "dimension": "Zone",
  "saved_by": "user_789"
}
```

**Response:**
```json
{
  "chart_id": "chart_abc123",
  "status": "ready",
  "sql": "SELECT ...",
  "rows_json": [...],
  "chart_type": "bar",
  "chart_payload": {...},
  "insight_text": "...",
  "narrative_text": "...",
  "stats_json": {...},
  "inferred_metrics": ["actual_tmt"],
  "inferred_dimensions": ["Zone"],
  "overwritten": true,
  "affected_dashboards": ["dash_001", "dash_002"]
}
```

**Side effects (in order):**
1. `update_chart_request` — sql, rows_json, chart_type, chart_payload, chart_data, insight_text, narrative_text, stats_json, status = "ready"
2. Row in `quantyx_chart_sql_history` (`save_mode = "overwrite"`, `sql` = new SQL)
3. `create_chart_event` (`event_type = "sql_editor_overwrite"`, `details.previous_sql` = old SQL)
4. `_emit_dashboard_chart_overwrite_events` — refresh event for each affected dashboard

---

### 4. `GET /charts/{chart_id}/sql-history` — History

Returns full SQL edit history for a chart.

**Response:**
```json
{
  "chart_id": "chart_abc123",
  "history": [
    {
      "history_id": "sqlhist_abc123",
      "sql": "SELECT Zone, SUM(...) ...",
      "metric_names": ["actual_tmt"],
      "dimensions": ["Zone"],
      "save_mode": "overwrite",
      "saved_by": "user_789",
      "row_count": 12,
      "stats_json": {...},
      "created_at": "2026-04-02T10:30:00Z"
    }
  ]
}
```

---

## Shared Internal Helper: `_execute_editor_sql`

All three action endpoints share the same pipeline:

```
1. _infer_metrics_and_dimensions(sql)
   → fills metric_names / dimensions if not supplied

2. _validate_editor_sql(sql, tenant_id, domain_id)
   → destructive keyword check
   → SQL must start with SELECT or WITH
   → table scope check (only tenant/domain tables)
   → LIMIT injection (cap 500)
   → EXPLAIN dry-run

3. run_query(settings, sql, [], scoped_conn, statement_timeout_ms)
   → rows

4. build_workspace_chart(rows, metric_name, metric_names, dimensions)
   → chart_type, chart_payload, chart_warnings

5. build_chart_inference(settings, chart_type, rows, metric_name, dim_key, chart_title)
   → insight_text, narrative_text, stats_json

Returns EditorResult(
  sql, rows, chart_type, chart_payload, chart_data,
  insight_text, narrative_text, stats_json,
  metric_names, dimensions, inferred
)
```

---

## Validation Rules

| Rule | Detail |
|---|---|
| Destructive keywords blocked | `DROP`, `DELETE`, `INSERT`, `UPDATE`, `TRUNCATE`, `ALTER`, `GRANT` |
| Must be SELECT | SQL must start with `SELECT` or `WITH` after stripping comments |
| Table scope | Only tables in the tenant/domain's scoped connection allowed |
| LIMIT injection | Added if absent; capped at 500 rows for editor runs |
| EXPLAIN dry-run | Catches syntax errors before hitting data |
| Statement timeout | `SQL_EDITOR_QUERY_TIMEOUT_MS` env var, default 20 000 ms |
| `SELECT *` guard | Allowed but auto-inference returns empty metric_names — user must supply explicitly |

---

## Schema Changes

### `quantyx_chart_requests` — one new column

```sql
ALTER TABLE public.quantyx_chart_requests
  ADD COLUMN IF NOT EXISTS editor_source_chart_id TEXT NULL;

COMMENT ON COLUMN public.quantyx_chart_requests.editor_source_chart_id
  IS 'For sql_editor charts: the chart_id this was forked from via save-as-new.';
```

### New table — `quantyx_chart_sql_history`

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_chart_sql_history (
  history_id      TEXT PRIMARY KEY,
  chart_id        TEXT NOT NULL,
  tenant_id       TEXT NOT NULL,
  sql             TEXT NOT NULL,
  metric_names    JSONB NULL,
  dimensions      JSONB NULL,
  row_count       INT  NULL,
  save_mode       TEXT NOT NULL,
  saved_by        TEXT NULL,
  stats_json      JSONB NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chart_sql_history_chart
  ON public.quantyx_chart_sql_history (chart_id, created_at DESC);
```

### New `chart_event` types

| event_type | When |
|---|---|
| `sql_editor_execute` | Preview run (no save) |
| `sql_editor_save_new` | Saved as new chart |
| `sql_editor_overwrite` | Overwrote existing chart — `details.previous_sql` captured |

---

## UI Flow

```
GET /charts/{chart_id}
  → chart rendered with [Edit SQL] button

[Edit SQL] clicked
  → SQL editor panel opens with chart.sql pre-populated
  → metric_names and dimensions shown (from chart record or inferred)

User edits SQL
  → [Preview] → POST /charts/{chart_id}/execute
    → new rows + chart preview shown inline (not saved)
    → inferred_metrics / inferred_dimensions displayed for confirmation

User satisfied
  → [Save as New]      → POST /charts/{chart_id}/save-as-new
                           → new chart_id returned, UI navigates to it
  → [Overwrite]        → PUT  /charts/{chart_id}/overwrite
                           → same chart_id, chart re-renders with new data
                           → affected_dashboards listed in response (UI can notify)
  → [View SQL History] → GET  /charts/{chart_id}/sql-history
                           → shows timeline of all edits with rollback view
```

---

## Files to Change

| File | Change |
|---|---|
| `services/api/main.py` | Add `POST /charts/{id}/execute`, `POST /charts/{id}/save-as-new`, `PUT /charts/{id}/overwrite`, `GET /charts/{id}/sql-history`; add `_execute_editor_sql`, `_infer_metrics_and_dimensions`, `_emit_dashboard_chart_overwrite_events` helpers |
| `services/ai/charts_store.py` | Add `editor_source_chart_id` to `create_chart_request` / `get_chart_request`; add `create_chart_sql_history`, `get_chart_sql_history` functions |
| `services/api/schemas.py` | Add `EditorExecuteRequest`, `EditorSaveRequest`, `EditorExecuteResponse`, `EditorOverwriteResponse`, `ChartSqlHistoryResponse` Pydantic models |
| `services/ai/llm_sql_direct.py` | Extract `_validate_sql` as a standalone reusable function (currently embedded in `build_sql_query`) |
| `scripts/apply_agentic_tables.sh` | Phase 49 migration: `editor_source_chart_id` column + `quantyx_chart_sql_history` table |
| `artifacts/quantyx_tables_updates.sql` | Add `editor_source_chart_id` to `CREATE TABLE quantyx_chart_requests`; add full `quantyx_chart_sql_history` definition |

---

## Security

- Editor SQL runs under the same **read-only scoped connection** (`ScopedConnection`) as all workspace queries — no privilege escalation
- Table scope check prevents cross-tenant data access
- All SQL (including previous SQL on overwrite) persisted in `quantyx_chart_sql_history` and `quantyx_chart_events` for full audit trail
- Overwrite preserves `conversation_ids` — no orphaning of conversation history
- No `created_by` restriction on overwrite — any tenant user may edit
