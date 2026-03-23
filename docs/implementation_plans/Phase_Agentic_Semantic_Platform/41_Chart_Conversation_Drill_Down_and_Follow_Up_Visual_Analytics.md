# Phase 41: Chart Conversation, Drill-Down, and Follow-Up Visual Analytics

## Objective
Make every persisted chart conversational so users can ask follow-up questions directly from a chart, request drill-downs or filters, and receive new SQL-backed charts and summaries derived from the original chart context.

This phase should let users do things like:
- show this chart only for one zone or region
- drill this bar into plants or sales areas
- compare this category with last month
- split this line by region
- exclude one value and regenerate the chart
- explain why this point spiked

The goal is not only NL chat over the dataset. The goal is chart-scoped conversational analytics where the current chart becomes the first-class context object for the next question.

---

## Problem

Current workspace conversation can answer questions against the deployed semantic layer, but it is still weak at chart-centric follow-up.

The gap today is:
- a user sees a chart
- the user wants to refine or drill it
- the system has the chart payload and SQL, but does not yet treat that chart as a reusable conversational object

As a result:
- follow-up questions lose chart context
- users must restate dimensions, filters, and time grain manually
- drill-down workflows feel disconnected from the dashboard
- the system does not reliably translate chart follow-ups into safe SQL refinements and new chart artifacts

This creates product friction because chart exploration is inherently sequential:
- chart
- question
- refined chart
- another question
- deeper chart

That loop should feel like a conversation, not a reset.

---

## Target State
1. Every persisted chart has a reusable chart conversation context.
2. Users can ask follow-up questions from a chart without restating the full query.
3. The system can safely interpret requests such as:
   - add filter
   - remove filter
   - drill down
   - roll up
   - compare periods
   - split series
   - sort/rank/top-N
   - explain a specific spike or bar
4. Follow-up requests compile into:
   - refined SQL
   - updated chart spec
   - summary/inference text
   - persisted derived chart artifacts
5. Chart follow-ups remain scoped to the original chart’s semantic context unless the user explicitly broadens scope.
6. The conversation remembers chart lineage:
   - source chart
   - derived chart
   - applied filters
   - drill path
   - transformation history

---

## Why This Phase Is Needed

Phases 24, 25, 34, and 39 gave the platform:
- workspace conversation
- artifact persistence
- LLM-first query interpretation
- safe SQL compilation

Phase 40 improved dashboard composition and chart context.

But a major product gap still remains:
- charts are generated as outputs
- not yet treated as interactive conversational starting points

This phase closes that loop and turns charts into living analytical objects.

---

## Core Product Definition

This feature should be thought of as:
- chart conversation
- chart follow-up analytics
- chart drill-down intelligence

not just:
- chat about charts

The system should support three layers of interaction:

### 1) Chart-Scoped Follow-Up
User references the current chart implicitly:
- show only south zone
- break this by plant
- compare with previous month

### 2) Chart Explanation
User asks about observed behavior in the chart:
- why is this point high?
- why did this category drop?
- what is driving this spike?

### 3) Chart Transformation
User asks to reshape the chart:
- convert this to a bar chart
- split by region
- show top 10 only
- switch from month to day

---

## User Stories
- As an analyst, I want to click or reference a chart and ask follow-up questions without rewriting the original request.
- As a business user, I want to filter or drill the current chart conversationally.
- As a workspace user, I want each derived chart to persist in the conversation with lineage to the original chart.
- As a reviewer, I want to know what changed between the original chart and the follow-up chart.

---

## Scope

### In scope
- chart-scoped follow-up chat
- chart context resolution from `chart_id`
- conversational drill-down and filter application
- SQL refinement from prior chart SQL and semantic intent
- new derived chart persistence
- chart lineage and transformation history
- chart summary/inference regeneration for derived charts
- chart follow-up audit metadata

### Out of scope
- arbitrary free-form BI notebook editing
- unrestricted SQL editing inside chart conversation
- frontend layout redesign beyond chart action entry points
- replacing the generic NL conversation flow

---

## Required Product Behavior

### 1) The Chart Is the First-Class Context Object
Each follow-up should be anchored to:
- `chart_id`
- original chart SQL
- original chart dimensions
- original metric(s)
- original filters
- chart type
- dashboard context
- chart lineage metadata

The user should not need to restate:
- metric
- grain
- table
- current filters
- dimension context

unless they want to change them.

### 2) Follow-Ups Should Be Intent-Classified
The first implementation should classify follow-ups into a small set of chart intents:
- `add_filter`
- `remove_filter`
- `replace_filter`
- `drill_down`
- `roll_up`
- `change_grain`
- `change_chart_type`
- `split_series`
- `rank_or_top_n`
- `period_comparison`
- `explain_point_or_segment`
- `regenerate_with_adjustment`

