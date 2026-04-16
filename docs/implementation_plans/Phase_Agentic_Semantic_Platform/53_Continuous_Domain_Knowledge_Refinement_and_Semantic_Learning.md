# Phase 53: Continuous Domain Knowledge Refinement and Semantic Learning

## Goal

Make semantic understanding a continuous lifecycle instead of a one-time deployment artifact.

After the initial agentic run has created:

- schema graph
- semantic graph
- ontology
- hierarchies
- metrics
- dashboards
- chart interaction metadata

the system should allow users to continuously improve domain knowledge by adding or correcting:

- business context
- hierarchy definitions
- column descriptions
- metric meanings and formulas
- aliases and glossary terms
- business rules and exclusions
- chart interpretation hints
- entity relationships and join expectations

The platform should absorb these updates safely, persist them as structured knowledge, validate them deterministically where possible, and make them available to downstream charting, query planning, anomaly detection, correlation, and conversations.

---

## Why This Phase Is Needed

The current deployment model is strong for initial bootstrapping, but real semantic quality improves over time.

In practice, users often realize later that:

- a hierarchy is incomplete or ordered incorrectly
- a column name is cryptic and needs business meaning
- a product or code mapping is missing
- a metric formula needs to be overridden
- a table should not be joined
- a chart should use a different default grain
- a dimension should be treated as a level in a hierarchy
- a measure should be excluded from KPI generation

Today, many of these improvements require a new deployment or manual edits in multiple places.

This phase turns semantic improvement into a first-class product loop:

- add knowledge later
- validate it
- persist it
- apply it selectively
- propagate it into downstream behavior

---

## Product Principles

### 1. Deployment Is Bootstrap, Not Final Truth

The first agentic run gives the initial model of the domain.
It should not be treated as the final or immutable semantic truth.

### 2. Human Knowledge Must Override Weak Inference

If a user later provides:

- a hierarchy
- a column meaning
- a metric definition
- a business exception

that should be able to override weaker heuristic or LLM-derived semantics.

### 3. Runtime Querying Stays Deterministic

Even though semantics can improve continuously, runtime query planning, drill-down, and chart filtering should remain deterministic.

This means:

- knowledge refinement can be LLM-assisted
- runtime compilation should use persisted approved semantics

### 4. Changes Must Be Versioned and Auditable

Semantic improvements change downstream behavior.
So every update should be:

- persisted
- attributable
- versioned
- reviewable
- reversible if needed

### 5. Refinement Should Be Incremental

The system should not require a full redeploy for every semantic improvement.

Some changes should trigger:

- immediate local propagation
- partial recomputation
- or full redeployment only when necessary

### 6. Domain Packs Should Ask Better Questions

Each domain pack should be able to define default business-context questions that help the system gather the missing semantic details needed for strong dashboard generation.

This means a domain pack should not only provide:

- metric templates
- chart guidance
- hierarchy hints

It should also provide:

- a default context questionnaire
- default dashboard-discovery questions
- optional follow-up clarification questions

These questions act as structured context prompts for users, not as runtime NL queries to the warehouse.

---

## Types of Knowledge Users May Add Later

### A. Business Context Additions

Examples:

- "Use the operational date column as the canonical day for reporting."
- "Use fiscal year boundaries instead of calendar year for reporting."
- "Do not compare current month until the month is complete."
- "Exclude invalid or zero-value records from KPI calculations."

### B. Hierarchy Additions or Corrections

Examples:

- `country > state > city > location > site`
- `category > subcategory > product`
- "Store should not appear above district in the hierarchy"

### C. Column Descriptions

Examples:

- `business_entity_id` means customer-facing business identifier
- `internal_entity_id` is internal and should not be shown by default
- `status_code` values map to business-facing labels

### D. Metric Semantics

Examples:

- "Growth rate should compare to prior month, not prior day"
- "Use the approved aggregate measure as total volume"
- "This measure is operational, not executive KPI"

### E. Join or Relationship Corrections

Examples:

- "Do not join the transaction fact to external reference tables for KPI calculation"
- "Use the reference table only for labels, not for aggregation grain"

### F. Query and Chart Guidance

Examples:

- "Monthly trend should be the default for forecasting"
- "Geographic levels are the preferred drill path"
- "Internal identifiers should only appear at the deepest drill level"

### G. Interpretation Guidance

Examples:

- "A one-day dip is not operationally significant unless repeated"
- "Small premium-segment fluctuations are expected and should not be treated as anomalies by default"

---

## Core Concept

Introduce a persistent domain knowledge refinement layer that sits above raw schema profiling and below runtime execution.

This layer should hold:

- inferred semantics from deployment
- human corrections
- approved overrides
- learned ranking hints
- source provenance

Think of it as:

- domain memory
- semantic feedback registry
- refinement artifact store

This layer should also hold:

- pack-defined context questions
- pack-defined clarification prompts
- pack-defined dashboard discovery questions

---

## Domain Pack Context Questions

One important extension to this phase is:

- every domain pack should be able to declare default business questions that help gather better context for dashboard generation

These are not user analytics questions like:

- "show me sales by region"

They are semantic discovery questions like:

- what does success look like in this domain
- what are the most important KPIs
- what are the preferred drill paths
- what time grains matter most
- what exclusions or business rules should always apply

### Why This Matters

Users often know the business, but they do not know what context the system needs in order to produce strong dashboards.

So instead of asking users for a blank block of context text, the system should be able to ask:

- a reusable set of high-value domain questions
- based on the selected pack

This improves:

- semantic extraction quality
- metric proposal quality
- hierarchy quality
- dashboard composition quality
- anomaly/correlation interpretation

---

## What These Questions Should Do

They should help the system collect:

- KPI priorities
- business definitions
- time semantics
- hierarchy semantics
- default filters
- exclusions
- alert/anomaly sensitivity guidance
- benchmark/target context
- quality expectations

### Example Question Categories

#### KPI Questions

- What are the most important business outcomes this dashboard should track?
- Which measures are operational vs executive?
- Which metrics should always be visible first?

#### Time Questions

- What is the canonical operational date?
- Should analysis prefer daily, weekly, monthly, or fiscal views?
- Are there incomplete periods that should be suppressed?

#### Hierarchy Questions

- What is the preferred business drill path from broad to detailed levels?
- Which identifiers are internal-only and should not be shown by default?
- Which dimensions are most meaningful for drill-down?

#### Filter and Rule Questions

- Which records should always be excluded?
- Are there invalid states or placeholder records to ignore?
- Are there mandatory business rules for KPI calculation?

#### Dashboard Intent Questions

- Is this dashboard meant for operations, management, planning, finance, or data quality?
- Which comparisons matter most: trend, target, variance, ranking, mix, or forecast?

#### Data Trust Questions

