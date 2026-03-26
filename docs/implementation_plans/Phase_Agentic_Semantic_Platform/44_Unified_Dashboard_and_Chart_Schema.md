# Unified Dashboard and Chart Schema

## Problem

Dashboards and charts currently exist in separate tables depending on how they were created, creating diverging data models that will cause long-term pain:

### Dashboard fragmentation

| Table | Created by | ID prefix | Key fields |
|---|---|---|---|
| `quantyx_dashboard_specs` | Agentic run / DashboardAgent | `dash_` | `title`, `spec` JSONB blob (embeds all chart titles, quality, chart_plan) |
| `quantyx_user_dashboards` | User via API | `udash_` | `name`, `description`, `status`, `created_by` |
| `quantyx_user_dashboard_charts` | User pinning a chart | — | `chart_id`, `position`, `added_by` (FK to user_dashboards) |

System dashboards store charts **inside the `spec` JSONB**. User dashboards store charts as **separate rows** in a join table. There is no foreign key linking `quantyx_dashboard_specs` charts to `quantyx_chart_requests`. Refresh, quality, and insight tables all reference `dashboard_id` but span both ID spaces inconsistently.

### Chart fragmentation

| Table | Purpose | Created by |
|---|---|---|
| `quantyx_chart_requests` | Primary chart store — holds question, SQL, rows, chart spec | Agentic run + workspace conversations |
| `quantyx_dashboard_chart_snapshots` | Point-in-time data snapshot for dashboard refresh | Dashboard refresh job |
| `quantyx_chart_events` | Lifecycle events for a chart | Charts store |

`quantyx_chart_requests` is the right primary table but it lacks a `chart_source` discriminator, a human `title`, and a `created_by` field — so you cannot tell whether a chart came from an agentic run, a workspace conversation, or a user pin.

---

## Target Design

### Unified Dashboards