This should keep the system reliable and auditable.

### 3) SQL Should Be Refined, Not Replanned From Scratch By Default
Default behavior should be:
- start from the existing chart SQL/query payload
- apply validated transformations
- regenerate SQL safely

The system should not immediately abandon chart context and plan from scratch unless:
- the request cannot be represented as a refinement
- the user explicitly broadens or changes the analytical question materially

### 4) Derived Charts Must Be Persisted
Each follow-up should create:
- a new chart artifact
- a conversation message
- lineage metadata
- summary/inference if successful

This lets the user and the system both refer back to:
- original chart
- derived chart
- prior chart branch

---

## Key Product Decisions

### A) Refinement-First, Replan-Second
Recommended order:
1. resolve chart context
2. classify follow-up intent
3. attempt safe chart refinement
4. if refinement is not valid, fall back to chart-aware replan

This is the right balance between:
- preserving user context
- maintaining safety
- supporting richer chart changes

### B) Chart Conversation Should Prefer Semantic Transformations Over Raw SQL Edits
The user may ask:
- filter to west zone
- drill to plant

Internally this should resolve to:
- add filter on dimension
- replace dimension
- update group-by
- update grain

not:
- arbitrary SQL text mutation

### Current backend v1 examples
The current implementation foundation should support these chart-aware carry-forward behaviors:

#### 1) Carry forward the source metric
If the source chart is:
- `Daily Sales by Zone`

and the user asks:
- `Drill this into region`

the system should keep the same metric:
- `daily_sales`

and only change the dimensional shape.

Expected semantic behavior:
- source metric reused
- source dashboard/chart context preserved
- no need for the user to restate the metric name

#### 2) Carry forward or replace dimensions
If the source chart is:
- `Monthly Target Quantity by SBU`

and the user asks:
- `Show this by region instead`

the system should:
- keep the source metric
- replace the current dimension `SBU_Name`
- with the requested dimension `Region_Name` if it is valid in scope

If the source chart already has a dimension and the user asks:
- `Keep this same chart`

the system should carry forward the existing dimension set.

#### 3) Add simple selected-category filters
If the user clicked a bar for:
- `selected_category = "West Zone"`

and asks:
- `Break this by plant`

the system should add a filter hint equivalent to:
- `Zone_Name = 'West Zone'`

before compiling the next chart.

Likewise, if the user selected a time point such as:
- `selected_time_value = "2026-02-01"`

the system should try to add a corresponding time filter hint before compilation.

These v1 examples are intentionally narrow:
- carry the source metric forward
- carry or replace dimensions
- add simple selected-category or selected-time filters

This is the right first step before implementing deeper chart lineage and full refinement compilation.

### C) Explanation Questions Need Different Handling Than Drill-Down Questions
These are different product behaviors:

Drill-down:
- changes the chart

Explanation:
- may keep the chart but produce:
  - explanatory text
  - supporting evidence query
  - one or more supporting charts

So the system should support:
- `refine_chart`
- `explain_chart_behavior`

as two different task modes.

---

## Conversation Model

### Input contract
Chart follow-up requests should use the existing workspace chat/conversation API and accept:
- `conversation_id`
- `tenant_id`
- `domain_id`
- `chart_id`
- `question`
- optional `dashboard_id`
- optional `selected_point`
- optional `selected_series`
- optional `selected_category`
- optional `selected_time_value`

This allows both:
- generic follow-up on the whole chart
- context-sensitive follow-up on a clicked point/bar/series

Interpretation rule:
- no `chart_id` means normal domain/workspace conversation mode
- `chart_id` present means chart-scoped conversation mode
- the same conversation thread should contain both domain-level and chart-level messages

### Output contract
The response should produce:
- interpreted chart-follow-up plan
- refined semantic query payload
- refined SQL
- derived chart id
- derived chart payload
- summary text
- inference text
- lineage metadata
- validation warnings

The output should still be returned through the same chat response model used by workspace conversation, with additive chart-follow-up metadata rather than a separate response type.

---

## Follow-Up Intent Examples

### Filters
- Show this only for West Zone.
- Exclude Common and Mumbai Ref.
- Keep only top 5 SBU values.

### Drill-down
- Drill this zone into regions.
- Break this monthly total by plant.
- Show this point by sales area.

### Roll-up
- Roll this plant chart up to region.
- Show summary by zone instead.

