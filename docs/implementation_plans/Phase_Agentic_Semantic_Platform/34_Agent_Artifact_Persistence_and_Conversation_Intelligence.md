# Phase 34: Agent Artifact Persistence and Conversation Intelligence

## Objective
Make every agent in the workspace deployment flow persist its own durable artifacts, then make workspace conversations and message queries load and use those persisted artifacts as the sole tenant/domain-scoped semantic intelligence source.

This phase closes the gap between:
- agentic run execution-time state
- persisted semantic assets
- conversational query-time intelligence

---

## Problem
- Several agents still compute useful outputs only in memory or only emit run events.
- Conversations currently consume only a subset of persisted artifacts.
- Query resolution can drift toward global/static catalog behavior instead of tenant/domain-scoped deployment artifacts.
- There is no single persisted "semantic intelligence bundle" for a canonical deployment run.

This produces three bad outcomes:
1. agent outputs are not replayable as first-class semantic assets
2. chat intelligence is incomplete relative to deployment work
3. deployed tenant/domain semantics are not guaranteed to be the same semantics used in conversations

---

## Target State
1. Every agent persists a durable artifact set tied to `tenant_id + domain_id + run_id + scope`.
2. Every persisted artifact is versioned, queryable, and replayable.
3. Workspace conversations use only persisted artifacts for the bound tenant/domain/run scope.
4. Query resolution is reconstructed from persisted intelligence, not transient run state.
5. The canonical deployment run becomes the semantic source of truth for workspace chat.

---

## Scope
1. Define per-agent persistence contracts.
2. Add missing storage for agent outputs that are currently in-memory only.
3. Build a scoped conversation intelligence loader for tenant/domain/run.
4. Update conversation/query APIs to use persisted artifacts only.
5. Add observability proving which persisted artifacts were loaded for each user query.

Out of scope:
- replacing the orchestration graph itself
- redesigning dashboard refresh orchestration
- replacing every legacy non-workspace query entrypoint in one step

---

## Current Gap Summary

### Agents that already persist meaningful artifacts
- `ProfilingAgent`: facts, dimensions
- `ContextAgent`: glossary terms, hierarchy overrides
- `GlossaryAgent`: glossary terms
- `OntologyAgent`: glossary terms, hierarchy overrides
- `MetricAgent`: metrics
- `RollupPlannerAgent`: rollups

### Agents with incomplete persistence
- `SchemaAgent`: schema graph exists in run state but not as a dedicated deployment artifact
- `JoinAgent`: join candidates, uniqueness checks, and coverage checks are not persisted as first-class semantic assets
- `SemanticModelAgent`: model classifications are not persisted as tenant/domain/run artifacts
- chart/dashboard planning stages: parts are persisted, but not as a unified conversation intelligence source

### Consumption gap
Workspace conversations should use:
- schema graph
- profiling outputs
- semantic model classifications
- join graph
- glossary
- ontology
- hierarchy hints
- facts
- dimensions
- metrics
- semantic contract
- rollups

Today they use only a partial subset.

---

## Per-Agent Artifact Contract

### 1) SchemaAgent
Persist:
- schema graph
- table list
- column metadata
- source scan linkage

Required usage in conversations:
- table/column grounding
- dimension fallback generation
- semantic ambiguity reduction

### 2) ProfilingAgent
Persist:
- table profiling stats
- candidate keys
- numeric/time/categorical classifications
- measure eligibility metadata
- fact candidates
- dimension candidates

Required usage in conversations:
- metric support validation
- dimension validation
- query planner safety

### 3) ContextAgent
Persist:
- extracted context entities
- glossary candidates
- hierarchy hints
- context-to-schema associations

Required usage in conversations:
- business phrase grounding
- synonym interpretation
- hierarchy-aware explanations

### 4) GlossaryAgent
Persist:
- normalized glossary terms
- synonyms
- abbreviations
- source/provenance

Required usage in conversations:
- phrase normalization
- abbreviation expansion
- deterministic dimension aliasing

