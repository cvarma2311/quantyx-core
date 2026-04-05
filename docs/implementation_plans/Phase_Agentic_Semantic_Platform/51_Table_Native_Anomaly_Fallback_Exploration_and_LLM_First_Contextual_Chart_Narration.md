# Phase 51: Table-Native Anomaly Fallback Exploration and LLM-First Contextual Chart Narration

## Objective

Upgrade the anomaly detection and anomaly dashboard flow so it does not dead-end when no strong anomaly candidates are detected.

This phase adds:

1. table-native anomaly fallback exploration over scoped facts and safe joins
2. exploratory anomaly dashboards even when hard anomaly candidates are zero
3. LLM-first anomaly chart narration grounded in chart data plus business context
4. stronger anomaly interpretation using dashboard context, quality signals, and correlation context

---

## Problem

The current anomaly flow is candidate-first:

- `AnomalyDetectionAgent` detects anomaly candidates
- if candidate count is zero, it returns early
- `AnomalyDashboardAgent` requires investigation artifacts, synthesis, and executed evidence queries
- therefore the anomaly dashboard is skipped with `insufficient_artifacts`

This causes two product problems:

1. users get a dead-end "no anomalies found" outcome instead of a useful exploratory dashboard
2. chart narratives remain too local and too template-like, without enough business-context interpretation

---

## Target State

### 1) Exploratory Fallback Mode

When hard anomaly candidates are zero:

- do not stop
- create an anomaly investigation in `fallback_exploration` mode
- query the scoped tables directly
- build time-axis-safe exploratory anomaly charts
- produce a dashboard that explains:
  - major timeline behavior
  - trend breaks and soft anomalies
  - category/entity contribution shifts
  - readiness gaps and next investigative cuts

### 2) Table-Native Querying

Fallback exploration should build safe deterministic queries over:

- timeline totals
- category-over-time trends
- latest-period category breakdowns
- recent-period movers / delta comparisons
- optional multi-table joined timelines when safe join edges exist

### 3) LLM-First Chart Narration

All anomaly dashboard charts should use LLM-first contextual narration based on:

- chart title and type
- complete chart data or faithful compacted series payload
- business context text
- anomaly investigation summary
- dashboard quality and readiness warnings
- correlation context when available

The chart output should explain:

- what the chart shows
- what changed
- why it matters in business terms
- uncertainty / caveats
- what to inspect next

### 4) Dashboard Dual Mode

Anomaly dashboards should support:

- investigation mode: confirmed anomaly candidates exist
- exploratory mode: no confirmed candidates, but the system still produces anomaly-oriented exploratory analysis

---

## Scope

### In scope

- no-candidate fallback anomaly investigation flow
- table-native exploratory query generation
- optional join-aware fallback exploration when safe join edges exist
- exploratory anomaly dashboard rendering
- LLM-first contextual anomaly chart narration
- persistence of fallback investigation artifacts

### Out of scope

- unrestricted SQL generation
- causal inference
- replacing the statistical candidate detector

---

## Workflow

Updated anomaly flow:

1. `DashboardAgent`
2. `CorrelationAgent`
3. `AnomalyDetectionAgent`
4. if hard candidates exist:
   - standard anomaly investigation
5. else:
   - `AnomalyFallbackExplorer`
   - exploratory query execution
   - exploratory anomaly synthesis
6. `AnomalyDashboardAgent`

---

## Functional Requirements

### Requirement A: No-Candidate Runs Must Not Skip the Dashboard

If `candidate_count_after_threshold == 0`:

- create an investigation anyway
- persist fallback executed queries
- persist exploratory synthesis
- render an anomaly dashboard

### Requirement B: Timeline Axis Must Be Real

Fallback exploration must use only real time columns for:

- anomaly timeline charts
- time comparisons
- trend and change analysis

### Requirement C: Category and Entity Exploration

Fallback exploration should generate:

- category-over-time trend charts
- latest-period contribution charts
- mover charts across recent periods

### Requirement D: LLM-First Contextual Chart Narration

Every anomaly chart should persist:

- `insight_text`
- `narrative_text`
- `stats_json`

with LLM-first generation over full chart context and deterministic fallback.

### Requirement E: Correlation-Aware Anomaly Context

When correlation context exists, anomaly synthesis should mention:

- related correlations
- related category shifts
- divergent or lagged patterns that matter for anomaly interpretation

---

## Implementation Tickets

### 51A.1 Fallback Exploration Query Builder

- derive safe timeline and group-by exploration queries from profiled tables and metric defs
- prefer fact-native scoped tables
- optionally use join edges for safe multi-table exploration

### 51A.2 Fallback Investigation Persistence

- create anomaly investigations even with zero hard candidates
- persist fallback query results, synthesis, and dashboard context

### 51A.3 Exploratory Dashboard Rendering

- render anomaly dashboards from fallback executed queries instead of skipping
- include readiness and warning sections

### 51B.1 LLM-First Contextual Chart Narration

- add anomaly chart narration helper using chart data + context
- use it for anomaly dashboard chart persistence

### 51B.2 Soft-Anomaly Synthesis

- summarize exploratory findings even when they are below hard threshold
- distinguish observed evidence vs hypothesis vs next-step guidance

### 51B.3 Join-Aware Exploration

- when multiple tables and safe join edges exist, produce joined exploratory views for anomaly context

---

## Success Criteria

1. Zero-candidate runs still produce an anomaly dashboard.
2. Anomaly dashboards contain exploratory charts built from scoped table data.
3. Chart narratives explain the chart in business context, not just with template text.
4. Investigation artifacts are persisted for both standard and fallback anomaly flows.
5. Correlation context is available to anomaly synthesis and narrative layers.

---

## Dependencies

- Phase 38 for anomaly investigation persistence
- Phase 43 for correlation context reuse
- Phase 45 for scoped live connections
- Phase 46 for per-chart inference persistence
- Phase 47 for LLM-first dashboard intelligence patterns