- Which fields are known to be unreliable?
- Which tables should not be used for KPI generation?
- Are there known duplication or quality concerns?

---

## Pack Contract Extension

Each domain pack should be able to provide a questionnaire file, for example:

- `packs/<domain>/context_questions.yml`

Suggested structure:

```yaml
question_groups:
  - group_id: dashboard_objectives
    title: Dashboard Objectives
    questions:
      - question_id: primary_kpis
        prompt: What are the most important KPIs this dashboard should track?
        answer_type: text
        required: true

      - question_id: dashboard_audience
        prompt: Who is the main audience for this dashboard?
        answer_type: single_select
        options: [operations, management, finance, planning, quality]
        required: false

  - group_id: hierarchy_and_grain
    title: Hierarchy and Grain
    questions:
      - question_id: preferred_drill_path
        prompt: What is the preferred business drill path from broad to detailed levels?
        answer_type: text
        required: false

      - question_id: preferred_time_grain
        prompt: Which time grain is most important for decision-making?
        answer_type: single_select
        options: [day, week, month, quarter]
        required: false
```

### What the Pack Should Be Allowed to Define

- question groups
- prompts
- answer types
- required vs optional
- suggested defaults
- help text
- which semantic artifact type the answer should influence

---

## How Pack Questions Should Be Used

### 1. Deployment-Time Context Guidance

When a user selects a domain pack, the UI should be able to display:

- a default context questionnaire from the pack

This gives users a guided way to provide strong semantic context.

### 2. Context Gap Filling

If context is sparse, the system can identify which important question groups are unanswered:

- KPI priorities missing
- hierarchy missing
- time semantics missing
- exclusions missing

and ask follow-up questions selectively.

### 3. Refinement After Deployment

Later, if the user adds more knowledge, those same pack questions can be reused as refinement prompts.

This fits Phase 53 well because refinement is not only free-form text. It can also be:

- guided semantic Q&A driven by the pack

### 4. Structured Mapping Into Semantic Artifacts

Each answer should map into one or more downstream semantic artifact categories:

- KPI answer -> metric priority / dashboard guidance
- hierarchy answer -> hierarchy refinement artifact
- date answer -> time semantics artifact
- exclusions answer -> rule artifact
- audience answer -> dashboard intent / chart preference artifact

---

## New Artifact Type: Context Question Answers

To support this, add a refinement artifact type like:

- `context_question_answer`

Example:

```json
{
  "artifact_type": "context_question_answer",
  "artifact_json": {
    "question_id": "preferred_drill_path",
    "group_id": "hierarchy_and_grain",
    "answer_text": "country > state > district > location > site",
    "maps_to": ["hierarchy_override"]
  }
}
```

This lets the system preserve:

- the original business answer
- the question it responded to
- the semantic interpretation derived from it

---

## API Ideas for Pack Questions

### Get default pack questions

`GET /semantic/context-questions?tenant_id=...&domain_id=...`

or

`GET /packs/{pack_id}/context-questions`

### Submit answers

`POST /semantic/context-answers`

Payload:

```json
{
  "tenant_id": "ns-1",
  "domain_id": "example_domain",
  "answers": [
    {
      "question_id": "primary_kpis",
      "answer_text": "Revenue, margin, and fulfillment rate"
    },
    {
      "question_id": "preferred_drill_path",
      "answer_text": "country > state > district > location > site"
    }
  ]
}
```

These should then flow into:

- `quantyx_domain_refinement_inputs`
- `quantyx_domain_refinement_artifacts`

---

## How This Improves Dashboard Creation

Without pack questions:

- users provide uneven context
- important semantic details are often missing
- dashboard quality depends too much on how well the user phrased the initial text

With pack questions:

- the system gathers the highest-value semantic inputs consistently
- dashboard generation becomes more predictable
- packs can steer users toward the exact context needed for good chart composition

This is especially useful for:

- new users
- sparse contexts
- highly specialized domains

---

## Proposed Architecture

### Layer 1. Raw Semantic Artifacts

Generated during initial or later agentic runs:

- schema graph
- profiling artifacts
- join proposals
- ontology proposals
- metric proposals
- hierarchy proposals
- glossary proposals

These are candidate semantics.

### Layer 2. Refinement Artifacts

Persist user-added or agent-suggested improvements as structured updates:

- context additions
- hierarchy corrections
- column annotations
- metric corrections
- join restrictions
- chart guidance
- interpretation guidance
- context question answers

These become refinement inputs.

### Layer 3. Approved Semantic State

A reconciled semantic state built from:

- raw semantic artifacts
- approved refinements
- deterministic validation
- ranking and precedence rules

This approved semantic state is what downstream systems should consume.

---

## What Should Happen When Users Add More Context Later

### Example

A user initially deploys with minimal context.
Later they add:

- hierarchy information
- column descriptions
- business rules for financial year
- metric explanation

The system should do this:

1. store the new input as domain refinement input
2. classify it into semantic categories
3. extract structured candidates
4. validate candidates
5. merge them with existing semantic state
6. recompute affected downstream artifacts
7. preserve audit history

---

## Refinement Flow

### Step 1. Input Collection

Users may provide refinement input through:

- inline context text
- uploaded documentation
- explicit hierarchy UI
- explicit metric override UI
- column description UI
- conversation-based semantic correction

Examples:

- "Actually the internal identifier should not be the default drill field; prefer the business identifier"
- "Growth rate should be month over month"
- "The hierarchy should move from broad geography to local entity"

### Step 2. Refinement Classification

Classify the input into one or more semantic refinement categories:

- glossary
- hierarchy
- metric
- filter rule
- join rule
- chart preference
- anomaly interpretation rule
- correlation interpretation rule

This can be LLM-assisted, but output must be structured.

### Step 3. Structured Extraction

Transform the refinement input into structured artifacts.

Examples:

```json
{
  "artifact_type": "hierarchy_override",
  "domain_id": "example_domain",
  "levels": ["country", "state", "city", "location", "site"]
}
```

```json
{
  "artifact_type": "column_annotation",
  "table": "fact_transactions",
  "column": "business_entity_id",
  "business_label": "Business Entity Code",
  "description": "Business-facing identifier used for entity-level grouping",
  "display_priority": "high"
}
```

### Step 4. Deterministic Validation

Validate the refinement before accepting it:

- hierarchy levels must map to real columns or approved semantic levels
- table/column references must exist
- metric expressions must parse and validate
- join restrictions must reference real joins
- chart preferences must reference real dimensions or metrics

If something cannot be validated:

- persist it as pending or advisory
- do not apply it blindly

### Current Backend Rollout: Auto-Approval First

For the first backend implementation, valid refinement artifacts are auto-approved after deterministic validation.

Manual approval/rejection is intentionally deferred to a later product slice.

Current behavior:

