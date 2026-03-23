# Phase 40: Context-Driven Cross-Table Dashboard Composition and Titling

## Objective
Replace the current table-first dashboard composition behavior with a context-driven, cross-table dashboard planning system that:
- derives the dashboard title from the full set of validated KPIs, chart intents, and business context
- composes charts across all eligible scoped tables instead of anchoring primarily to one picked table
- allows more than 10 charts when those charts add real analytical value
- produces dashboards that behave like a coherent analytical narrative rather than a per-table summary

This phase should make dashboards feel like they represent the business question or business domain, not the name of the dominant source table.

---

## Problem

Current dashboard generation still has several structural limitations:
- dashboard title often collapses to a table-derived label
- chart selection tends to over-focus on one or two tables
- broader scoped tables may be underused even when they contain meaningful KPI or benchmark context
- chart-count limits are too rigid for richer domains that legitimately need more coverage
- the workflow does not yet reason well about how charts from multiple tables should combine into one business dashboard

This creates a product gap:
- users select multiple scoped tables and provide rich business context
- but the resulting dashboard can still look like a summary of one table instead of an integrated domain view

---

## Target State
1. Dashboard title is derived from the overall dashboard theme, KPI families, chart set, and context text.
2. Dashboard planning is performed across all scoped and semantically eligible tables.
3. Charts from different tables are intentionally combined into one coherent dashboard narrative.
4. The planner may generate more than 10 charts when justified by:
   - distinct KPI families
   - distinct analytical purposes
   - cross-table evidence value
5. Chart count is governed by value density and quality, not by a hard small cap alone.
6. Each included chart must have a clear role in the dashboard story:
   - trend
   - comparison
   - breakdown
   - target vs actual
   - benchmark
   - quality/rate
   - operational driver
7. Dashboard metadata should explicitly record which tables contributed to the dashboard title and story.

---

## Why This Phase Is Needed

Phases 27, 35, and 37 improved:
- dashboard/chart titling
- KPI-first charting
- LLM-first chart proposal and broader composition

But the current runtime still shows a residual table-first bias:
- title generation can still inherit from one dominant table
- chart breadth can still be artificially narrow
- multi-table domains can look fragmented or incomplete

This phase addresses that final composition gap directly.

---

## Core Principles

### 1) Dashboard Title Must Be Contextual, Not Table-Derived
The dashboard title should come from:
- domain id
- context text
- selected KPI families
- chart intents
- dominant business concepts
- cross-table analytical theme

The title should not default to:
- raw table names
- single source table identity
- whichever table happened to win a heuristic pick

Examples of good title sources:
- sales, target, pace, and benchmark KPIs
- production, downtime, and productivity KPI families
- market performance, benchmark comparison, and target achievement

### 2) Dashboard Composition Must Be Scope-Wide
If the user scoped 3 or more tables, the dashboard planner should consider all eligible tables rather than centering almost entirely on one table.

This does not mean every table must always produce charts.

It does mean:
- every eligible table should be evaluated for KPI contribution
- the planner should be able to pull the best charts from different tables into one dashboard
- omission of a scoped table should be deliberate and explainable

### 3) Chart Count Should Be Value-Based
The planner should allow more than 10 charts when justified.

Recommended rule:
- default target range: 8 to 14 charts
- allow expansion to 16 or 18 when:
  - there are multiple distinct KPI families
  - there are important cross-table comparisons
  - there are both target and benchmark contexts
  - quality remains acceptable

Hard caps should be:
- configurable
- domain-aware
- quality-aware

### 4) Multi-Table Dashboards Need Story Architecture
Charts should be grouped into story roles rather than left as a flat list.

Recommended story sections:
- Executive overview
- Core trends
- Target and pace tracking
- Benchmark or industry comparison
- Key business breakdowns
- Supporting diagnostic context

---

## Scope

### In scope
- dashboard title synthesis from chart set and business context
- cross-table dashboard planning
- broader chart-count policy
- value-ranked chart inclusion
- chart grouping into story sections
- explicit dashboard contribution metadata by table and KPI family
- quality-aware chart-count expansion

