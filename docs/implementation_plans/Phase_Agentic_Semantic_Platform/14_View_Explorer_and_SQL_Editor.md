# Phase 14: View Explorer + SQL Editor APIs

## Objective
Expose created fact/dimension/rollup views to end users, including schema metadata, so they can query via a SQL editor in the UI.

---

## User Experience
- View list (fact/dimension/rollup views)
- Schema preview (columns + types)
- SQL editor to run `SELECT` queries

---

## Required APIs

### 1) List Views
**GET /views**

Query params:
- `tenant_id`
- `domain_id` (optional)

Response:
```json
{
  "views": [
    {
      "view_name": "fact_lpg_plant_operations",
      "schema": "public",
      "type": "fact",
      "created_at": "2026-02-20T10:00:00Z"
    }
  ]
}
```

---

### 2) View Schema
**GET /views/{view_name}/schema**

Query params:
- `tenant_id`

Response:
```json
{
  "view_name": "fact_lpg_plant_operations",
  "schema": "public",
  "columns": [
    {"name": "sap_id", "type": "text"},
    {"name": "process_date", "type": "date"}
  ]
}
```

---

### 3) SQL Editor Execution
**POST /views/query**

Request:
```json
{
  "tenant_id": "VC_101",
  "sql": "SELECT * FROM public.fact_lpg_plant_operations LIMIT 100"
}
```

Response:
```json
{
  "rows": [...],
  "columns": ["sap_id", "process_date"],
  "row_count": 100,
  "chart": {
    "type": "table",
    "payload": { "columns": ["sap_id", "process_date"], "rows": [] }
  }
}
```

---

## Backend Implementation

### View Registry Source
Use existing `quantyx_fact_views_registry` as source of truth:
- view_name
- schema_name
- tenant_id
- type (fact|dimension|rollup)

### Schema Introspection
Use `information_schema.columns` to list view columns.

---

## Success Criteria
- Users can list all available views
- Users can inspect schemas
- Users can run ad‑hoc SQL safely
