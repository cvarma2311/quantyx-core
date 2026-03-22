# Phase 38: Anomaly Investigation and Action Intelligence

## Objective
Add a new LLM-first workflow agent that detects business anomalies, investigates the strongest explanatory areas in the data, produces multiple ranked why-hypotheses with evidence and confidence, and generates both descriptive and prescriptive action insights for analysts.

This agent should help users answer questions such as:
- why did production drop yesterday?
- why is productivity underperforming in a plant or zone?
- what changed materially versus the normal baseline?
- what should the analyst inspect next?

The goal is not only anomaly detection. The goal is anomaly investigation, driver explanation, and action-oriented insight generation over both validated semantic KPIs and approved raw operational columns.

---

## Problem

Current agentic workflow is strong at:
- semantic understanding
- KPI generation
- chart generation
- dashboard composition
- workspace conversation persistence

But it still lacks a first-class investigative agent that answers:
- what is abnormal?
- where is the abnormality concentrated?
- which slices of data best explain it?
- what are the strongest likely drivers?
- what operational follow-up actions should be taken?

Today this leaves a gap between:
- semantic analytics outputs
and
- analyst-grade diagnostic reasoning

As a result:
- dashboards can show performance movement without explaining why
- users must manually explore many slices to identify likely causes
- action suggestions are not persisted as reusable investigation artifacts

---

## Target State
1. A dedicated `AnomalyInvestigationAgent` runs as part of the agentic workflow.
2. The agent detects meaningful business anomalies across performance, productivity, production, utilization, quality, and operational metrics.
3. The agent can investigate using both:
   - validated KPI metrics
   - approved raw columns from scoped tables
4. The agent identifies high-signal investigative areas such as:
   - plants
   - zones
   - regions
   - products
   - process or equipment slices where available
   - unusual time windows
5. The agent produces multiple ranked why-hypotheses with confidence, evidence, and next-step validation guidance.
6. The agent generates both:
   - descriptive insights
   - prescriptive actions
7. Investigation artifacts are persisted and reusable in workspace conversations, dashboards, and follow-up analysis.

---

## Core Principles

### 1) LLM-First, Evidence-Grounded
This agent should be LLM-first.

That means the first layer of intelligence should come from a well-prompted agent task that is given:
- anomaly candidates
- dashboard context
- semantic metric context
- raw operational evidence
- high-signal investigative areas
- business context text
- ontology and hierarchy hints

The LLM should be the primary layer for:
- deciding what is important
- selecting promising investigative paths
- synthesizing mixed evidence
- drafting ranked hypotheses
- generating descriptive insight
- generating prescriptive actions
- proposing anomaly-dashboard content

Deterministic logic should still exist, but as a support layer for:
- anomaly candidate generation
- evidence extraction
- slice ranking
- validation
- confidence calibration
- persistence safety

So the architecture is not:
- deterministic first, LLM later

It is:
- LLM first for investigation reasoning
- deterministic second for grounding and validation

Even in cases where deterministic anomaly candidates are generated before the LLM step, those should be treated as evidence inputs to the LLM agent rather than the primary reasoning system.

The agent must remain grounded in deterministic evidence from:
- metric time-series
- baseline comparisons
- peer comparisons
- dimensional decomposition
- raw operational columns
- anomaly history

### 2) Raw Data Is Allowed but Guarded
The agent may analyze raw columns in addition to KPI metrics, but:
- raw identifiers and codes must not be treated as causal measures
- explanations must cite actual evidence artifacts
- unsupported causal claims must be avoided
- all findings must remain scoped to approved tenant/domain data

### 3) Multiple Hypotheses, Not Single-Cause Certainty
The agent should return multiple competing explanations with confidence rather than pretending to know one definitive root cause when data only supports probabilistic reasoning.

### 4) Persist Investigation Artifacts
Anomaly investigations should become durable semantic intelligence assets, not transient text.

---

## Scope

### In scope
- anomaly detection on business KPIs and selected operational raw fields
- ranking anomalies by business severity and confidence
- identification of high-signal investigative areas
- driver and contribution analysis
- peer and baseline comparison
- ranked why-hypothesis generation
- descriptive and prescriptive insight generation
- persistence of investigation artifacts in workspace scope
- reuse of investigation artifacts in workspace chat and dashboards

### Out of scope
- full causal inference or scientific proof of causality
- automatic workflow execution of operational actions
- unrestricted analysis over every raw column without eligibility rules
- replacing the main deterministic query planner

---

## User Stories
- As an analyst, I want to know why production, productivity, or performance changed materially so I can investigate faster.
- As an operations manager, I want anomalies prioritized by business severity and supported with clear evidence.
- As a business user, I want multiple likely explanations instead of a shallow single-line narrative.
- As a workspace user, I want anomaly investigations and action suggestions to be persisted and reusable in later conversations.

---

## Agent Responsibilities

The new agent should perform five responsibilities:

### 1) Detect
Detect candidate anomalies across:
- KPI time-series
- target vs actual gaps
- peer-relative underperformance
- abnormal raw operational shifts
- contradictory signal patterns such as:
  - production down with downtime up
  - output flat with productivity down
  - rejection rate up while net hours remain stable

### 2) Localize
Identify where the anomaly is concentrated across:
- time
- hierarchy levels
- major dimensions
- raw operational segments

### 3) Investigate
Analyze the strongest explanatory slices and evidence-rich areas using:
- metric decomposition
- delta contribution analysis
- baseline comparisons
- peer comparisons
- co-movement and supporting signal checks
- prior anomaly pattern matches when available

### 4) Explain
Generate multiple ranked why-hypotheses with:
- explanation text
- confidence
- evidence summary
- impacted scope
- suggested validation step

### 5) Recommend
Generate:
- descriptive insight
- prescriptive next actions
- follow-up investigative questions
- suggested supporting charts or queries