**Single table: `quantyx_dashboards`**

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_dashboards (
  dashboard_id          TEXT PRIMARY KEY,           -- new prefix: db_<hex>
  tenant_id             TEXT NOT NULL,
  domain_id             TEXT NOT NULL,
  name                  TEXT NOT NULL,              -- human-readable name (was title for system, name for user)
  description           TEXT NULL,                  -- optional context
  dashboard_type        TEXT NOT NULL DEFAULT 'system',  -- 'system' | 'user'
  status                TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'archived'

  -- Agentic / system fields (null for user dashboards initially)
  run_id                TEXT NULL,                  -- agentic run that generated this dashboard
  latest_refresh_id     TEXT NULL,                  -- most recent refresh run
  quality_score         FLOAT NULL,
  quality_gate_passed   BOOLEAN NULL,
  chart_plan            JSONB NULL,                 -- ordered chart plan from agentic run (metadata only)

  -- User fields (null for system dashboards)
  created_by            TEXT NULL,

  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboards_tenant
  ON public.quantyx_dashboards (tenant_id, domain_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dashboards_type
  ON public.quantyx_dashboards (tenant_id, dashboard_type, status);
```

**Single chart-link table: `quantyx_dashboard_charts`**

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_charts (
  entry_id              TEXT PRIMARY KEY,           -- dc_<hex>
  dashboard_id          TEXT NOT NULL
    REFERENCES public.quantyx_dashboards(dashboard_id) ON DELETE CASCADE,
  chart_id              TEXT NOT NULL,              -- references quantyx_charts
  position              INTEGER NOT NULL DEFAULT 0,
  title_override        TEXT NULL,                  -- optional display title for this slot
  added_by              TEXT NULL,
  added_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (dashboard_id, chart_id)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_charts_dashboard
  ON public.quantyx_dashboard_charts (dashboard_id, position ASC);

CREATE INDEX IF NOT EXISTS idx_dashboard_charts_chart
  ON public.quantyx_dashboard_charts (chart_id);
```

> **What happens to `spec` JSONB?**  The `spec` blob from `quantyx_dashboard_specs` is decomposed: chart metadata (title, position) moves into `quantyx_dashboard_charts` rows; the `chart_plan` summary stays on the dashboard row as a slim JSONB; raw quality data is preserved in `quality_score` / `quality_gate_passed` columns. The full spec blob is no longer the source of truth.

---

### Unified Charts

**Evolve `quantyx_chart_requests` → `quantyx_charts`**

Add three new columns to the existing table (backward-compatible ALTER, no data loss):

```sql
ALTER TABLE public.quantyx_chart_requests
  ADD COLUMN IF NOT EXISTS chart_source  TEXT NULL,   -- 'agentic_run' | 'workspace' | 'conversation' | 'user_pin'
  ADD COLUMN IF NOT EXISTS title         TEXT NULL,   -- human display title for the chart
  ADD COLUMN IF NOT EXISTS created_by    TEXT NULL;   -- user id or agent name

CREATE INDEX IF NOT EXISTS idx_chart_requests_source
  ON public.quantyx_chart_requests (tenant_id, domain_id, chart_source, status, updated_at DESC);
```

The table is not renamed (too many downstream references) — the logical rename to "charts" is expressed through the API and store layer, not the physical table name.

`quantyx_dashboard_chart_snapshots` and `quantyx_chart_events` are **unchanged** — they are append-only audit/snapshot tables and reference `chart_id`, which remains stable.

---

## Migration

### Step 1 — Schema changes (DDL only, additive)

Apply the following in order (no data loss, no downtime):

```sql
-- 1a. Create unified dashboards table
CREATE TABLE IF NOT EXISTS public.quantyx_dashboards ( ... );
CREATE INDEX ...;

-- 1b. Create unified dashboard-charts link table
CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_charts ( ... );
CREATE INDEX ...;

-- 1c. Add discriminator columns to chart_requests
ALTER TABLE public.quantyx_chart_requests
  ADD COLUMN IF NOT EXISTS chart_source TEXT NULL,
  ADD COLUMN IF NOT EXISTS title        TEXT NULL,
  ADD COLUMN IF NOT EXISTS created_by   TEXT NULL;
```

### Step 2 — Migrate system dashboards (`quantyx_dashboard_specs`)

```sql
-- 2a. Copy dashboard header rows
INSERT INTO public.quantyx_dashboards (
  dashboard_id, tenant_id, domain_id, name, description,
  dashboard_type, status, run_id, quality_score, quality_gate_passed,
  chart_plan, created_at, updated_at
)
SELECT
  dashboard_id,
  tenant_id,
  domain_id,
  title AS name,
  NULL  AS description,
  'system' AS dashboard_type,
  'active' AS status,
  NULL  AS run_id,          -- backfilled in step 2b
  (spec->'quality'->>'quality_score')::float AS quality_score,
  (spec->'quality'->>'gate_passed')::boolean AS quality_gate_passed,
  spec->'chart_plan' AS chart_plan,
  created_at,
  updated_at
FROM public.quantyx_dashboard_specs
ON CONFLICT (dashboard_id) DO NOTHING;

-- 2b. Backfill run_id from agent_run_events
UPDATE public.quantyx_dashboards d
SET run_id = sub.run_id
FROM (
  SELECT DISTINCT ON (artifacts->>'dashboard_id')
    artifacts->>'dashboard_id' AS dashboard_id,
    run_id
  FROM public.quantyx_agent_run_events
  WHERE agent_name = 'DashboardAgent'
    AND status = 'completed'
    AND artifacts->>'dashboard_id' IS NOT NULL
  ORDER BY artifacts->>'dashboard_id', created_at DESC
) sub
WHERE d.dashboard_id = sub.dashboard_id
  AND d.dashboard_type = 'system';

-- 2c. Expand spec.charts array into dashboard_charts rows
-- (Run via Python migration script — see scripts/migrate_dashboard_specs.py)
-- Each element in spec->'charts' that has a chart_id gets one row in
-- quantyx_dashboard_charts with the correct position.
```

The Python migration script (`scripts/migrate_dashboard_specs.py`) handles step 2c because jsonb array expansion with positional index is cleaner in Python than in SQL.

### Step 3 — Migrate user dashboards (`quantyx_user_dashboards`)

```sql
-- 3a. Copy user dashboard headers
INSERT INTO public.quantyx_dashboards (
  dashboard_id, tenant_id, domain_id, name, description,
  dashboard_type, status, created_by, created_at, updated_at
)
SELECT
  dashboard_id, tenant_id, domain_id, name, description,
  'user' AS dashboard_type,
  status,
  created_by,
  created_at,
  updated_at
FROM public.quantyx_user_dashboards
ON CONFLICT (dashboard_id) DO NOTHING;

-- 3b. Copy chart links
INSERT INTO public.quantyx_dashboard_charts (
  entry_id, dashboard_id, chart_id, position, added_by, added_at
)
SELECT entry_id, dashboard_id, chart_id, position, added_by, added_at
FROM public.quantyx_user_dashboard_charts
ON CONFLICT (dashboard_id, chart_id) DO NOTHING;
```

### Step 4 — Backfill chart_source on existing chart_requests

```sql
-- Charts linked to agentic runs → 'agentic_run'
UPDATE public.quantyx_chart_requests
SET chart_source = 'agentic_run'
WHERE run_id IS NOT NULL
  AND chart_source IS NULL;

-- Remaining charts with a question → 'workspace'
UPDATE public.quantyx_chart_requests
SET chart_source = 'workspace'
WHERE run_id IS NULL
  AND question IS NOT NULL
  AND chart_source IS NULL;
```

---

## Code Change Inventory

A full audit of every file that touches the old tables or store functions, with exactly what must change.

---

### 1. `services/ai/dashboards_store.py` — **New file**

Create from scratch. This is the single source of truth for all dashboard and dashboard-chart operations. Replaces all dashboard logic currently split across `user_dashboards_store.py` and the dashboard functions in `semantic_graph_store.py`.

Public interface:

```python
create_dashboard(settings, *, tenant_id, domain_id, name, description, dashboard_type,
                 run_id, chart_plan, quality_score, quality_gate_passed, created_by) -> dict

get_dashboard(settings, dashboard_id, tenant_id=None) -> dict | None

list_dashboards(settings, tenant_id, domain_id=None, *, dashboard_type=None,
                status="active", limit=50, offset=0) -> list[dict]

update_dashboard(settings, dashboard_id, *, name=None, description=None, status=None,
                 run_id=None, latest_refresh_id=None, quality_score=None,
                 quality_gate_passed=None, chart_plan=None) -> dict | None

delete_dashboard(settings, dashboard_id, tenant_id=None) -> bool

add_chart(settings, dashboard_id, chart_id, *, position=None,
          title_override=None, added_by=None) -> dict

remove_chart(settings, dashboard_id, chart_id) -> bool

reorder_charts(settings, dashboard_id, ordered_chart_ids: list[str]) -> list[dict]

get_dashboard_with_charts(settings, dashboard_id, tenant_id=None) -> dict | None
# Returns dashboard row + charts[] with full quantyx_chart_requests data joined
```

All functions write to `quantyx_dashboards` and `quantyx_dashboard_charts`. No references to old tables.

---

### 2. `services/ai/user_dashboards_store.py` — **Deprecate → Delete**

All 9 functions become one-line delegates to `dashboards_store.py` during the transition window, then the file is deleted.

| Function | Delegates to |
|---|---|
| `create_user_dashboard()` | `dashboards_store.create_dashboard(..., dashboard_type="user")` |
| `get_user_dashboard()` | `dashboards_store.get_dashboard()` |
| `list_user_dashboards()` | `dashboards_store.list_dashboards(..., dashboard_type="user")` |
| `update_user_dashboard()` | `dashboards_store.update_dashboard()` |
| `delete_user_dashboard()` | `dashboards_store.delete_dashboard()` |
| `add_chart_to_dashboard()` | `dashboards_store.add_chart()` |
| `remove_chart_from_dashboard()` | `dashboards_store.remove_chart()` |
| `reorder_dashboard_charts()` | `dashboards_store.reorder_charts()` |
| `get_dashboard_with_charts()` | `dashboards_store.get_dashboard_with_charts()` |

Direct table references that must go: `quantyx_user_dashboards` (lines 28, 57, 94, 132, 147, 153, 196, 209, 214, 228, 233), `quantyx_user_dashboard_charts` (lines 167, 186, 209, 228, 264, 276).

---

### 3. `services/ai/semantic_graph_store.py` — **Update 4 functions**

| Function | Lines | Change |
|---|---|---|
| `persist_dashboard_spec()` | ~493–512 | Write header to `quantyx_dashboards` (`dashboard_type='system'`) and expand `spec.charts[]` into `quantyx_dashboard_charts` rows |
| `list_dashboard_specs()` | 514–535 | Delegate to `dashboards_store.list_dashboards(..., dashboard_type='system')` |
| `get_dashboard_spec()` | 538–549 | Delegate to `dashboards_store.get_dashboard()` |
| `update_dashboard_spec()` | 552–578 | Delegate to `dashboards_store.update_dashboard()` |

Direct table references that must go: `quantyx_dashboard_specs` (lines 504, 520, 530, 543, 573).

---

### 4. `services/ai/charts_store.py` — **Update 4 functions**

| Function | Change |
|---|---|
| `create_chart_request()` | Add `chart_source: str \| None`, `title: str \| None`, `created_by: str \| None` params. Include in INSERT column list and VALUES. |
| `get_chart_request()` | Add `chart_source`, `title`, `created_by` to SELECT column list. |
| `get_latest_chart_request_by_question()` | Add `chart_source`, `title`, `created_by` to SELECT column list. |
| `update_chart_request()` | Add optional `title: str \| None` param so titles can be set post-creation. |

No table rename — `quantyx_chart_requests` stays. Only additive column additions.

---

### 5. `services/api/schemas.py` — **Update 6 classes**

| Class | Lines | Change |
|---|---|---|
| `DashboardListResponse` | ~321 | Add `total: int` field; update `dashboards` items to unified shape |
| `DashboardResponse` | ~325 | Add `dashboard_type`, `description`, `run_id`, `latest_refresh_id`, `quality_score`, `quality_gate_passed`, `created_by`; remove system-only `spec` field from public response |
| `DashboardUpdateRequest` | ~335 | Replace with unified `UpdateDashboardRequest` covering both system and user fields |
| `CreateDashboardRequest` | ~2294 | Add `dashboard_type: str = "user"` field |
| `AddChartToDashboardRequest` | ~2307 | Add `title_override: str \| None` field |
| Chart response schema (inline dict) | various | Add `chart_source`, `title`, `created_by` to chart payloads returned in responses |

---

### 6. `services/api/main.py` — **Update imports + ~35 call sites + 4 endpoints**

**Imports (top of file):**

```python
# Remove
from services.ai.user_dashboards_store import (
    create_user_dashboard, get_user_dashboard, list_user_dashboards,
    update_user_dashboard, delete_user_dashboard, add_chart_to_dashboard,
    remove_chart_from_dashboard, reorder_dashboard_charts, get_dashboard_with_charts,
)

# Remove from semantic_graph_store import line
list_dashboard_specs, get_dashboard_spec, update_dashboard_spec

# Add
from services.ai.dashboards_store import (
    create_dashboard, get_dashboard, list_dashboards, update_dashboard,
    delete_dashboard, add_chart, remove_chart, reorder_charts,
    get_dashboard_with_charts,
)
```

**Call sites — dashboard functions (~18 usages):**

| Line(s) | Old call | New call |
|---|---|---|
| 11489 | `list_dashboard_specs(settings, tenant_id, domain_id)` | `list_dashboards(settings, tenant_id, domain_id, dashboard_type="system")` |
| 11587, 11683, 11739–40, 11813–14, 11886, 12272 | `get_dashboard_spec(settings, dashboard_id)` | `get_dashboard(settings, dashboard_id)` |
| 1131 | `get_dashboard_spec(settings, dashboard_id)` (in refresh worker) | `get_dashboard(settings, dashboard_id)` |
| 1270–74, 1291 | `update_dashboard_spec(settings, dashboard_id, spec=spec, ...)` | `update_dashboard(settings, dashboard_id, chart_plan=..., quality_score=..., ...)` |
| 8362 | `get_dashboard_spec(settings, link.get("dashboard_id"))` | `get_dashboard(settings, link.get("dashboard_id"))` |
| 18715 | `get_dashboard_spec(settings, dashboard_id)` (chart-plan endpoint) | `get_dashboard(settings, dashboard_id)` |
| 18945–50 | `create_user_dashboard(...)` | `create_dashboard(..., dashboard_type="user")` |
| 19011–21 | `list_user_dashboards(...)` | `list_dashboards(..., dashboard_type="user")` |
| 19090 | `get_dashboard_with_charts(...)` | `get_dashboard_with_charts(...)` (same name, new store) |
| 19148–58 | `update_user_dashboard(...)` | `update_dashboard(...)` |
| 19186–92 | `delete_user_dashboard(...)` | `delete_dashboard(...)` |
| 19261–80 | `add_chart_to_dashboard(...)` | `add_chart(...)` |
| 19313–17 | `remove_chart_from_dashboard(...)` | `remove_chart(...)` |
| 19379–83 | `reorder_dashboard_charts(...)` | `reorder_charts(...)` |

**Call sites — chart functions (add `chart_source`):**

| Line(s) | Caller context | `chart_source` value to add |
|---|---|---|
| 7509–18 | Workspace conversation | `"workspace"` |
| 17871–81 | Dataset chart creation | `"workspace"` |
| 18085–93 | Metric chart creation | `"workspace"` |
| 18177–90 | `POST /charts` endpoint | `"workspace"` |
| Agentic orchestrator (charts_store call) | Agentic run | `"agentic_run"` |

**Endpoint changes (4 merges):**

| Action | Old | New |
|---|---|---|
| Merge | `GET /dashboards` + `GET /dashboards/` | Single `GET /dashboards` with `dashboard_type` filter |
| Merge | `POST /dashboards/` | `POST /dashboards` (no trailing slash) |
| Merge | `GET /dashboards/{id}` (×2, lines 11531 + 19022) | Single handler using `get_dashboard_with_charts()` |
| Merge | `PUT /dashboards/{id}` + `PATCH /dashboards/{id}` | Single `PATCH /dashboards/{id}` using `update_dashboard()` |

---

### 7. `services/ai/agentic_orchestrator.py` — **4 changes**

This file has the most critical agentic-side wiring. It is the only place outside of `main.py` that calls both `persist_dashboard_spec` and `create_chart_request`.

**7a. Import change (line 46)**

```python
# Remove
from services.ai.semantic_graph_store import persist_dashboard_spec

# Add
from services.ai.dashboards_store import create_dashboard, add_chart as add_chart_to_dashboard
```

**7b. DashboardAgent — `persist_dashboard_spec` call site (lines 4580–4586)**

Current:
```python
dash_result = persist_dashboard_spec(settings, tenant_id, domain_id, dashboard_spec, title=dashboard_title)
dash_id = dash_result.get("dashboard_id")
state["dashboard_id"] = dash_id
```

After — decompose the spec blob; create the dashboard row then link each chart individually:
```python
dash_result = create_dashboard(
    settings,
    tenant_id=tenant_id, domain_id=domain_id,
    name=dashboard_title,
    dashboard_type="system",
    run_id=run_id,
    chart_plan=dashboard_spec.get("chart_plan"),
    quality_score=...,        # from spec.quality.quality_score
    quality_gate_passed=...,  # from spec.quality.gate_passed
)
dash_id = dash_result.get("dashboard_id")
state["dashboard_id"] = dash_id
# Link each chart that was created during this run
for position, chart_id in enumerate(chart_ids):
    add_chart_to_dashboard(settings, dash_id, chart_id, position=position, added_by="DashboardAgent")
```

The emitted event payload (lines 4598–4604) that writes `dashboard_id` and `chart_ids` into `quantyx_agent_run_events.artifacts` JSONB **does not need to change** — it already stores whatever `dash_id` is in state.

**7c. AnomalyDetectionAgent — `persist_dashboard_spec` call site (lines 5302–5308)**

Same change as 7b — replace with `create_dashboard(..., dashboard_type="system")` then `add_chart_to_dashboard()` for each anomaly chart in `chart_ids`.

```python
anomaly_dash = create_dashboard(
    settings,
    tenant_id=tenant_id, domain_id=domain_id,
    name=dashboard_title,
    dashboard_type="system",
    run_id=run_id,
)
anomaly_dashboard_id = anomaly_dash.get("dashboard_id")
for position, chart_id in enumerate(anomaly_chart_ids):
    add_chart_to_dashboard(settings, anomaly_dashboard_id, chart_id, position=position, added_by="AnomalyDetectionAgent")
```

**7d. `create_chart_request` call sites — add `chart_source="agentic_run"`**

| Lines | Context | Change |
|---|---|---|
| 4083–4101 | DashboardAgent chart creation loop | Add `chart_source="agentic_run"` |
| 5259–5276 | AnomalyDetectionAgent chart creation loop | Add `chart_source="agentic_run"` |

`update_chart_request` call sites (lines 4117–4127 and 5279–5289) — **no change needed**.

**7e. `/agentic/runs` API routes — no change needed**

The six agentic run routes (`GET /agentic/runs/{run_id}`, `/events`, `/events/{id}/artifacts`, `/stream`, `/chat`, `POST /agentic/runs`) read `dashboard_id` and `chart_ids` from the `quantyx_agent_run_events.artifacts` JSONB column. That JSONB is written by the orchestrator at step 7b/7c above and already contains whatever ID is returned by the store. The routes themselves are pure pass-through — they do not query `quantyx_dashboard_specs` or `quantyx_user_dashboards` directly. **No route-level change required.**

The one place that does resolve a `dashboard_id` from agent events is `list_dashboards_endpoint` (line 11489) — already covered in item 6 above.

---

### 8. Correlation modules — confirmed scope

**`services/ai/correlation_agent.py` — No change**

Only READS from `quantyx_chart_requests` (lines 143, 158 — two SELECT queries scoped by `run_id` or `tenant_id/domain_id`). Table name is unchanged; the new `chart_source`, `title`, `created_by` columns are additive and don't affect these reads.

**`services/ai/correlation_store.py` — No change**

Writes exclusively to Phase 43 correlation tables (`quantyx_correlation_runs`, `quantyx_anomaly_results`, `quantyx_correlation_pairs`, `quantyx_investigation_threads`, `quantyx_forward_projections`). No dashboard or chart table writes.

**`services/ai/correlation_charts.py` — No change**

Pure spec generation — computes amCharts 5 JSON specs for six chart types. No database writes at all.

**Correlation chart bridging — implemented in Phase 44**

Correlation charts (forecast bands, heatmaps, scatter plots, etc.) were previously generated as JSON specs and discarded — never written to `quantyx_chart_requests`. Phase 44 bridges them:

**`_run_correlation_background` (main.py ~line 19414)**

After `generate_correlation_charts()` returns its list of `{chart_type, metric_name, pair_id, correlation_run_id, spec}` dicts, the background worker now:

1. Calls `create_chart_request(chart_source="correlation", created_by="CorrelationAgent")` for each chart spec, collecting `chart_id` values
2. Calls `update_chart_request(status="completed", chart_type=..., chart_payload=spec)` immediately — correlation charts have no async SQL step
3. Creates a `quantyx_dashboards` row (`dashboard_type="system"`) via `create_dashboard()`
4. Links every registered chart via `add_chart_to_dashboard()`

This means:
- Correlation charts now have a `chart_id` in `quantyx_chart_requests` with `chart_source = "correlation"`
- They appear in `GET /dashboards` alongside system and user dashboards
- They can be pinned to user dashboards via `POST /dashboards/{id}/charts`
- `GET /charts/{id}` returns the full amCharts 5 spec in `chart_payload`

**`services/ai/charts_store.py` — updated** (`create_chart_request` accepts `chart_source`, `title`, `created_by`)

**`services/ai/dashboards_store.py` — new file** (CRUD over `quantyx_dashboards` + `quantyx_dashboard_charts`)

---

### 9. `services/ai/anomaly_store.py` — **No code change, migration safety note**

This file stores `dashboard_id` as a plain text foreign reference in two tables:

| Table | Column | Stores |
|---|---|---|
| `quantyx_anomaly_investigations` | `dashboard_id` | ID of the anomaly dashboard created by AnomalyDetectionAgent |
| `quantyx_anomaly_investigations` | `source_dashboard_id` | ID of the source system dashboard that triggered the investigation |
| `quantyx_anomaly_dashboard_links` | `dashboard_id` | Same IDs as above, in a link/join table |

These columns store `dash_` prefixed IDs written by `persist_dashboard_spec()` in the orchestrator. After the migration, those same `dash_` IDs are preserved in `quantyx_dashboards` (via `ON CONFLICT DO NOTHING` in Step 3 of the migration script). All existing anomaly links remain valid — no data inconsistency.

No code change is required in `anomaly_store.py`. The `dashboard_id` string value is correct regardless of which table it physically lives in.

---

### 10. `services/ai/tenant_purge.py` — **Update purge table list**

| Change | Lines |
|---|---|
| Add `quantyx_dashboards` to the purge list | ~line 91 |
| Add `quantyx_dashboard_charts` to the purge list | ~line 91 |
| Keep `quantyx_chart_requests` (unchanged table name) | line 90 |
| Remove `quantyx_dashboard_specs`, `quantyx_user_dashboards`, `quantyx_user_dashboard_charts` from purge list after old tables are dropped | ~line 91 |
| Line 472 JOIN on `quantyx_chart_requests` — no change needed | line 472 |

---

### 10. `scripts/verify_workspace_deployment_persistence.py` — **Update 2 queries**

| Lines | Change |
|---|---|
| ~619, ~628 | `SELECT ... FROM public.quantyx_dashboard_specs` → `SELECT ... FROM public.quantyx_dashboards WHERE dashboard_type = 'system'` |

---

### 11. `artifacts/quantyx_agentic_tables.sql` — **Add new DDL, annotate retired tables**

| Change |
|---|
| Add `CREATE TABLE quantyx_dashboards` DDL |
| Add `CREATE TABLE quantyx_dashboard_charts` DDL |
| Mark `quantyx_dashboard_specs` as retired with a comment |

---

### 12. `scripts/apply_agentic_tables.sh` — **No change needed**

The migration is handled by `scripts/migrate_unified_dashboards.sh`. The apply script doesn't need updating.

---

### Summary — Complete File Change List

| File | Status | Key details |
|---|---|---|
| `services/ai/dashboards_store.py` | **Created ✅** | New unified CRUD — 9 functions over `quantyx_dashboards` + `quantyx_dashboard_charts`; `get_dashboard_with_charts` includes `sql`, `params`, `query_payload`, `chart_data` in JOIN |
| `services/ai/user_dashboards_store.py` | **Delegated ✅** | All 9 functions are thin delegates to `dashboards_store`; file kept for backward compat during cutover |
| `services/ai/semantic_graph_store.py` | **Updated ✅** | `persist_dashboard_spec`, `list/get/update_dashboard_spec` delegate to `dashboards_store`; `get_dashboard_spec` synthesizes backward-compat `spec` blob so refresh worker still works |
| `services/ai/charts_store.py` | **Updated ✅** | `create_chart_request` accepts `chart_source`, `title`, `created_by`; gracefully handles `UndefinedColumn` pre-migration |
| `services/ai/agentic_orchestrator.py` | **Updated ✅** | Import changed; `persist_dashboard_spec` (×2) replaced with `_create_dashboard` + `_add_chart_to_dashboard`; `chart_source="agentic_run"` added to `create_chart_request` (×2) |
| `services/api/main.py` | **Updated ✅** | `dashboards_store` imports added; `user_dashboards_store` import kept as delegating shim; `chart_source="workspace"` added to 4 workspace call sites; `list_dashboards`, `get_dashboard`, `update_dashboard`, `delete_dashboard` imported |
| `services/ai/correlation_agent.py` | No change | Read-only SQL on `quantyx_chart_requests`; new columns are additive |
| `services/ai/correlation_store.py` | No change | Writes only to Phase 43 correlation tables — no dashboard/chart writes |
| `services/ai/correlation_charts.py` | No change | Pure spec generation; return value is now consumed by `_run_correlation_background` |
| `services/ai/anomaly_store.py` | No change | Stores `dashboard_id` as text — old `dash_` IDs preserved in new table by migration |
| `services/ai/tenant_purge.py` | **Updated ✅** | Added `quantyx_dashboards`, `quantyx_dashboard_charts`; added `quantyx_user_dashboards`, `quantyx_user_dashboard_charts` (with retire annotation) |
| `services/api/schemas.py` | **Updated ✅** | `DashboardListResponse` gains `total`; `DashboardResponse` gains `dashboard_type`, `name`, `description`, `run_id`, `quality_score`, `quality_gate_passed`, `created_by`, `charts`, optional `spec`; `CreateDashboardRequest` gains `dashboard_type`; `AddChartToDashboardRequest` gains `title_override`; `UpdateDashboardRequest` gains `status` |
| `services/api/main.py` endpoint merges | **Updated ✅** | `list_dashboards_endpoint` returns both types unified with `dashboard_type` filter param; `get_dashboard_endpoint` handles both system and user; `GET /dashboards/` hidden (`include_in_schema=False`) as alias; `POST /dashboards/` → `POST /dashboards`; duplicate `GET /dashboards/{id}` hidden; all user handlers use `_ds_` store functions |
| `scripts/verify_workspace_deployment_persistence.py` | **Updated ✅** | `quantyx_dashboard_specs` → `quantyx_dashboards WHERE dashboard_type='system'` |
| `artifacts/quantyx_agentic_tables.sql` | **Updated ✅** | `quantyx_dashboards` + `quantyx_dashboard_charts` DDL added; old tables annotated as retired with DROP commands |
| `scripts/migrate_unified_dashboards.sh` | **Created ✅** | Idempotent 8-step migration |

### `_synthesize_spec()` — backward compatibility helper

`semantic_graph_store.get_dashboard_spec()` now calls `dashboards_store.get_dashboard_with_charts()` and reconstructs the `spec` JSONB structure that callers expect:

```python
spec = {
    "charts": [
        {
            "chart_id": ..., "title": ..., "type": ...,
            "sql": ..., "params": ..., "metric": ...,
            "dimensions": ..., "chart_data": ..., "chart_payload": ...
        }
    ],
    "chart_plan": [...],          # from quantyx_dashboards.chart_plan
    "quality": {
        "quality_score": ...,     # from quantyx_dashboards.quality_score
        "gate_passed": ...,       # from quantyx_dashboards.quality_gate_passed
    }
}
```

This ensures the dashboard refresh worker (`job_type == "dashboard_refresh"`, line ~1135) continues to work without any changes — it reads `spec.get("charts")` to know which charts to re-execute.

### `/agentic/runs` routes — explicitly confirmed NO change needed

The six agentic run routes read `dashboard_id` and `chart_ids` from `quantyx_agent_run_events.artifacts` JSONB. That JSONB is written by the orchestrator (step 7b/7c above) and already stores whatever ID is returned by whichever store function creates the dashboard. The routes are pure pass-through and do not query `quantyx_dashboard_specs` or any old table directly.

| Route | Confirmed safe |
|---|---|
| `POST /agentic/runs` | Starts run — no dashboard/chart table access |
| `GET /agentic/runs/{run_id}` | Returns run metadata — no dashboard/chart table access |
| `GET /agentic/runs/{run_id}/events` | Reads `quantyx_agent_run_events.artifacts` JSONB — pass-through of whatever ID is stored |
| `GET /agentic/runs/{run_id}/events/{event_id}/artifacts` | Same — reads JSONB artifacts |
| `GET /agentic/runs/{run_id}/stream` | SSE stream of event rows — pass-through |
| `GET /agentic/runs/{run_id}/chat` | Extracts `dashboard_id`, `chart_ids` from JSONB via `_events_as_chat_messages()` — pass-through |

---

## API Changes

### Current State → Final State (route delta)

**Before Phase 44: 20 routes, fragmented across two parallel sets**

| Method | Route | Serves |
|---|---|---|
| `GET` | `/dashboards` | System dashboards only |
| `GET` | `/dashboards/` | User dashboards only — **duplicate list** |
| `POST` | `/dashboards/` | Create user dashboard |
| `GET` | `/dashboards/{id}` | System dashboard (line 11531) |
| `GET` | `/dashboards/{id}` | User dashboard + charts (line 19022) — **duplicate path** |
| `PUT` | `/dashboards/{id}` | Update system dashboard |
| `PATCH` | `/dashboards/{id}` | Update user dashboard — **duplicate path** |
| `DELETE` | `/dashboards/{id}` | User dashboard only |
| `POST` | `/dashboards/{id}/charts` | User dashboard — add chart |
| `DELETE` | `/dashboards/{id}/charts/{chart_id}` | User dashboard — remove chart |
| `PUT` | `/dashboards/{id}/charts/order` | User dashboard — reorder |
| `POST` | `/dashboards/{id}/refresh` | System dashboard refresh |
| `GET` | `/dashboards/{id}/refresh/{refresh_id}` | Refresh status |
| `GET` | `/dashboards/{id}/refresh/{refresh_id}/events` | Refresh events |
| `GET` | `/dashboards/{id}/refresh/{refresh_id}/stream` | Refresh SSE stream |
| `GET` | `/dashboards/{id}/insights` | System insights |
| `POST` | `/charts` | Create chart |
| `GET` | `/charts/{id}` | Get chart |
| `GET` | `/charts/plan` | Dashboard chart plan (dashboard-scoped, wrong home) |
| `GET` | `/charts/{id}/conversations` | Conversations from chart |

---

**After Phase 44: 18 routes, fully unified**

### Dashboard Routes (13 routes)

| Method | Route | Purpose | Notes |
|---|---|---|---|
| `GET` | `/dashboards` | List all dashboards | Filter by `dashboard_type=system\|user`, `status`, `domain_id`, `limit`, `offset` |
| `POST` | `/dashboards` | Create a dashboard | `dashboard_type` in body (`system` or `user`) |
| `GET` | `/dashboards/{id}` | Get dashboard + its charts | Works for both types |
| `PATCH` | `/dashboards/{id}` | Update dashboard metadata | Replaces both `PUT` and `PATCH` |
| `DELETE` | `/dashboards/{id}` | Archive or delete a dashboard | Works for both types |
| `POST` | `/dashboards/{id}/charts` | Pin a chart to the dashboard | Works for both types |
| `DELETE` | `/dashboards/{id}/charts/{chart_id}` | Remove a chart from the dashboard | Works for both types |
| `PUT` | `/dashboards/{id}/charts/order` | Reorder charts | Works for both types |
| `POST` | `/dashboards/{id}/refresh` | Trigger data refresh | System dashboards; no-op or 400 for user dashboards |
| `GET` | `/dashboards/{id}/refresh/{refresh_id}` | Refresh run status | No change |
| `GET` | `/dashboards/{id}/refresh/{refresh_id}/events` | Refresh events list | No change |
| `GET` | `/dashboards/{id}/refresh/{refresh_id}/stream` | SSE stream of refresh | No change |
| `GET` | `/dashboards/{id}/insights` | AI insights for dashboard | No change |

**Removed:** `GET /dashboards/`, `POST /dashboards/`, duplicate `GET /dashboards/{id}` (19022), `PUT /dashboards/{id}` (merged into `PATCH`)

### Chart Routes (5 routes)

| Method | Route | Purpose | Notes |
|---|---|---|---|
| `POST` | `/charts` | Create a chart | Adds `chart_source`, `title`, `created_by` to request/response |
| `GET` | `/charts/{id}` | Get chart status + payload | Response gains `chart_source`, `title`, `created_by` |
| `GET` | `/charts/{id}/conversations` | Conversations spawned from this chart | No change |
| `GET` | `/dashboards/{id}/chart-plan` | Chart plan for a dashboard | **Moved** from `/charts/plan` — it is dashboard-scoped |
| ~~`GET`~~ | ~~`/charts/plan`~~ | *(retired)* | Replaced by `/dashboards/{id}/chart-plan` |

---

### Unified Response Shapes

**`GET /dashboards` — list response:**

```json
{
  "total": 8,
  "dashboards": [
    {
      "dashboard_id": "dash_abc",
      "dashboard_type": "system",
      "tenant_id": "LPG_206",
      "domain_id": "lpg_production_distribution",
      "name": "LPG Production Dashboard",
      "description": null,
      "status": "active",
      "chart_count": 6,
      "run_id": "run_xxx",
      "latest_refresh_id": "dref_xxx",
      "quality_score": 0.9,
      "quality_gate_passed": true,
      "created_by": null,
      "created_at": "2026-03-01T10:00:00Z",
      "updated_at": "2026-03-01T10:00:00Z"
    },
    {
      "dashboard_id": "udash_def",
      "dashboard_type": "user",
      "tenant_id": "LPG_206",
      "domain_id": "lpg_production_distribution",
      "name": "My Zone View",
      "description": "Zone-wise productivity charts",
      "status": "active",
      "chart_count": 3,
      "run_id": null,
      "latest_refresh_id": null,
      "quality_score": null,
      "quality_gate_passed": null,
      "created_by": "user_001",
      "created_at": "2026-03-25T10:00:00Z",
      "updated_at": "2026-03-25T10:00:00Z"
    }
  ]
}
```

**`GET /dashboards/{id}` — detail response (both types):**

```json
{
  "dashboard_id": "dash_abc",
  "dashboard_type": "system",
  "name": "LPG Production Dashboard",
  "description": null,
  "status": "active",
  "run_id": "run_xxx",
  "latest_refresh_id": "dref_xxx",
  "quality_score": 0.9,
  "quality_gate_passed": true,
  "created_by": null,
  "created_at": "...",
  "updated_at": "...",
  "charts": [
    {
      "entry_id": "dc_001",
      "chart_id": "chart_xyz",
      "position": 0,
      "title_override": null,
      "chart_type": "line",
      "title": "Monthly Productivity Trend",
      "chart_source": "agentic_run",
      "status": "completed"
    }
  ]
}
```

**`GET /charts/{id}` — chart response (new fields):**

```json
{
  "chart_id": "chart_xyz",
  "chart_source": "agentic_run",
  "title": "Monthly Productivity by Zone",
  "created_by": null,
  "tenant_id": "LPG_206",
  "domain_id": "lpg_production_distribution",
  "run_id": "run_xxx",
  "question": "Show productivity trend by month",
  "sql": "SELECT ...",
  "chart_type": "line",
  "chart_payload": {},
  "rows_json": [],
  "status": "completed",
  "created_at": "...",
  "updated_at": "..."
}
```

### `chart_source` values

| Value | Set by | Meaning |
|---|---|---|
| `agentic_run` | Agentic orchestrator | Chart generated during a canonical deployment run |
| `workspace` | Workspace conversation | Chart generated from a user question in a conversation |
| `correlation` | CorrelationAgent | Chart generated by the Phase 43 statistical correlation run |
| `user_pin` | UI / future | Chart pinned manually by a user (future) |
| `unknown` | Migration backfill | Pre-existing chart with no traceable source |

---

## Migration Script

All database migration steps are consolidated in a single idempotent shell script:

```
scripts/migrate_unified_dashboards.sh
```

Run it with:

```bash
bash scripts/migrate_unified_dashboards.sh
```

Prerequisites:
- `.env` file present with `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- Python 3.10+ with `psycopg2` installed (used for Step 8 — JSON array expansion)
- Script is **idempotent**: safe to re-run; uses `ON CONFLICT DO NOTHING` and `IF NOT EXISTS` throughout

### What the script executes

| Step | Action | Mechanism |
|---|---|---|
| 1 | Create `quantyx_dashboards` table + indexes | `CREATE TABLE IF NOT EXISTS` |
| 1 | Create `quantyx_dashboard_charts` table + indexes | `CREATE TABLE IF NOT EXISTS` |
| 2 | Add `chart_source`, `title`, `created_by` to `quantyx_chart_requests` | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |
| 3 | Copy system dashboards from `quantyx_dashboard_specs` | `INSERT ... ON CONFLICT DO NOTHING` |
| 4 | Backfill `run_id` from `quantyx_agent_run_events` (DashboardAgent) | `UPDATE ... WHERE run_id IS NULL` |
| 5 | Copy user dashboards from `quantyx_user_dashboards` | `INSERT ... ON CONFLICT DO NOTHING` |
| 6 | Copy chart links from `quantyx_user_dashboard_charts` | `INSERT ... ON CONFLICT DO NOTHING` |
| 7 | Set `chart_source = 'agentic_run'` where `run_id IS NOT NULL` | `UPDATE` |
| 7 | Set `chart_source = 'workspace'` where `question IS NOT NULL` | `UPDATE` |
| 7 | Set `chart_source = 'unknown'` for any remaining nulls | `UPDATE` |
| 8 | Expand `spec.charts[]` from `quantyx_dashboard_specs` into `quantyx_dashboard_charts` rows | Python inline script |

The script prints a verification summary (row counts by `dashboard_type` and `chart_source`) at the end and lists the `DROP TABLE` commands to run manually after smoke-testing.

### Old tables — drop only after validation

```sql
-- Run manually after confirming the new tables serve all API traffic
DROP TABLE public.quantyx_user_dashboard_charts;
DROP TABLE public.quantyx_user_dashboards;
DROP TABLE public.quantyx_dashboard_specs;
```

---

## Implementation Sequence

```
Step 1: Run DB migration
        bash scripts/migrate_unified_dashboards.sh

Step 2: Create services/ai/dashboards_store.py
        Full CRUD over quantyx_dashboards + quantyx_dashboard_charts

Step 3: Update services/ai/charts_store.py
        Add chart_source, title, created_by to create_chart_request()
        Update all callers (agentic_orchestrator.py, main.py workspace routes)

Step 4: Update services/ai/semantic_graph_store.py
        persist_dashboard_spec() → writes to quantyx_dashboards + quantyx_dashboard_charts
        list/get/update dashboard functions → delegate to dashboards_store

Step 5: Update services/ai/user_dashboards_store.py
        All functions delegate to dashboards_store (keeps callers working during cutover)

Step 6: Update services/api/schemas.py
        Unified DashboardResponse, DashboardListResponse with dashboard_type
        Add chart_source, title, created_by to chart response schemas

Step 7: Update services/api/main.py
        Merge GET /dashboards + GET /dashboards/ → single endpoint
        All dashboard handlers use dashboards_store
        chart_source set on all chart creation paths

Step 8: Validate + remove dead code
        Delete user_dashboards_store.py after all callers are updated
        Drop old tables (see SQL above)
```

---

## Tables to Retire (after validation)

| Table | Replaced by |
|---|---|
| `quantyx_dashboard_specs` | `quantyx_dashboards` (dashboard_type = 'system') |
| `quantyx_user_dashboards` | `quantyx_dashboards` (dashboard_type = 'user') |
| `quantyx_user_dashboard_charts` | `quantyx_dashboard_charts` |

**Tables that stay unchanged:**

| Table | Reason |
|---|---|
| `quantyx_chart_requests` | Evolved in-place (additive columns only) |
| `quantyx_chart_events` | Append-only audit log, `chart_id` reference is stable |
| `quantyx_dashboard_chart_snapshots` | Refresh snapshot, `dashboard_id` reference backfilled to new IDs |
| `quantyx_dashboard_refresh_runs` | Refresh job tracker — `dashboard_id` field updated to match new IDs |
| `quantyx_dashboard_insight_artifacts` | Same as above |