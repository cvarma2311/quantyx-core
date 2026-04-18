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

### Current Backend Rollout: Auto-Approval Default with Manual Governance APIs

For the first backend implementation, valid refinement artifacts are auto-approved after deterministic validation.

Manual governance APIs are also available for reviewer and admin screens, but the default end-user path remains auto-approval.

Current behavior:

- raw refinement input is persisted
- structured artifacts are extracted
- artifacts that pass deterministic validation are marked `auto_approved`
- invalid artifacts remain pending or invalid
- semantic state can be rebuilt immediately from `auto_approved` artifacts
- selective propagation jobs are queued from auto-approved artifacts, with refresh actions derived from artifact type
- the propagation runner can rebuild semantic state, apply hierarchy refinements, apply metric refinements, recompute chart interaction metadata, queue dashboard refresh jobs, persist semantic glossary terms, and mark query/workspace/anomaly context refreshes as active-state read-through
- workspace conversation messages can auto-write back likely semantic corrections into the same refinement pipeline before query planning
- impact preview, audit timeline, conflict diagnostics, state history, rollback/state activation, and explicit artifact approve/reject APIs are implemented for governance flows

Remaining UI work should add:

- reviewer-facing approval queue screens
- semantic diff and impact preview screens
- audit timeline screens
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
- manual review can use the governance APIs for impact preview, audit, conflict diagnostics, rollback, and artifact approve/reject

## UI Integration Guide

This section is for UI developers and designers. It assumes the initial agentic deployment has completed for a tenant/domain, for example after `demo_workspace_deployment_lpg`.

Use these placeholders in examples:

- `BASE_URL=http://localhost:8000`
- `TENANT_ID=VC_101`
- `DOMAIN_ID=lpg_production_distribution`
- `RUN_ID=<completed_agentic_run_id>`
- `CONVERSATION_ID=<workspace_conversation_id>`
- `SEMANTIC_STATE_ID=<semantic_state_id>`
- `ARTIFACT_ID=<refinement_artifact_id>`

The UI should not ask end users to choose `refinement_kind`. For normal semantic improvement, the UI sends raw text and `type=semantics`; the backend classifies the text, extracts artifacts, validates them, auto-approves valid artifacts, rebuilds semantic state, and queues propagation.

### Section A: Automatic Semantic Intake and Auto-Approval

Use this flow for the main user experience. This is the happy path where a user adds context or correction text and the platform applies valid refinements automatically.

#### A1. Load Semantic Context Questions

Purpose: render optional semantic discovery questions after the agentic run.

```http
GET /semantic/context-questions?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}
```

Example:

```bash
curl -s "$BASE_URL/semantic/context-questions?tenant_id=$TENANT_ID&domain_id=$DOMAIN_ID"
```

Response:

```json
{
  "domain_id": "lpg_production_distribution",
  "question_groups": [
    {
      "group_id": "dashboard_objectives",
      "title": "Dashboard Objectives",
      "questions": [
        {
          "question_id": "primary_kpis",
          "prompt": "What are the most important KPIs this dashboard should track?",
          "answer_type": "text",
          "required": true,
          "maps_to": ["metric_refinement", "chart_guidance"]
        }
      ]
    }
  ]
}
```

UI notes:

- present these as plain business questions
- do not expose artifact names as user choices
- submit free-text answers through `POST /semantic/intake`

#### A2. Submit User Text Through Semantic Intake