### 5) OntologyAgent
Persist:
- ontology concepts
- synonym edges
- hierarchy edges
- concept-to-asset mappings

Required usage in conversations:
- semantic matching
- domain concept expansion
- KPI intent understanding

### 6) JoinAgent
Persist:
- join candidates
- join validations
- uniqueness evidence
- coverage evidence
- approval state

Required usage in conversations:
- deterministic cross-table planning
- safe dimension expansion
- explainability of joins used

### 7) MetricAgent
Persist:
- scoped metric definitions
- SQL
- source model / dataset
- supported dimensions
- provenance and confidence

Required usage in conversations:
- metric resolution
- allowed aggregations
- final SQL planning

### 8) SemanticModelAgent
Persist:
- fact model classifications
- dimension model classifications
- dataset semantic roles

Required usage in conversations:
- model-aware query planning
- correct grain assumptions
- safer dimension/metric combination logic

### 9) RollupPlannerAgent
Persist:
- rollup definitions
- serving status
- dimensionality and time-grain support

Required usage in conversations:
- rollup hit selection
- execution optimization

### 10) Chart/Dashboard Agents
Persist:
- chart intent/spec
- dashboard spec
- chart-to-metric lineage
- dashboard summaries where relevant

Required usage in conversations:
- follow-up analytics
- dashboard-aware continuation
- explainability of prior responses

---

## Data Model Plan

## 1) Artifact storage principle
Every artifact row must include:
- `tenant_id`
- `domain_id`
- `run_id`
- `connection_id`
- `database_name`
- `schema_name`
- `artifact_key`
- `version_no`
- `is_current`
- `lifecycle_status`
- `source_type`
- timestamps

This aligns all agent outputs to the same scoping model already used in facts/dimensions/metrics.

## 2) New or extended storage needed

### A) `quantyx_schema_graph_artifacts`
Purpose:
- persist schema graph produced by `SchemaAgent`

Suggested payload:
- graph JSON
- tables JSON
- columns JSON
- scan linkage metadata

### B) `quantyx_table_profile_artifacts`
Purpose:
- persist profiling outputs from `ProfilingAgent`

Suggested payload:
- row counts
- key candidates
- eligible measures
- semantic roles per column

### C) `quantyx_join_registry`
Purpose:
- persist `JoinAgent` outputs

Suggested payload:
- left/right table
- join keys
- confidence
- uniqueness evidence
- coverage evidence
- approval status

### D) `quantyx_model_registry`
Purpose:
- persist `SemanticModelAgent` outputs

Suggested payload:
- dataset id
- model type (`fact|dimension|bridge|unknown`)
- grain
- time column
- supporting evidence

### E) extend existing semantic stores
Existing stores should consistently include run/version semantics where missing:
- `quantyx_glossary_terms`
- `quantyx_hierarchy_overrides`
- `quantyx_facts_registry`
- `quantyx_dimensions_registry`
- `quantyx_metrics_registry`
- `quantyx_semantic_contracts`
- rollup metadata tables

---

## Conversation Intelligence Loader

## Goal
Create one internal loader that reconstructs the tenant/domain/run semantic bundle from persisted artifacts.

Suggested internal contract:
```python
load_conversation_intelligence(
    tenant_id: str,
    domain_id: str,
    run_id: str | None = None,
    connection_id: str | None = None,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> ConversationIntelligenceBundle
```

Bundle contents:
- `schema_graph`
- `profiles`
- `joins`
- `facts`
- `dimensions`
- `metrics`
- `glossary`
- `ontology`
- `semantic_models`
- `semantic_contract`
- `rollups`
- `artifact_versions`

Rules:
1. default to the canonical completed deployment run for the tenant/domain
2. scope by active conversation run if pinned
3. do not merge in global/static metrics for workspace conversations
4. do not use transient run state
5. expose diagnostics for loaded counts and source run ids

---

## API / Behavior Changes

## Actual API Impact So Far

These are the concrete API and payload changes already introduced in code as part of the first step toward run-scoped conversation intelligence.