### Time changes
- Switch this from month to day.
- Compare this month with previous month.
- Show trailing 3 months.

### Chart reshaping
- Turn this into a bar chart.
- Split this line by region.
- Show share instead of total.

### Explanation
- Why is this category so high?
- Why did this point spike?
- What changed compared with last month?

---

## Workflow Design

Recommended workflow:
1. `ChartConversationAgent` resolves chart context from `chart_id`
2. `ChartFollowUpIntentAgent` classifies requested change
3. `ChartRefinementAgent` proposes semantic transformation
4. deterministic validator checks:
   - metric validity
   - dimension validity
   - filter validity
   - grain validity
   - SQL safety
5. `DerivedChartAgent` compiles the refined chart and persists it
6. `SummaryInferenceAgent` regenerates summary/inference text
7. workspace conversation persists the full follow-up artifact set

This should happen inside the existing conversation flow, not as a separate chart-only execution path.

---

## Data and Artifact Model

New additive concepts likely needed:

### Chart conversation context
- source chart metadata
- semantic query payload
- current dimensions
- current filters
- current grain
- chart lineage state

### Chart lineage
- `source_chart_id`
- `parent_chart_id`
- `derived_chart_id`
- `follow_up_intent`
- `transformation_summary`

### Follow-up audit
- original user question
- resolved follow-up intent
- accepted transformations
- rejected transformations
- final SQL

Optional SQL tables:
- `quantyx_chart_lineage`
- `quantyx_chart_followup_events`
- `quantyx_chart_conversation_context`

If possible, some of this can first live in existing chart/workspace JSON artifacts before new tables are introduced.

---

## API Direction

This feature should use the existing workspace chat API, not a separate public follow-up endpoint.

Recommended request shape:
- keep the existing chat payload
- add optional chart-scoped context fields

Suggested payload:
```json
{
  "tenant_id": "tenant_1",
  "domain_id": "market_performance_analysis",
  "conversation_id": "conv_123",
  "chart_id": "chart_abc",
  "question": "Drill this zone into region and exclude Common.",
  "selected_category": "West Zone"
}
```

Suggested response:
```json
{
  "conversation_id": "conv_123",
  "source_chart_id": "chart_abc",
  "derived_chart_id": "chart_def",
  "follow_up_intent": "drill_down",
  "transformation_summary": [
    "added filter Zone_Name = 'West Zone'",
    "replaced dimension zone with region",
    "added exclusion filter for SBU_Name = 'Common'"
  ],
  "summary_text": "Regional drill-down for West Zone shows ...",
  "warnings": []
}
```

Recommended behavior:
- the user stays in the same conversation thread
- chart-derived messages appear in normal conversation history
- source and derived charts are tied to those messages via additive metadata

Optional later read APIs may still be useful for:
- chart lineage inspection
- chart conversation context debugging

But they should be additive support APIs, not the primary interaction surface.

---

## UI / UX Direction

Recommended first-entry points:
- chart overflow action: `Ask this chart`
- chart overflow action: `Drill down`
- chart overflow action: `Filter this chart`
- chart point click: `Explain this point`

The chat UI should show:
- source chart preview
- interpreted transformation
- derived chart preview
- lineage breadcrumb

The message thread should remain unified:
- chart follow-up messages appear inline with other workspace messages
- chart artifacts are attached to those messages
- users can revisit the history of chart-driven questions naturally

Example breadcrumb:
- `Daily Sales by Zone` → `West Zone only` → `Drilled to Region`

---

## Safety Rules

### SQL safety
- follow-up SQL must remain `SELECT`-only
- allowed transformations must be dimension/filter/grain/chart-shape safe transformations
- no arbitrary user SQL injection

### Semantic safety
- only valid metric and dimension substitutions
- no identifier/code dimensions unless allowed by policy
- pack/domain policies must still apply
- chart follow-up must respect tenant/domain scope

### Conversation safety
- if the request no longer fits chart refinement, explicitly say the system is broadening to a chart-aware replan

---

## Quality Rules

### Accept only if
- the transformation is semantically valid
- SQL is safe
- the derived chart has rows
- chart type aligns with the refined query shape

### Warnings / failure cases
- `invalid_chart_followup_dimension`
- `invalid_chart_followup_filter`
- `invalid_chart_followup_grain`
- `unsafe_chart_followup_sql`
- `chart_followup_no_rows`
- `chart_followup_replanned_from_scratch`

---

## Relationship to Existing Phases

This phase builds on:
- Phase 24 for workspace run and conversation scoping
- Phase 25 for conversation history
- Phase 33 for query/data/chart inference loop
- Phase 34 for artifact persistence
- Phase 39 for LLM-first query interpretation and safe compilation
- Phase 40 for stronger chart metadata and story context