- raw refinement input is persisted
- structured artifacts are extracted
- artifacts that pass deterministic validation are marked `auto_approved`
- invalid artifacts remain pending or invalid
- semantic state can be rebuilt immediately from `auto_approved` artifacts
- selective propagation jobs are queued from auto-approved artifacts, with refresh actions derived from artifact type
- the propagation runner can rebuild semantic state, apply hierarchy refinements, apply metric refinements, recompute chart interaction metadata, queue dashboard refresh jobs, persist semantic glossary terms, and mark query/workspace/anomaly context refreshes as active-state read-through
- workspace conversation messages can auto-write back likely semantic corrections into the same refinement pipeline before query planning

Later manual approval work should add:

- reviewer-specific approval and rejection endpoints
- semantic diff and impact preview before approval
- approval ownership and audit UI
- stricter approval rules for high-impact changes such as metric formulas, join restrictions, and canonical time rules

### Step 5. Merge and Precedence

Merge the refinement into the approved semantic state.

Suggested precedence:

1. approved explicit user override
2. approved admin/domain override
3. previous approved refinement
4. deployment-time inferred semantics
5. heuristic fallback

### Step 6. Propagation

Only recompute what is affected.

Examples:

- hierarchy change:
  - update business hierarchies
  - update chart interaction metadata
  - update suggested drilldowns

- metric formula change:
  - update metric registry
  - invalidate affected charts
  - refresh affected dashboards

- column description change:
  - update glossary and semantic labels
  - improve chart titles / narratives / conversation references

- business time rule change:
  - update date semantics
  - update growth and forecast logic
  - refresh affected charts

---

## What Should Be Stored

### Option 1. Reuse Existing Tables Only

Possible but not ideal.

You could keep pushing these into:

- context tables
- override tables
- semantic feedback tables

This is workable for a small scope, but becomes hard to reason about as refinement types grow.

### Option 2. Add a Dedicated Refinement Layer

Recommended.

Introduce new storage for structured semantic refinement.

Suggested tables:

#### `quantyx_domain_refinement_inputs`

Raw user/agent-provided refinement submissions.

Fields:

- `refinement_input_id`
- `tenant_id`
- `domain_id`
- `source_type`
- `source_text`
- `source_file_id`
- `submitted_by`
- `submitted_at`
- `status`

#### `quantyx_domain_refinement_artifacts`

Structured extracted refinement artifacts.

Fields:

- `artifact_id`
- `refinement_input_id`
- `artifact_type`
- `artifact_json`
- `validation_status`
- `validation_errors_json`
- `approved`
- `approved_by`
- `approved_at`

#### `quantyx_domain_semantic_state`

Resolved current semantic state snapshot for a domain.

Fields:

- `semantic_state_id`
- `tenant_id`
- `domain_id`
- `version_no`
- `state_json`
- `created_from_artifact_ids`
- `created_at`
- `is_active`

#### `quantyx_semantic_propagation_jobs`

Tracks downstream partial rebuilds triggered by refinements.

Fields:

- `job_id`
- `tenant_id`
- `domain_id`
- `trigger_type`
- `affected_scope_json`
- `status`
- `created_at`
- `completed_at`

---

## Recommended Reuse of Existing Tables

Even with new refinement tables, keep using these existing structures where appropriate:

- existing context storage for raw business context
- existing hierarchy override storage for approved explicit hierarchies
- existing metric registry for approved metrics
- existing semantic feedback store where it already captures correction signals

But add a more unified refinement layer above them so the system has one place to reason about:

- what changed
- what was approved
- what current semantic state is active

---

## How the Knowledge Should Improve the Domain Over Time

### 1. Better Hierarchies

Initial deployment may infer:

- `state -> location -> district`

Later refinement can correct this to:

- `country -> state -> district -> location -> site`

Then:

- chart drilldowns improve
- suggested navigation improves
- conversation drill logic improves

### 2. Better Labels and Narratives

If users describe columns later:

- chart titles improve
- LLM narratives become more business-specific
- conversation answers use business language instead of raw field names

### 3. Better Metric Safety

If users clarify:

- growth rate logic
- exclusions
- null handling
- entity grain

Then:

- planner becomes more accurate
- anomaly and correlation use better semantics
- dashboard quality improves

### 4. Better Query Planning

If users restrict:

- joins
- tables
- preferred dimensions

Then:

- runtime query planning becomes more deterministic
- fewer invalid charts are proposed

---

## Relationship to Agentic Runs

This phase does not replace deployment.
It extends deployment into a refinement lifecycle.

### Initial Run

Produces:

- baseline semantic state

### Later Refinement Run

Produces:

- updated semantic state version
- changed hierarchy artifacts
- changed labels/descriptions
- changed chart guidance
- propagation jobs

### Selective Rebuild

Instead of full redeploy every time, support:

- `refresh_hierarchies`
- `refresh_glossary`
- `refresh_metrics`
- `refresh_chart_interaction_metadata`
- `refresh_affected_dashboards`

---

## API Ideas

### Add refinement input

`POST /semantic/refinements`

Payload examples:

```json
{
  "tenant_id": "ns-1",
  "domain_id": "example_domain",
  "source_type": "text",
  "text": "Use hierarchy country > state > district > location > site"
}
```

### List refinements

`GET /semantic/refinements?tenant_id=...&domain_id=...`

### Approve/reject refinement artifact

`POST /semantic/refinements/{artifact_id}/approve`

### Rebuild semantic state

`POST /semantic/state/rebuild`

### Get current semantic state

`GET /semantic/state?tenant_id=...&domain_id=...`

### Trigger selective propagation

`POST /semantic/propagation`

---

## UI Ideas

### Domain Knowledge Panel

A dedicated workspace area where users can:

- add business context
- define or edit hierarchies
- annotate columns
- override metric meaning
- specify chart guidance

### Semantic Diff View

Show:

- current semantic state
- proposed new changes
- downstream impact

### Impact Preview

Before approval, show:

- affected charts
- affected dashboards
- affected drill paths
- affected metrics

---

## LLM Role in This Phase

The LLM should help with:

- classifying free-text refinements
- extracting structured candidates
- drafting glossary descriptions
- mapping user wording to schema columns
- ranking conflicting candidate interpretations

The LLM should not be the final runtime authority.

Final approval should come from:

- deterministic validation
- explicit approval rules
- or human approval for high-impact changes

---

## Deterministic Validation Examples

### Hierarchy Validation

- every level must resolve to:
  - a real column
  - or an approved semantic alias
- level ordering must avoid duplicates
- base table must be identifiable

### Column Annotation Validation

- referenced table and column must exist
- display label can be free text
- semantic class must be from approved set if provided

### Metric Validation

- referenced columns must exist
- formula must parse safely
- aggregation must match measure eligibility rules

### Rule Validation

