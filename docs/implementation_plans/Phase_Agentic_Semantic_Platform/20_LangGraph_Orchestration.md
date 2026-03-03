# Phase 20: LangGraph Orchestration (Multi‑Agent Control)

## Objective
Adopt LangGraph to orchestrate multi‑agent workflows with shared state, retries, and explicit control flow.

---

## Why LangGraph
- Multi‑agent workflow control
- Shared state object across agents
- Explicit retries + fallbacks
- Observability + traceability

---

## Graph Definition (High‑Level)

```
Schema ─┬→ Profiling ─┬→ Join ─────────────┐
        │             ├→ Metric → Rollup ─┤
        │             └→ Model ───────────┤
        └→ Context → Ontology → Glossary ─┘
                       │
                       └→ Quality ───────→ Dashboard
```

Optional branches:
- Diagnostics agent
- Rollup planner

---

## Node Contracts (Inputs → Outputs)

### SchemaNode
- **Reads:** tenant_id, schema_ids
- **Writes:** schema_graph

### ProfilingNode
- **Reads:** schema_graph
- **Writes:** profiling_stats, grain_candidates

### ContextNode
- **Reads:** context_text
- **Writes:** context_entities, hierarchy_hints

### OntologyNode
- **Reads:** context_entities, hierarchy_hints, glossary_terms
- **Writes:** ontology (concepts, synonym_edges, hierarchy_edges)

### GlossaryNode
- **Reads:** context_entities
- **Writes:** glossary_terms

### JoinNode
- **Reads:** schema_graph, profiling_stats
- **Writes:** join_edges

### MetricNode
- **Reads:** schema_graph, profiling_stats
- **Writes:** metric_defs

### ModelNode
- **Reads:** profiling_stats
- **Writes:** model_classifications

### RollupNode
- **Reads:** metric_defs, profiling_stats
- **Writes:** rollup_plan, rollups_created

### QualityNode
- **Reads:** join_edges, ontology
- **Writes:** quality_report

### DashboardNode
- **Reads:** metric_defs, glossary_terms, join_edges
- **Writes:** dashboard_spec

---

## State Schema (Shared)

```json
{
  "schema_graph": {},
  "profiling_stats": {},
  "grain_candidates": [],
  "context_entities": [],
  "hierarchy_hints": [],
  "glossary_terms": [],
  "ontology": {},
  "join_edges": [],
  "metric_defs": [],
  "model_classifications": [],
  "rollup_plan": [],
  "quality_report": {},
  "dashboard_spec": {},
  "errors": []
}
```

---

## Conditional Branching Rules

- If `schema_graph` missing → stop run (fatal)
- If profiling fails → skip grain detection and proceed
- If join_edges empty → allow single‑table metrics only
- If metric_defs empty → fallback to numeric column sums
- If dashboard_spec fails → fallback to default 3‑chart template

---

## Parallel Execution Notes
- `Profiling`, `Context` branches run in parallel after `Schema`.
- `Join`, `Metric`, `Model` run in parallel after `Profiling`.
- `Quality` waits for `Join` + `Ontology`.
- `Dashboard` waits for `Rollup` + `Quality`.

## Parallelism Summary (Implementation)
- Parallel edges are now active in the LangGraph flow.
- Independent agents execute concurrently to reduce total runtime.
- Deterministic ordering is preserved by join nodes (Quality/Dashboard).

---

## Retry + Fallback Matrix

| Node | Retry Count | Fallback |
|---|---|---|
| Schema | 1 | fail run |
| Profiling | 2 | skip profiling stats |
| Context | 1 | proceed without context entities |
| Glossary | 1 | empty glossary |
| Join | 2 | heuristic joins |
| Metric | 1 | numeric sums |
| Dashboard | 1 | default template |

---

## Idempotency + Re‑runs

- `run_id` is the idempotency key.
- If a run exists:
  - resume from last completed node
  - skip nodes with valid output in state
- If input schema/context changed:
  - invalidate prior state keys
  - rerun dependent nodes

---

## Event Emission (Streaming Hooks)
Each node emits events into `quantyx_agent_run_events`:
- `status`: queued → running → completed / failed
- `message`: summarized user‑safe update
- `artifacts`: output summaries

Event schema:
```json
{
  "run_id": "run_123",
  "agent_name": "JoinAgent",
  "status": "completed",
  "message": "Detected 7 join paths",
  "artifacts": {"joins": 7}
}
```

---

## LangGraph State Persistence

- Runtime state is stored in memory.
- On each node completion, persist snapshot into `quantyx_agent_run_events`.
- Optional: `quantyx_agent_run_state` snapshot table for full state recovery.

---

## Error Taxonomy

- `schema_error`
- `profiling_error`
- `context_error`
- `glossary_error`
- `join_error`
- `metric_error`
- `dashboard_error`

Errors are logged into `errors[]` state and emitted as events.

---

## LangGraph vs Existing Job System

- **LangGraph** controls agent execution order and state.
- **Existing job system** provides scheduling + persistence.
- Integration: Job system creates run_id, LangGraph executes nodes.

---

## LangGraph Studio (Local Dev UI)

LangGraph Studio is **local-only** and requires no API key.

Suggested usage:
1. Export env:
   - `LANGGRAPH_STUDIO_ENABLED=true`
   - `LANGGRAPH_STUDIO_PORT=2024`
2. Run Studio in a separate terminal:
   - `langgraph dev --port 2024`
3. Open Studio UI:
   - `http://127.0.0.1:2024`

Quick start:
```bash
export LANGGRAPH_STUDIO_ENABLED=true
export LANGGRAPH_STUDIO_PORT=2024
langgraph dev --port 2024
```

All agent events are already streamed to your UI via:
- `GET /agentic/runs/{run_id}/stream`
- `GET /chat/{chat_id}/stream`

---

## Success Criteria
- Deterministic orchestration
- Clear error handling + retries
- Stable state propagation across agents