---

## Workflow Placement

Recommended workflow insertion:
- after `DashboardAgent`
- after the primary operational dashboard is composed
- using KPI, chart, and dashboard artifacts already produced by the workflow
- reusable later during dashboard refresh and workspace why-analysis

Suggested run order:
1. `MetricAgent`
2. `ChartAgent`
3. `DashboardAgent`
4. `AnomalyInvestigationAgent`
5. `AnomalyDashboardAgent`
6. `Insight/Workspace persistence`

Reason:
- the anomaly agent should investigate over the final KPI, chart, and dashboard outputs instead of shaping them too early
- the main operational dashboard should remain the primary business dashboard
- anomaly investigation should generate a second, analyst-oriented anomaly dashboard focused on diagnosis and actions

### Trigger Contract
The default trigger for this phase should be:
- automatic execution inside the post-dashboard stage of the canonical `/agentic run`

Initial required behavior:
- deployment-time anomaly investigation runs automatically after the primary dashboard is completed
- anomaly artifacts are attached to the same `run_id`
- anomaly dashboard generation happens inside the same run when sufficient evidence exists

Secondary trigger modes should remain supported by architecture, but can be implemented later:
- dashboard refresh triggered anomaly investigation
- targeted workspace why-analysis
- explicit user-triggered anomaly re-investigation

For the initial phase, the source of truth should be:
- the anomaly flow is part of the same agentic run lifecycle as dashboard generation

### Agent Stage Names
The workflow should use stable stage names so UI and APIs can depend on them:
- `AnomalyDetectionAgent`
- `AnomalyDashboardAgent`

Recommended semantic interpretation:
- `AnomalyDetectionAgent` includes:
  - anomaly evidence assembly
  - LLM-first anomaly prioritization
  - LLM-guided evidence querying
  - LLM synthesis of hypotheses/actions/insights
- `AnomalyDashboardAgent` includes:
  - anomaly dashboard JSON composition
  - anomaly evidence chart creation
  - anomaly dashboard persistence and linking

---

## Inputs

The agent should consume:
- tenant/domain scope
- canonical deployment run context
- schema graph
- profiling summary
- validated KPI metrics
- approved raw columns from scoped tables
- ontology and hierarchy metadata
- context text and domain pack hints
- primary dashboard and chart artifacts from the completed workflow
- optional analyst question for targeted why-analysis

Optional future inputs:
- targets and forecasts
- refresh history
- prior investigation artifacts
- user feedback on accepted/rejected hypotheses

### Fact-table query allowance
During anomaly investigation, the agent should be allowed to request additional read-only data as needed.

This should be an explicit part of the phase contract:
- the anomaly agent may issue `SELECT` queries
- those queries may read from fact tables in any validated combination needed for investigation
- the purpose is to let the agent gather more evidence during analysis rather than relying only on precomputed dashboard artifacts

This is especially important when:
- the dashboard shows the anomaly but not enough explanatory detail
- the LLM decides a deeper slice or comparison is needed
- multiple fact tables need to be combined to explain production, productivity, utilization, or quality shifts

The expected model is:
- LLM decides what additional evidence is needed
- deterministic query-safety and semantic validation decide whether the query is allowed
- execution remains read-only and evidence-oriented

---

## LLM-First Investigation Architecture

The anomaly workflow should be designed as an LLM-first investigative pipeline.

### Stage 1: Evidence Assembly
Build an evidence bundle containing:
- top anomaly candidates
- anomaly scores and baselines
- dashboard context
- metric definitions
- high-signal investigative areas
- supporting raw signal changes
- hierarchy and ontology context
- context text and domain pack guidance

This stage is deterministic and exists to prepare grounded inputs for the LLM agent.

### Stage 2: LLM Investigation Task
Run a dedicated anomaly-investigation prompt that asks the LLM to:
- identify the most important anomaly worth explaining
- prioritize the most informative slices
- choose the high-signal investigative areas that deserve focus first
- generate multiple why-hypotheses
- assign confidence and rationale
- generate descriptive insights
- generate prescriptive actions
- suggest anomaly dashboard content
- decide whether additional fact-table evidence must be queried

If the LLM determines that current evidence is insufficient, it should be allowed to request additional read-only `SELECT` queries over fact tables before finalizing hypotheses.

### LLM Planning Output Contract
The planning task should return JSON with:
- `prioritized_anomaly_ids`
- `planning_summary`
- `evidence_focus`
- `prioritized_investigative_areas`
- `evidence_queries`

`prioritized_investigative_areas` should contain objects with:
- `anomaly_id`
- `dimension`
- `value`
- `rationale`
- `confidence`

`evidence_queries` should contain objects with:
- `query_id`
- `title`
- `sql`
- `reason`

### LLM Synthesis Output Contract
The synthesis task should return JSON with:
- `summary_text`
- `hypotheses`
- `actions`
- `insights`
- `dashboard_suggestions`

Each hypothesis should contain:
- `title`
- `explanation`
- `confidence`
- `anomaly_ids`
- `likely_drivers`
- `supporting_evidence`
- `validation_step`

Each action should contain:
- `action_type`
- `action_text`
- `confidence`
- `priority`
- `linked_hypothesis_titles`
- `recommended_owner`

`dashboard_suggestions` should contain additive guidance only, such as:
- panel title
- chart intent
- evidence priority
- story-card summary

### Stage 3: Deterministic Validation
Validate that the LLM output references:
- real metrics
- real dimensions
- real entity scopes
- real evidence artifacts
- supported dashboard panels

Reject or downgrade unsupported claims.

High-signal investigative area selection should also be LLM-first:
- the LLM chooses which dimensions/values matter most
- deterministic ranking and evidence summaries act as support inputs and fallback only
- persistence should treat LLM-selected areas as primary when they validate successfully