### Out of scope
- anomaly-specific dashboard logic
- front-end layout redesign
- unrestricted chart explosion without quality controls
- replacing semantic KPI validation rules

---

## User Stories
- As an analyst, I want a dashboard title that reflects the business analysis, not the source table name.
- As a user who selected multiple tables, I want the dashboard to use those tables meaningfully.
- As a business user, I want richer dashboards when the domain needs them, not an artificially tiny chart set.
- As a reviewer, I want to understand why each chart was included and which table or KPI family it came from.

---

## Target Workflow Changes

Current conceptual behavior:
1. pick one dominant table
2. choose a few KPI charts around it
3. derive the title from table-centric context

Target behavior:
1. identify KPI families across all scoped tables
2. identify analytical roles needed for the domain
3. propose candidate charts across all eligible tables
4. rank charts by value, coverage, and redundancy
5. compose a multi-table dashboard story
6. synthesize a dashboard title from the composed chart set
7. persist contribution metadata and story sections

---

## New Planning Model

### A) Dashboard Theme Extraction
Before composing charts, derive a dashboard theme object from:
- domain id
- context text
- validated KPI metrics
- approved raw signal families
- scoped tables
- selected benchmark or target tables

Example theme object:
- primary_theme: market performance
- subthemes:
  - daily sales
  - target achievement
  - monthly pace
  - industry comparison
- preferred grains:
  - day
  - month
- preferred dimensions:
  - zone
  - region
  - SBU

### B) Cross-Table KPI Family Map
Build a dashboard composition input that groups metrics by:
- KPI family
- table
- business role
- time grain
- dimension suitability

This allows the planner to answer:
- which table best serves daily trend coverage?
- which table best serves target tracking?
- which table best serves benchmark comparison?

### C) Story Role Quotas
Replace a single global chart-count cap with role quotas.

Suggested starting quotas:
- executive trends: 2 to 4
- breakdowns: 2 to 4
- target/pace: 2 to 3
- benchmark/comparison: 1 to 3
- supporting diagnostics: 1 to 4

### D) Redundancy Controls
Even when allowing more charts, prevent low-signal duplication.

Reject charts that are redundant across:
- same metric
- same grain
- same category role
- same source table
- same analytical insight

---

## Dashboard Title Contract

The title generator should consume:
- chart plan as the planning input
- persisted successful charts as the final source of truth
- dashboard theme object
- KPI families represented
- contribution by table
- story sections
- context text and pack/domain preferences

It should output:
- `dashboard_title`
- `dashboard_title_reason`
- `dashboard_title_sources`

### Runtime source of truth
Title generation should follow this input contract:
- planning input may start from `chart_plan`
- final title synthesis must use persisted successful charts only
- the following must be excluded from title synthesis:
  - skipped charts
  - zero-row charts
  - semantically rejected charts
  - charts rejected by runtime SQL/chart validation

### Title generation rules
1. Prefer business-domain phrases over table names.
2. Prefer aggregated dashboard meaning over local chart terminology.
3. If multiple KPI families are represented, title should reflect the family grouping, not only one metric.
4. Table names may appear only as a fallback when business context is genuinely missing.

### Title fallback order
The runtime fallback order should be:
1. LLM-generated title from persisted successful charts
2. deterministic theme title from persisted successful charts
3. domain-derived title
4. table-name fallback only as a last resort, with a warning in quality metadata

Table-name fallback should be warning-only, not an automatic dashboard failure.

### Examples
Better:
- Market Performance Overview
- Sales, Targets, and Benchmark Performance
- Commercial Performance and Pace Tracking
- Cross-Market Sales and Target Achievement Overview

Worse:
- M60 Level Metadata Performance Overview
- MOM Day Level Data Dashboard

---

## Required Metadata Additions

Dashboard JSON should remain compatible with the existing structure, but include additive metadata such as:
- `dashboard_theme`
- `dashboard_title_reason`
- `dashboard_title_sources`
- `story_sections`
- `table_contributions`
- `kpi_family_contributions`
- `chart_selection_rationale`

