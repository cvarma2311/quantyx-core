# Phase 7: SQL Templates + Data Models

## 1) Semantic Graph Tables (Postgres)

### 1.1 `semantic_nodes`
```sql
CREATE TABLE IF NOT EXISTS public.semantic_nodes (
  node_id TEXT PRIMARY KEY,
  node_type TEXT NOT NULL, -- concept|metric|dimension|model|column|synonym|timegrain|rule
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  metadata JSONB NULL,
  confidence NUMERIC NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_semantic_nodes_domain_type
  ON public.semantic_nodes (domain_id, node_type);
```

### 1.2 `semantic_edges`
```sql
CREATE TABLE IF NOT EXISTS public.semantic_edges (
  edge_id TEXT PRIMARY KEY,
  src_node_id TEXT NOT NULL,
  dst_node_id TEXT NOT NULL,
  edge_type TEXT NOT NULL, -- concept_metric|concept_dimension|synonym_concept|metric_model|dimension_column|model_join|rule
  confidence NUMERIC NULL,
  source TEXT NOT NULL, -- rule|llm|user_confirmed|imported
  metadata JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_semantic_edges_src
  ON public.semantic_edges (src_node_id, edge_type);
```

### 1.3 `semantic_usage`
```sql
CREATE TABLE IF NOT EXISTS public.semantic_usage (
  usage_id TEXT PRIMARY KEY,
  question_hash TEXT NOT NULL,
  question_text TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  resolved_metric TEXT NOT NULL,
  resolved_dimensions JSONB NULL,
  resolved_filters JSONB NULL,
  intent TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_semantic_usage_question
  ON public.semantic_usage (question_hash, tenant_id, domain_id);
```

---

## 2) Diagnostic / Inference SQL Templates

### 2.1 Baseline Metric Comparison
```sql
-- Total metric in window A and B
SELECT
  'A' AS window_label,
  SUM(metric_expr) AS metric_value
FROM fact_table
WHERE time_col BETWEEN :a_start AND :a_end

UNION ALL

SELECT
  'B' AS window_label,
  SUM(metric_expr) AS metric_value
FROM fact_table
WHERE time_col BETWEEN :b_start AND :b_end;
```

### 2.2 Driver Delta by Dimension
```sql
SELECT
  dim_col AS driver,
  SUM(CASE WHEN time_col BETWEEN :a_start AND :a_end THEN metric_expr ELSE 0 END) AS metric_a,
  SUM(CASE WHEN time_col BETWEEN :b_start AND :b_end THEN metric_expr ELSE 0 END) AS metric_b,
  (SUM(CASE WHEN time_col BETWEEN :a_start AND :a_end THEN metric_expr ELSE 0 END) -
   SUM(CASE WHEN time_col BETWEEN :b_start AND :b_end THEN metric_expr ELSE 0 END)) AS delta
FROM fact_table
GROUP BY dim_col
ORDER BY delta ASC
LIMIT 20;
```

### 2.3 Correlation with Driver Metrics
```sql
-- Example: correlation between production and downtime by day
SELECT
  corr(prod, downtime) AS correlation
FROM (
  SELECT
    DATE_TRUNC('day', time_col) AS day,
    SUM(production_expr) AS prod,
    SUM(downtime_expr) AS downtime
  FROM fact_table
  WHERE time_col BETWEEN :a_start AND :a_end
  GROUP BY DATE_TRUNC('day', time_col)
) t;
```

---

## 3) Deterministic Query SQL Template

### 3.1 Metric + Dimension
```sql
SELECT
  dim_col,
  SUM(metric_expr) AS metric_value
FROM fact_table
WHERE time_col BETWEEN :start AND :end
GROUP BY dim_col
ORDER BY metric_value DESC
LIMIT :limit;
```

### 3.2 Trend
```sql
SELECT
  DATE_TRUNC(:grain, time_col) AS period,
  SUM(metric_expr) AS metric_value
FROM fact_table
WHERE time_col BETWEEN :start AND :end
GROUP BY DATE_TRUNC(:grain, time_col)
ORDER BY period ASC;
```

---

## 4) Data Model: Explanation Payload

```json
{
  "question": "Why is my production down?",
  "intent": "diagnostic",
  "metric": "production_mt",
  "baseline": {
    "window_a": {"start": "2026-02-16", "end": "2026-02-22"},
    "window_b": {"start": "2026-02-09", "end": "2026-02-15"}
  },
  "drivers": [
    {
      "dimension": "plant",
      "driver": "Plant_42",
      "delta": -1200,
      "pct_change": -0.18
    }
  ],
  "correlations": [
    {
      "metric": "downtime",
      "correlation": 0.72
    }
  ],
  "explanation": "Production is down 9.2% WoW, driven primarily by Plant_42 (-18%)..."
}
```

---

## 5) Data Model: Deterministic Resolution Trace

```json
{
  "resolved_metric": "production_mt",
  "resolved_dimensions": ["region"],
  "time_filter": {"start": "2026-02-16", "end": "2026-02-22"},
  "rules_applied": ["last_week", "by_dimension"],
  "graph_edges_used": ["concept->metric", "concept->dimension"],
  "llm_used": false
}
```

---

## 6) Success Criteria

- Diagnostic queries produce ranked driver list
- Correlation metrics are computed with traceable SQL
- Deterministic SQL templates cover 80% of KPI queries