Purpose: one simple endpoint for user-provided semantic text.

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
  "source_run_id": "run_...",
  "submitted_by": "ui:user"
}
```

Minimal request:

```json
{
  "tenant_id": "VC_101",
  "type": "semantics",
  "text": "Field ship_to_id means Ship-To Customer."
}
```

Response:

```json
{
  "status": "processed",
  "type": "semantics",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "inferred_refinement_kind": "metric_refinement",
  "refinement_input_id": "ref_...",
  "semantic_state_id": "sem_state_...",
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
      },
      "validation_errors_json": [],
      "summary": "Metric refinement for growth_rate"
    }
  ],
  "propagation_jobs": [
    {
      "job_id": "semprop_...",
      "status": "queued",
      "refresh_actions": [
        "refresh_metrics",
        "refresh_affected_dashboards",
        "refresh_anomaly_correlation_context",
        "refresh_workspace_semantics"
      ],
      "affected_scope_json": {
        "artifact_ids": ["ref_art_..."],
        "artifact_types": ["metric_refinement"],
        "affected_metrics": ["growth_rate"],
        "impact_level": "high"
      }
    }
  ]
}
```

Backend behavior:

1. infers `refinement_kind`
2. extracts one or more structured artifacts
3. validates artifacts
4. marks valid artifacts `auto_approved`
5. rebuilds active semantic state
6. queues propagation jobs
7. returns artifact and job summaries for the UI

UI notes:

- show a lightweight confirmation such as "Semantic update applied"
- show invalid artifacts as clarification prompts, not as system errors
- use `propagation_jobs[].job_id` only for advanced status panels

#### A3. Create or Open Workspace Conversation

Purpose: start the conversational workspace for the completed deployment.

```http
POST /workspace/conversations
```

Request:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "title": "LPG semantic refinement test",
  "created_by": "ui:user"
}
```

Response:

```json
{
  "conversation_id": "conv_...",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "run_id": "run_...",
  "title": "LPG semantic refinement test",
  "status": "active"
}
```

If this returns `409`, the deployment is missing or its required intelligence artifacts are incomplete.

#### A4. Send Normal Workspace Message

Purpose: run a normal conversation query against the active semantic state.

```http
POST /workspace/conversations/{CONVERSATION_ID}/messages
```

Request:

```json
{
  "user_query": "Show production trend by plant for the last 30 days",
  "resume_context": true,
  "stream": false
}
```

Response:

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
    "run_id": "run_..."
  }
}
```

Runtime behavior:

- active semantic state is loaded
- refined glossary terms are merged into planning
- restricted joins from approved `join_rule` artifacts are removed from candidates

#### A5. Conversation Correction Auto-Writeback

Purpose: allow corrections inside chat without a separate UI form.

Request:

```json
{
  "user_query": "Actually growth rate should use prior month as the baseline and should be evaluated monthly.",
  "resume_context": true,
  "stream": false
}
```

Backend behavior:

- detects correction language
- creates a conversation-sourced refinement
- auto-approves valid artifacts
- rebuilds semantic state
- queues propagation
- continues the conversation response

UI notes:

- no separate writeback API call is required
- the UI can confirm the change by calling `GET /semantic/audit` or `GET /semantic/refinements`

#### A6. List Refinements

Purpose: show semantic update history or a developer/admin detail panel.

```http
GET /semantic/refinements?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}&include_artifacts=true&limit=50
```

Response:

```json
{
  "refinements": [
    {
      "refinement_input_id": "ref_...",
      "source_type": "conversation",
      "refinement_kind": "metric_refinement",
      "status": "processed",
      "conversation_id": "conv_...",
      "submitted_by": "ui:user",
      "artifacts": [
        {
          "artifact_id": "ref_art_...",
          "artifact_type": "metric_refinement",
          "validation_status": "valid",
          "approval_status": "auto_approved"
        }
      ]
    }
  ]
}
```

#### A7. Fetch Active Semantic State

Purpose: admin/developer verification of the resolved active state.

```http
GET /semantic/state?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}
```

Response:

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
      "metric_overrides": [],
      "column_annotations": [],
      "join_rules": []
    }
  },
  "created_from_artifact_ids": ["ref_art_..."]
}
```

#### A8. Track Propagation Jobs

Purpose: show downstream refresh status in admin/debug views.

```http
GET /semantic/propagation?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}&limit=20
```

Response:

