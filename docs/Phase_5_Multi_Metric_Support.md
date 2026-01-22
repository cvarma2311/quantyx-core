# Phase 5: Multi-Metric Support

This phase extends the AI Query Engine to support queries that request
multiple metrics in a single question or request payload.

Goal: allow users to ask questions like
"How is HPCL doing vs BPCL for MS this quarter?" and return multiple metrics
(e.g., industry_sales_tmt, hpcl_vs_company_sales_diff_tmt, hpcl_vs_company_sales_ratio)
from a single request.

---

## 1) API support (implemented)

Request supports:
- `metrics: [..]` for multi-metric queries
- `metric: "..."` for single metric (backward compatible)

Response returns:
- `metrics: [..]` list
- `dimensions: [..]`
- `rows: [...]` with one column per metric name

---

## 2) Resolver support (implemented)

OpenAI resolver now returns:
```json
{
  "metrics": ["industry_sales_tmt", "hpcl_vs_company_sales_diff_tmt"],
  "dimensions": ["company_name", "calendar_quarter", "fiscal_year", "product_name"],
  "filters": [ ... ]
}
```

---

## 3) SQL generation (implemented: single base table)

Current implementation requires all metrics to resolve to the same base table.
For example, metrics on `fact_industry_performance_monthly` can be combined in
one SELECT. If metrics map to different base tables, the API returns:
```
"All metrics must be from the same base table"
```

---

## 4) Guardrails

- Dimensions must be allowed by every requested metric.
- Filters must use valid dimensions, and must be allowed by every metric.
- LIMIT is always applied.

---

## 5) Example request (HPCL vs BPCL)

```bash
curl -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{
    "metrics": [
      "industry_sales_tmt",
      "hpcl_vs_company_sales_diff_tmt",
      "hpcl_vs_company_sales_ratio"
    ],
    "dimensions": ["company_name", "calendar_quarter", "fiscal_year", "product_name"],
    "filters": [
      {"field": "company_name", "operator": "IN", "value": ["HPCL", "BPCL"]},
      {"field": "product_name", "operator": "=", "value": "MS"},
      {"field": "calendar_quarter", "operator": "=", "value": 2},
      {"field": "fiscal_year", "operator": "=", "value": "2024-2025"}
    ],
    "limit": 100,
    "explain": true
  }'
```

---

## 6) Next improvements

- Support multi-table metrics via subquery joins or a unified fact model.
- Add time-window enforcement and query audit logging.