### 1) `POST /workspace/conversations/{conversation_id}/messages`
External request payload:
- no change required

Behavior change:
- the message query now executes against the conversation's bound `run_id`
- conversations no longer need to pass semantic scope in payload because the bound deployment run is used internally

Impact:
- non-breaking behavior improvement
- no client payload migration required

### 2) `POST /chat`
Request payload change:
- optional `run_id` added

New optional request shape:
```json
{
  "question": "What is total LPG production by plant last week?",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "run_id": "run_1a0f427c86ec",
  "mode": "sync"
}
```

Impact:
- additive only
- existing clients continue to work
- callers can explicitly bind a chat request to a deployment run for debug/admin replay
- for normal product use, backend resolves the canonical deployment `run_id` from `tenant_id + domain_id`
- current code path already does this backend resolution

### 3) `POST /query`
Request payload change:
- optional `run_id` added to `QueryRequest`

New optional request shape:
```json
{
  "question": "top 3 zones with high productivity",
  "tenant_id": "DEBUG_LPG_001",
  "domain_id": "lpg_production_distribution",
  "run_id": "run_1a0f427c86ec",
  "limit": 50
}
```

Impact:
- additive only
- existing clients continue to work
- allows deterministic query execution against one deployment run for debug/admin replay
- for normal product use, backend resolves the canonical deployment `run_id` from `tenant_id + domain_id`
- current code path already does this backend resolution and fails clearly if no completed deployment exists

### 4) `GET /agentic/debug/intelligence`
New endpoint added.

Purpose:
- inspect the run-scoped conversation intelligence bundle
- verify what a deployment run contributed before debugging conversations

Example:
```http
GET /agentic/debug/intelligence?tenant_id=VC_101&domain_id=lpg_production_distribution&run_id=run_1a0f427c86ec
```

Impact:
- additive only
- debug/diagnostic endpoint, not required for product clients

## Planned API Tightening

These are not yet enforced everywhere, but are the intended future-state API rules for this phase.

### 1) Workspace conversations remain the preferred customer API
`POST /workspace/conversations/{conversation_id}/messages`
- should continue to avoid asking clients for `run_id`
- the conversation must already be bound to a deployment run
- backend must always resolve `run_id` from the conversation record

### 2) `run_id` remains optional at API level
Future rule:
- workspace messages always execute with a bound deployment `run_id` resolved from conversation state
- direct `/chat` and `/query` should resolve `run_id` from canonical deployment for `tenant_id + domain_id`
- explicit `run_id` remains optional and should be used only for debug, replay, or admin workflows

This is the preferred contract because semantic intelligence remains run-scoped without making normal product clients carry orchestration identifiers.

### 3) No legacy compatibility requirement
Per current product direction:
- we do not need migrations or fallback behavior to support older deployment artifact contracts
- only future deployments need to satisfy the full artifact bundle contract
- conversations should fail clearly if a future run is missing required artifacts

### 1) `POST /workspace/deployments`
No behavior change at API shape level.
Internal change:
- each agent stage must persist its artifacts before stage completion

### 2) `POST /workspace/conversations`
Conversation must bind to a concrete deployment run.
Optional future enhancement:
- snapshot artifact version summary into conversation metadata for audit/replay

### 3) `POST /workspace/conversations/{conversation_id}/messages`
Must load intelligence only from persisted deployment artifacts for that conversation scope.

Required behavior:
- metric resolution from scoped metrics only
- dimension grounding from scoped facts/dimensions/schema graph
- semantic phrase expansion from glossary/ontology only for that scope
- join planning from persisted validated joins
- rollup selection from scoped rollups only

### 4) Diagnostics
Add structured logs and optional debug payloads:
- artifact counts loaded by type
- run id and scope used
- metric candidates considered
- joins selected
- fallback reason if no scoped artifact supports the request

---

## Implementation Plan

### Phase 34.1: Persistence contract normalization
- document agent-to-artifact ownership
- normalize common scoping/version fields across all semantic stores
- add missing run-aware fields where needed
Status:
- implemented

