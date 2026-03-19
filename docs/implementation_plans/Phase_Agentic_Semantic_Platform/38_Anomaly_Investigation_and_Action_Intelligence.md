# Phase 38: Anomaly Investigation and Action Intelligence

## Objective
Add a new LLM-assisted workflow agent that detects business anomalies, investigates the strongest explanatory areas in the data, produces multiple ranked why-hypotheses with evidence and confidence, and generates both descriptive and prescriptive action insights for analysts.

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

### 1) LLM-Assisted, Not LLM-Unbounded
The agent should be LLM-assisted for:
- selecting promising investigative paths
- synthesizing mixed evidence
- drafting ranked hypotheses
- generating narrative summaries and action insights

But it should remain grounded in deterministic evidence from:
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

---

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

### LLM-assisted investigation
- choose promising slice combinations
- connect multiple weak signals into coherent hypotheses
- identify which dimensions are most worth drilling into
- synthesize narrative and actions from evidence

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

### 3) Evidence-backed actions only
Every suggested action must link back to:
- at least one ranked hypothesis
- at least one evidence artifact

### 4) Confidence labeling
All hypotheses and actions must be labeled with confidence or certainty bands.

### 5) Scope safety
All analysis must remain tenant/domain scoped and use only approved deployment artifacts or scoped raw tables.

---

## Implementation Plan

### Phase 38.1: Investigation Artifact Model
- define durable anomaly and investigation artifacts
- attach them to tenant/domain/run and optionally dashboard/conversation
- persist hypotheses, evidence, and action recommendations

Expected result:
- anomaly investigations become reusable workspace intelligence

### Phase 38.2: Deterministic Anomaly Candidate Detection
- add anomaly candidate generation over KPI metrics and approved raw signals
- score anomalies by severity, confidence, and business relevance
- support day/week/month baselines and peer comparisons

Expected result:
- the workflow can surface high-value anomaly candidates before explanation

### Phase 38.3: High-Signal Investigative Area Ranking
- rank dimensions, hierarchy levels, and raw-signal slices by explanatory strength
- compute delta contribution, concentration, peer divergence, and variance concentration

Expected result:
- the agent identifies where analysts should look first

### Phase 38.4: LLM-Assisted Hypothesis Generation
- pass anomaly summary, ranked investigative areas, KPI context, raw evidence, and hierarchy context into an LLM prompt
- generate multiple competing why-hypotheses with confidence and rationale
- normalize output into structured hypothesis objects

Expected result:
- the system proposes plausible, evidence-grounded explanations instead of one shallow narrative

### Phase 38.5: Hypothesis Validation and Evidence Binding
- validate that each hypothesis references real dimensions, metrics, entities, and evidence artifacts
- reject unsupported explanations
- require evidence links for persisted hypotheses

Expected result:
- the agent remains grounded and auditable

### Phase 38.6: Action Insight Generation
- generate both:
  - descriptive insights
  - prescriptive recommended actions
- classify actions by priority, confidence, and likely owner

Expected result:
- outputs move from passive explanation to analyst-operational guidance

### Phase 38.7: Anomaly Dashboard Generation
- generate a second dashboard dedicated to anomaly analysis after the primary business dashboard is complete
- compose anomaly dashboard panels from:
  - anomaly summaries
  - ranked hypotheses
  - high-signal investigative areas
  - supporting evidence charts
  - action recommendations

Expected result:
- analysts receive a dedicated anomaly dashboard instead of buried anomaly notes inside the main dashboard

### Phase 38.8: Dashboard and Workspace Integration
- let the anomaly dashboard and investigation artifacts be attached to the same deployment run
- let workspace chat retrieve and reuse persisted investigation artifacts
- support why-style follow-up turns over prior investigations and anomaly dashboard panels

Expected result:
- anomaly intelligence becomes part of the conversational workspace, not a disconnected side pipeline

### Phase 38.9: Quality Gates and Regression Coverage
- add anti-hallucination checks for hypotheses and actions
- add anomaly-dashboard quality checks for duplicate, weak, or unsupported panels
- enforce causal-language guardrails
- add regression tests for anomaly ranking, hypothesis persistence, and workspace reuse

Expected result:
- the agent remains reliable as more anomaly and action logic is added

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