It should not replace generic workspace conversation.

Instead:
- generic conversation remains domain-level
- chart conversation becomes chart-scoped and refinement-first
- both modes should still use the same workspace conversation and history model

---

## Recommended Phased Implementation

### Phase 41.1: Chart Context Resolution
- resolve chart by `chart_id`
- reconstruct chart semantic context
- persist chart conversation context

### Phase 41.2: Follow-Up Intent Classification
- classify user follow-up into supported chart actions
- validate if refinement-first is possible

### Phase 41.3: Safe Chart Refinement Compiler
- apply filter, drill, grain, and dimension transformations
- compile refined semantic query and SQL

### Phase 41.4: Derived Chart Persistence and Lineage
- persist derived chart and lineage records
- connect source and derived charts in workspace history

### Phase 41.5: Chart Explanation Mode
- support questions about spikes, drops, bars, and segments
- generate evidence-backed explanation plus optional supporting charts

### Phase 41.6: UI and Conversation Integration
- chart entry points
- lineage display
- reusable follow-up history

---

## Backend Implementation Checklist

Use this checklist as the execution tracker for the backend portion of Phase 41.

### Same Chat API Integration
- [x] Extend the existing workspace chat payload to accept optional:
  - `chart_id`
  - `selected_point`
  - `selected_series`
  - `selected_category`
  - `selected_time_value`
- [x] Treat `chart_id` as a chart-scoped conversation mode switch inside the same chat API.
- [x] Keep chart follow-up messages in the same conversation thread and history model.

### Chart Context Resolution
- [x] Resolve persisted chart context from `chart_id`:
  - source SQL
  - query payload
  - chart dimensions
  - metrics
  - chart type
  - dashboard context
- [x] Persist user-message metadata tying the question to the source chart.
- [x] Add chart-context metadata into assistant responses and workspace memory.

### Intent and Refinement
- [x] Classify chart follow-up intent before generic domain planning.
- [~] Support refinement-first behavior for:
  - filters
  - drill-down
  - roll-up
  - grain changes
  - top-N
- [~] Fall back to chart-aware replan only when refinement is invalid or unsupported.
- [~] Emit a warning when the system replans from scratch instead of refining the chart.

### Derived Chart Persistence
- [x] Persist derived charts as normal chart artifacts.
- [~] Record source-to-derived chart lineage.
  - persisted now in derived chart `query_payload.chart_followup`
  - deeper standalone lineage model still pending
- [x] Persist transformation summary and accepted/rejected refinements.

### Response Contract
- [x] Return chart-follow-up metadata through the normal chat response:
  - `source_chart_id`
  - `derived_chart_id`
  - `follow_up_intent`
  - `transformation_summary`
  - `warnings`
- [x] Keep backward compatibility for chat consumers that ignore chart-scoped metadata.

### Quality and Safety
- [x] Ensure chart follow-up SQL remains `SELECT`-only.
- [ ] Keep pack/domain policy filters active during chart follow-ups.
- [ ] Reject invalid metric, dimension, and grain substitutions.
- [ ] Reject derived charts with zero rows or invalid chart/data shape.

---

## Initial Brainstorming Recommendations

If we want this feature to feel strong in v1, the first release should support a narrow but high-value set of follow-ups:
- add filter
- remove filter
- drill down to a lower dimension
- roll up to a higher dimension
- change time grain
- top-N
- explain selected point or selected category

That gives a very usable chart conversation loop without trying to solve every BI interaction on day one.

The most important product rule should be:
- preserve chart context unless the user explicitly asks a different analytical question

That is what will make the experience feel intelligent rather than stateless.

---

## Acceptance Criteria

1. A user can ask a follow-up question against a persisted `chart_id` without restating the full chart query.
2. The system can apply at least filter, drill-down, roll-up, and grain-change transformations safely.
3. Derived charts are persisted with lineage back to the source chart.
4. Chart follow-up responses include transformation summaries and warnings when applicable.
5. Explanation-mode questions can produce chart-aware reasoning and, where useful, supporting derived charts.
6. Chart follow-ups use the same workspace chat API and the same conversation history model.
7. Existing workspace conversation behavior remains backward compatible.

---

## Recommendation

This should be the next phase if the product goal is:
- conversational dashboards
- iterative chart exploration
- chart-driven analyst workflows

This is the right next step if the current pain is:
- "I can see the chart, but I cannot talk to it"
- "I want to drill or filter without rebuilding the question"
- "I want follow-up charts from the current chart, not from scratch"
