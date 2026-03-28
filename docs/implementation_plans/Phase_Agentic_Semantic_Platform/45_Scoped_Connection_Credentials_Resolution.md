# Phase 45: Scoped Connection Credentials Resolution

## Problem Statement

The current implementation resolves `connection_id → database_name` from `quantyx_connection_scopes` but only changes the `dbname` parameter when connecting to customer databases. All other connection parameters (host, port, user, password) are still taken from `.env` settings (the Application DB / datafusion credentials).

The `databases` table in the Application DB stores the **full connection details** for each customer database:

```sql
SELECT name, host, port, user_name, password, connection_type, database_name
FROM public.databases
WHERE id = <connection_id>
```

These credentials must be used for all customer-facing queries: agentic runs, workspace conversations, chart execution, dashboard building, view queries, etc.

---

## Architecture

```
Application DB (datafusion / .env)
├── public.quantyx_tenant_scopes      → tenant_id + domain_id → connection_id
├── public.quantyx_connection_scopes  → connection_id → database_name, schema_name
└── public.databases                  → connection_id (id) → host, port, user_name, password, database_name

Customer DB (resolved at runtime per tenant)
└── <schema>.<fact_tables>            → queried using credentials from databases table
```

**Flow:**
1. Incoming request carries `tenant_id` + `domain_id`
2. `quantyx_tenant_scopes` resolves → `connection_id`
3. `databases WHERE id = connection_id` resolves → `{host, port, user_name, password, database_name}`
4. `quantyx_connection_scopes` resolves → `schema_name` (may override database_name if different)
5. All customer SQL runs using those credentials, not `.env` settings

---

## New Data Type: `ScopedConnection`

**File: `services/ai/connection_registry.py`**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ScopedConnection:
    connection_id: str
    host: str
    port: int
    user: str
    password: str
    database_name: str
    schema_name: str
    connection_type: str = "postgresql"
```

---

## Step 1 — Add `resolve_database_credentials` to `connection_registry.py`

Query the `databases` table using `connection_id` as the row id:

```python
def resolve_database_credentials(
    settings: Settings,
    connection_id: str,
    schema_name: str,
) -> ScopedConnection | None:
    sql = """
        SELECT name, host, port, user_name, password, connection_type, database_name
        FROM public.databases
        WHERE id = %s
    """
    rows = run_query(settings, sql, [connection_id])
    if not rows:
        return None
    row = rows[0]
    return ScopedConnection(
        connection_id=connection_id,
        host=str(row["host"]),
        port=int(row["port"]),
        user=str(row["user_name"]),
        password=str(row["password"]),
        database_name=str(row.get("database_name") or ""),
        schema_name=schema_name,
        connection_type=str(row.get("connection_type") or "postgresql"),
    )
```

Note: `run_query` here uses `settings` (App DB) since `databases` table lives in datafusion.

---

## Step 2 — In-Memory Cache for Credentials

Credentials won't change mid-request. Add a simple TTL cache to avoid hitting the DB on every SQL call within a request or run:

```python
import time
from threading import Lock

_cred_cache: dict[str, tuple[ScopedConnection, float]] = {}
_cred_cache_lock = Lock()
_CRED_CACHE_TTL_SECONDS = 300  # 5 minutes

def resolve_database_credentials_cached(
    settings: Settings,
    connection_id: str,
    schema_name: str,
) -> ScopedConnection | None:
    cache_key = f"{connection_id}:{schema_name}"
    with _cred_cache_lock:
        if cache_key in _cred_cache:
            cred, ts = _cred_cache[cache_key]
            if time.monotonic() - ts < _CRED_CACHE_TTL_SECONDS:
                return cred
    cred = resolve_database_credentials(settings, connection_id, schema_name)
    if cred:
        with _cred_cache_lock:
            _cred_cache[cache_key] = (cred, time.monotonic())
    return cred
```

---

## Step 3 — Update `run_query` in `services/ai/db.py`

Replace the `database_name: str | None` parameter with `scoped_conn: ScopedConnection | None`:

```python
from services.ai.connection_registry import ScopedConnection