Example additive fields:
```json
{
  "dashboard_theme": {
    "primary_theme": "market_performance",
    "subthemes": ["daily_sales", "monthly_target", "monthly_pace", "benchmark_comparison"]
  },
  "dashboard_title_reason": "Selected charts span sales, target, pace, and benchmark KPI families across three scoped tables.",
  "dashboard_title_sources": {
    "tables": ["MOM_DAY_LEVEL_DATA", "M60_LEVEL_METADATA", "industry_performance"],
    "kpi_families": ["sales", "target", "pace", "benchmark"]
  },
  "story_sections": [
    {"section": "Executive overview", "chart_ids": ["chart_1", "chart_2"]},
    {"section": "Target and pace", "chart_ids": ["chart_3", "chart_4"]},
    {"section": "Benchmark comparison", "chart_ids": ["chart_5"]}
  ]
}
```

---

## Quality Rules

The broader dashboard should still satisfy quality rules.

### Required checks
- title must not equal the raw chosen table name unless explicitly justified
- at least 2 distinct tables should contribute when 2 or more eligible scoped tables produce valid persisted charts
- charts with zero rows must not be counted toward coverage
- charts rejected for semantic mismatch must not contribute to title synthesis
- redundant charts should be pruned
- role coverage should be checked across trend, breakdown, comparison, target/pace, and quality/rate where relevant
- only persisted successful charts should contribute to:
  - title synthesis
  - story sections
  - table contribution counts
  - KPI family contribution counts

### Recommended gating behavior
- if the dashboard remains single-table despite multi-table eligibility, emit a warning:
  - `insufficient_cross_table_coverage`
- if title falls back to table name, emit a warning:
  - `table_derived_dashboard_title`
- if chart count exceeds configured threshold but redundancy score is high, emit a warning:
  - `overexpanded_low_value_dashboard`

---

## Runtime Controls

Recommended env/runtime controls:
- `AGENTIC_DASHBOARD_MIN_CHARTS`
- `AGENTIC_DASHBOARD_TARGET_MAX_CHARTS`
- `AGENTIC_DASHBOARD_HARD_MAX_CHARTS`
- `AGENTIC_DASHBOARD_ALLOW_BROAD_COMPOSITION`
- `AGENTIC_DASHBOARD_REQUIRE_MULTI_TABLE_COVERAGE`
- `AGENTIC_DASHBOARD_TITLE_LLM_ENABLED`
- `AGENTIC_DASHBOARD_SECTIONING_ENABLED`

Recommended defaults:
- `AGENTIC_DASHBOARD_MIN_CHARTS=8`
- `AGENTIC_DASHBOARD_HARD_MAX_CHARTS=16`
- `AGENTIC_DASHBOARD_ALLOW_BROAD_COMPOSITION=true`
- `AGENTIC_DASHBOARD_REQUIRE_MULTI_TABLE_COVERAGE=true`
- `AGENTIC_DASHBOARD_TITLE_LLM_ENABLED=true`
- `AGENTIC_DASHBOARD_SECTIONING_ENABLED=true`

For the current implementation track, the working chart-count target should be:
- 8 to 16 charts

### Runtime control migration clarification
Current runtime behavior uses:
- `AGENTIC_CHART_MIN_CHARTS`
- `AGENTIC_CHART_MAX_CHARTS`
- `AGENTIC_DASHBOARD_TITLE_MODEL`
- `AGENTIC_DASHBOARD_TITLE_TIMEOUT_SEC`

Migration guidance:
- treat `AGENTIC_CHART_MIN_CHARTS` as the current effective minimum chart control
- treat `AGENTIC_CHART_MAX_CHARTS` as the current effective hard maximum chart control
- `AGENTIC_DASHBOARD_TARGET_MAX_CHARTS` and `AGENTIC_DASHBOARD_HARD_MAX_CHARTS` remain the forward-looking naming model for later cleanup
- until the migration is completed, runtime and docs should consider `AGENTIC_CHART_*` authoritative for chart count
- dashboard title generation is currently controlled by:
  - `AGENTIC_DASHBOARD_TITLE_MODEL`
  - `AGENTIC_DASHBOARD_TITLE_TIMEOUT_SEC`

