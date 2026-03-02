# Phase AE: Multi‑Agent LLM Parallelism (Context + dbt)

Goal: split LLM work into parallel, bounded agents to reduce latency, improve
fault isolation, and support retries. This phase covers context extraction and
dbt scaffolding with agent‑level jobs.

---

## 1) Why

Current single‑shot LLM calls can time out or fail as payload size grows.
By splitting tasks into small agents we get:
- parallel execution
- shorter prompts
- isolated failure + retry
- better observability per output

---

## 2) Agent Breakdown

### 2.1 Context Extraction Agents

Agent A — Glossary/Synonyms  
- Input: raw context text  
- Output: terms, synonyms, abbreviations  
- Table: `quantyx_glossary_terms` (via apply)

Agent B — Hierarchies  
- Input: raw context text  
- Output: hierarchy objects  
- Table: `quantyx_hierarchy_overrides` (via apply)

Agent C — Metric Candidates  
- Input: context + schema summary  
- Output: metric candidates  
- Table: `quantyx_metrics_registry` (via apply)

Agent D — Question Intents  
- Input: context text  
- Output: sample questions + intent tags  
- Table: `quantyx_context_extractions` (payload)

### 2.2 dbt Scaffolding Agents

Agent E — Fact/Dim Candidates  
- Input: schema summary + glossary  
- Output: fact/dim candidates  
- Table: `quantyx_facts_registry`, `quantyx_dimensions_registry` (if enabled)

Agent F — SQL Generator  
- Input: fact/dim definitions + schema  
- Output: dbt SQL stubs  
- Storage: DB scaffold table + filesystem

Agent G — Schema/YAML Generator  
- Input: SQL + schema  
- Output: schema.yml stubs  
- Storage: DB scaffold table + filesystem

### 2.3 Entity Mapping Agents (Column → Ontology)

Agent H — Table Mapping  
- Input: ontology + glossary + one table’s columns  
- Output: mapping candidates for that table  
- Storage: `quantyx_entity_mapping_agents` (per‑table chunk), merged into `quantyx_entity_mappings`

Notes:
- Each table is treated as its own agent.
- Large tables can be split into chunks; each chunk is a sub‑agent.

---

## 3) Job Model (Parallel)

Each agent runs as a **job type**:
- `context_glossary`
- `context_hierarchies`
- `context_metrics`
- `context_questions`
- `dbt_infer_models`
- `dbt_generate_sql`
- `dbt_generate_yaml`

Jobs can be triggered in parallel and merged into a single extraction result.

---

## 4) API Additions

### 4.1 Async context extraction (multi‑agent)

`POST /context/extract/async`

Payload:
```json
{
  "tenant_id": "tenant_a",
  "context_id": "ctx_123",
  "extraction_types": ["abbreviations", "synonyms", "hierarchies", "metric_candidates", "question_intents"],
  "mode": "parallel"
}
```

Response:
```json
{ "job_id": "job_ctx_123", "status": "queued" }
```

### 4.2 Agent fan‑out contract (internal)

When `mode=parallel`, the handler creates **child jobs**:
```json
{
  "parent_job_id": "job_ctx_123",
  "children": [
    {"job_type": "context_glossary", "payload": {...}},
    {"job_type": "context_hierarchies", "payload": {...}},
    {"job_type": "context_metrics", "payload": {...}},
    {"job_type": "context_questions", "payload": {...}}
  ]
}
```

The parent job status becomes:
- `running` when children are queued
- `completed` only when all children complete
- `failed` if any child fails (with error aggregation)

### 4.2 Job result aggregation

`GET /jobs/{job_id}/result`

Result merges agent outputs:
```json
{
  "extractions": {
    "abbreviations": [...],
    "synonyms": [...],
    "hierarchies": [...],
    "metric_candidates": [...],
    "question_intents": [...]
  }
}
```

---

## 4.3 Job Payload Schemas (Detailed)

### context_glossary
```json
{
  "tenant_id": "tenant_a",
  "context_id": "ctx_123",
  "raw_text": "...",
  "model": "gpt-4o-mini"
}
```

### context_hierarchies
```json
{
  "tenant_id": "tenant_a",
  "context_id": "ctx_123",
  "raw_text": "...",
  "model": "gpt-4o-mini"
}
```

### context_metrics
```json
{
  "tenant_id": "tenant_a",
  "context_id": "ctx_123",
  "raw_text": "...",
  "schema_summary": {...},
  "model": "gpt-4o-mini"
}
```

### context_questions
```json
{
  "tenant_id": "tenant_a",
  "context_id": "ctx_123",
  "raw_text": "...",
  "model": "gpt-4o-mini"
}
```

---

## 4.4 Job Worker Orchestration (Pseudo‑logic)

```
if job_type == "context_extract":
  fan_out child jobs
  track child status
  merge results into extraction payload
```

---

## 4.5 End‑to‑End Example (Parent + Children + Merge)

### Parent job submit
`POST /context/extract/async`
```json
{
  "tenant_id": "tenant_a",
  "context_id": "ctx_123",
  "extraction_types": ["abbreviations", "synonyms", "hierarchies", "metric_candidates", "question_intents"],
  "mode": "parallel"
}
```