def run_query(
    settings: Settings,
    sql: str,
    params: list[object],
    scoped_conn: ScopedConnection | None = None,
) -> list[dict]:
    if scoped_conn:
        host     = scoped_conn.host
        port     = scoped_conn.port
        dbname   = scoped_conn.database_name
        user     = scoped_conn.user
        password = scoped_conn.password
    else:
        host     = settings.db_host
        port     = settings.db_port
        dbname   = settings.db_name
        user     = settings.db_user
        password = settings.db_password

    conn = psycopg2.connect(
        host=host, port=port, dbname=dbname,
        user=user, password=password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.commit()
        return [dict(row) for row in rows]
    finally:
        conn.close()
```

> **Backward compatibility**: all existing callers that don't pass `scoped_conn` continue to use App DB settings unchanged. Only customer-data callers are updated.

---

## Step 4 — Update `_resolve_scope_values` in `main.py`

Extend the return value to include the `ScopedConnection`:

```python
def _resolve_scope_values(
    tenant_id: str,
    domain_id: str,
) -> tuple[str, str, str, list[str] | None, ScopedConnection | None]:
    registry = get_tenant_scope(settings, tenant_id, domain_id)
    connection_id = (registry or {}).get("connection_id")
    if not connection_id:
        raise HTTPException(status_code=400, detail="tenant scope not configured")

    scopes = resolve_connection_scope(settings, connection_id)
    if not scopes:
        raise HTTPException(status_code=404, detail="tenant scope connection not registered")
    database_name = scopes[0].get("database_name")
    schema_name = scopes[0].get("schema_name")
    if not database_name or not schema_name:
        raise HTTPException(status_code=400, detail="tenant scope not configured")

    scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)

    return (connection_id, database_name, schema_name, registry.get("tables") if registry else None, scoped_conn)
```

All existing callers of `_resolve_scope_values` use positional unpacking — add `scoped_conn` as the 5th element. Callers that don't need it can use `*_` or just ignore the last value.

---

## Step 5 — Thread `scoped_conn` Through Execution Paths

Replace all `database_name=...` kwargs on `run_query` calls with `scoped_conn=scoped_conn`.

### 5a. `services/api/main.py` — `query()` endpoint

```python
connection_id, database_name, schema_name, tables, scoped_conn = _resolve_scope_values(
    request.tenant_id, domain_id
)
# ... later ...
rows = run_query(settings, built.sql, built.params, scoped_conn=scoped_conn)
rollup_rows = run_query(settings, rollup_sql, rollup_params, scoped_conn=scoped_conn)
by_company_rows = run_query(settings, by_company_built.sql, by_company_built.params, scoped_conn=scoped_conn)
```

### 5b. `main.py` — `get_chart` refresh endpoint

```python
_, _, _, _, scoped_conn = _resolve_scope_values(_chart_tenant_id, _chart_domain_id)
rows = run_query(settings, row.get("sql") or "", row.get("params") or [], scoped_conn=scoped_conn)
```

### 5c. `main.py` — dashboard refresh job

```python
_, _, _, _, scoped_conn = _resolve_scope_values(_dc_tenant, _dc_domain)
rows = run_query(settings, sql, params, scoped_conn=scoped_conn)
```

### 5d. `main.py` — `views_query` endpoint

```python
_, _, _, _, _vq_scoped_conn = _resolve_scope_values(request.tenant_id, resolved_domain_id)
rows = run_query(settings, sql_text, [], scoped_conn=_vq_scoped_conn)
```

### 5e. `main.py` — `_list_fact_table_columns`, `_fact_columns_for_metric`, `_build_scoped_dimension_access`

Replace `database_name: str | None` params with `scoped_conn: ScopedConnection | None`:

```python
def _list_fact_table_columns(schema_name: str, table_name: str, scoped_conn=None) -> list[str]:
    rows = run_query(settings, sql, [schema_name, table_name], scoped_conn=scoped_conn)
```

### 5f. `main.py` — `_execute_passthrough_workspace_query`

```python
def _execute_passthrough_workspace_query(*, ..., scoped_conn=None) -> QueryResult:
    rows = run_query(settings, sql_text, params or None, scoped_conn=scoped_conn)
```

### 5g. `services/ai/agentic_orchestrator.py` — store `ScopedConnection` in LangGraph state

In `_resolve_scope_values` equivalent inside orchestrator (or passed in from `initial_state`):

**Option A (preferred):** Store the full credentials dict in state at run-start:
```python
# In agentic_run initial_state construction (main.py):
scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)
initial_state["scoped_conn"] = {
    "host": scoped_conn.host,
    "port": scoped_conn.port,
    "user": scoped_conn.user,
    "password": scoped_conn.password,
    "database_name": scoped_conn.database_name,
    "schema_name": scoped_conn.schema_name,
} if scoped_conn else None
```

**In orchestrator nodes**, reconstruct `ScopedConnection` from state:
```python
def _scoped_conn_from_state(state: dict) -> ScopedConnection | None:
    raw = state.get("scoped_conn")
    if not raw:
        return None
    return ScopedConnection(
        connection_id=str(state.get("connection_id") or ""),
        host=raw["host"],
        port=int(raw["port"]),
        user=raw["user"],
        password=raw["password"],
        database_name=raw["database_name"],
        schema_name=raw["schema_name"],
    )