```json
{
  "jobs": [
    {
      "job_id": "semprop_...",
      "trigger_type": "semantic_intake_auto_approved",
      "status": "queued",
      "affected_scope_json": {
        "artifact_ids": ["ref_art_..."],
        "artifact_types": ["metric_refinement"],
        "refresh_actions": ["refresh_metrics"],
        "impact_level": "high"
      }
    }
  ]
}
```

Optional test-only runner:

```http
POST /semantic/propagation/{job_id}/run?tenant_id={TENANT_ID}
```

Response:

```json
{
  "job_id": "semprop_...",
  "status": "completed",
  "affected_scope_json": {
    "action_results": [
      {
        "action": "refresh_metrics",
        "status": "completed"
      }
    ]
  }
}
```

### Section B: Manual Governance, Approval, Rollback, and Review

Use this flow for admin/reviewer screens. These APIs support reviewability, impact preview, manual approval/rejection, conflict diagnostics, rollback, and audit history.

#### B1. Preview Semantic Impact

Purpose: show what would change before approval or help admins understand an already submitted refinement.

```http
POST /semantic/impact-preview
```

Request with raw text:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "text": "Growth rate should use prior month as the baseline."
}
```

Request with existing refinement:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "refinement_input_id": "ref_..."
}
```

Response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "refinement_input_id": "ref_...",
  "inferred_refinement_kind": "metric_refinement",
  "impact_level": "high",
  "artifact_count": 1,
  "active_semantic_state_id": "sem_state_...",
  "diff_summary": [
    {
      "artifact_id": "ref_art_...",
      "artifact_type": "metric_refinement",
      "change_type": "update_existing",
      "target": "growth_rate",
      "summary": "Refines growth_rate: month_over_month_growth",
      "current_artifact_id": "ref_art_old",
      "artifact_json": {
        "metric_name": "growth_rate",
        "formula": "month_over_month_growth"
      }
    }
  ],
  "affected_scope": {
    "artifact_types": ["metric_refinement"],
    "refresh_actions": [
      "refresh_metrics",
      "refresh_affected_dashboards",
      "refresh_anomaly_correlation_context",
      "refresh_workspace_semantics"
    ],
    "affected_metrics": ["growth_rate"],
    "impact_level": "high"
  }
}
```

Designer notes:

- show `impact_level` prominently
- show `diff_summary` as the review list
- show `affected_scope.refresh_actions` as downstream effects

#### B2. Audit Timeline

Purpose: show a chronological semantic history.

```http
GET /semantic/audit?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}&limit=50
```

Response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "refinements": [],
  "semantic_states": [],
  "propagation_jobs": [],
  "timeline": [
    {
      "event_type": "refinement",
      "event_id": "ref_...",
      "created_at": "2026-04-18T10:00:00",
      "summary": "metric_refinement refinement processed",
      "details": {
        "submitted_by": "ui:user",
        "artifact_count": 1
      }
    }
  ]
}
```

Designer notes:

- use `timeline[]` for the main activity feed
- use `refinements`, `semantic_states`, and `propagation_jobs` for drill-in panels

#### B3. Conflict Diagnostics

Purpose: show competing refinements for the same semantic target.

```http
GET /semantic/conflicts?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}
```

