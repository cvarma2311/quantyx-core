# Phase 38: Chart Conversations and User Dashboard Management

## Objective

Two independent features built on top of the existing `quantyx_chart_requests` and
`quantyx_workspace_conversations` infrastructure:

1. **Chart-based conversation linking** — a conversation can be started from a chart, and
   all conversations linked to a given `chart_id` can be fetched.

2. **User-created dashboard management** — users can create named dashboards, add any
   `chart_id` (from agentic runs or ad-hoc chart builds) to them, reorder charts, and
   manage dashboards independently of agentic deployment runs.

---

## Current State

### Relevant existing tables

| Table | Key columns |
|---|---|
| `quantyx_chart_requests` | `chart_id`, `tenant_id`, `domain_id`, `question`, `chart_type`, `chart_data`, `status` |
| `quantyx_workspace_conversations` | `conversation_id`, `tenant_id`, `domain_id`, `run_id` |
| `quantyx_workspace_messages` | `message_id`, `conversation_id`, `tenant_id`, `domain_id` |
| `quantyx_dashboard_refresh_runs` | agentic deployment dashboards — not user-managed |
| `quantyx_dashboard_chart_snapshots` | agentic chart snapshots per refresh — not user-managed |

### Gap

- No link exists between `chart_id` and `conversation_id`.
- No user-managed dashboard table exists. Existing `quantyx_dashboard_*` tables
  are exclusively for agentic deployment refresh cycles.

---

## Feature 1: Chart-based Conversations

### Schema change — `quantyx_tables_updates.sql`

Add `source_chart_id` to `quantyx_workspace_conversations`:

```sql
ALTER TABLE public.quantyx_workspace_conversations
  ADD COLUMN IF NOT EXISTS source_chart_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_workspace_conversations_chart
  ON public.quantyx_workspace_conversations (source_chart_id, created_at DESC)
  WHERE source_chart_id IS NOT NULL;
```

This is a nullable back-reference. Conversations not started from a chart leave it NULL.

### Store change — `services/ai/workspace_store.py`

Add `source_chart_id` parameter to `create_workspace_conversation`:

```python
def create_workspace_conversation(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    run_id: str,
    source_chart_id: str | None = None,
) -> dict:
    conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
    sql = """
        INSERT INTO public.quantyx_workspace_conversations
          (conversation_id, tenant_id, domain_id, run_id, source_chart_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING conversation_id, created_at
    """
    ...
```

Add a new read function:

```python
def list_conversations_by_chart(
    settings: Settings,
    chart_id: str,
    tenant_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return all conversations that originated from a given chart_id."""
    sql = """
        SELECT c.conversation_id, c.tenant_id, c.domain_id, c.run_id,
               c.source_chart_id, c.created_at, c.updated_at,
               COUNT(m.message_id) AS message_count
          FROM public.quantyx_workspace_conversations c
          LEFT JOIN public.quantyx_workspace_messages m
                 ON m.conversation_id = c.conversation_id
         WHERE c.source_chart_id = %s
           AND (%s IS NULL OR c.tenant_id = %s)
         GROUP BY c.conversation_id
         ORDER BY c.created_at DESC
         LIMIT %s OFFSET %s
    """
    ...
```

### API changes — `services/api/main.py`

#### New route: GET conversations for a chart

```
GET /charts/{chart_id}/conversations
```

Query params: `tenant_id` (optional), `limit` (default 50), `offset` (default 0)

Response:
```json
{
  "chart_id": "chart_abc123",
  "total": 3,
  "conversations": [
    {
      "conversation_id": "conv_xyz",
      "tenant_id": "a13",
      "domain_id": "market_performance_analysis",
      "run_id": "run_abc",
      "source_chart_id": "chart_abc123",
      "message_count": 7,
      "created_at": "2026-03-25T10:00:00Z",
      "updated_at": "2026-03-25T10:05:00Z"
    }
  ]
}
```

