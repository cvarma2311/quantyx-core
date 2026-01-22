# Phase 4: AI Query Engine

This guide documents the Phase 4 implementation for the AI Query Engine.

Goal: expose a minimal API that can resolve a question to a metric, generate
safe SQL against the marts layer, and return results.

---

## 1) Service layout

Why: keep AI and API layers separated and modular for future expansion.

Created:
- `services/api/main.py` (FastAPI app)
- `services/api/schemas.py` (request/response models)
- `services/ai/` (catalog loader, schema loader, SQL builder, resolver)

---

## 2) Environment variables

Why: configure DB access, dbt manifest path, and OpenAI credentials without
hardcoding secrets.

Add to `.env` (do not commit secrets):
```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
DBT_MANIFEST_PATH=dbt/target/manifest.json
METRICS_CATALOG_PATH=contracts/metrics/core_metrics.yml
```

DB connection variables are already in `.env`:
```
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
DB_SCHEMA
```

---

## 3) Schema introspection

Why: use dbt artifacts as the source of truth for what models/columns exist.

Endpoint:
- `GET /schema`

This reads `dbt/target/manifest.json` and exposes models + columns.
Run `dbt docs generate` if the manifest does not exist.

---

## 4) Metric catalog

Why: metrics defined in `contracts/metrics/core_metrics.yml` govern what the
AI can answer and prevent KPI drift.

Endpoint:
- `GET /metrics`

---

## 5) Query flow

Why: separate resolution, SQL generation, and execution for safety and audit.

1) Resolve metric + dimensions (OpenAI) from the question
2) Build SQL with guardrails (read-only, enforced LIMIT)
3) Execute with parameterized queries via psycopg2

Endpoint:
- `POST /query`

Example request:
```json
{
  "question": "How is HPCL doing vs BPCL for MS in Q2 of FY 2024-2025?",
  "dimensions": ["company_name", "calendar_quarter", "fiscal_year", "product_name"],
  "filters": [
    {"field": "company_name", "operator": "IN", "value": ["HPCL", "BPCL"]},
    {"field": "product_name", "operator": "=", "value": "MS"},
    {"field": "calendar_quarter", "operator": "=", "value": 2},
    {"field": "fiscal_year", "operator": "=", "value": "2024-2025"}
  ],
  "limit": 100,
  "explain": true
}
```

Note: the canonical company name for HPCL comes from `industry_performance.comname`
(mapped to `company_name` in staging).

---

## 6) Running the API

From the repo root:
```bash
uvicorn services.api.main:app --reload --port 8000
```

Health check:
```bash
curl http://localhost:8000/health
```

---

## 7) Known limitations (MVP)

- Multi-table metrics are only supported for `sales_vs_target_achievement_pct`.
- Filters are allowed only on dimensions declared in the metric catalog.
- Time-window enforcement is not yet mandatory (add in Phase 4 hardening).

---

## 8) Next steps

- Add stricter time window enforcement in the SQL guard.
- Add a small test suite for catalog loading and SQL generation.
- Add audit logging for queries and SQL used.
