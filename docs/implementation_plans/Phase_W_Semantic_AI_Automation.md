# Phase W: Semantic AI Automation (Generic Facts/Dimensions + Lineage)

Goal: Improve AI‑generated semantic models so we create **generic, reusable facts and dimensions** based on schema + question types, not only the literal questions. Automate lineage creation with an LLM‑first approach and heuristic fallback. Ensure **every** AI‑ or human‑created object appears on the canvas.

---

## 1) Outcomes

1. **Generic semantic model generation**
   - Facts and dimensions are derived from schema + intent taxonomy (not tied to a single question).
2. **Question understanding**
   - Identify common question types (trend, variance, top‑N, breakdown, ranking, anomaly, share, cohort, etc.).
3. **Automated lineage**
   - LLM suggests Fact↔Dimension and Fact↔Metric links.
   - Heuristics used as fallback.
4. **Canvas completeness**
   - All generated and manually created nodes appear on the canvas with edges.

---

## 2) New Behavior

### 2.1 Generic Facts & Dimensions
We should not generate only for a single question. We generate:
- Core facts per business process (sales, production, inventory, dispatch, utilization).
- Key dimensions per entity (location, product, time, asset, customer).

### 2.2 Question Type Taxonomy
We classify questions to infer **semantic needs**:
- **Trend**: requires time column + grain
- **Variance / Comparison**: needs at least one metric with time
- **Top‑N / Ranking**: needs metric + dimension
- **Share / Contribution**: needs metric + denominator
- **Anomaly**: time + baseline metric
- **Breakdown**: metric + dimension hierarchy

We use this to:
- Recommend missing dimensions
- Recommend required fact grains
- Suggest default metrics (but not limited to the question)

---

## 3) API Changes

### 3.1 New: Semantic Suggestion API (LLM‑first)
`POST /semantic/suggest`

Purpose:
- Generate generic facts/dimensions/metrics + lineage from schema + question types.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "petroleum_refinery",
  "inputs": {
    "schema_summary": "fact_dispatch: [dispatch_date, plant_id, product_id, volume_tmt]",
    "questions": [
      "Top 5 plants by dispatch volume this month",
      "Which products are trending down YoY?"
    ],
    "glossary": "MFM=Mass Flow Meter, bay = loading bay"
  },
  "model": "gpt-4o-mini"
}
```

Response (aligned with Phase V payloads):
```json
{
  "facts": [
    {
      "table_name": "fact_dispatch_daily",
      "grain": "day",
      "time_column": "dispatch_date",
      "measures": ["volume_tmt"],
      "dimensions": ["plant_id", "product_id"],
      "description": "Daily dispatch fact",
      "status": "draft"
    }
  ],
  "dimensions": [
    {
      "name": "dim_plant",
      "keys": ["plant_id"],
      "attributes": ["plant_name", "region_name"],
      "description": "Plant dimension",
      "status": "draft"
    }
  ],
  "metrics": [
    {
      "metric_name": "dispatch_volume_tmt",
      "type": "sum",
      "sql": "{{ ref('fact_dispatch_daily') }}.volume_tmt",
      "grain": "day",
      "dimensions": ["plant_id", "product_id"],
      "description": "Total dispatch volume",
      "status": "suggested"
    }
  ],
  "lineage": {
    "edges": [
      {"from": "dim_plant", "to": "fact_dispatch_daily"},
      {"from": "fact_dispatch_daily", "to": "dispatch_volume_tmt"}
    ]
  },
  "question_types": ["top_n", "trend", "comparison"]
}
```

### 3.2 New: Persist Suggested Semantic Model
`POST /semantic/suggest/apply`

Purpose:
- Persist facts/dimensions/metrics + lineage to registries and canvas.

Request (aligned with Phase V payloads):
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "petroleum_refinery",
  "facts": [
    {
      "table_name": "fact_dispatch_daily",
      "grain": "day",
      "time_column": "dispatch_date",
      "measures": ["volume_tmt"],
      "dimensions": ["plant_id", "product_id"],
      "description": "Daily dispatch fact",
      "status": "draft"
    }
  ],
  "dimensions": [
    {
      "name": "dim_plant",
      "keys": ["plant_id"],
      "attributes": ["plant_name", "region_name"],
      "description": "Plant dimension",
      "status": "draft"
    }
  ],
  "metrics": [
    {
      "metric_name": "dispatch_volume_tmt",
      "type": "sum",
      "sql": "{{ ref('fact_dispatch_daily') }}.volume_tmt",
      "grain": "day",
      "dimensions": ["plant_id", "product_id"],
      "description": "Total dispatch volume",
      "status": "suggested"
    }
  ],
  "lineage": {
    "edges": [
      {"from": "dim_plant", "to": "fact_dispatch_daily"},
      {"from": "fact_dispatch_daily", "to": "dispatch_volume_tmt"}
    ]
  }
}
```

### 3.3 Update: Existing LLM flows
- `/onboard/infer-models` should call semantic suggestion internally (LLM‑first).
- If LLM fails, fallback to heuristic inference.

---

## 4) LLM Prompts (LLM‑first with fallback)

### 4.1 Prompt goals
1. Identify **generic** facts/dimensions (not question‑specific).
2. Produce lineage edges explicitly.
3. Explain **grain** and **time column** choices.

### 4.2 Fallback heuristics
- Fact detection: numeric + date column.
- Dimension detection: `_id`/`_code` keys + text attributes.
- Lineage edges:
  - Fact.dimensions → Dimension.key match
  - Metric.sql → Fact ref match

---

## 5) Persistence and Canvas Integration

### 5.1 Persistence
Persist all AI‑generated objects:
- `quantyx_facts_registry`
- `quantyx_dimensions_registry`
- `quantyx_metrics_registry`

### 5.2 Canvas Nodes/Edges
Canvas should use:
- Nodes: registry objects
- Edges: LLM lineage + heuristic fallback

### 5.3 Manual + AI parity
All objects (manual or AI) use the same registries and appear on canvas.

---

## 6) Changes Required (Checklist)

1. **New semantic suggestion endpoints**
   - `/semantic/suggest`
   - `/semantic/suggest/apply`
2. **Prompt files**
   - `services/ai/prompts/semantic_suggest.md`
   - `services/ai/prompts/semantic_lineage.md`
3. **Lineage computation**
   - New LLM helper
   - Heuristic fallback in `services/ai/semantic_lineage.py`
4. **Persistence**
   - Reuse existing upsert functions
5. **Canvas API**
   - `GET /lineage` should include AI‑generated edges

---

## 7) Open Questions

1. Should we persist suggested metrics automatically or require approval?
2. Should lineage edges be versioned per suggestion run?
3. Do we want a “confidence score” per edge? (LLM + heuristic)
