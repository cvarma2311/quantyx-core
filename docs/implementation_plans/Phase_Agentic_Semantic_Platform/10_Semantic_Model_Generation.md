# Phase 10: Semantic Model Generation (Cube‑Style Concepts)

## Objective
Auto‑generate Cube‑style semantic models (measures, dimensions, joins, segments, time grains, rollups) from schema + context using agents.

---

## Mapping: Cube Concepts → Our System

| Cube Concept | Our Equivalent | Source |
|---|---|---|
| Cube (model) | Fact model node + base table/view | Schema Agent + Profiling Agent |
| Measure | Metric node + SQL formula | Metric Agent |
| Dimension | Dimension node + column edge | Schema Agent + Profiling Agent |
| Segment | Filter rule node | Rule Engine |
| Join | Model↔Model edge | Join Agent |
| Time dimension | Time dimension node + grain | Profiling Agent |
| Pre‑aggregation | Rollup registry + materialized table | Rollup Planner |

---

## Generation Pipeline

1) **Schema Classification**
   - Detect facts vs dimensions
   - Identify numeric + time columns

2) **Metric Synthesis**
   - Build formulas from numeric columns
   - Attach metrics to base models

3) **Dimension Extraction**
   - Generate dimension nodes for categorical columns
   - Bind dimension → column edges

4) **Join Discovery**
   - Use PK/FK and naming heuristics
   - Score join confidence

5) **Segment Rules**
   - Convert common filters into reusable rules

6) **Time Grains**
   - Detect time columns
   - Assign default grains (day/week/month)

7) **Rollup Planning**
   - Generate rollup tables for top query patterns

---

## Output Artifacts

- `semantic_nodes`
- `semantic_edges`
- `quantyx_rollup_registry`
- Rollup tables
- Model classifications (fact/dimension)

---

## Example Output

### Metric Node
```json
{
  "node_type": "metric",
  "name": "production_mt",
  "formula": "(production_14_2kg*14.2 + production_19kg*19)/1000",
  "base_model": "fact_lpg_plant_operations"
}
```

### Dimension Node
```json
{
  "node_type": "dimension",
  "name": "region",
  "column": "region",
  "base_model": "fact_lpg_plant_operations"
}
```

---

## Success Criteria
- 80% of required semantic model is generated without manual input
- Deterministic resolution coverage > 70%
- Rollup hit rate > 60%