- filters and exclusions must reference valid fields
- benchmark or target references must resolve

---

## Propagation Rules

Not every semantic refinement needs a full redeploy.

### No Rebuild Needed

- glossary wording only
- chart narration guidance only

### Partial Rebuild Needed

- hierarchy change
- column label change
- metric description change
- display preference change

### Full or Broad Rebuild Needed

- metric formula change
- join restriction change
- canonical time dimension change
- domain-wide business rule change

---

## Suggested Rollout Plan

### 53A. Refinement Input Capture

Add APIs and storage for new domain refinement inputs.

### 53B. Structured Refinement Extraction

Use LLM + deterministic mapping to convert free text into structured artifacts.

### 53C. Validation and Approval

Validate artifacts and establish approval flow.

### 53D. Resolved Semantic State

Build a domain-level semantic state snapshot that merges deployment artifacts and approved refinements.

### 53E. Selective Propagation

Refresh only affected hierarchies, metrics, chart metadata, and dashboards.

Current backend rollout:

- `quantyx_semantic_propagation_jobs` is available for queued propagation work
- `POST /semantic/propagation` can queue a manual propagation job
- `GET /semantic/propagation` lists queued propagation jobs
- `POST /semantic/propagation/{job_id}/run` runs queued propagation best-effort
- auto-approved refinements enqueue propagation jobs after processing
- artifact types are mapped to refresh actions such as `refresh_hierarchies`, `refresh_metrics`, `refresh_chart_interaction_metadata`, `refresh_query_planner_constraints`, and `refresh_affected_dashboards`
- the runner can rebuild semantic state, apply hierarchy refinements into hierarchy override/business hierarchy stores, apply metric refinements into the metric registry, recompute chart interaction metadata, and queue dashboard refresh jobs
- `refresh_query_planner_constraints` is implemented as active semantic-state read-through; query planning filters restricted joins and merges refined glossary terms at runtime
- `refresh_workspace_semantics` is implemented as active semantic-state read-through for workspace conversations
- `refresh_glossary` and `refresh_chart_labels` persist refined glossary terms from approved column annotations
- `refresh_anomaly_correlation_context` is implemented as active semantic-state read-through; correlation narration receives interpretation rules, metric refinements, chart guidance, and business context

### 53F. Conversation-Driven Semantic Correction

Allow conversation feedback like:

- "that hierarchy is wrong"
- "use the business identifier instead of the internal identifier"
- "this metric should be month-over-month"

and route it into the refinement pipeline.

Current backend rollout:

- workspace user messages are screened for likely semantic corrections
- inferred correction kinds are submitted as `source_type = conversation`
- valid extracted artifacts are auto-approved, semantic state is rebuilt, and propagation jobs are enqueued
- manual review, impact preview, and explicit approve/reject endpoints remain deferred

## End-to-End API Test Flow for UI Integration

This flow assumes the initial agentic deployment has already completed for a tenant/domain, for example after running the demo workspace deployment such as `demo_workspace_deployment_lpg`.

Use these placeholders in the examples:

- `BASE_URL=http://localhost:8000`
- `TENANT_ID=VC_101`
- `DOMAIN_ID=lpg_production_distribution`
- `RUN_ID=<completed_agentic_run_id>`
- `CONNECTION_ID=<optional_connection_id>`
- `DATABASE_NAME=<optional_database_name>`
- `SCHEMA_NAME=<optional_schema_name>`

The connection/database/schema values are optional for most UI calls. If omitted, the backend resolves the active deployment scope for the tenant/domain.

Recommended UI contract: the UI should not ask the user to select `refinement_kind`, and it should not construct the lower-level semantic refinement payload for simple text input. The UI should send only:

- the text the user entered
- the user-facing intent/type, for example `semantics`
- tenant/domain/conversation/run identifiers already available in the workspace

The backend should own classification, structured artifact extraction, validation, auto-approval, semantic-state rebuild, and propagation.

The lower-level `POST /semantic/refinements` API remains useful for admin/debug tooling and structured imports. For that API, `refinement_kind` can be sent as `auto`; the backend derives the concrete kind from text or structured payload and persists the resolved value. Advanced/admin callers may still send an explicit kind when they know it.

Backend inference currently maps:

- hierarchy/drill path language to `hierarchy`
- metric/KPI/formula/growth language to `metric_refinement`
- field/column/means/represents/label language to `column_annotation`
- do-not-join/exclude/filter language to `join_rule`
- anomaly/correlation/significant/alert/expected/ignore language to `interpretation_rule`
- chart/dashboard/trend/forecast/ranking language to `chart_guidance`
- context question payloads with `question_id`, `answer_text`, or `maps_to` to `context_question_answer`
- everything else to `business_context`

### Recommended Wrapper API for UI

Add a UI-facing wrapper endpoint:

```http
POST /semantic/intake
```