---

## SQL / Data Model Changes

Likely no mandatory new tables are required for v1.

However, the following additive fields may be persisted in existing dashboard spec JSON:
- dashboard theme metadata
- title reasoning metadata
- table contribution metadata
- KPI family contribution metadata
- story sections
- chart selection rationale

Optional later table:
- `quantyx_dashboard_composition_audit`
  - stores chart ranking rationale, excluded candidates, redundancy reasons, and title-source reasoning

---

## API / Stream Impacts

### Stream
`DashboardAgent` completion payload should include:
- `dashboard_theme`
- `table_contributions`
- `kpi_family_contributions`
- `story_sections`
- `dashboard_title_reason`
- `dashboard_title_sources`
- `selected_successful_chart_ids`
- `rejected_chart_ids`
- `role_selection`

Example `DashboardAgent completed` stream payload:
```json
{
  "dashboard_id": "dash_abc123",
  "dashboard_title": "Market Performance and Pace Overview",
  "dashboard_theme": {
    "primary_theme": "sales",
    "subthemes": ["sales", "target", "pace", "benchmark"],
    "selected_tables": ["MOM_DAY_LEVEL_DATA", "M60_LEVEL_METADATA", "industry_performance"],
    "table_contributions": [
      {"table": "MOM_DAY_LEVEL_DATA", "chart_count": 6},
      {"table": "M60_LEVEL_METADATA", "chart_count": 4},
      {"table": "industry_performance", "chart_count": 2}
    ],
    "kpi_family_contributions": [
      {"family": "sales", "count": 6},
      {"family": "target", "count": 3},
      {"family": "pace", "count": 2},
      {"family": "benchmark", "count": 1}
    ]
  },
  "dashboard_title_reason": "Derived from persisted successful charts, KPI families, and cross-table contribution.",
  "dashboard_title_sources": {
    "tables": ["MOM_DAY_LEVEL_DATA", "M60_LEVEL_METADATA", "industry_performance"],
    "kpi_families": ["sales", "target", "pace", "benchmark"],
    "successful_chart_ids": ["chart_1", "chart_2", "chart_3"]
  },
  "story_sections": [
    {"section": "Executive overview", "chart_ids": ["chart_1", "chart_2"], "summary": "Executive overview contains 2 charts."},
    {"section": "Target and pace tracking", "chart_ids": ["chart_3"], "summary": "Target and pace tracking contains 1 chart."}
  ],
  "role_selection": {
    "role_targets": {
      "executive_trends": {"min": 2, "max": 4},
      "breakdowns": {"min": 2, "max": 4}
    },
    "role_counts": {
      "executive_trends": 3,
      "breakdowns": 3,
      "target_pace": 2,
      "benchmark_comparison": 1,
      "quality_rate": 1,
      "supporting_diagnostics": 1
    },
    "missing_roles": [],
    "low_value_chart_count": 0
  },
  "selected_successful_chart_ids": ["chart_1", "chart_2", "chart_3"],
  "rejected_chart_ids": ["chart_9"],
  "quality_report": {
    "gate_passed": true,
    "warnings": []
  }
}
```

### API
Existing dashboard APIs can remain stable if additive JSON fields are included in the spec.

No new mandatory public endpoint is required for v1.

Dashboard read APIs should treat the following fields as additive but stable when present:
- `dashboard_theme`
- `dashboard_title_reason`
- `dashboard_title_sources`
- `table_contributions`
- `kpi_family_contributions`
- `story_sections`
- `selected_successful_chart_ids`
- `rejected_chart_ids`
- `role_selection`

Backward compatibility rule:
- existing consumers may ignore these fields without breaking
- new consumers should prefer these additive fields over inferring theme or contribution coverage from raw chart titles