Response:
```json
{ "job_id": "job_ctx_123", "status": "queued" }
```

### Child jobs created
```json
{
  "parent_job_id": "job_ctx_123",
  "children": [
    { "job_id": "job_glossary_1", "job_type": "context_glossary" },
    { "job_id": "job_hier_1", "job_type": "context_hierarchies" },
    { "job_id": "job_metrics_1", "job_type": "context_metrics" },
    { "job_id": "job_questions_1", "job_type": "context_questions" }
  ]
}
```

### Merged result (job result)
`GET /jobs/job_ctx_123/result`
```json
{
  "job_id": "job_ctx_123",
  "status": "completed",
  "result": {
    "extraction_id": "ext_123",
    "context_id": "ctx_123",
    "extractions": {
      "abbreviations": [{"abbr": "SBU", "definition": "Strategic Business Unit"}],
      "synonyms": [{"term": "sales area", "synonyms": ["territory"]}],
      "hierarchies": [{"name": "sales_org", "levels": ["zone", "region", "sales_area"]}],
      "metric_candidates": [{"metric_name": "output_tmt", "table": "fact_production_daily"}],
      "question_intents": [{"question": "Which plants are underperforming?", "metrics": ["output_tmt"]}]
    }
  }
}
```

### Persisted extraction (DB)
Row in `public.quantyx_context_extractions`:
```json
{
  "extraction_id": "ext_123",
  "context_id": "ctx_123",
  "extraction_type": "combined",
  "payload": {
    "abbreviations": [...],
    "synonyms": [...],
    "hierarchies": [...],
    "metric_candidates": [...],
    "question_intents": [...]
  }
}
```

---

## 5) Storage Changes

No new tables required; reuse:
- `quantyx_context_extractions`
- `quantyx_glossary_terms`
- `quantyx_hierarchy_overrides`
- `quantyx_metrics_registry`
- dbt scaffold tables

Optional: add `agent_name` field to extraction payload for traceability.

---

## 6) How This Connects to Onboarding Phases

### Phase L (Business Context Intake)
- Multi‑agent extraction replaces the single LLM call.
- Parent job aggregates child outputs into one extraction payload.
- `/context/apply` consumes the merged extraction payload.

### Phase N/Q (Connection‑Scoped Onboarding)
- Applied hierarchies/entities are stored with `context_id`.
- Multiple contexts can be active; Ask uses the union.

### Phase AB (Ask What)
- Glossary + hierarchy + metric candidates are now cleaner and more complete.
- Ask uses merged extraction results via overrides + glossary tables.

### Phase AC (Ask Why)
- Driver dimension hints can be populated from context_metrics agent outputs.

### Phase Demo (LPG)
- Parallel extraction reduces timeouts and makes demo stable.

---

## 7) Merge Logic (Deterministic)

Agent outputs merge into a single payload in this order:
1) `abbreviations` + `synonyms` (de‑dupe by normalized term)
2) `hierarchies` (de‑dupe by `name`; if conflict, keep highest confidence)
3) `metric_candidates` (de‑dupe by `metric_name + table`)
4) `question_intents` (unique questions)

Conflict handling:
- If two agents produce the same key with different values:
  - prefer higher confidence
  - else prefer more recent
  - else keep both with `source_agent` tags

The merged output is what `/context/apply` consumes.

---

## 7.1 Merge Utility (Implementation Live)

Proposed module:
`services/ai/context_merge.py`

Signature:
```python
def merge_extractions(agent_payloads: list[dict]) -> dict:
    \"\"\"Merge agent outputs into one extraction payload.\"\"\"
```

Inputs:
- `agent_payloads`: list of dicts with keys:
  - `agent_name`
  - `confidence` (optional)
  - `payload` (extractions)

Output:
- merged extraction payload with optional `sources` metadata.

Example merge output:
```json
{
  "abbreviations": [...],
  "synonyms": [...],
  "hierarchies": [...],
  "metric_candidates": [...],
  "question_intents": [...],
  "_sources": {
    "hierarchies": {"sales_org": ["context_hierarchies"]},
    "metric_candidates": {"output_tmt": ["context_metrics"]}
  }
}
```

---

## 7.2 Schema Changes (Required)

Add agent attribution fields to extraction storage:

```sql
ALTER TABLE public.quantyx_context_extractions
  ADD COLUMN IF NOT EXISTS agent_name TEXT NULL,
  ADD COLUMN IF NOT EXISTS parent_job_id TEXT NULL;
```

Per‑agent persistence (required):
```sql
CREATE TABLE IF NOT EXISTS public.quantyx_context_extraction_agents (
  agent_run_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  payload JSONB NOT NULL,
  confidence NUMERIC NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 8) Acceptance Criteria

- Context extraction runs in parallel agents.
- Partial failures are isolated and retried per agent.
- Aggregated result is deterministic and persisted.
- dbt scaffolding jobs run independently (facts/dims, SQL, YAML).