Request:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "type": "semantics",
  "text": "Growth rate should use prior month as the baseline and should be evaluated monthly.",
  "conversation_id": "conv_...",
  "source_run_id": "<completed_agentic_run_id>",
  "submitted_by": "ui:user"
}
```

Minimal required fields:

- `tenant_id`
- `type`
- `text`

Optional fields:

- `domain_id`
- `conversation_id`
- `source_run_id`
- `submitted_by`
- `connection_id`
- `database_name`
- `schema_name`

Backend behavior:

1. Validate `type == "semantics"`.
2. Resolve `domain_id` from tenant/domain context if omitted.
3. Resolve connection/database/schema from the active deployment scope if omitted.
4. Use deterministic classification first to infer the candidate `refinement_kind`.
5. Optionally call the LLM extractor to produce one or more structured artifacts from the user text.
6. Fall back to deterministic extraction when the LLM is unavailable or disabled.
7. Create the lower-level refinement input using:
   - `source_type = "text"` or `source_type = "conversation"` when `conversation_id` is present
   - `refinement_kind = <inferred_kind>`
   - `text = <user text>`
   - `auto_process = true`
   - `rebuild_state = true`
8. Validate extracted artifacts against schema/metric/join context where possible.
9. Mark valid artifacts as `auto_approved`.
10. Rebuild active semantic state.
11. Queue semantic propagation jobs from the approved artifact types.
12. Return a UI-friendly summary.

Suggested response:

```json
{
  "status": "processed",
  "type": "semantics",
  "inferred_refinement_kind": "metric_refinement",
  "refinement_input_id": "ref_...",
  "semantic_state_id": "sem_state_...",
  "artifacts": [
    {
      "artifact_id": "ref_art_...",
      "artifact_type": "metric_refinement",
      "validation_status": "valid",
      "approval_status": "auto_approved",
      "summary": "Growth rate uses prior month as monthly baseline"
    }
  ],
  "propagation_jobs": [
    {
      "job_id": "semprop_...",
      "status": "queued",
      "refresh_actions": [
        "refresh_semantic_state",
        "refresh_metrics",
        "refresh_query_planner_constraints"
      ]
    }
  ]
}
```

Wrapper API implementation options:

- reuse the existing `infer_refinement_kind(...)` helper for first-pass classification
- reuse `create_refinement_input(...)`, `process_refinement_input(...)`, `rebuild_semantic_state(...)`, and `enqueue_semantic_propagation_for_artifacts(...)`
- expose `POST /semantic/intake` as a thin orchestration wrapper rather than duplicating refinement logic
- keep `POST /semantic/refinements` as the lower-level power-user API

LLM role:

- The LLM should not decide whether to apply a change directly.
- The LLM can extract richer structured artifact JSON from text, for example multiple artifacts from one paragraph.
- Deterministic validation still decides whether an artifact can become `auto_approved`.
- If the LLM is disabled or fails, deterministic extraction should still produce a useful fallback artifact where possible.

Example: one UI text input can create multiple artifacts:

```json
{
  "type": "semantics",
  "text": "Growth rate should use prior month as baseline. Field ship_to_id means Ship-To Customer. Do not join orders with customer_reference for KPI calculations."
}
```

Backend may extract:

```json
[
  {
    "artifact_type": "metric_refinement",
    "artifact_json": {
      "metric_name": "growth_rate",
      "formula": "month_over_month_growth",
      "grain": "month"
    }
  },
  {
    "artifact_type": "column_annotation",
    "artifact_json": {
      "column": "ship_to_id",
      "business_label": "Ship-To Customer"
    }
  },
  {
    "artifact_type": "join_rule",
    "artifact_json": {
      "rule_type": "join_restriction",
      "left_table": "orders",
      "right_table": "customer_reference",
      "allowed": false
    }
  }
]
```

UI implication:

- The main user-facing UI should call `POST /semantic/intake`.
- The UI should show returned inferred kind/artifacts as status, not as required user input.
- If validation fails, show `validation_errors_json` and ask the user to clarify in natural language.
- The admin/debug UI may still call `POST /semantic/refinements` directly.

### 1. Confirm Pack Questions for the UI

Use this to render semantic discovery questions for the domain.

```bash
curl -s "$BASE_URL/semantic/context-questions?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID"
```

Expected response shape:

```json
{
  "domain_id": "lpg_production_distribution",
  "question_groups": [
    {
      "group_id": "dashboard_objectives",
      "title": "Dashboard Objectives",
      "questions": []
    }
  ]
}
```

UI behavior:

- show the returned question groups as optional post-run context capture
- submit each free-text answer through `POST /semantic/intake` with `type=semantics`
- use `POST /semantic/refinements` only for admin/debug flows that intentionally send structured payloads
- backend keeps `auto_process=true` and `rebuild_state=true` internally for the current auto-approval path

### 2. Submit Direct Semantic Refinement Text

Use this lower-level API for admin/debug tooling. The main UI should prefer the wrapper `POST /semantic/intake` so it can send only user text plus `type=semantics`.

```bash
curl -s -X POST "$BASE_URL/semantic/refinements" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "source_type": "text",
    "refinement_kind": "auto",
    "text": "Growth rate should use prior month as the baseline and should be evaluated at month grain.",
    "source_run_id": "<completed_agentic_run_id>",
    "submitted_by": "ui:user",
    "auto_process": true,
    "rebuild_state": true
  }'
```

Expected response shape:

```json
{
  "refinement_input_id": "ref_...",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "source_type": "text",
  "refinement_kind": "metric_refinement",
  "status": "processed",
  "artifacts": [
    {
      "artifact_id": "ref_art_...",
      "artifact_type": "metric_refinement",
      "validation_status": "valid",
      "approval_status": "auto_approved",
      "artifact_json": {
        "metric_name": "growth_rate",
        "formula": "month_over_month_growth",
        "grain": "month"
      }
    }
  ],
  "semantic_state_id": "sem_state_..."
}
```

Important backend behavior:

- the input is persisted in `quantyx_domain_refinement_inputs`
- structured artifacts are persisted in `quantyx_domain_refinement_artifacts`
- valid artifacts are marked `auto_approved`
- semantic state is rebuilt immediately
- propagation jobs are queued automatically for the affected artifact types

### 3. Submit Structured Context Question Answers

Use this when the UI captures answers from `GET /semantic/context-questions`.

```bash
curl -s -X POST "$BASE_URL/semantic/refinements" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "source_type": "structured",
    "refinement_kind": "auto",
    "payload": {
      "group_id": "hierarchy_and_grain",
      "question_id": "preferred_drill_path",
      "answer_text": "Use hierarchy Zone > Region > Plant for drill downs.",
      "maps_to": ["hierarchy_override"]
    },
    "source_run_id": "<completed_agentic_run_id>",
    "submitted_by": "ui:user",
    "auto_process": true,
    "rebuild_state": true
  }'