Example dashboard-spec payload shape:
```json
{
  "title": "Market Performance and Pace Overview",
  "dashboard_title": "Market Performance and Pace Overview",
  "dashboard_theme": {
    "primary_theme": "sales",
    "selected_tables": ["MOM_DAY_LEVEL_DATA", "M60_LEVEL_METADATA", "industry_performance"]
  },
  "dashboard_title_reason": "Derived from persisted successful charts, KPI families, and cross-table contribution.",
  "dashboard_title_sources": {
    "tables": ["MOM_DAY_LEVEL_DATA", "M60_LEVEL_METADATA", "industry_performance"],
    "kpi_families": ["sales", "target", "pace", "benchmark"],
    "successful_chart_ids": ["chart_1", "chart_2", "chart_3"]
  },
  "table_contributions": [
    {"table": "MOM_DAY_LEVEL_DATA", "chart_count": 6},
    {"table": "M60_LEVEL_METADATA", "chart_count": 4}
  ],
  "kpi_family_contributions": [
    {"family": "sales", "count": 6},
    {"family": "target", "count": 3}
  ],
  "story_sections": [
    {"section": "Executive overview", "chart_ids": ["chart_1", "chart_2"], "summary": "Executive overview contains 2 charts."}
  ],
  "role_selection": {
    "role_counts": {
      "executive_trends": 3,
      "breakdowns": 3,
      "target_pace": 2
    },
    "missing_roles": [],
    "low_value_chart_count": 0
  },
  "selected_successful_chart_ids": ["chart_1", "chart_2", "chart_3"],
  "rejected_chart_ids": ["chart_9"],
  "quality": {
    "gate_passed": true,
    "warnings": []
  }
}
```

---

## Execution Checklist

Use this checklist as the working implementation tracker for Phase 40.

### Title Source of Truth
- [x] Add deterministic dashboard theme extraction from metrics, chart plan, scoped tables, and context text.
- [x] Define and document the exact runtime source of truth for title synthesis:
  - validated selected charts only
  - zero-row and rejected charts excluded
  - persisted dashboard-spec inputs only
- [x] Add a strict title fallback order:
  - LLM title from validated charts
  - deterministic theme title
  - domain-derived title
  - table-name fallback only with warning
- [x] Explicitly forbid table-name-derived titles when business-domain/KPI-family context is available.

### Cross-Table Eligibility
- [x] Define exact table eligibility rules for dashboard composition:
  - KPI-bearing table
  - benchmark/comparison-only table
  - target-only table
  - raw-signal-only table
- [x] Persist per-table contribution metadata in the dashboard spec.
- [x] Add warnings when scoped eligible tables are omitted without an explicit rejection reason.

### Role-Based Composition
- [x] Map chart intents to dashboard story roles explicitly.
- [x] Define whether role quotas are minimums, targets, or hard caps.
- [x] Implement fallback behavior when a role has no valid candidates.
- [x] Implement role-aware chart ranking instead of flat scoring only.

### Chart Count and Value Density
- [x] Increase runtime default chart range beyond the previous small cap.
- [x] Define value-density scoring inputs:
  - KPI family diversity
  - analytical-role coverage
  - table contribution diversity
  - redundancy score
  - evidence quality
- [x] Add a domain-aware expansion rule for 8 to 16 plus charts.
- [x] Add a hard guard against low-value chart explosion.

### Title Contract
- [x] Persist additive dashboard metadata:
  - `dashboard_theme`
  - `dashboard_title_reason`
  - `dashboard_title_sources`
- [x] Define the exact JSON contract for these title fields in the document.
- [x] Add one concrete end-to-end example payload from a multi-table run.

### Story Sections
- [x] Define a persisted `story_sections` contract.
- [x] Implement chart-to-section assignment.
- [x] Define section ordering rules.
- [x] Add acceptance criteria that require persisted story sections.