```

Then in each node:
```python
scoped_conn = _scoped_conn_from_state(state)
rows = run_query(settings, sql, [], scoped_conn=scoped_conn)
```

Apply to:
- `schema_node` → `enrich_schema_graph_columns(..., scoped_conn=scoped_conn)`
- `profiling_node` → `profile_tables(..., scoped_conn=scoped_conn)`
- `join_node` → join coverage `run_query(..., scoped_conn=scoped_conn)`
- `dashboard_node` → chart SQL `run_query(..., scoped_conn=scoped_conn)`
- `anomaly_node` → `_execute_llm_evidence_queries(..., scoped_conn=scoped_conn)`

### 5h. `agentic_agents.py` — `enrich_schema_graph_columns`, `profile_tables`

Replace `database_name: str | None` with `scoped_conn: ScopedConnection | None`:

```python
def enrich_schema_graph_columns(settings, schema_graph, schema_name, scoped_conn=None):
    rows = run_query(settings, sql, [schema_name], scoped_conn=scoped_conn)

def profile_tables(settings, tables, schema_name, scoped_conn=None):
    rows = run_query(settings, sql, [...], scoped_conn=scoped_conn)
```

---

## Step 6 — Security: Never Log Passwords

Add a `__repr__` to `ScopedConnection` that masks the password:

```python
def __repr__(self) -> str:
    return (
        f"ScopedConnection(connection_id={self.connection_id!r}, "
        f"host={self.host!r}, port={self.port}, user={self.user!r}, "
        f"database_name={self.database_name!r}, schema_name={self.schema_name!r})"
    )
```

Never pass `scoped_conn` objects directly to logger calls.

---

## Step 7 — Update `_resolve_scope_values` Callers

All existing callers use positional unpacking. Add `scoped_conn` as 5th return value:

| Caller site (main.py) | Current | Updated |
|---|---|---|
| `query()` endpoint | `connection_id, database_name, schema_name, tables = ...` | `connection_id, database_name, schema_name, tables, scoped_conn = ...` |
| Chart refresh | `_, _chart_database_name, _, _ = ...` | `_, _, _, _, scoped_conn = ...` |
| Dashboard refresh | resolve inline | resolve inline with 5-tuple |
| `views_query` | resolve inline | resolve inline with 5-tuple |
| `interpret_workspace_query` callers | `_, _, schema_name, _ = ...` | `_, _, schema_name, _, scoped_conn = ...` |
| Agentic run `initial_state` builder | `connection_id, database_name, schema_name, tables = ...` | `connection_id, database_name, schema_name, tables, scoped_conn = ...` |

---

## Execution Order

1. **`connection_registry.py`** — add `ScopedConnection` dataclass + `resolve_database_credentials` + `resolve_database_credentials_cached`
2. **`db.py`** — update `run_query` signature: replace `database_name` param with `scoped_conn`
3. **`agentic_agents.py`** — update `enrich_schema_graph_columns` + `profile_tables` to use `scoped_conn`
4. **`agentic_orchestrator.py`** — add `_scoped_conn_from_state` helper; update all 5 `run_query` call sites; store `scoped_conn` dict in initial_state
5. **`main.py`** — update `_resolve_scope_values` return type; update all callers; update `_list_fact_table_columns`, `_fact_columns_for_metric`, `_build_scoped_dimension_access`, `_execute_passthrough_workspace_query`

---

## What Stays Unchanged

- `execute_non_query` — always writes to App DB (quantyx metadata tables). No `scoped_conn`.
- `execute_returning_query` — always writes to App DB. No `scoped_conn`.
- `run_query` calls for quantyx metadata (tenant scopes, canvas, audit logs, job tracking) — no `scoped_conn`, always App DB.
- `resolve_database_credentials` itself uses plain `run_query(settings, ...)` — queries `databases` table in App DB.

---

## Files Modified

| File | Change |
|---|---|
| `services/ai/connection_registry.py` | Add `ScopedConnection`, `resolve_database_credentials`, `resolve_database_credentials_cached` |
| `services/ai/db.py` | Replace `database_name` param with `scoped_conn: ScopedConnection | None` in `run_query` |
| `services/ai/agentic_agents.py` | `enrich_schema_graph_columns`, `profile_tables` use `scoped_conn` |
| `services/ai/agentic_orchestrator.py` | `_scoped_conn_from_state` helper; 5 node run_query call sites; initial_state builder |
| `services/api/main.py` | `_resolve_scope_values` 5-tuple return; all customer `run_query` callers; helper functions |