```

Expected result:

- a `context_question_answer` artifact is created
- derived artifacts may also be created when the answer can be parsed deterministically, for example `hierarchy_override`
- valid artifacts are auto-approved and included in the active semantic state

### 4. List Refinements and Show Status in the UI

Use this for a refinement history panel.

```bash
curl -s "$BASE_URL/semantic/refinements?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID&include_artifacts=true&limit=50"
```

Useful UI fields:

- `refinement_input_id`
- `source_type`
- `refinement_kind`
- `status`
- `conversation_id`
- `artifacts[].artifact_type`
- `artifacts[].validation_status`
- `artifacts[].approval_status`
- `semantic_state_id`

Current approval behavior:

- valid artifacts should show `approval_status=auto_approved`
- invalid artifacts should show validation errors and must not be treated as active
- explicit approve/reject buttons should remain hidden or disabled until the later approval workflow is implemented

### 5. Fetch the Active Semantic State

Use this to verify the backend has merged the new refinement into the active semantic state.

```bash
curl -s "$BASE_URL/semantic/state?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID"
```

Expected response shape:

```json
{
  "semantic_state_id": "sem_state_...",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "version_no": 3,
  "is_active": true,
  "state_json": {
    "summary": {
      "approved_refinement_artifact_count": 2
    },
    "refinements": {
      "hierarchies": [],
      "metric_overrides": [],
      "column_annotations": [],
      "join_rules": [],
      "interpretation_rules": []
    }
  },
  "created_from_artifact_ids": ["ref_art_..."]
}
```

UI behavior:

- use this as a read-only diagnostic or admin detail view
- do not ask the user to manually activate anything in the current auto-approval path

### 6. Check Queued Propagation Jobs

After submitting refinements, the backend queues propagation jobs automatically.

```bash
curl -s "$BASE_URL/semantic/propagation?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID&limit=20"
```

Expected response shape:

```json
{
  "jobs": [
    {
      "job_id": "semprop_...",
      "tenant_id": "VC_101",
      "domain_id": "lpg_production_distribution",
      "trigger_type": "refinement_auto_approved",
      "status": "queued",
      "affected_scope_json": {
        "artifact_ids": ["ref_art_..."],
        "artifact_types": ["metric_refinement"],
        "refresh_actions": [
          "refresh_semantic_state",
          "refresh_metrics",
          "refresh_query_planner_constraints"
        ],
        "affected_metrics": ["growth_rate"]
      }
    }
  ]
}
```

UI behavior:

- show queued/running/completed propagation status in an admin/debug panel if useful
- the normal user flow does not need to manually run jobs unless you are testing the runner from the UI

### 7. Run a Propagation Job Manually for Testing

Use this during UI/backend testing to force a queued propagation job to execute.

```bash
curl -s -X POST "$BASE_URL/semantic/propagation/<job_id>/run?tenant_id=$TENANT_ID"
```

Expected response shape:

```json
{
  "job_id": "semprop_...",
  "status": "completed",
  "affected_scope_json": {
    "action_results": [
      {
        "action": "refresh_semantic_state",
        "status": "completed",
        "semantic_state_id": "sem_state_..."
      },
      {
        "action": "refresh_metrics",
        "status": "completed"
      },
      {
        "action": "refresh_query_planner_constraints",
        "status": "completed",
        "mode": "active_semantic_state_read_through"
      }
    ]
  }
}
```

Current action behavior:

- `refresh_hierarchies` writes approved hierarchy refinements into hierarchy override/business hierarchy stores
- `refresh_metrics` writes approved metric refinements into the metric registry
- `refresh_chart_interaction_metadata` recomputes chart interaction metadata
- `refresh_affected_dashboards` queues dashboard refresh jobs
- `refresh_query_planner_constraints` is read-through from active semantic state
- `refresh_workspace_semantics` is read-through from active semantic state
- `refresh_glossary` and `refresh_chart_labels` persist refined glossary terms
- `refresh_anomaly_correlation_context` is read-through from active semantic state

### 8. Create a Workspace Conversation After the Agentic Run

Use this when the UI opens a conversational workspace for the completed deployment.

```bash
curl -s -X POST "$BASE_URL/workspace/conversations" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "title": "LPG semantic refinement test",
    "created_by": "ui:user"
  }'
```

Expected response shape:

```json
{
  "conversation_id": "conv_...",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "run_id": "<completed_agentic_run_id>",
  "title": "LPG semantic refinement test",
  "status": "active"
}
```

If the response is `409`, the tenant/domain either has no completed deployment or the required deployment intelligence artifacts are incomplete.

### 9. Send a Normal Workspace Message

Use this to verify existing conversation behavior still works with active semantic state read-through.

```bash
curl -s -X POST "$BASE_URL/workspace/conversations/<conversation_id>/messages" \
  -H "Content-Type: application/json" \
  -d '{
    "user_query": "Show production trend by plant for the last 30 days",
    "resume_context": true,
    "stream": false
  }'
```

Expected response shape:

```json
{
  "conversation_id": "conv_...",
  "message_id": "msg_...",
  "response": {
    "chart_type": "line",
    "chart_title": "Production Trend by Plant",
    "sql": "SELECT ..."
  },
  "context_used": {
    "resume_context": true,
    "run_id": "<completed_agentic_run_id>"
  }
}
```

Runtime behavior:

- active semantic state is loaded for this tenant/domain/scope
- refined glossary terms are merged into query planning
- restricted joins from approved `join_rule` artifacts are removed from join candidates

### 10. Send a Conversation Correction and Let It Auto-Write Back

Use this when the user gives more context after the initial agentic run has completed.

```bash
curl -s -X POST "$BASE_URL/workspace/conversations/<conversation_id>/messages" \
  -H "Content-Type: application/json" \
  -d '{
    "user_query": "Actually growth rate should use prior month as the baseline and should be evaluated monthly.",
    "resume_context": true,
    "stream": false
  }'
```

Backend behavior:

- the message is screened for correction markers such as `actually`, `should use`, `instead of`, `do not`, `prefer`, `means`, or `represents`
- the backend infers a `refinement_kind`, for example `metric_refinement`
- the message is submitted as `source_type=conversation`
- valid artifacts are `auto_approved`
- semantic state is rebuilt before the workspace query path continues
- propagation jobs are enqueued for downstream refreshes

Then verify the writeback:

```bash
curl -s "$BASE_URL/semantic/refinements?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID&include_artifacts=true&limit=10"
```

Look for:

```json
{
  "source_type": "conversation",
  "refinement_kind": "metric_refinement",
  "conversation_id": "conv_...",
  "artifacts": [
    {
      "validation_status": "valid",
      "approval_status": "auto_approved"
    }
  ]
}
```

### 11. Test Join Rule Writeback

Use this to verify query planner constraints.

```bash
curl -s -X POST "$BASE_URL/workspace/conversations/<conversation_id>/messages" \
  -H "Content-Type: application/json" \
  -d '{
    "user_query": "Actually do not join orders with customer_reference for KPI calculations.",
    "resume_context": true,
    "stream": false
  }'
```

Then verify:

```bash
curl -s "$BASE_URL/semantic/state?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID"
```

Look under:

```json
{
  "state_json": {
    "refinements": {
      "join_rules": [
        {
          "artifact_json": {
            "rule_type": "join_restriction",
            "left_table": "orders",
            "right_table": "customer_reference",
            "allowed": false
          }
        }
      ]
    }
  }
}
```

After this, normal query/workspace APIs should load the active semantic state and remove that restricted join pair from candidate joins.

### 12. Test Glossary / Label Refresh

Use this when the user says what a field means.

```bash
curl -s -X POST "$BASE_URL/semantic/refinements" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "source_type": "text",
    "refinement_kind": "auto",
    "text": "Field ship_to_id means Ship-To Customer and should be shown as a business identifier.",
    "source_run_id": "<completed_agentic_run_id>",
    "submitted_by": "ui:user",
    "auto_process": true,
    "rebuild_state": true
  }'
```

Then run the queued propagation job, or create a manual one:

```bash
curl -s -X POST "$BASE_URL/semantic/propagation" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "trigger_type": "manual_glossary_refresh",
    "affected_scope": {
      "artifact_ids": [],
      "artifact_types": ["column_annotation"],
      "refresh_actions": ["refresh_glossary", "refresh_chart_labels"],
      "affected_columns": ["ship_to_id"],
      "affected_tables": [],
      "affected_metrics": [],
      "impact_level": "targeted"
    }
  }'