### Quality and Gating
- [x] Define when poor cross-table coverage is warning-only versus blocking.
- [x] Define when table-derived title fallback is warning-only versus blocking.
- [x] Define when redundancy causes pruning versus dashboard failure.
- [x] Ensure title synthesis excludes:
  - zero-row charts
  - semantically rejected charts
  - invalid comparison charts

### Anomaly Interaction
- [x] Define how Phase 40 dashboard outputs feed anomaly investigation.
- [x] Define whether anomaly should consume:
  - dashboard theme
  - table contributions
  - KPI family contributions
- [x] Define whether poor dashboard composition should block anomaly by policy.

### Stream and API Contracts
- [x] Add an example `DashboardAgent completed` stream payload including new fields.
- [x] Add explicit field expectations for dashboard read APIs.
- [x] Define backward compatibility rules for existing consumers.

### Runtime Controls
- [x] Clarify coexistence or replacement of:
  - `AGENTIC_CHART_MIN_CHARTS`
  - `AGENTIC_CHART_MAX_CHARTS`
  - `AGENTIC_DASHBOARD_TARGET_MAX_CHARTS`
  - `AGENTIC_DASHBOARD_HARD_MAX_CHARTS`
- [x] Add recommended defaults and migration guidance.

### Current Status
- [x] Phase 40.1 foundation implemented:
  - deterministic dashboard theme extraction
  - dashboard title reason/source metadata
- [x] Phase 40.2 foundation implemented:
  - broader default chart-count limits
  - basic broader table coverage in chart selection
- [x] Additional runtime implemented:
  - final title generation from persisted successful charts only
  - LLM title fallback before deterministic, domain, and table fallback
  - role-based quota selection diagnostics
  - cross-table coverage warnings
  - low-value overexpansion guardrails
  - anomaly consumption of dashboard theme and contribution metadata
- [ ] Pending:
  - deeper omission reasons for every eligible-but-unused table
  - optional richer section summaries
  - broader UI consumption of role-selection diagnostics

---

## Implementation Phases

### Phase 40.1: Dashboard Theme Extraction
- derive cross-table dashboard theme from context, metrics, and scoped tables
- persist theme metadata in dashboard spec

### Phase 40.2: Cross-Table Candidate Expansion
- evaluate eligible chart candidates across all scoped tables
- track table-level and KPI-family-level contributions

### Phase 40.3: Role-Based Composition
- replace a single small chart cap with role quotas and value ranking
- allow 8 to 16 charts when justified

### Phase 40.4: Context-Driven Title Synthesis
- generate dashboard title from theme, selected charts, and KPI-family coverage
- remove raw table-name bias from default title generation

### Phase 40.5: Story Sectioning
- group charts into coherent sections
- persist section metadata for UI and workspace reuse

### Phase 40.6: Quality Gates and Regression
- add warnings and regression checks for:
  - table-derived titles
  - insufficient multi-table coverage
  - low-value overexpansion
  - redundant chart sets

---

## Acceptance Criteria

1. A multi-table scoped deployment can produce a dashboard whose title does not contain the dominant source table name.
2. When multiple scoped tables are eligible, at least 2 tables contribute charts unless quality rules explicitly reject them.
3. Dashboard composition can exceed 10 charts when the role-based planner justifies it.
4. Charts with zero rows or semantic mismatches are excluded from title reasoning and story coverage.
5. Dashboard JSON persists title reasoning, story sections, and table/KPI-family contributions.
6. Dashboard completion payload includes role-selection diagnostics and successful/rejected chart ids.
7. Anomaly planning and synthesis receive dashboard theme, table contributions, and KPI-family contributions.
8. Existing dashboard API consumers continue to work without requiring a new schema.

---

## Recommendation

This phase should be implemented next if the product goal is:
- dashboards that feel domain-aware rather than table-aware
- broader analytical coverage across all selected tables
- richer executive and analyst dashboards without arbitrary small-chart limits

This is the right next step if the current pain is:
- "the dashboard title is just a table name"
- "the dashboard only uses one table even though I selected many"
- "I want a broader, more complete dashboard when the data supports it"