For additional evidence queries, deterministic validation must ensure:
- `SELECT`-only execution
- no writes, DDL, or mutation statements
- joins only across approved fact-table combinations or validated semantic relationships
- tenant/domain scope enforcement
- bounded row limits and safe execution constraints

### Evidence Query Protocol
During anomaly analysis, additional SQL must follow this protocol:
- allowed forms:
  - `SELECT ...`
  - `WITH ... SELECT ...`
- blocked forms:
  - `INSERT`
  - `UPDATE`
  - `DELETE`
  - `DROP`
  - `ALTER`
  - `CREATE`
  - `TRUNCATE`
  - multiple statements
- query count should be bounded per run
- row count should be bounded per query
- execution should be time-bounded
- table references should be restricted to approved fact tables for the active scope
- joins should be allowed only when they are semantically approved or explicitly permitted for scoped fact analysis

### Stage 4: Persistence and Reuse
Persist:
- hypotheses
- actions
- evidence references
- anomaly dashboard spec

These persisted artifacts then become reusable in workspace chat and dashboard refresh flows.

## Detection Model

The anomaly layer should be hybrid:

### Deterministic detection
- rolling baseline deviation
- previous-period delta
- moving average / moving variance checks
- change-point style break detection
- peer-relative underperformance
- target miss detection
- anomalous raw-signal movement

### LLM-first investigation
- choose promising slice combinations
- decide which anomalies deserve narrative focus
- decide which investigative areas deserve focus first
- connect multiple weak signals into coherent hypotheses
- identify which dimensions are most worth drilling into
- synthesize narrative and actions from evidence
- propose anomaly dashboard composition

---

## High-Signal Investigative Areas

This phase defines `high-signal investigative areas` as the most explanatory slices or subspaces for a given anomaly.

Examples:
- plant clusters driving most of the output drop
- one product family causing most of the productivity degradation
- one operational shift with abnormal downtime or rejection patterns
- one region or zone diverging materially from peers
- one time segment where variance sharply increased

The agent should rank these areas using evidence such as:
- contribution to delta
- concentration of variance
- divergence from baseline
- divergence from peers
- recurrence in historical anomaly patterns

The intended behavior is:
- LLM chooses the primary investigative areas
- deterministic slice ranking provides candidate evidence and fallback choices

## Fallback Policy

### 1) If LLM planning fails
- use deterministic anomaly evidence bundle as fallback
- allow deterministic high-signal investigative areas to remain available
- skip additional evidence queries
- continue run without failing the full dashboard flow

### 2) If evidence queries are rejected
- record rejected queries
- continue synthesis with existing evidence
- reduce confidence / add warnings

### 3) If LLM synthesis fails
- persist anomaly investigation summary and evidence only
- do not block dashboard completion
- skip hypothesis/action persistence

### 4) If anomaly dashboard generation fails
- keep investigation artifacts
- do not fail the main dashboard run
- record anomaly-dashboard failure as a non-terminal artifact warning

---

## Output Contract

Each investigation should produce a structured artifact with:
- anomaly summary
- anomaly type
- impacted metric or raw signal
- severity
- confidence
- affected scope
- baseline window
- comparison window
- high-signal investigative areas
- ranked hypotheses
- evidence artifacts
- descriptive insights
- prescriptive actions
- follow-up questions
- suggested charts and queries
- anomaly dashboard spec

### Hypothesis object
Each hypothesis should include:
- `title`
- `explanation`
- `confidence`
- `impacted_metrics`
- `likely_drivers`
- `supporting_evidence`
- `validation_step`
- `suggested_actions`

### Action object
Each action should include:
- `action_type`
- `action_text`
- `confidence`
- `priority`
- `linked_hypothesis_id`
- `recommended_owner`

### Anomaly dashboard object
The anomaly workflow should also generate a separate analyst-facing dashboard, but its JSON should stay as close as possible to the existing dashboard spec used by `DashboardAgent`.

It should reuse the same top-level dashboard JSON shape:
- `title`
- `dashboard_title`
- `charts`
- `story`
- `insights`
- `quality`
- `chart_plan`
- `chart_candidates`

Anomaly-specific meaning should be expressed through:
- chart titles
- chart metadata
- story cards
- insights text
- optional anomaly metadata fields added in a backward-compatible way

The anomaly dashboard should not introduce a brand-new incompatible dashboard JSON schema unless the current dashboard contract proves insufficient.

### Optional anomaly-specific metadata
If extra anomaly context is needed, it should be attached in additive fields such as:
- `dashboard_kind: "anomaly"`
- `anomaly_summary`
- `anomaly_ids`
- `hypothesis_ids`
- `action_ids`

These fields should be optional and should not break existing dashboard consumers.

## Anomaly Dashboard V1

The anomaly dashboard should be a second dashboard generated after the main business dashboard and optimized for analyst investigation rather than executive overview.

Its JSON contract should mirror the existing dashboard JSON as closely as possible, with anomaly content represented primarily through the normal:
- `charts`
- `story.cards`
- `insights`
- `quality`

and only minimal additive anomaly metadata when necessary.

### V1 dashboard goal
Give analysts one place to understand:
- what went wrong
- where it is concentrated
- what likely explains it
- what to investigate next

### V1 layout

#### Section 1: Anomaly Summary Strip
Top summary cards should show:
- number of anomalies detected
- highest-severity anomaly
- most impacted KPI
- most impacted entity scope
- strongest-confidence hypothesis

Purpose:
- give an immediate triage view before drill-down

#### Section 2: Primary Anomaly Timeline
Charts should show:
- anomaly metric versus baseline over time
- anomaly score or severity over time
- optional peer or target comparison when available

Purpose:
- establish what changed and when

#### Section 3: Concentration View
Charts should show where the anomaly is concentrated:
- by plant
- by zone
- by region
- by product or process slice when available

Preferred chart shapes:
- sorted bar chart
- waterfall or delta contribution chart
- heatmap when multi-entity time intensity is strong

