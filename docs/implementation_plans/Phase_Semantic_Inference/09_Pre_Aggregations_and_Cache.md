# Phase 9: Pre‑Aggregations + Cache Orchestration (Cube‑Style)

## Objective
Add Cube‑style rollups and orchestration so most queries hit pre‑aggregated tables or cached results instead of raw facts.

---

## 1) Rollup Registry

Create a registry to define rollups (metric + dimensions + grain + filters).

**Table: `quantyx_rollup_registry`**
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_rollup_registry (
  rollup_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  base_model TEXT NOT NULL,           -- fact table/view
  metric_name TEXT NOT NULL,
  dimensions JSONB NOT NULL,
  time_grain TEXT NOT NULL,           -- day|week|month
  filters JSONB NULL,
  rollup_table TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 2) Rollup Materialization

Generate SQL and materialize into rollup tables.

**Example materialization SQL**
```sql
CREATE TABLE IF NOT EXISTS public.rollup_prod_mt_by_region_month AS
SELECT
  region,
  date_trunc('month', process_date) AS month,
  SUM((production_14_2kg*14.2 + production_19kg*19)/1000) AS production_mt
FROM public.fact_lpg_plant_operations
GROUP BY region, date_trunc('month', process_date);
```

Refresh strategy:
- **incremental** for time‑partitioned data
- **full rebuild** if schema changes

---

## 3) Query Planner (Rollup First)

Resolution order:
1. Cache hit (exact query signature)
2. Rollup match (best rollup covers requested dims + grain)
3. Raw fact query

Rollup selection:
- Prefer smallest rollup that satisfies requested dims + grain
- If filters are subset of rollup filters

---

## 4) Cache Orchestration

Two‑level cache:
- **Memory cache** for exact queries
- **Persistent cache** via rollup tables

Cache keys:
- `tenant_id + domain_id + metric + dims + filters + grain`

---

## 5) Refresh Orchestration

**Background jobs**:
- `rollup_build`
- `rollup_refresh`

Triggers:
- time‑based schedule (e.g., hourly/daily)
- on new data ingestion
- on schema change

---

## 6) Integration with Semantic Graph

- Graph provides candidate rollups based on frequent queries
- Usage statistics (`semantic_usage`) drive rollup recommendations

---

## 7) Success Criteria

- ≥ 70% queries served from rollups
- P95 query time < 2s
- Cache hit rate > 60%

