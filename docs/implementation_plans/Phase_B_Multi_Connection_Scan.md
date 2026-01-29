# Phase B Extension: Multi-Connection Schema Scan

Goal: allow `/onboard/scan-connection` to scan multiple connections, databases, and schemas in one request.

## Why
- Large customers run multiple databases and schemas per domain.
- UI needs a single scan job for a holistic schema view.

---

## API changes

### 1) New request shape
Replace single-connection payload with an array:
```json
{
  "connections": [
    {
      "connection_id": "conn_prod",
      "db_type": "postgres",
      "host": "db.company.com",
      "port": 5432,
      "user": "readonly_user",
      "password": "******",
      "databases": [
        {
          "name": "prod_warehouse",
          "schemas": [
            {
              "name": "public",
              "tables": ["fact_production_daily", "dim_plant"]
            }
          ]
        }
      ],
      "sample_rows": 100,
      "limit": 20,
      "cursor": null
    }
  ]
}
```

### 2) Response shape
```json
{
  "connections": [
    {
      "connection_id": "conn_prod",
      "databases": [
        {
          "name": "prod_warehouse",
          "schemas": [
            {
              "name": "public",
              "tables": [
                {
                  "table": "fact_production_daily",
                  "columns": [
                    { "name": "output_tmt", "data_type": "numeric", "profile": { "mean": 124.5 } }
                  ]
                }
              ],
              "limit": 20,
              "cursor": null,
              "next_cursor": "ZmFjdF9wcm9kdWN0aW9uX2RhaWx5"
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Backend changes

1) **Pydantic schemas**
   - New `OnboardScanMultiConnectionRequest`
   - New nested response shapes for connection/database/schema

2) **Connection scanner**
   - Extend `services/ai/onboarding/connection_scan.py`
   - Add loop for multiple connections
   - Per schema cursor pagination
   - Keep sample_rows cap at 100

3) **API handler**
   - Update `/onboard/scan-connection` to accept new payload
   - Return structured response per connection

---

## Downstream updates

1) **UI**
   - Render grouped sections by connection → database → schema
   - Allow user to expand/collapse
   - Track per-schema pagination cursor

2) **Docs**
   - Update `artifacts/V2_API.md`
   - Update `artifacts/ONBOARDING_API_FLOW.md`

3) **Metrics + ontology flow**
   - `/onboard/map` should accept multiple schema/table selections
   - `/metrics/suggested` should accept multiple schema/table selections
   - Add `connection_id`, `database`, and `schema` to these request payloads

4) **Model inference**
   - `/onboard/infer-models` should accept multi-connection context
   - Allow `facts`/`dims` suggestions per schema

5) **Explore endpoints**
   - `/schema` should support a `connection_id` and `database` filter
   - `/datasets` should be linked to the selected connection scope
   - `/dimensions` should honor the same connection scope

6) **Audit + governance**
   - Store scan payloads and results for traceability
   - Link scan job IDs to later onboarding actions (map, infer, metrics)

---

## Acceptance criteria
- Multiple connections in one request are scanned
- UI can page through results per schema
- Scan results include profiles and sample stats per table
- Scan payload + results persisted for audit and troubleshooting

---

## Storage schema (required)

Store scan requests and results as JSON for replay and UI caching.

Tables:
- `public.quantyx_schema_scans`
- `public.quantyx_connection_registry`
- `public.quantyx_connection_scopes`

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_schema_scans (
  scan_id TEXT PRIMARY KEY,
  tenant_id TEXT,
  domain_id TEXT,
  requested_by TEXT,
  status TEXT NOT NULL DEFAULT 'completed',
  request_payload JSONB NOT NULL,
  result_payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quantyx_schema_scans_domain_time
  ON public.quantyx_schema_scans (domain_id, created_at DESC);
```