Purpose:
- identify where analysts should look first

#### Section 4: High-Signal Investigative Areas
This section should present the top ranked investigative slices with:
- area label
- severity contribution
- confidence
- short rationale

Example cards:
- `Plant Hazira: 41% of production shortfall`
- `West Zone: strongest peer divergence`
- `19kg stream: largest rejection-rate increase`

Purpose:
- compress the best drill-down targets into one analyst-readable block

#### Section 5: Ranked Hypotheses Panel
Each hypothesis card should include:
- title
- explanation
- confidence
- linked evidence
- recommended validation step

Purpose:
- show multiple likely explanations without forcing false certainty

#### Section 6: Evidence Charts
Charts should support the top hypotheses with:
- supporting trend comparisons
- before-vs-after comparisons
- co-movement charts
- raw operational signal evidence

Purpose:
- make the explanation auditable through data, not just narrative

#### Section 7: Action Insights Panel
The action section should contain:
- immediate actions
- next investigation actions
- monitor-only recommendations
- suggested owner or team when inferable

Purpose:
- convert explanation into execution guidance

#### Section 8: Follow-Up Questions
This section should include analyst-ready prompts such as:
- why did Plant A underperform versus peers?
- did downtime or rejection rate increase before the drop?
- which product stream explains most of the decline?
- is this anomaly recurring versus prior periods?

Purpose:
- help workspace users continue the investigation conversationally

### V1 minimum panel contract
The first implementation should guarantee at least:
- 1 summary card group
- 1 primary anomaly timeline
- 1 concentration chart
- 1 high-signal investigative area panel
- 1 ranked hypothesis panel
- 1 action insight panel

If evidence quality is high, add:
- supporting evidence charts
- peer comparison chart
- anomaly recurrence panel

### V1 JSON compatibility rule
The anomaly dashboard should be serializable through the same dashboard persistence and retrieval path as the existing dashboard spec.

That means:
- `charts` remain normal dashboard chart objects
- summary and hypothesis content should map into `story.cards` and `insights`
- anomaly-specific panel semantics should come from titles, summaries, and chart metadata
- existing dashboard rendering code should need little or no branching to render the anomaly dashboard

Only add dedicated anomaly fields when the current dashboard JSON cannot faithfully express the required analyst behavior.

### Mandatory vs Optional Fields
Mandatory persisted anomaly dashboard fields:
- `title`
- `dashboard_title`
- `charts`
- `story`
- `insights`

Recommended additive anomaly fields:
- `dashboard_kind`
- `anomaly_summary`
- `anomaly_ids`
- `hypothesis_ids`
- `action_ids`

Chart-level recommended metadata:
- `anomaly_ids`
- `hypothesis_ids`
- `action_ids`
- `query_id`
- `metric_ids`
- `evidence_artifact_ids`

### V1 chart selection rules
- prefer one primary KPI anomaly per dashboard rather than mixing too many anomalies at once
- prefer charts tied to the top 1-3 hypotheses
- prefer analyst-readable concentration charts over decorative variety
- suppress low-confidence panels instead of filling the dashboard with weak content

### V1 artifact linkage
Each dashboard panel should reference:
- anomaly id
- hypothesis ids when applicable
- source metric ids
- source query or evidence artifact ids

This makes the anomaly dashboard reusable in workspace chat and refresh-safe during later recomputation.

### Example anomaly dashboard JSON
The anomaly dashboard should look like a normal dashboard spec with anomaly-specific metadata added in a backward-compatible way.

```json
{
  "title": "LPG Production Anomaly Investigation",
  "dashboard_title": "LPG Production Anomaly Investigation",
  "dashboard_kind": "anomaly",
  "anomaly_summary": {
    "investigation_id": "inv_01",
    "severity_score": 0.91,
    "confidence_score": 0.83,
    "primary_anomaly": "Total production down 18% versus trailing 14-day baseline"
  },
  "anomaly_ids": ["an_01"],
  "hypothesis_ids": ["hyp_01", "hyp_02", "hyp_03"],
  "action_ids": ["act_01", "act_02", "act_03"],
  "charts": [
    {
      "title": "Total Production vs Baseline",
      "type": "line",
      "intent": "trend",
      "metric": "total_production",
      "table": "lpg_plant_operations",
      "time_column": "process_date",
      "time_grain": "day",
      "metric_intent": "volume",
      "metadata": {
        "anomaly_id": "an_01",
        "hypothesis_ids": ["hyp_01"],
        "metric_ids": ["lpg_production_distribution__total_production"],
        "evidence_artifact_ids": ["ev_01"]
      }
    },
    {
      "title": "Production Drop by Plant",
      "type": "bar",
      "intent": "breakdown",
      "metric": "total_production_delta",
      "table": "lpg_plant_operations",
      "category_column": "plant_name",
      "metric_intent": "volume",
      "metadata": {
        "anomaly_id": "an_01",
        "hypothesis_ids": ["hyp_01", "hyp_02"],
        "metric_ids": ["lpg_production_distribution__total_production"],
        "evidence_artifact_ids": ["ev_02"]
      }
    },
    {
      "title": "Downtime Trend for Impacted Plants",
      "type": "line",
      "intent": "multi_series",
      "metric": "downtime_hours",
      "table": "lpg_plant_operations",
      "time_column": "process_date",
      "category_column": "plant_name",
      "time_grain": "day",
      "metric_intent": "utilization",
      "metadata": {
        "anomaly_id": "an_01",
        "hypothesis_ids": ["hyp_01"],
        "evidence_artifact_ids": ["ev_03"]
      }
    },
    {
      "title": "Rejection Rate by Product Stream",
      "type": "bar",
      "intent": "breakdown",
      "metric": "rejection_rate_pct",
      "table": "lpg_plant_operations",
      "category_column": "product_stream",
      "metric_intent": "quality",
      "metadata": {
        "anomaly_id": "an_01",
        "hypothesis_ids": ["hyp_03"],
        "evidence_artifact_ids": ["ev_04"]
      }
    }
  ],
  "story": {
    "title": "LPG Production Anomaly Investigation",
    "cards": [
      {
        "title": "Summary",
        "summary": "Total production fell 18% versus the trailing 14-day baseline, concentrated in three plants."
      },
      {
        "title": "High-Signal Areas",
        "summary": "Plant Hazira, West Zone, and the 19kg stream explain most of the observed deviation."
      },
      {
        "title": "Top Hypothesis",
        "summary": "The leading explanation is downtime-related throughput loss, supported by rising downtime hours in the most impacted plants."
      },
      {
        "title": "Action",
        "summary": "Inspect downtime logs, shift allocation, and rejection-rate changes for the impacted plant cluster."
      }
    ]
  },
  "insights": [
    "Production is materially below baseline with strongest concentration in three plants.",
    "Downtime increase appears aligned with the largest production decline.",
    "Rejection-rate movement in one product stream may be amplifying the output shortfall."
  ],
  "quality": {
    "confidence": 0.83,
    "warnings": []
  },
  "chart_plan": [],
  "chart_candidates": []
}
```