```

Run the returned `job_id`:

```bash
curl -s -X POST "$BASE_URL/semantic/propagation/<job_id>/run?tenant_id=$TENANT_ID"
```

Expected action result:

```json
{
  "action": "refresh_glossary",
  "status": "completed",
  "applied_term_count": 1
}
```

### 13. Test Anomaly / Correlation Context

Submit an interpretation rule:

```bash
curl -s -X POST "$BASE_URL/semantic/refinements" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "source_type": "text",
    "refinement_kind": "auto",
    "text": "Ignore planned weekend shutdown dips when interpreting anomalies.",
    "source_run_id": "<completed_agentic_run_id>",
    "submitted_by": "ui:user",
    "auto_process": true,
    "rebuild_state": true
  }'
```

Then queue a manual read-through refresh for test visibility:

```bash
curl -s -X POST "$BASE_URL/semantic/propagation" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "trigger_type": "manual_anomaly_context_refresh",
    "affected_scope": {
      "artifact_ids": [],
      "artifact_types": ["interpretation_rule"],
      "refresh_actions": ["refresh_anomaly_correlation_context"],
      "affected_columns": [],
      "affected_tables": [],
      "affected_metrics": [],
      "impact_level": "targeted"
    }
  }'
```

Run the returned job:

```bash
curl -s -X POST "$BASE_URL/semantic/propagation/<job_id>/run?tenant_id=$TENANT_ID"
```

Expected action result:

```json
{
  "action": "refresh_anomaly_correlation_context",
  "status": "completed",
  "mode": "active_semantic_state_read_through",
  "interpretation_rule_count": 1
}
```

When correlation runs execute, the backend loads active semantic state and passes interpretation rules, metric refinements, chart guidance, and business context into correlation narration.

### 14. UI Integration Sequence

Recommended UI sequence after the initial agentic run completes:

1. Create or open the workspace conversation for the completed deployment.
2. Load `GET /semantic/context-questions` and optionally render a "Improve semantics" panel.
3. When the user submits semantic context text, call `POST /semantic/intake` with `type=semantics` and the raw text.
4. Show refinement history from `GET /semantic/refinements`.
5. Show active state/debug information from `GET /semantic/state` only in an admin or developer panel.
6. For normal chat, call `POST /workspace/conversations/{conversation_id}/messages`.
7. If the message is a correction, the backend auto-writes it to refinements; the UI does not need a separate writeback call.
8. Poll `GET /semantic/propagation` if the UI wants to show downstream refresh status.
9. For testing only, call `POST /semantic/propagation/{job_id}/run` to force queued jobs to execute.

### 15. What the UI Should Not Build Yet

Do not build these as active controls yet:

- manual approve/reject buttons
- semantic diff approval screens
- high-impact approval ownership workflow
- conflict resolution UI

For now, show them as "planned" or hide them. The backend path is intentionally auto-approval after validation.

### 53G. Semantic Diff and Audit UI

Show what changed, why, and how it affects downstream analytics.

---

## Implementation-First Breakdown

The best first implementation slice is:

1. refinement input APIs
2. structured refinement artifact storage
3. semantic state snapshot model

This gives the platform a durable refinement backbone before propagation and UI diffing are added.

---

## Phase 53.1: Refinement Input APIs

### Objective

Create a standard way for users and later agents to submit post-deployment semantic improvements.

This should support:

- plain text context additions
- explicit hierarchy submissions
- column description submissions
- metric refinement submissions
- rule and guidance submissions

### Why Start Here

Without a formal input contract, later semantic knowledge has nowhere consistent to land.
The system needs one ingestion point before it can classify, validate, or propagate anything.

### API Surface

#### `POST /semantic/refinements`

Creates a refinement input submission.

Example payload:

```json
{
  "tenant_id": "ns-1",
  "domain_id": "example_domain",
  "source_type": "text",
  "refinement_kind": "business_context",
  "text": "Use hierarchy country > state > district > location > site"
}
```

Example explicit hierarchy payload:

```json
{
  "tenant_id": "ns-1",
  "domain_id": "example_domain",
  "source_type": "structured",
  "refinement_kind": "hierarchy",
  "payload": {
    "name": "Primary Geography",
    "levels": ["country", "state", "district", "location", "site"]
  }
}
```

#### `GET /semantic/refinements`

List refinement submissions for a tenant/domain with filters:

- `status`
- `refinement_kind`
- `submitted_by`
- `limit`

#### `GET /semantic/refinements/{refinement_input_id}`

Returns one submission plus extracted artifacts if already processed.

#### `POST /semantic/refinements/{refinement_input_id}/process`

Triggers structured extraction and validation.

This may later be automatic, but an explicit API helps with testing and observability.

### Initial Request Model

Suggested fields:

- `tenant_id`
- `domain_id`
- `source_type`
  - `text`
  - `structured`
  - `conversation`
  - `file`
- `refinement_kind`
  - `business_context`
  - `hierarchy`
  - `column_annotation`
  - `metric_refinement`
  - `join_rule`
  - `chart_guidance`
  - `interpretation_rule`
- `text`
- `payload`
- `source_context_id`
- `conversation_id`
- `submitted_by`

### Validation Rules

At input stage, validation should be shallow:

- `tenant_id` required
- `domain_id` required
- `source_type` required
- at least one of `text` or `payload` required
- `refinement_kind` must be from approved enum

Do not do heavy semantic validation here.
That belongs in artifact extraction and approval.

### Storage for 53.1

Add table:

#### `quantyx_domain_refinement_inputs`

Suggested columns:

- `refinement_input_id text primary key`
- `tenant_id text not null`
- `domain_id text not null`
- `source_type text not null`
- `refinement_kind text not null`
- `source_text text null`
- `source_payload_json jsonb null`
- `source_context_id text null`
- `source_file_id text null`
- `conversation_id text null`
- `submitted_by text null`
- `status text not null default 'submitted'`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

### Immediate Deliverables

- new store file, for example:
  - `services/ai/domain_refinement_store.py`
- API endpoints in:
  - [main.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/api/main.py)
- request/response schemas in:
  - [schemas.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/api/schemas.py)

### Success Criteria for 53.1

- user can submit refinement input after deployment
- input is persisted durably
- input can be listed and inspected later
- input has status lifecycle support

---

## Phase 53.2: Structured Refinement Artifact Storage

### Objective

Convert raw refinement input into structured, typed semantic artifacts that can be validated and merged.

### Why This Is Separate

Raw input should not directly alter semantic behavior.
The system should first extract explicit artifacts, such as:

- hierarchy proposal
- column annotation
- metric rule
- join restriction
- chart guidance

### Extraction Model

Refinement extraction can be:

- deterministic for structured payloads
- LLM-assisted for free text

But the output must always be structured.

### Example Artifact Shapes

#### Hierarchy Artifact

```json
{
  "artifact_type": "hierarchy_override",
  "artifact_json": {
    "name": "Primary Geography",
    "levels": ["country", "state", "district", "location", "site"],
    "preferred": true
  }
}
```

#### Column Annotation Artifact

```json
{
  "artifact_type": "column_annotation",
  "artifact_json": {
    "table": "fact_transactions",
    "column": "business_entity_id",
    "business_label": "Business Entity Code",
    "description": "Business-facing identifier used for entity-level drill",
    "display_priority": "high"
  }
}
```

#### Metric Refinement Artifact

```json
{
  "artifact_type": "metric_refinement",
  "artifact_json": {
    "metric_name": "period_growth_rate",
    "formula": "month_over_month_growth",
    "grain": "month",
    "time_column": "event_date"
  }
}
```

### Storage for 53.2

Add table:

#### `quantyx_domain_refinement_artifacts`

Suggested columns:

- `artifact_id text primary key`
- `refinement_input_id text not null`
- `tenant_id text not null`
- `domain_id text not null`
- `artifact_type text not null`
- `artifact_json jsonb not null`
- `validation_status text not null default 'pending'`
- `validation_errors_json jsonb null`
- `approval_status text not null default 'pending'`
- `approved_by text null`
- `approved_at timestamptz null`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

### Artifact Extraction Service

Recommended new module:

- `services/ai/domain_refinement_extractor.py`

Responsibilities:

- read `quantyx_domain_refinement_inputs`
- classify or trust `refinement_kind`
- produce one or more structured artifacts
- persist them into `quantyx_domain_refinement_artifacts`

### Deterministic Validation in 53.2

At this stage, validation should ensure the artifact is structurally well-formed.

Examples:

- hierarchy levels list is non-empty
- referenced table/column fields are strings
- metric refinement contains a metric target

Do not yet merge into active semantic state until approval and state build.

### Success Criteria for 53.2

- one raw refinement input can produce structured artifacts
- artifacts are typed and queryable
- artifacts retain linkage to their original submission
- artifacts can be marked pending/approved/rejected

---

## Phase 53.3: Semantic State Snapshot Model

### Objective

Create a single resolved semantic state snapshot per tenant/domain version that downstream systems can trust.

This state should merge:

- deployment-time semantic artifacts
- approved refinement artifacts
- precedence rules

### Why This Matters

Without a resolved semantic state, downstream consumers would need to merge:

- schema artifacts
- hierarchy overrides
- context refinements
- metric corrections
- glossary updates

on every read.

That becomes slow and inconsistent.

Instead, build one current approved state and let downstream systems read from that.

### Suggested Storage

Add table:

#### `quantyx_domain_semantic_state`

Suggested columns:

- `semantic_state_id text primary key`
- `tenant_id text not null`
- `domain_id text not null`
- `version_no integer not null`
- `state_json jsonb not null`
- `created_from_artifact_ids jsonb not null default '[]'::jsonb`
- `trigger_type text not null`
- `created_at timestamptz not null default now()`
- `is_active boolean not null default true`

### Suggested `state_json` Structure

```json
{
  "hierarchies": [],
  "column_annotations": [],
  "metric_overrides": [],
  "join_rules": [],
  "chart_guidance": [],
  "business_rules": [],
  "glossary": []
}
```

This should not replace all existing artifact tables.
It should be the resolved read model for downstream consumers.

### State Builder

Recommended new module:

- `services/ai/domain_semantic_state_builder.py`

Responsibilities:

1. load latest deployment semantic artifacts
2. load approved refinement artifacts
3. apply precedence rules
4. build `state_json`
5. version and persist the new active semantic state

### Precedence Rules

Recommended order:

1. approved explicit refinement artifact
2. approved override table entry
3. active deployment artifact
4. heuristic fallback

### Downstream Consumers That Should Eventually Read This State

- chart interaction metadata binder
- hierarchy suggestion builder
- workspace conversation semantics loader
- metric resolution
- anomaly/correlation contextual narrators
- future refinement diff UI

### Success Criteria for 53.3

- a domain can have a current semantic state snapshot
- the state is versioned
- it records which artifacts created it
- downstream systems can be migrated to read from it incrementally

---

## Recommended First Delivery Order

The best implementation order is:

### Step 1

Add:

- `quantyx_domain_refinement_inputs`
- `POST /semantic/refinements`
- `GET /semantic/refinements`
- `GET /semantic/refinements/{id}`

### Step 2

Add:

- `quantyx_domain_refinement_artifacts`
- artifact extraction service
- `POST /semantic/refinements/{id}/process`

### Step 3

Add:

- `quantyx_domain_semantic_state`
- semantic state builder
- `GET /semantic/state`
- `POST /semantic/state/rebuild`

Only after these three should we implement:

- selective propagation jobs
- semantic diff UI
- conversation-driven semantic correction writeback

Current status: selective propagation jobs and conversation-driven semantic correction writeback are implemented for the auto-approval backend path. Semantic diff UI remains later work.

---

## Concrete Backend Files Likely Needed

### New

- `services/ai/domain_refinement_store.py`
- `services/ai/domain_refinement_extractor.py`
- `services/ai/domain_semantic_state_builder.py`

### Existing files to extend

- [main.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/api/main.py)
- [schemas.py](/Users/vnagaraju/PycharmProjects/quantyx-core/services/api/schemas.py)
- existing artifact consumers later, such as:
  - hierarchy store
  - chart interaction builder
  - workspace semantic loader

---

## Risks

### 1. Semantic Drift

Too many unreviewed refinements can make semantics inconsistent.

Mitigation:

- approval flow
- versioned semantic state
- audit trail

### 2. Over-Application

A local refinement might unexpectedly affect too many dashboards.

Mitigation:

- impact preview
- selective propagation

### 3. Runtime Instability

If refinements are applied directly without validation, runtime query planning may break.

Mitigation:

- deterministic validation before activation

### 4. Conflicting Knowledge

Two users may define different hierarchy meanings.

Mitigation:

- precedence rules
- explicit approval ownership
- active semantic state versioning

---

## Success Criteria

This phase is complete when:

1. users can add business context after deployment
2. the system can classify and extract structured semantic refinements
3. refinements are validated and versioned
4. approved refinements improve current semantic state
5. affected hierarchies, metrics, labels, and chart metadata can be selectively refreshed
6. runtime querying and drill behavior continue to use deterministic approved semantics
7. the domain becomes measurably more accurate over time without requiring full manual rebuilds

---

## Relationship to Existing Phases

- Phase 24 provides tenant/domain deployment lifecycle
- Phase 34 provides durable agent artifacts
- Phase 36 makes business context a first-class semantic input
- Phase 41 and Phase 52 make chart interaction depend on semantic quality
- This phase extends all of them by turning semantic quality into an ongoing learning and refinement loop