### Phase 34.2: Persist missing agent outputs
- add schema graph artifact persistence
- add join registry persistence
- add semantic model persistence
- add profiling artifact persistence where only derived registries exist today
Status:
- implemented via dedicated run-scoped stores for schema graph, table profiles, joins, and semantic models

### Phase 34.3: Conversation intelligence bundle
- implement `load_conversation_intelligence(...)`
- load all scoped persisted artifacts in one place
- expose counts/versions for logs and testing
Status:
- implemented via the run-scoped intelligence loader used by `/workspace/conversations/{conversation_id}/messages`, `/query`, and `/chat`

### Phase 34.4: Workspace conversation enforcement
- route workspace message queries through the bundle only
- remove remaining fallback to unrelated global/static catalog metrics for workspace requests
- enforce tenant/domain/run scoping consistently
Status:
- implemented for workspace conversations and tenant/domain-scoped query execution
- normal product APIs resolve canonical deployment `run_id` in backend
- explicit `run_id` remains optional for debug/admin replay only

### Phase 34.5: Query planner integration
- use persisted joins for multi-table planning
- use persisted semantic models for fact/dimension compatibility checks
- use persisted profiling evidence for measure/dimension safety
Status:
- implemented for persisted join-aware SQL planning
- implemented for semantic-model-aware metric pruning and ranking before SQL build
- implemented for scoped dimension/filter grounding using persisted join-connected tables
- implemented for explicit semantic validation of incompatible grain and missing time-support combinations before SQL build
- profiling evidence is loaded and used for dimension candidates and table metadata; heuristics can still be deepened further without changing the Phase 34 contract

### Phase 34.6: Replay and audit
- allow inspection of which artifact versions powered a conversation turn
- support replay/debug from conversation to deployment artifact set
Status:
- implemented with run-scoped intelligence inspection and structured query logs
- implemented with per-turn artifact lineage snapshots persisted into workspace message `summary_json` and `inference_json`
- direct `/query` responses now expose `artifact_lineage` for debug/admin replay and audit

---

## Acceptance Criteria
1. Every agent in the deployment graph has a defined persisted artifact output.
2. `SchemaAgent`, `JoinAgent`, and `SemanticModelAgent` no longer rely on in-memory-only outputs for downstream chat behavior.
3. Workspace conversation queries load only tenant/domain/run-scoped persisted artifacts.
4. No workspace conversation query resolves to metrics outside the bound tenant/domain scope.
5. Debug logs clearly show which persisted artifacts were loaded for each query.
6. A completed deployment run can be replayed into conversation intelligence without reading transient orchestration state.
7. If a required artifact class is missing, the system fails explicitly with a scoped diagnostic instead of silently falling back to unrelated semantics.

---

## Test Plan
1. Deployment test:
   run a workspace deployment and assert artifact rows exist for each agent-owned store.

2. Scope isolation test:
   create two tenants/domains with different metrics and verify each conversation resolves only its own scoped artifacts.

3. Replay test:
   start a conversation after deployment restart and verify the same persisted artifacts are loaded without in-memory dependency.

4. Join test:
   persist validated joins and verify multi-table conversation queries use those joins only.

5. Negative test:
   remove scoped metrics for a tenant/domain and verify conversation fails with a scoped semantic diagnostic instead of using global metrics.

6. Audit test:
   confirm a message turn can be traced back to the exact run/artifact versions used.

---

## Dependencies
- Phase 12 for storage conventions
- Phase 20 for orchestration stage boundaries
- Phase 22 for run event and artifact observability
- Phase 24 for deployment-run and conversation binding
- Phase 25 for tenant-first conversation entry
- Phase 29 and Phase 30 for semantic role and metric generation quality
- Phase 31 for safe SQL planning

---

## Success Criteria
- Deployment artifacts become the single semantic source of truth for workspace chat.
- Agent intelligence is durable, auditable, and reusable after the run finishes.
- Conversations respond using the same persisted tenant/domain semantics produced by deployment.