---

## Persistence Model

The investigation result must be persisted as reusable workspace intelligence.

Recommended persisted artifacts:
- anomaly record
- ranked hypotheses
- supporting charts
- anomaly dashboard spec
- supporting query outputs
- evidence tables or previews
- descriptive summary
- prescriptive actions
- follow-up questions
- provenance metadata

Recommended storage additions:
- anomaly investigation artifact rows tied to:
  - `tenant_id`
  - `domain_id`
  - `run_id`
  - optional `conversation_id`
  - optional `dashboard_id`

The workspace chat layer should be able to reference these artifacts directly when users ask:
- why did this happen?
- what changed?
- what actions should we take?

## Recommended SQL / Data Model Changes

This phase will likely require new persistence tables plus small extensions to existing dashboard and workspace artifacts.

The exact final schema can be adjusted during implementation, but the plan should assume SQL changes are required.

### 1) `quantyx_anomaly_investigations`
Store the top-level anomaly investigation record for a run, refresh, or targeted workspace analysis.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_investigations (
  investigation_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  conversation_id TEXT NULL,
  dashboard_id TEXT NULL,
  source_dashboard_id TEXT NULL,
  trigger_source TEXT NOT NULL, -- deployment|refresh|workspace|targeted
  status TEXT NOT NULL, -- queued|running|completed|failed|partial_completed
  title TEXT NULL,
  summary_text TEXT NULL,
  severity_score NUMERIC NULL,
  confidence_score NUMERIC NULL,
  anomaly_summary_json JSONB NULL,
  quality_json JSONB NULL,
  error_message TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_anomaly_investigations_scope
  ON public.quantyx_anomaly_investigations (tenant_id, domain_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomaly_investigations_run
  ON public.quantyx_anomaly_investigations (run_id, created_at DESC);
```

### 2) `quantyx_anomaly_records`
Store individual anomaly candidates found during one investigation.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_records (
  anomaly_id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  metric_id TEXT NULL,
  raw_signal_name TEXT NULL,
  anomaly_type TEXT NOT NULL, -- deviation|change_point|peer_divergence|target_miss|contradiction
  entity_scope_json JSONB NULL,
  baseline_window_json JSONB NULL,
  comparison_window_json JSONB NULL,
  severity_score NUMERIC NULL,
  confidence_score NUMERIC NULL,
  evidence_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_anomaly_records_investigation
  ON public.quantyx_anomaly_records (investigation_id, severity_score DESC, created_at DESC);
```

### 3) `quantyx_anomaly_hypotheses`
Store multiple ranked why-hypotheses per anomaly or investigation.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_hypotheses (
  hypothesis_id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL,
  anomaly_id TEXT NULL,
  rank_no INT NOT NULL DEFAULT 1,
  title TEXT NOT NULL,
  explanation_text TEXT NOT NULL,
  confidence_score NUMERIC NULL,
  likely_drivers_json JSONB NULL,
  supporting_evidence_json JSONB NULL,
  validation_step_text TEXT NULL,
  provenance_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_anomaly_hypotheses_investigation
  ON public.quantyx_anomaly_hypotheses (investigation_id, rank_no ASC, created_at ASC);
```

### 4) `quantyx_anomaly_actions`
Store descriptive and prescriptive action outputs tied to ranked hypotheses.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_actions (
  action_id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL,
  anomaly_id TEXT NULL,
  hypothesis_id TEXT NULL,
  action_type TEXT NOT NULL, -- descriptive|prescriptive|monitor|validation
  priority TEXT NULL, -- high|medium|low
  confidence_score NUMERIC NULL,
  recommended_owner TEXT NULL,
  action_text TEXT NOT NULL,
  metadata_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_anomaly_actions_investigation
  ON public.quantyx_anomaly_actions (investigation_id, created_at ASC);
```

### 5) `quantyx_anomaly_dashboard_links`
Link the generated anomaly dashboard to the investigation and primary dashboard when both exist.

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_anomaly_dashboard_links (
  link_id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL,
  dashboard_id TEXT NOT NULL,
  source_dashboard_id TEXT NULL,
  role TEXT NOT NULL, -- anomaly_dashboard|source_dashboard
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_anomaly_dashboard_links_role
  ON public.quantyx_anomaly_dashboard_links (investigation_id, dashboard_id, role);
```

### 6) Recommended extensions to existing dashboard spec persistence
The current `quantyx_dashboard_specs.spec` JSON can likely store the anomaly dashboard without a new table, but the spec should allow additive metadata such as:

```json
{
  "dashboard_kind": "anomaly",
  "anomaly_summary": {},
  "anomaly_ids": ["an_1"],
  "hypothesis_ids": ["hyp_1", "hyp_2"],
  "action_ids": ["act_1", "act_2"]
}
```

This means SQL table changes for `quantyx_dashboard_specs` are optional if:
- anomaly metadata is stored inside existing `spec JSONB`
- current dashboard retrieval APIs already return the full spec body

### 7) Recommended extensions to workspace message/artifact persistence
If workspace conversations need to retrieve investigations directly, existing workspace message artifacts should be allowed to reference:
- `investigation_id`
- `anomaly_ids`
- `hypothesis_ids`
- `action_ids`
- `dashboard_id` for the anomaly dashboard

This can likely be handled by additive JSON inside existing artifact payloads rather than mandatory new tables.

### 8) Optional refresh integration table changes
If anomaly investigations run automatically during dashboard refresh, the refresh model may need one of:
- a nullable `investigation_id` on `quantyx_dashboard_refresh_runs`
- or a cross-link table between refresh runs and anomaly investigations

Recommended optional link table:

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_refresh_investigations (
  link_id TEXT PRIMARY KEY,
  refresh_id TEXT NOT NULL,
  investigation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dashboard_refresh_investigation
  ON public.quantyx_dashboard_refresh_investigations (refresh_id, investigation_id);
```

### SQL design notes
- keep anomaly data tenant/domain/run scoped
- allow linkage to both deployment-time and conversation-time investigations
- persist hypotheses and actions as first-class rows, not only embedded JSON blobs
- reuse `JSONB` for evidence payloads, area rankings, and metadata that will evolve
- prefer additive changes to dashboard/workspace tables instead of breaking existing contracts

---

## API / UX Exposure

This phase should support three entry modes:

### 1) Proactive
Auto-run after primary dashboard generation during deployment or dashboard refresh to surface the most important anomalies and likely explanations.

### 2) Reactive
Run when users ask why-questions in workspace chat.

### 3) Targeted
Run on a specific KPI, entity, hierarchy node, or time range.

Potential future API surfaces:
- `GET /workspace/anomalies`
- `GET /workspace/anomalies/{anomaly_id}`
- `POST /workspace/anomalies/investigate`
- `GET /workspace/investigations/{investigation_id}`

This phase does not require the final public API shape immediately, but the persisted artifact model should assume these APIs will exist.

### Initial API Contract
The initial implementation should expose at least:

#### `GET /workspace/anomalies`
Query params:
- `tenant_id`
- `domain_id`
- optional `run_id`
- optional `limit`

Returns:
- investigation list for a tenant/domain/run scope

#### `GET /workspace/anomalies/{investigation_id}`
Returns:
- investigation metadata
- anomaly records
- hypotheses
- actions
- linked dashboards

#### `GET /workspace/anomalies/{investigation_id}/dashboard`
Returns:
- linked anomaly dashboard spec using the existing dashboard contract

These APIs should remain additive and should not change existing dashboard endpoints.

## Event Stream Contract

Because the anomaly flow runs inside the agentic run, the run stream should expose at least:

### `AnomalyDetectionAgent` completed artifacts
- `investigation_id`
- `candidate_count`
- `anomaly_ids`
- `prioritized_anomaly_ids`
- `high_signal_investigative_areas`
- `fallback_high_signal_investigative_areas`
- `executed_queries`
- `rejected_queries`
- `hypothesis_ids`
- `action_ids`
- `anomaly_insights`

### `AnomalyDashboardAgent` completed artifacts
- `dashboard_id`
- `dashboard_title`
- `chart_ids`
- `chart_count`
- `investigation_id`

These stream artifacts should be stable enough for UI progress and diagnostics.

---

## Guardrails

### 1) No unsupported causal claims
The agent must distinguish:
- observed association
- likely driver
- confirmed cause

### 2) Raw-column eligibility rules
Raw columns may participate only if they are:
- eligible operational signals
- valid dimensions
- approved numeric measures

### 3) Read-only fact-table query safety
The anomaly agent may request additional evidence using fact tables, but only through:
- validated `SELECT` queries
- approved table combinations
- safe joins and bounded limits

No mutation SQL is allowed.

### 4) Evidence-backed actions only
Every suggested action must link back to:
- at least one ranked hypothesis
- at least one evidence artifact

### 5) Confidence labeling
All hypotheses and actions must be labeled with confidence or certainty bands.

### 6) Scope safety
All analysis must remain tenant/domain scoped and use only approved deployment artifacts or scoped raw tables.

### 7) Weak-result suppression
The workflow should suppress low-quality outputs rather than forcing noisy content.

Examples:
- if no anomaly exceeds severity threshold, anomaly dashboard may be skipped
- if hypotheses are low-confidence, only summary + evidence may persist
- if evidence queries are rejected, synthesis should continue with available evidence but quality should be downgraded

## Quality Thresholds

The phase should define at least initial default thresholds:
- minimum anomaly severity threshold for dashboard inclusion
- confidence bands:
  - high
  - medium
  - low
- maximum number of evidence queries per investigation
- maximum rows returned per evidence query

Initial rule suggestions:
- low-confidence hypotheses should not dominate the dashboard
- anomaly dashboard should be skipped if no meaningful anomaly survives thresholds
- warnings should be attached when the anomaly flow falls back from LLM to deterministic evidence only

Current implementation defaults:
- `AGENTIC_ANOMALY_MIN_SEVERITY=0.15`
- `AGENTIC_ANOMALY_MIN_HYPOTHESIS_CONFIDENCE=0.35`
- `AGENTIC_ANOMALY_MAX_EVIDENCE_QUERIES=5`
- `AGENTIC_ANOMALY_EVIDENCE_QUERY_ROW_LIMIT=200`

Current runtime behavior:
- anomaly candidates below `AGENTIC_ANOMALY_MIN_SEVERITY` are filtered before persistence and dashboard generation
- hypotheses below `AGENTIC_ANOMALY_MIN_HYPOTHESIS_CONFIDENCE` are not persisted
- evidence query requests above `AGENTIC_ANOMALY_MAX_EVIDENCE_QUERIES` are rejected with `max_query_limit_exceeded`
- anomaly dashboard generation is skipped when investigation artifacts are insufficient
- quality warnings are attached when planning fails, synthesis fails, queries are rejected, or no strong hypotheses survive threshold

## Runtime Controls / Feature Flags

This phase should allow environment-driven runtime control such as:
- anomaly LLM mode on/off/auto
- anomaly planning model
- anomaly synthesis model
- anomaly evidence query limit
- anomaly evidence query row limit
- anomaly dashboard generation enabled/disabled
- anomaly detection enabled/disabled

Current implementation flags:
- `AGENTIC_ANOMALY_DETECTION_ENABLED`
- `AGENTIC_ANOMALY_DASHBOARD_ENABLED`
- `AGENTIC_ANOMALY_LLM_MODE`
- `AGENTIC_ANOMALY_PLAN_MODEL`
- `AGENTIC_ANOMALY_PLAN_TIMEOUT_SEC`
- `AGENTIC_ANOMALY_SYNTHESIS_MODEL`
- `AGENTIC_ANOMALY_SYNTHESIS_TIMEOUT_SEC`
- `AGENTIC_ANOMALY_MIN_SEVERITY`
- `AGENTIC_ANOMALY_MIN_HYPOTHESIS_CONFIDENCE`
- `AGENTIC_ANOMALY_MAX_EVIDENCE_QUERIES`
- `AGENTIC_ANOMALY_EVIDENCE_QUERY_ROW_LIMIT`

These flags should be documented because rollout will likely be staged.

## Refresh and Versioning Behavior

The phase should explicitly define how anomaly artifacts behave across runs and refreshes.

Initial recommended rule:
- deployment-time anomaly dashboard is versioned with the same deployment run

Follow-up behavior to implement later:
- dashboard refresh may create refreshed anomaly investigation artifacts
- workspace-targeted investigations may create investigation artifacts without creating a canonical anomaly dashboard

The doc should assume:
- anomaly dashboard is attached to a deployment run when generated during the canonical run
- refresh-triggered anomaly artifacts may either:
  - create a new linked anomaly dashboard
  - or update a refresh-scoped anomaly artifact set

This should be clarified before full refresh integration.

---

## Implementation Plan

### Phase 38.1: Investigation Artifact Model
- define durable anomaly and investigation artifacts
- attach them to tenant/domain/run and optionally dashboard/conversation
- persist hypotheses, evidence, and action recommendations

Expected result:
- anomaly investigations become reusable workspace intelligence

### Phase 38.2: Deterministic Anomaly Evidence Assembly
- add anomaly candidate generation over KPI metrics and approved raw signals
- score anomalies by severity, confidence, and business relevance
- support day/week/month baselines and peer comparisons
- treat these outputs as evidence inputs for the LLM, not the final prioritized anomaly list

Expected result:
- the workflow provides a grounded anomaly evidence bundle for LLM-first investigation

### Phase 38.3: Deterministic Investigative Area Evidence
- rank dimensions, hierarchy levels, and raw-signal slices by explanatory strength
- compute delta contribution, concentration, peer divergence, and variance concentration
- use this as LLM support evidence and fallback only, not as the primary investigative-area decision layer

Expected result:
- the LLM receives grounded candidate slices it can prioritize, refine, or reject

### Phase 38.4: LLM-First Investigation Prompt and Task
- add a dedicated anomaly-investigation prompt/task as the primary reasoning layer
- pass anomaly summary, dashboard context, ranked investigative areas, KPI context, raw evidence, and hierarchy context into the LLM
- ask the LLM to decide what matters, which anomaly to prioritize, which investigative areas to focus on, what additional fact-table evidence is needed, and what explanations and actions should be generated
- normalize output into structured objects for hypotheses, actions, and anomaly-dashboard suggestions

Expected result:
- the anomaly agent reasons in an LLM-first way instead of behaving like a deterministic detector with narrative added later

### Phase 38.5: LLM-Guided Evidence Querying
- let the LLM request additional read-only fact-table `SELECT` queries when existing evidence is insufficient
- validate requested queries against semantic scope, table eligibility, join safety, and row limits
- execute approved queries and feed the results back into the investigation context

Expected result:
- the agent can deepen its analysis with fresh fact-table evidence instead of being limited to the initial dashboard snapshot

### Phase 38.6: LLM-Assisted Hypothesis Generation
- pass anomaly summary, ranked investigative areas, KPI context, raw evidence, and any additional approved fact-table query results into an LLM prompt
- generate multiple competing why-hypotheses with confidence and rationale
- normalize output into structured hypothesis objects

Expected result:
- the system proposes plausible, evidence-grounded explanations instead of one shallow narrative

### Phase 38.7: Hypothesis Validation and Evidence Binding
- validate that each hypothesis references real dimensions, metrics, entities, and evidence artifacts
- reject unsupported explanations
- require evidence links for persisted hypotheses

Expected result:
- the agent remains grounded and auditable

### Phase 38.8: Action Insight Generation
- generate both:
  - descriptive insights
  - prescriptive recommended actions
- classify actions by priority, confidence, and likely owner

Expected result:
- outputs move from passive explanation to analyst-operational guidance

### Phase 38.9: Anomaly Dashboard Generation
- generate a second dashboard dedicated to anomaly analysis after the primary business dashboard is complete
- compose anomaly dashboard panels from:
  - anomaly summaries
  - ranked hypotheses
  - high-signal investigative areas
  - supporting evidence charts
  - action recommendations

Expected result:
- analysts receive a dedicated anomaly dashboard instead of buried anomaly notes inside the main dashboard

### Phase 38.10: Dashboard and Workspace Integration
- let the anomaly dashboard and investigation artifacts be attached to the same deployment run
- let workspace chat retrieve and reuse persisted investigation artifacts
- support why-style follow-up turns over prior investigations and anomaly dashboard panels

Expected result:
- anomaly intelligence becomes part of the conversational workspace, not a disconnected side pipeline

### Phase 38.11: Quality Gates and Regression Coverage
- add anti-hallucination checks for hypotheses and actions
- add anomaly-dashboard quality checks for duplicate, weak, or unsupported panels
- enforce causal-language guardrails
- add regression tests for anomaly ranking, hypothesis persistence, and workspace reuse

Expected result:
- the agent remains reliable as more anomaly and action logic is added

## Acceptance Criteria

- anomaly flow runs automatically as part of the post-dashboard stage of the agentic run
- anomaly investigation rows persist for successful runs with valid anomaly evidence
- LLM planning can prioritize anomalies and investigative areas
- LLM may request additional safe read-only evidence queries
- rejected evidence queries do not fail the main agentic run
- hypotheses and actions persist when synthesis succeeds
- anomaly dashboard persists using the existing dashboard JSON contract
- anomaly dashboard links back to the source dashboard and investigation
- workspace anomaly read APIs can retrieve:
  - investigation
  - hypotheses
  - actions
  - linked anomaly dashboard
- when LLM steps fail, deterministic evidence artifacts still remain available as fallback

## Remaining Follow-On Work

The initial implementation establishes the anomaly investigation backbone, but several follow-on areas remain and should be tracked as explicit sub-phases or backlog items.

### 1) Dashboard composition refinement
Current state:
- [`services/ai/anomaly_dashboard.py`](/Users/vnagaraju/PycharmProjects/quantyx-core/services/ai/anomaly_dashboard.py) builds a dashboard that is JSON-compatible with the existing dashboard contract
- the current composition is still baseline and mostly driven by executed evidence queries plus summary artifacts

Pending enhancement:
- use `dashboard_suggestions` from the LLM more deeply to shape:
  - panel ordering
  - story-card priority
  - chart inclusion/exclusion
  - chart prominence
  - section emphasis for hypotheses vs actions vs evidence

Target outcome:
- anomaly dashboards should feel intentionally curated by the investigation agent rather than mechanically assembled from query outputs

### 2) Query safety tightening
Current state:
- the validator enforces read-only `SELECT` / `WITH ... SELECT`
- mutation SQL is blocked
- table references are restricted to allowed fact-like tables
- query count and row limits are enforced
- cross joins, comma joins, and unsupported multi-table joins are rejected
- joined tables must share approved join-key columns inferred from profiling metadata

Pending enhancement:
- tighten join policy in [`services/ai/agentic_orchestrator.py`](/Users/vnagaraju/PycharmProjects/quantyx-core/services/ai/agentic_orchestrator.py)
- introduce explicit semantic table-combination rules
- validate join paths against known semantic relationships where possible
- optionally add execution timeout, cost, or cardinality guardrails

Target outcome:
- evidence querying should be safe not only syntactically, but also semantically and operationally

### 3) Workspace reuse deepening
Current state:
- anomaly artifacts are persisted
- anomaly read APIs can retrieve investigations, hypotheses, actions, and linked dashboards
- when a `conversation_id` is present, anomaly summary/artifact references can also be written into workspace messages and conversation memory

Pending enhancement:
- allow workspace conversation flows to actively reuse prior anomaly investigations as context
- support follow-up why-questions over persisted anomaly artifacts
- surface prior investigations as reusable evidence inputs for future runs or analyst conversations

Target outcome:
- anomaly intelligence becomes a first-class memory and reasoning asset inside the conversational workspace

### 4) Refresh integration
Current state:
- anomaly investigation is currently attached to the canonical post-dashboard `/agentic run`

Pending enhancement:
- support refresh-triggered anomaly regeneration
- define whether refresh creates:
  - a new anomaly investigation version
  - a new anomaly dashboard
  - or a refresh-scoped update linked to an earlier dashboard/investigation chain

Target outcome:
- anomaly intelligence remains current as dashboards refresh, rather than being limited to the initial deployment run

### 5) UI / product surfacing
Current state:
- backend APIs and persistence are present
- anomaly artifacts can be retrieved programmatically

Pending enhancement:
- add dedicated frontend surfacing such as:
  - anomaly tab
  - anomaly investigation list
  - linked anomaly dashboard entry point
  - workspace affordances for “why” follow-ups

Target outcome:
- anomaly investigation should be discoverable and usable in the product, not only through backend API access

---

## Dependencies
- depends on Phase 24 for tenant/domain deployment and workspace-scoped persistence
- depends on Phase 34 for persisted agent artifact consumption by workspace conversations
- depends on Phase 35 for KPI-first evidence quality
- depends on Phase 36 for context-aware KPI meaning
- depends on Phase 37 for broad validated KPI and chart coverage
- complements `Phase AC: Ask "Why" / Driver Analysis` by adding deployment-time and workspace-native anomaly investigation artifacts, multi-hypothesis reasoning, and action intelligence

---

## Example Analyst Outcome

Example:
- anomaly: total production fell 18% versus trailing 14-day baseline
- high-signal investigative areas:
  - Plant A
  - Zone West
  - 19kg production stream
- ranked hypotheses:
  - downtime-related throughput loss
  - shift-level hours reduction
  - rejection increase in one plant cluster
- suggested actions:
  - inspect downtime and maintenance logs for Plant A
  - compare manpower and shift allocation against previous 7 days
  - review rejection-rate trend for 19kg stream

This is the target user experience:
- faster diagnosis
- better evidence trails
- better follow-up questioning
- better actionability
