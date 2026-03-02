# Phase Semantic Inference: Deterministic Query + Diagnostic Reasoning

Goal: Make /query deterministic-first and add an inference layer that explains *why* a metric changed by analyzing deltas and driver correlations, then persists learned semantics.

---

## Core Principle

Make `/query` deterministic by default using a compiled semantic graph. Only use LLM when the graph cannot resolve, and then promote the resolution back into the graph so the next run is deterministic.

---

## 1) The Semantic Graph (not just metadata tables)

Think of a graph with these node types:

- **Concept:** Plant, Region, Production, Time, Productivity
- **Metric:** `production_mt`, `productivity`, etc.
- **Dimension:** `region`, `process_date`, `sap_id`, `sales_area`
- **Model:** fact tables, dimension tables, views
- **Column:** physical columns with datatype, lineage
- **Synonym:** “plant”, “sap_id”, “plant_id”
- **Time Grain:** day, week, month
- **Join Edge:** model↔model relationships
- **Rule:** deterministic heuristic/constraint

Each edge has **confidence** + **provenance** (`llm`, `rule`, `user_confirmed`).

You can store this in Postgres with adjacency tables (fast enough initially), but structure it like a graph so it can eventually live in Neo4j/Neptune if needed.

---

## 1a) LLM-Derived Ontology/Glossary From Context Text

If you only provide **detailed application context text** (business definitions + table/column descriptions), the system can **derive** the following via LLM + validation:

- **Ontology** (entity types + relationships)
- **Glossary** (terms + synonyms)
- **Metric registry** (metric names + formulas)
- **Join hints** (likely keys, hierarchies)

These derived artifacts are then used to populate the semantic graph:
- Concept nodes
- Concept → metric edges
- Concept → dimension edges
- Synonym → concept edges
- Metric → model edges
- Model ↔ model join edges (validated against schema)

**Validation rule:** any LLM-derived node/edge must be verified against schema scan results before being promoted.

---

## 2) Query Resolution Pipeline (fast, deterministic)

**A. Cache → B. Semantic Graph → C. LLM fallback**

1) **Cache lookup**
   - Exact question + normalized variants (case, whitespace, numbers)
   - If found, re‑apply only time filters to keep “last week” fresh

2) **Semantic Graph resolve (deterministic)**
   - Tokenize question
   - Match to Concepts
   - Map Concepts → Metrics/Dimensions via edges
   - Ensure all metrics resolve to one base model if possible
   - Apply time semantics from time grammar

3) **Failover to LLM**
   - LLM receives: question + top candidate concepts + top candidate metrics/dims
   - LLM returns candidates + rationales
   - Validate the output against the graph
   - If valid, persist into graph with confidence + `source=llm`

---

## 3) How the graph evolves (learning loop)

Every time a user asks a question:

- If resolved deterministically → log it as confirmed usage
- If LLM resolves → save new edges:
  - synonym → concept
  - concept → metric/dim
  - question pattern → metric/dim combo
- If user corrects result → lower confidence on those edges

Over time the system becomes deterministic for most queries.

---

## 4) Rules that remove LLM calls

You can cover 60–80% of queries with rules like:

- “trend / last X months” → time grain = month
- “by plant/region” → pick available dimension synonyms in fact
- “total” → sum metric
- “top N” → `ORDER BY metric DESC LIMIT N`
- “last week” → time filter on fact time column

These rules live in a **Semantics Rule Engine** that works on the graph.

---

## 5) Joins across tables (multi‑table)

You’ll need Join Graph metadata with confidence:

- edges: fact → dim via join_key
- source: inferred, LLM, user‑confirmed
- if not confident, ask clarifying questions

This allows multi‑table resolution without LLM.

---

## 6) Storage (pragmatic evolution)

Start with Postgres:

- `semantic_nodes` (id, type, name, normalized_name)
- `semantic_edges` (src_id, dst_id, edge_type, confidence, source)
- `semantic_usage` (question, resolved_to, timestamp)

Later, if join graph gets complex, move to Neo4j and keep a sync job.

---

## 7) Determinism‑first strategy

In `/query`:

1) Normalize question → lookup semantic cache
2) If cache hit:
   - refresh time filters
   - run SQL
3) If cache miss:
   - rule engine + graph
4) If still unresolved → LLM
5) Persist LLM resolution → semantic graph

---

## 8) The “Semantic Contract”

A contract per domain:

- canonical metric names
- canonical dimensions
- allowed time grains
- default joins

All LLM outputs must map to this contract.

---

## 9) A practical example

Question: **“What is total LPG production by plant last week?”**

Deterministic resolution:

- Concept: Production → metric = `production_mt`
- Concept: Plant → dimension candidate = `sap_id` (exists in fact)
- Time: last week → `process_date` between dates

Result: **no LLM needed.**

---

## 10) Immediate improvements to make `/query` fast

- Pre‑compute fact column sets
- Store dimension → fact availability
- Store metric → fact base table
- Cache LLM results (question hash + scope)

---

## Recommendation: minimum viable semantic layer

Start with:

1) `semantic_nodes` + `semantic_edges`
2) A resolver that is:
   - rule‑based
   - graph‑based
3) A learning loop to store LLM output in graph

That is enough to stop expensive LLM calls and make `/query` deterministic.

---

# Diagnostic / “Why” Questions

## Does the above logic still work?
Yes — but diagnostics require an **Inference Layer** on top of query resolution.

**Resolve → Compute → Explain**

---

## Step 1) Determine Intent Type

This question is **diagnostic + comparative**.
So the system should switch to **Root‑Cause Mode** rather than simple aggregation.

Deterministic rule:
- contains {"why", "down", "drop", "decline"} → diagnostic

---

## Step 2) Identify Target Metric

From semantic graph:

- “production” → `production_mt`
- Default grain if not specified: day or week (configurable)

---

## Step 3) Determine the “Down” Baseline

We need a reference period.

Deterministic rule:
- If no time is specified → compare last 7 days vs previous 7 days (or current month vs prior month)

Example:
- Window A: last 7 days
- Window B: previous 7 days

---

## Step 4) Pull Comparative Data

Run deterministic queries for:

1) Total production for A vs B
2) Breakdown by likely drivers

Likely drivers from semantic graph:
- plant / region / sales area
- line / carousel / machine (if present)
- shifts / process_date
- rejection / downtime metrics

---

## Step 5) Compute Deltas + Rank Contributors

For each dimension/driver:

- delta = A - B
- % change
- rank top negative contributors

Example:
- Region: Delhi → -12%
- Plant: Plant_42 → -18%
- Machine: Head_03 → -22%
- Downtime metric ↑ +30%

---

## Step 6) Correlate with Other Metrics

For the same period:

- check rejects, downtime, input volume, supply shortage
- compute correlation with production drop

Rank causes by:
- correlation strength
- magnitude impact

---

## Step 7) Build Explanation Output

Example:

“Production is down 9.2% WoW, driven primarily by Plant_42 (-18%) and Delhi Region (-12%).
This coincides with a 28% increase in downtime on Head_03.”

---

## Step 8) Persist in Semantic Memory

Save:
- diagnostic question → metric + baseline + driver dimensions

Next time: deterministic resolution.

---

## Summary

A diagnostic question still uses the same deterministic semantic resolution, then layers inference:

1) Intent detection
2) Baseline definition
3) Delta analysis
4) Driver correlation
5) Explanation builder

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
