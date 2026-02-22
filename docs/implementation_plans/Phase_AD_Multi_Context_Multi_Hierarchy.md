# Phase AD: Multi-Context + Multi-Hierarchy Support

Goal: support **multiple contexts per tenant/domain** and **multiple hierarchies
per single context**, with the ability to mark **multiple contexts as active**.
Ask must consider **all active contexts** when resolving semantics.

---

## 1) Problem

Customers provide multiple context sources:
- process docs
- ops glossaries
- hierarchy notes (often more than one hierarchy)

We must:
1) store multiple contexts per tenant/domain,
2) keep multiple hierarchies per **single context**,
3) allow **multiple active contexts** per scope for Ask.

---

## 2) Data Model Changes (SQL)

### 2.1 Context selection registry
Store **active contexts** per scope (many-to-many).

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_context_scope_active (
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  context_id TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, domain_id, connection_id, database_name, schema_name, context_id)
);

CREATE INDEX IF NOT EXISTS idx_context_scope_active_context
  ON public.quantyx_context_scope_active (context_id);

CREATE INDEX IF NOT EXISTS idx_context_scope_active_scope
  ON public.quantyx_context_scope_active (tenant_id, domain_id, connection_id, database_name, schema_name, is_active);
```

### 2.2 Hierarchy overrides: multiple hierarchies per context

Require hierarchy rows to be tied to a context and uniquely versioned.

```sql
ALTER TABLE public.quantyx_hierarchy_overrides
  ADD COLUMN IF NOT EXISTS context_id TEXT NULL,
  ADD COLUMN IF NOT EXISTS hierarchy_group TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_hierarchy_overrides_context
  ON public.quantyx_hierarchy_overrides (tenant_id, domain_id, context_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_hierarchy_overrides_scope_name_context
  ON public.quantyx_hierarchy_overrides (
    tenant_id, domain_id, connection_id, database_name, schema_name,
    context_id, hierarchy_name, is_current
  );
```

Notes:
- `context_id` should be populated from `quantyx_context_extractions.context_id`.
- `hierarchy_group` allows multiple hierarchy types (e.g., geography, supply_chain).

---

## 3) API Contract Changes

### 3.1 Context ingest/extract

No changes required for ingest/extract payloads.

### 3.2 Context apply (hierarchies)

Allow selecting **multiple hierarchies from one context** explicitly:

`POST /context/apply`

```json
{
  "tenant_id": "tenant_a",
  "domain_id": "lpg_production_distribution",
  "extraction_id": "ext_123",
  "apply": {"entities": true, "hierarchies": true, "glossary": true},
  "hierarchy_selection": {
    "names": ["geography", "supply_chain"],
    "apply_all": false
  }
}
```

Behavior:
- Apply only selected hierarchy names when `apply_all=false`.
- Persist `context_id` on each hierarchy row.
Note:
- A **single** context extraction can include multiple hierarchy objects.

### 3.3 Activate contexts for Ask

`PATCH /context/{context_id}`

```json
{
  "status": "active"
}
```

Server behavior:
- Upsert `quantyx_context_scope_active` with `is_active=true` for the current scope.
- **Multiple** contexts can be active.
Default behavior:
- `/context/apply` auto-activates the context unless explicitly deactivated later.

Optional deactivate:
```json
{ "status": "inactive" }
```

### 3.4 List hierarchies by context

`GET /hierarchies`

Add optional filter:
- `context_id`
- `group_by_context=true`

Response (grouped):
```json
{
  "contexts": [
    {
      "context_id": "ctx_123",
      "hierarchies": [
        {"name": "geography", "levels": ["zone","region","state","district"]},
        {"name": "supply_chain", "levels": ["plant","bottling_unit","depot","distributor"]}
      ]
    }
  ]
}
```

---

## 4) Ask Resolution Changes

Ask must use **all active contexts** for hierarchy resolution:
1) Resolve active contexts from `quantyx_context_scope_active` (is_active=true).
2) Load hierarchies bound to all active `context_id` values.
3) Merge hierarchies by `hierarchy_name` (dedupe by name + levels).
4) If no active context, fall back to latest contexts in scope or return a
   deterministic warning.

---

## 5) Affected Components

### API Endpoints
- `/context/apply` (select hierarchy names + persist context_id)
- `/context/{context_id}` (activate)
- `/hierarchies` (filter/group by context)
- `/query` (Ask reads active context)

### Tables
- `quantyx_context_scope_active` (new)
- `quantyx_hierarchy_overrides` (new columns/indexes)

---

## 6) Acceptance Criteria

- Multiple contexts can be ingested for the same tenant/domain.
- Each context can contain multiple hierarchies.
- Multiple active contexts can be selected for Ask.
- Ask uses the union of hierarchies from all active contexts.
- `/hierarchies` can return hierarchies grouped by context.