#### Modified route: POST create conversation (existing endpoint)

Extend the request body to accept `source_chart_id`:

```
POST /agentic/conversations
```

Request body addition:
```json
{
  "run_id": "run_abc",
  "tenant_id": "a13",
  "domain_id": "market_performance_analysis",
  "source_chart_id": "chart_abc123"   ← new optional field
}
```

### Schema model — `services/api/schemas.py`

```python
class CreateConversationRequest(BaseModel):
    run_id: str
    tenant_id: str
    domain_id: str
    source_chart_id: Optional[str] = None
```

---

## Feature 2: User Dashboard Management

### New tables — `quantyx_tables_updates.sql`

#### `quantyx_user_dashboards`

Stores user-created named dashboards. Independent of agentic deployment dashboards.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_user_dashboards (
  dashboard_id   TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL,
  domain_id      TEXT NOT NULL,
  name           TEXT NOT NULL,
  description    TEXT NULL,
  status         TEXT NOT NULL DEFAULT 'active',  -- active | archived
  created_by     TEXT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_dashboards_tenant
  ON public.quantyx_user_dashboards (tenant_id, domain_id, status, updated_at DESC);
```

#### `quantyx_user_dashboard_charts`

Junction table: which charts belong to which dashboard, with explicit ordering.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_user_dashboard_charts (
  entry_id       TEXT PRIMARY KEY,
  dashboard_id   TEXT NOT NULL REFERENCES public.quantyx_user_dashboards(dashboard_id)
                   ON DELETE CASCADE,
  chart_id       TEXT NOT NULL,
  position       INTEGER NOT NULL DEFAULT 0,  -- display order within dashboard
  added_by       TEXT NULL,
  added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (dashboard_id, chart_id)             -- a chart appears once per dashboard
);

CREATE INDEX IF NOT EXISTS idx_user_dashboard_charts_dashboard
  ON public.quantyx_user_dashboard_charts (dashboard_id, position ASC);

CREATE INDEX IF NOT EXISTS idx_user_dashboard_charts_chart
  ON public.quantyx_user_dashboard_charts (chart_id);
```

### New store — `services/ai/user_dashboards_store.py`

```python
def create_user_dashboard(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    name: str,
    description: str | None = None,
    created_by: str | None = None,
) -> dict: ...

def get_user_dashboard(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
) -> dict | None: ...

def list_user_dashboards(
    settings: Settings,
    tenant_id: str,
    domain_id: str | None = None,
    status: str = "active",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]: ...

def update_user_dashboard(
    settings: Settings,
    dashboard_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict | None: ...

def delete_user_dashboard(
    settings: Settings,
    dashboard_id: str,
) -> bool: ...

def add_chart_to_dashboard(
    settings: Settings,
    dashboard_id: str,
    chart_id: str,
    position: int | None = None,  # None = append at end
    added_by: str | None = None,
) -> dict: ...

def remove_chart_from_dashboard(
    settings: Settings,
    dashboard_id: str,
    chart_id: str,
) -> bool: ...

def reorder_dashboard_charts(
    settings: Settings,
    dashboard_id: str,
    ordered_chart_ids: list[str],   # full new order
) -> list[dict]: ...

def get_dashboard_with_charts(
    settings: Settings,
    dashboard_id: str,
    tenant_id: str | None = None,
    include_chart_data: bool = True,
) -> dict | None:
    """
    Returns dashboard metadata + all charts in position order.
    Joins with quantyx_chart_requests to pull chart_type, chart_payload,
    chart_data, metric, title, status.
    """
    ...
```

### New API routes — `services/api/main.py`

All routes live under `/dashboards/`.

---

#### `POST /dashboards/`

Create a new named dashboard.

Request:
```json
{
  "tenant_id": "a13",
  "domain_id": "market_performance_analysis",
  "name": "HPCL Sales Overview",
  "description": "Key sales and target charts for FY2026"
}
```

Response `201`:
```json
{
  "dashboard_id": "udash_a1b2c3d4e5",
  "tenant_id": "a13",
  "domain_id": "market_performance_analysis",
  "name": "HPCL Sales Overview",
  "description": "Key sales and target charts for FY2026",
  "status": "active",
  "chart_count": 0,
  "created_at": "2026-03-25T10:00:00Z"
}
```

---

#### `GET /dashboards/`

List dashboards for a tenant.

Query params: `tenant_id` (required), `domain_id` (optional), `status` (default `active`),
`limit` (default 50), `offset` (default 0)

Response:
```json
{
  "total": 2,
  "dashboards": [
    {
      "dashboard_id": "udash_a1b2c3d4e5",
      "name": "HPCL Sales Overview",
      "domain_id": "market_performance_analysis",
      "chart_count": 4,
      "status": "active",
      "updated_at": "2026-03-25T10:05:00Z"
    }
  ]
}
```

---

#### `GET /dashboards/{dashboard_id}`

Get a dashboard with all its charts in order.

Query params: `tenant_id` (optional, used for access check)

Response:
```json
{
  "dashboard_id": "udash_a1b2c3d4e5",
  "name": "HPCL Sales Overview",
  "domain_id": "market_performance_analysis",
  "description": "...",
  "status": "active",
  "charts": [
    {
      "entry_id": "dce_001",
      "position": 0,
      "chart_id": "chart_344ec6b3c9",
      "title": "Daily Sales by Month",
      "chart_type": "line",
      "metric": "daily_sales",
      "status": "ready",
      "chart_payload": { ... },
      "chart_data": [ ... ],
      "added_at": "2026-03-25T10:01:00Z"
    },
    {
      "entry_id": "dce_002",
      "position": 1,
      "chart_id": "chart_c762fa59d7",
      "title": "Target Qty Tmt by Month",
      "chart_type": "line",
      "metric": "TARGET_QTY_TMT",
      "status": "ready",
      "chart_payload": { ... },
      "chart_data": [ ... ],
      "added_at": "2026-03-25T10:02:00Z"
    }
  ],
  "created_at": "2026-03-25T10:00:00Z",
  "updated_at": "2026-03-25T10:05:00Z"
}
```

---

#### `PATCH /dashboards/{dashboard_id}`

Rename or update dashboard metadata.

Request:
```json
{
  "name": "HPCL FY2026 Executive Dashboard",
  "description": "Updated description"
}
```

Response `200`: updated dashboard object (without charts for speed).

---

#### `DELETE /dashboards/{dashboard_id}`

Soft-delete (sets `status = 'archived'`) or hard-delete depending on `permanent` query param.

Query params: `permanent=false` (default) | `permanent=true`

Response `200`:
```json
{ "dashboard_id": "udash_a1b2c3d4e5", "status": "archived" }
```

---

#### `POST /dashboards/{dashboard_id}/charts`

Add a chart to a dashboard. If the chart is already in the dashboard, returns `409`.

Request:
```json
{
  "chart_id": "chart_344ec6b3c9",
  "position": 0
}
```

`position` is optional — omit to append at the end.

Response `201`:
```json
{
  "entry_id": "dce_001",
  "dashboard_id": "udash_a1b2c3d4e5",
  "chart_id": "chart_344ec6b3c9",
  "position": 0,
  "title": "Daily Sales by Month",
  "chart_type": "line",
  "status": "ready",
  "added_at": "2026-03-25T10:01:00Z"
}
```

---

#### `DELETE /dashboards/{dashboard_id}/charts/{chart_id}`

Remove a chart from a dashboard. Does not delete the chart itself.

Response `200`:
```json
{ "dashboard_id": "udash_a1b2c3d4e5", "chart_id": "chart_344ec6b3c9", "removed": true }
```

---

#### `PUT /dashboards/{dashboard_id}/charts/order`

Reorder all charts in a dashboard by supplying the full ordered list of `chart_id`s.

Request:
```json
{
  "chart_ids": [
    "chart_c762fa59d7",
    "chart_344ec6b3c9",
    "chart_ce1784971c"
  ]
}
```

Response `200`:
```json
{
  "dashboard_id": "udash_a1b2c3d4e5",
  "chart_count": 3,
  "order": [
    { "position": 0, "chart_id": "chart_c762fa59d7" },
    { "position": 1, "chart_id": "chart_344ec6b3c9" },
    { "position": 2, "chart_id": "chart_ce1784971c" }
  ]
}
```

---

### Schema models — `services/api/schemas.py`

```python
class CreateDashboardRequest(BaseModel):
    tenant_id: str
    domain_id: str
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None

class UpdateDashboardRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class AddChartToDashboardRequest(BaseModel):
    chart_id: str
    position: Optional[int] = None

class ReorderDashboardChartsRequest(BaseModel):
    chart_ids: list[str]
```

---

## Implementation Order

### Step 1 — Schema migrations

File: `artifacts/quantyx_tables_updates.sql`

1. `ALTER TABLE quantyx_workspace_conversations ADD COLUMN IF NOT EXISTS source_chart_id TEXT NULL`
2. Add index on `source_chart_id`
3. `CREATE TABLE quantyx_user_dashboards`
4. `CREATE TABLE quantyx_user_dashboard_charts`

Run with:
```bash
bash scripts/apply_agentic_tables.sh
```

### Step 2 — Store layer

1. Update `services/ai/workspace_store.py`:
   - Add `source_chart_id` param to `create_workspace_conversation`
   - Add `list_conversations_by_chart` function

2. Create `services/ai/user_dashboards_store.py` with all CRUD functions listed above.

### Step 3 — Schema models

Add `CreateConversationRequest`, `CreateDashboardRequest`, `UpdateDashboardRequest`,
`AddChartToDashboardRequest`, `ReorderDashboardChartsRequest` to `services/api/schemas.py`.

### Step 4 — API routes

Add to `services/api/main.py`:

```
GET  /charts/{chart_id}/conversations
POST /dashboards/
GET  /dashboards/
GET  /dashboards/{dashboard_id}
PATCH /dashboards/{dashboard_id}
DELETE /dashboards/{dashboard_id}
POST /dashboards/{dashboard_id}/charts
DELETE /dashboards/{dashboard_id}/charts/{chart_id}
PUT  /dashboards/{dashboard_id}/charts/order
```

Extend the existing conversation creation endpoint to accept `source_chart_id`.

---

## File Inventory

| File | Change type |
|---|---|
| `artifacts/quantyx_tables_updates.sql` | Add 4 SQL statements (1 ALTER + 1 index + 2 CREATEs) |
| `services/ai/workspace_store.py` | Add `source_chart_id` param + `list_conversations_by_chart` |
| `services/ai/user_dashboards_store.py` | New file — all dashboard CRUD |
| `services/api/schemas.py` | Add 4 new Pydantic models |
| `services/api/main.py` | Add 9 new routes, extend 1 existing route |

---

## Constraints

- Deleting a dashboard does **not** delete the underlying charts in `quantyx_chart_requests`.
- Adding a chart to a dashboard validates the `chart_id` exists in `quantyx_chart_requests` and returns `404` if not.
- `position` values are stored as given; gaps are allowed (no compaction required). The `order` endpoint normalizes them to `0, 1, 2, ...`.
- `source_chart_id` in conversations is informational — no foreign key constraint since charts may be from transient builds.
- A chart can appear in multiple dashboards (no restriction at DB level beyond `UNIQUE (dashboard_id, chart_id)`).

---

## Not in scope

- Sharing dashboards between tenants
- Dashboard permissions / ACL
- Chart refresh from within a dashboard (charts are snapshots from chart builds)
- Dashboard templates or cloning