Response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "conflict_count": 1,
  "conflicts": [
    {
      "conflict_key": "metric_refinement:growth_rate",
      "artifact_type": "metric_refinement",
      "severity": "high",
      "artifact_count": 2,
      "artifact_ids": ["ref_art_1", "ref_art_2"],
      "approval_statuses": ["auto_approved", "pending"],
      "summary": "Conflicting metric_refinement artifacts for metric_refinement:growth_rate"
    }
  ]
}
```

Designer notes:

- group conflicts by `severity`
- let reviewers open each artifact from `artifact_ids`
- conflict resolution can use approve/reject endpoints

#### B4. Manual Approve Artifact

Purpose: approve a valid artifact manually.

```http
POST /semantic/refinement-artifacts/{ARTIFACT_ID}/approve
```

Request:

```json
{
  "tenant_id": "VC_101",
  "approved_by": "reviewer:user",
  "reason": "Confirmed by domain owner",
  "rebuild_state": true
}
```

Response:

```json
{
  "artifact_id": "ref_art_...",
  "refinement_input_id": "ref_...",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "artifact_type": "metric_refinement",
  "artifact_json": {
    "metric_name": "growth_rate"
  },
  "validation_status": "valid",
  "validation_errors_json": [],
  "approval_status": "approved",
  "approved_by": "reviewer:user",
  "approved_at": "2026-04-18T10:00:00Z"
}
```

Backend behavior:

- only `validation_status=valid` artifacts can be approved
- state rebuild runs by default
- propagation is queued for the approved artifact

#### B5. Manual Reject Artifact

Purpose: reject a pending, approved, or auto-approved artifact.

```http
POST /semantic/refinement-artifacts/{ARTIFACT_ID}/reject
```

Request:

```json
{
  "tenant_id": "VC_101",
  "approved_by": "reviewer:user",
  "reason": "Metric definition conflicts with finance definition",
  "rebuild_state": true
}
```

Response:

```json
{
  "artifact_id": "ref_art_...",
  "refinement_input_id": "ref_...",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "artifact_type": "metric_refinement",
  "validation_status": "valid",
  "approval_status": "rejected",
  "approved_by": "reviewer:user",
  "approved_at": null
}
```

Backend behavior:

- if the artifact was active, semantic state is rebuilt without it
- no destructive delete occurs

#### B6. Semantic State History

Purpose: support rollback and state comparison screens.

```http
GET /semantic/state/history?tenant_id={TENANT_ID}&domain_id={DOMAIN_ID}&limit=50
```

Response:

```json
[
  {
    "semantic_state_id": "sem_state_3",
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "version_no": 3,
    "is_active": true,
    "trigger_type": "semantic_intake_auto_approved",
    "created_from_artifact_ids": ["ref_art_3"],
    "created_at": "2026-04-18T10:00:00Z"
  },
  {
    "semantic_state_id": "sem_state_2",
    "tenant_id": "VC_101",
    "domain_id": "lpg_production_distribution",
    "version_no": 2,
    "is_active": false
  }
]
```

#### B7. Activate / Roll Back to a Semantic State

Purpose: switch the active semantic state to a prior version.

```http
POST /semantic/state/{SEMANTIC_STATE_ID}/activate
```

Request:

```json
{
  "tenant_id": "VC_101",
  "activated_by": "reviewer:user",
  "reason": "Rollback after incorrect metric refinement"
}
```

Response:

```json
{
  "semantic_state_id": "sem_state_2",
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "version_no": 2,
  "is_active": true,
  "state_json": {},
  "created_from_artifact_ids": ["ref_art_2"]
}
```

Backend behavior:

- rollback is non-destructive
- previous states remain stored
- only one state is active for a tenant/domain/scope

### Recommended UI Screens

#### Automatic Flow Screens

- Post-run semantic question panel
- Simple semantic text input
- Semantic update confirmation
- Optional propagation status drawer
- Workspace conversation surface

#### Manual Governance Screens

- Impact preview screen using `POST /semantic/impact-preview`
- Audit timeline using `GET /semantic/audit`
- Conflict diagnostics using `GET /semantic/conflicts`
- Approval queue using `GET /semantic/refinements`
- Artifact approve/reject actions
- Semantic state history and rollback screen

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

At this implementation slice, do not merge directly into active semantic state until approval and state build are available. In the current backend, valid artifacts can be auto-approved and merged through the semantic state builder, while reviewer screens can use explicit approve/reject APIs.

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

Current status: selective propagation jobs, conversation-driven semantic correction writeback, impact preview, audit timeline, conflict diagnostics, rollback/state activation, and explicit artifact approve/reject APIs are implemented for the backend path. Dedicated semantic diff and governance UI screens remain later work.

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
