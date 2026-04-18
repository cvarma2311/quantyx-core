# Phase 55: Data Quality Agentic Workflow, Validation, and Enrichment

## Goal

Create a dedicated agentic process for the `data_quality_observability` domain pack.

The existing agentic deployment APIs and workspace deployment lifecycle should remain the entrypoint. The difference is that when the selected domain pack is data quality, the orchestration should branch into a data-quality-focused workflow instead of the normal business KPI/dashboard workflow.

The workflow should perform:

- data profiling
- completeness and missingness analysis
- validity checks
- referential integrity checks
- duplicate and fuzzy duplicate detection
- freshness and stability checks
- rule execution from user-provided context
- generated Excel quality report
- generated data quality dashboard
- optional data enrichment recommendations
- user-approved enrichment application, later

This phase is the agentic execution companion to Phase 54.

Phase 54 defines the data quality pack and product surface.
Phase 55 defines how the agentic runtime detects that pack, spawns specialized agents, runs validation, produces report/dashboard outputs, and integrates with workspace deployments.

---

## Product Reference

This should be inspired by data trust platforms such as Ataccama (`https://www.ataccama.com/`), especially the pattern of combining:

- automated data quality checks
- monitoring and observability
- anomaly detection
- remediation workflows
- reference data validation
- catalog/lineage context
- a machine-readable data trust layer for downstream agents

The implementation should not attempt to clone any vendor product.
The goal is to bring the same product category into our own agentic framework: validated, scored, explainable, and reviewable data trust.

---

## Target User Experience

### Initial Deployment

The UI starts the same deployment flow it uses today:

```http
POST /workspace/deployments
```

or the existing lower-level:

```http
POST /agentic/runs
```

Request example:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "connection_id": "conn_lpg",
  "database_name": "analytics",
  "schema_name": "public",
  "mode": "full",
  "context_text": "Validate customer and order data. Customer email must be present and valid. order.customer_id must exist in customer.customer_id. Pincode should map to the correct state where possible."
}
```

Backend behavior:

1. Resolve `domain_id`.
2. Load `packs/data_quality_observability`.
3. Detect `pack_type = data_quality`.
4. Start the normal deployment run record and event stream.
5. Route the run into the data quality LangGraph branch.
6. Persist all standard run events, chat logs, artifacts, dashboards, and workspace deployment metadata.

The UI should not need a separate deployment API.

### Output

When the run completes, the user should receive:

- a data quality summary
- a data trust scorecard
- a table/column quality dashboard
- an Excel report file or downloadable export artifact
- rule violation summaries
- referential integrity violations
- missingness findings
- duplicate/fuzzy duplicate candidates
- enrichment opportunities
- questions for enrichment approval or clarification

---

## Why This Needs a Separate Agentic Workflow

The current business-domain workflow is optimized for:

- semantic understanding
- metric generation
- KPI dashboards
- chart narratives
- workspace analytics

Data quality is different.

It needs agents that reason over the data itself:

- Which columns are incomplete?
- Which values are invalid?
- Which records violate rules?
- Which foreign keys fail?
- Which records are likely duplicates?
- Which missing values may be recoverable from trusted references?
- Which datasets are trusted enough for downstream AI and dashboards?

For a data quality domain, business KPI generation should be secondary or skipped. The primary output should be a trust and validation product.

---

## Triggering Rules

The workflow should branch into the data quality graph when any of these are true:

1. `domain_id == "data_quality_observability"`
2. loaded pack has `pack_type: data_quality`
3. loaded pack has `capabilities` containing `data_quality`, `validation`, or `profiling`
4. deployment request explicitly sends `workflow_mode: "data_quality"`

Recommended pack metadata:

```yaml
pack_id: data_quality_observability
pack_type: data_quality
capabilities:
  - profiling
  - validation
  - referential_integrity
  - data_observability
  - quality_dashboard
  - enrichment_recommendations
```

Fallback behavior:

- If the pack cannot be loaded, fail fast with a deployment error.
- If `workflow_mode=data_quality` but the pack is not data-quality capable, return a validation error.
- If the pack is data quality but some optional agents are disabled, complete the run with partial results and clear warnings.

---

## High-Level Architecture

The existing orchestration entrypoint remains:

- `services/ai/agentic_orchestrator.py::run_agentic_workflow`

Add a data-quality routing layer:

```python
if _is_data_quality_pack(domain_id, initial_state):
    return run_data_quality_agentic_workflow(settings, run_id, initial_state, event_callback)
return run_standard_agentic_workflow(settings, run_id, initial_state, event_callback)
```

Recommended new module:

- `services/ai/data_quality_orchestrator.py`

Recommended supporting modules:

- `services/ai/data_quality_agents.py`
- `services/ai/data_quality_profiler.py`
- `services/ai/data_quality_rules.py`
- `services/ai/data_quality_referential_integrity.py`
- `services/ai/data_quality_enrichment.py`
- `services/ai/data_quality_report.py`
- `services/ai/data_quality_dashboard.py`
- `services/ai/data_quality_store.py`

Do not duplicate the generic agentic run system.

Reuse:

- `quantyx_agent_runs`
- `quantyx_agent_run_events`
- `quantyx_agent_chat_logs`
- `quantyx_agent_event_artifacts`
- workspace deployment APIs
- dashboard persistence
- chart persistence
- run event streaming
- pack loading
- scoped connection resolution

Add data-quality-specific stores only for artifacts that need queryable product APIs.

---

## LangGraph / LangChain Orchestration

We should still use LangGraph/LangChain-style orchestration with explicit state and nodes.

### Data Quality Graph

```text
SchemaDiscovery
  -> DataQualityProfiling
  -> RuleExtraction
  -> ReferentialIntegrity
  -> ValidityExecution
  -> MissingnessAnalysis
  -> DuplicateDetection
  -> FreshnessStability
  -> TrustScoring
  -> EnrichmentOpportunityDiscovery
  -> ReportGeneration
  -> DashboardGeneration
  -> WorkspaceHandoff
```

Parallelizable branches:

```text
SchemaDiscovery
  -> DataQualityProfiling
      -> MissingnessAnalysis
      -> DuplicateDetection
      -> FreshnessStability
      -> RuleExtraction
          -> ValidityExecution
          -> ReferentialIntegrity
      -> EnrichmentOpportunityDiscovery
  -> TrustScoring
  -> ReportGeneration + DashboardGeneration
```

### Shared State

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_...",
  "connection_id": "conn_lpg",
  "database_name": "analytics",
  "schema_name": "public",
  "context_text": "...",
  "schema_graph": {},
  "table_profiles": {},
  "column_profiles": {},
  "validation_rules": [],
  "referential_rules": [],
  "validity_results": [],
  "missingness_results": [],
  "duplicate_results": [],
  "freshness_results": [],
  "stability_results": [],
  "trust_scores": {},
  "enrichment_opportunities": [],
  "enrichment_questions": [],
  "report_artifacts": [],
  "dashboard_spec": {},
  "quality_summary": {},
  "errors": [],
  "warnings": []
}
```

### Event Emission

Every agent must emit events through the existing run event stream.

Example:

```json
{
  "run_id": "run_...",
  "agent_name": "DataQualityProfilingAgent",
  "status": "completed",
  "message": "Profiled 18 tables and 243 columns",
  "artifacts": {
    "table_count": 18,
    "column_count": 243,
    "critical_tables": 3
  }
}
```

---

## Agent Design

### 1. DataQualityWorkflowRouter

Role:

- detect whether a deployment should use the data quality graph
- keep normal APIs unchanged
- write a clear run event showing selected workflow

Inputs:

- `domain_id`
- loaded pack metadata
- optional `workflow_mode`

Outputs:

- `workflow_kind = "data_quality"`
- `pack_config`
- `enabled_capabilities`

Quality gates:

- pack must exist
- pack must declare data-quality capability, unless `domain_id` is the built-in data quality pack

---

### 2. DataQualitySchemaAgent

Role:

- reuse schema discovery, but classify tables and relationships for data quality

Responsibilities:

- identify candidate primary keys
- identify candidate foreign keys
- identify reference/code tables
- identify address/location columns
- identify contact fields
- identify dates/timestamps for freshness
- identify columns suitable for governed enrichment
- identify sensitive fields that must not be used for enrichment proposal generation

Outputs:

```json
{
  "tables": [],
  "candidate_primary_keys": [],
  "candidate_foreign_keys": [],
  "reference_tables": [],
  "location_columns": [],
  "contact_columns": [],
  "freshness_columns": [],
  "sensitive_columns": []
}
```

---

### 3. DataQualityProfilingAgent

Role:

- run deeper profiling than the standard workflow

Responsibilities:

- row counts
- null counts
- blank counts
- null percentage
- distinct counts
- uniqueness ratios
- min/max for numeric and date columns
- string length distribution
- common patterns
- top values
- rare values
- malformed-looking values
- value entropy
- candidate key duplicate counts
- table-level freshness
- table-level completeness

This agent can reuse and extend `services/ai/agentic_agents.py::profile_tables`, but should persist a dedicated quality artifact shape.

Outputs:

- table profile artifacts
- column profile artifacts
- high-risk table list
- high-risk column list

---

### 4. DataQualityRuleExtractionAgent

Role:

- extract validation rules from pack config and user context

Rule sources:

1. `packs/data_quality_observability/validation_rules.yml`
2. user `context_text`
3. structured context answers
4. future uploaded rule files
5. inferred rules from schema profiling, with lower confidence

Context examples:

- "Customer email must be present and valid."
- "order.customer_id must exist in customer.customer_id."
- "Pincode should map to the correct state."
- "Invoice amount cannot be negative."
- "Order status must be one of CREATED, SHIPPED, CANCELLED."

Output rule types:

```json
{
  "rules": [
    {
      "rule_id": "dq_rule_...",
      "rule_type": "not_null",
      "severity": "critical",
      "table_name": "customer",
      "column_name": "email",
      "condition_json": {},
      "source": "context_text",
      "confidence": 0.92
    },
    {
      "rule_id": "dq_rule_...",
      "rule_type": "referential_integrity",
      "severity": "critical",
      "table_name": "orders",
      "column_name": "customer_id",
      "reference_table": "customer",
      "reference_column": "customer_id",
      "source": "context_text",
      "confidence": 0.95
    }
  ]
}
```

LLM usage:

- LLM can parse ambiguous natural language into candidate rules.
- Deterministic validation must verify referenced tables/columns exist.
- Low-confidence or unresolved rules remain `pending_review`.

---

### 5. DataValidityAgent

Role:

- execute non-referential validation rules

Rule types:

- `not_null`
- `not_blank`
- `regex_pattern`
- `numeric_range`
- `date_range`
- `allowed_values`
- `disallowed_values`
- `unique`
- `composite_unique`
- `conditional_required`
- `cross_column_consistency`
- `freshness_sla`

Execution requirements:

- generate safe SQL using quoted identifiers
- support table sampling for expensive checks
- support full-table checks where allowed
- return counts, percentages, and sample violating records
- never expose excessive raw PII in events

Output:

```json
{
  "rule_id": "dq_rule_...",
  "status": "failed",
  "checked_row_count": 100000,
  "violation_count": 1250,
  "violation_pct": 1.25,
  "sample_rows": [],
  "severity": "critical"
}
```

---

### 6. ReferentialIntegrityAgent

Role:

- validate relationships between tables

Rule sources:

- declared context rules
- inferred PK/FK candidates
- join graph evidence
- domain pack defaults

Checks:

- orphan foreign keys
- missing referenced keys
- duplicate primary keys
- invalid composite references
- reference table coverage
- unexpected null foreign keys where required

Example SQL pattern:

```sql
SELECT COUNT(*) AS orphan_count
FROM orders o
LEFT JOIN customer c
  ON o.customer_id = c.customer_id
WHERE o.customer_id IS NOT NULL
  AND c.customer_id IS NULL;
```

Outputs:

- relationship health
- orphan counts
- orphan percentages
- sample violating key values
- severity
- recommended remediation owner

---

### 7. MissingnessAnalysisAgent

Role:

- turn null/blank profiling into user-facing quality findings

Responsibilities:

- rank columns by missingness severity
- identify rows with multiple missing critical fields
- detect table-level completeness problems
- compare missingness across entities, dates, or source systems where possible
- identify missingness that blocks business use
- identify missingness that may be enrichable

Output examples:

- `customer.email` is 18.4 percent missing and critical for contactability.
- `customer.state` is 9.1 percent missing but may be derivable from pincode.
- `orders.ship_date` is missing in 3.2 percent of completed orders.

---

### 8. DuplicateDetectionAgent

Role:

- detect exact and likely duplicate records

Checks:

- duplicate candidate primary keys
- duplicate composite business keys
- duplicate normalized names
- fuzzy duplicate clusters for entity-like tables
- duplicate address/contact combinations

Implementation notes:

- start deterministic with exact duplicate groups
- add fuzzy matching only for suitable text columns
- cap large-table work
- persist candidate clusters with confidence and sample records
- phrase fuzzy results as candidates requiring review

Outputs:

```json
{
  "duplicate_groups": [],
  "fuzzy_duplicate_clusters": [
    {
      "cluster_id": "dup_cluster_...",
      "table_name": "customer",
      "match_columns": ["customer_name", "pincode"],
      "confidence": 0.84,
      "candidate_record_count": 3,
      "sample_values": []
    }
  ]
}
```

---

### 9. FreshnessAndStabilityAgent

Role:

- measure whether data is current and stable enough to trust

Freshness checks:

- latest timestamp per table
- lag from current time
- lag from expected SLA
- tables with no usable freshness column

Stability checks:

- row count change compared to prior snapshots
- null percentage change
- distinct ratio change
- category distribution shift
- new unexpected values

Initial implementation can compute freshness immediately and defer full drift until historical snapshots exist.

---

### 10. DataTrustScoringAgent

Role:

- compute explainable trust scores for tables, columns, and the overall deployment

Score components:

- completeness
- validity
- uniqueness
- referential integrity
- freshness
- duplicate risk
- stability
- enrichment readiness

Output:

```json
{
  "overall_trust_score": 82.4,
  "tables": [
    {
      "table_name": "customer",
      "trust_score": 71.2,
      "band": "warning",
      "components": {
        "completeness": 78.5,
        "validity": 91.0,
        "referential_integrity": 88.0,
        "duplicate_risk": 54.0,
        "freshness": 100.0
      }
    }
  ]
}
```

Rules:

- scores must be deterministic
- weights should come from pack config
- every score must include component explanations
- avoid black-box "AI trust score" language

Implemented status:

- Trust scoring now runs after:
  - duplicate detection
  - freshness/stability analysis
  - validation/referential rules
  - enrichment opportunity discovery
- Persisted table trust now includes component-level scores for:
  - completeness
  - validity
  - uniqueness
  - referential_integrity
  - freshness
  - duplicate_risk
  - stability
  - enrichment_readiness
- Table artifact `summary_json` now stores:
  - `trust_components`
  - `trust_component_explanations`
- Dashboard/report/API now read the persisted trust score rather than relying only on profiling-time trust.

---

### 11. DataEnrichmentOpportunityAgent

Role:

- identify missing values that may be safely recoverable from existing columns and row context

This agent does not directly mutate source data.
It proposes enrichment opportunities and questions for user approval.

Supported initial enrichment types:

- country from state/pincode/postal code
- state/province from pincode/postal code
- city from pincode/postal code
- country code normalization
- state code normalization
- canonical label normalization
- code-to-label derivation
- cross-column derivation
- temporal derivation
- latitude/longitude from full address, later and only if approved
- generic code/label normalization, later if a governed internal mapping source is available

Candidate column detection:

- column names like `country`, `country_code`, `state`, `state_code`, `province`, `city`, `postal_code`, `postcode`, `pincode`, `zip`
- generic address columns
- non-sensitive categorical code fields
- generic categorical columns like `status`, `gender`, `category`, `type`
- derived targets like `full_name`, `display_name`, `order_year`, `order_month`, `order_quarter`

Hard exclusions:

- names, phone numbers, emails, national IDs, account IDs, payment fields
- free-text notes
- high-cardinality identifiers
- anything marked sensitive by policy

Output:

```json
{
  "opportunity_id": "dq_enrich_...",
  "table_name": "customer",
  "target_column": "state",
  "target_column_alias": "state",
  "source_columns": ["pincode", "country"],
  "source_column_aliases": ["postal_code", "country"],
  "missing_count": 1240,
  "candidate_method": "postal_context_inference",
  "confidence": 0.87,
  "requires_user_approval": true,
  "question": "Can we use existing row context to propose missing customer.state values from pincode and country?"
}
```

Alias handling requirement:

- canonical normalization must not rename or mutate physical source columns
- backend should carry canonical semantic aliases alongside the physical column names
- examples:
  - `pincode` -> alias `postal_code`
  - `province` -> alias `state`
  - `status_label` -> alias `status`
- proposal payloads, staged artifacts, and UI contracts should expose both:
  - physical column name
  - canonical alias

Currently implemented candidate methods:

- `postal_context_inference`
- `location_hierarchy_inference`
- `country_code_normalization`
- `state_code_normalization`
- `canonical_label_normalization`
- `code_to_label_derivation`
- `cross_column_derivation`
- `temporal_derivation`

---

### 12. DataEnrichmentResearchAgent

Role:

- generate row-level fill proposals after the user approves LLM-based enrichment for a specific opportunity

Important constraints:

- no internet/provider lookup in this phase
- no PII should be sent outside the workspace database and configured LLM call path
- proposals must be based on row context, table context, user context, and same-table examples
- every proposal generation step must record model/evidence metadata, timestamp, and confidence
- fetched data must be stored as proposed enrichment, not applied correction
- user must approve before any writeback/export patch is generated

Example approval request:

```json
{
  "opportunity_id": "dq_enrich_...",
  "approved_by": "user@example.com",
  "max_records": 500
}
```

Output:

```json
{
  "proposal_id": "dq_enrich_prop_...",
  "opportunity_id": "dq_enrich_...",
  "status": "proposed",
  "matched_count": 480,
  "unmatched_count": 20,
  "source_references": [
    {
      "provider": "llm_context_inference",
      "retrieved_at": "2026-04-18T10:00:00Z"
    }
  ],
  "sample_proposed_values": []
}
```

---

### 13. DataQualityReportAgent

Role:

- generate a detailed Excel report and machine-readable report artifact

Report format:

- `.xlsx` as preferred export
- JSON report as canonical persisted artifact
- optional CSV exports per sheet later

Recommended workbook sheets:

1. `Executive Summary`
2. `Trust Scorecard`
3. `Table Quality`
4. `Column Quality`
5. `Missing Data`
6. `Validation Rules`
7. `Rule Violations`
8. `Referential Integrity`
9. `Duplicates`
10. `Fuzzy Duplicate Candidates`
11. `Freshness`
12. `Stability`
13. `Enrichment Opportunities`
14. `Recommended Actions`

Workbook requirements:

- include run metadata
- include tenant/domain/scope
- include generated timestamp
- include severity bands
- include filters/frozen headers
- include source rule IDs
- include sample rows only within configured privacy limits

Recommended library:

- `openpyxl` or `xlsxwriter`

Storage:

- write local generated artifact during run
- persist metadata in DB
- expose download through a report artifact endpoint

---

### 14. DataQualityDashboardAgent

Role:

- generate dashboards from data quality artifacts, not business fact metrics

Dashboard set:

- Data Trust Scorecard
- Missingness and Completeness Dashboard
- Validation Rule Failures Dashboard
- Referential Integrity Dashboard
- Duplicate Risk Dashboard
- Freshness and Stability Dashboard
- Enrichment Opportunity Dashboard
- Recommended Actions Dashboard

Dashboard chart examples:

- trust score by table
- columns by null percentage
- rule failures by severity
- orphan foreign key count by relationship
- duplicate risk by table
- stale tables by freshness lag
- enrichment opportunities by target column

Rules:

- mark dashboards as `dashboard_type = data_quality`
- do not mix data quality metrics with business KPI metrics
- use persisted quality artifacts as source data
- make dashboard discoverable separately from business dashboards

---

### 15. WorkspaceHandoffAgent

Role:

- make the completed data quality run usable in the workspace

Responsibilities:

- create workspace memory summary
- expose report/dashboard links
- expose top issues
- expose pending enrichment questions
- allow conversation follow-ups against the quality artifacts

Backend support now includes a question-centric enrichment API layer:

- `GET /data-quality/enrichment/questions`
- `POST /data-quality/enrichment/questions/{opportunity_id}/answer`
- `GET /data-quality/runs/{run_id}/hydration` for consolidated run reload state

Answer actions:

- `approve` -> generate proposal immediately using the existing LLM enrichment proposal flow
- `defer` -> keep the question visible but marked as deferred
- `reject` -> explicitly decline the enrichment path
- `reopen` -> move a deferred/rejected question back to pending review

Recommended run-reload pattern:

1. load the deployment timeline / run events
2. call `GET /data-quality/runs/{run_id}/hydration`

The hydration payload is intended to give the UI enough state to render:

- workflow banner
- top pending rule-review items
- top pending enrichment questions
- remediation summary
- artifact links

Example user questions after deployment:

- "Which table has the worst data quality?"
- "Show missing columns for customer."
- "Why is customer trust score low?"
- "Which referential integrity rules failed?"
- "What enrichment opportunities need approval?"
- "Generate a remediation task list for critical issues."

---

## Data Model Additions

Phase 54 already recommends dedicated quality artifacts.
Phase 55 should make them workflow-ready.

### `quantyx_data_quality_runs`

Purpose:

- one summary record per data quality workflow run

Fields:

```sql
CREATE TABLE IF NOT EXISTS public.quantyx_data_quality_runs (
  quality_run_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  connection_id TEXT NULL,
  database_name TEXT NULL,
  schema_name TEXT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  overall_trust_score NUMERIC NULL,
  summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ NULL
);
```

### `quantyx_data_quality_table_artifacts`

Purpose:

- queryable table-level quality results

Fields:

- `artifact_id`
- `quality_run_id`
- `run_id`
- `tenant_id`
- `domain_id`
- `connection_id`
- `database_name`
- `schema_name`
- `table_name`
- `row_count`
- `trust_score`
- `completeness_score`
- `validity_score`
- `uniqueness_score`
- `referential_integrity_score`
- `freshness_score`
- `duplicate_risk_score`
- `severity`
- `summary_json`
- `created_at`

### `quantyx_data_quality_column_artifacts`

Purpose:

- column-level profiling and quality results

Fields:

- `artifact_id`
- `quality_run_id`
- `table_name`
- `column_name`
- `data_type`
- `null_count`
- `null_pct`
- `blank_count`
- `blank_pct`
- `distinct_count`
- `distinct_ratio`
- `validity_score`
- `column_trust_score`
- `top_values_json`
- `pattern_summary_json`
- `quality_flags_json`

### `quantyx_data_quality_rules`

Purpose:

- persisted validation rules from pack/context/inference

Fields:

- `rule_id`
- `quality_run_id`
- `tenant_id`
- `domain_id`
- `rule_type`
- `severity`
- `table_name`
- `column_name`
- `reference_table`
- `reference_column`
- `condition_json`
- `source`
- `confidence`
- `status`
- `created_at`

### `quantyx_data_quality_rule_results`

Purpose:

- execution results for rules

Fields:

- `result_id`
- `rule_id`
- `quality_run_id`
- `status`
- `checked_row_count`
- `violation_count`
- `violation_pct`
- `sample_rows_json`
- `error_message`
- `executed_at`

### `quantyx_data_quality_duplicate_candidates`

Purpose:

- exact and fuzzy duplicate candidates

Fields:

- `candidate_id`
- `quality_run_id`
- `table_name`
- `duplicate_type`
- `match_columns_json`
- `confidence`
- `candidate_record_count`
- `sample_rows_json`
- `cluster_json`
- `review_status`

### `quantyx_data_quality_enrichment_opportunities`

Purpose:

- user-reviewable enrichment opportunities

Fields:

- `opportunity_id`
- `quality_run_id`
- `tenant_id`
- `domain_id`
- `table_name`
- `target_column`
- `source_columns_json`
- `missing_count`
- `candidate_method`
- `requires_user_approval`
- `confidence`
- `question`
- `status`
- `created_at`

### `quantyx_data_quality_enrichment_proposals`

Purpose:

- proposed enrichment values after approved staged proposal generation

Fields:

- `proposal_id`
- `opportunity_id`
- `quality_run_id`
- `status`
- `matched_count`
- `unmatched_count`
- `source_references_json`
- `proposed_values_json`
- `approved_by`
- `approved_at`
- `created_at`

### `quantyx_data_quality_reports`

Purpose:

- report export metadata

Fields:

- `report_id`
- `quality_run_id`
- `run_id`
- `tenant_id`
- `domain_id`
- `report_type`
- `file_name`
- `mime_type`
- `storage_uri`
- `summary_json`
- `created_at`

---

## API Surface

The standard deployment APIs remain the frontend entrypoint.
Add data-quality-specific APIs for reading results, reports, and enrichment workflows.

### 1. Start Data Quality Deployment

Use existing API:

```http
POST /workspace/deployments
```

Request:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "connection_id": "conn_lpg",
  "database_name": "analytics",
  "schema_name": "public",
  "mode": "full",
  "context_text": "Validate order.customer_id against customer.customer_id. Customer email must be present and valid."
}
```

Response:

```json
{
  "run_id": "run_...",
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "status": "queued",
  "workflow_kind": "data_quality"
}
```

### 2. Stream Run Progress

Use existing API:

```http
GET /agentic/runs/{run_id}/stream
```

Data quality agent names should appear in the stream:

- `DataQualitySchemaAgent`
- `DataQualityProfilingAgent`
- `DataQualityRuleExtractionAgent`
- `ReferentialIntegrityAgent`
- `DataValidityAgent`
- `MissingnessAnalysisAgent`
- `DuplicateDetectionAgent`
- `DataTrustScoringAgent`
- `DataQualityReportAgent`
- `DataQualityDashboardAgent`

### 3. Get Data Quality Run Summary

```http
GET /data-quality/runs/{run_id}
```

Response:

```json
{
  "quality_run_id": "dqrun_...",
  "run_id": "run_...",
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "status": "completed",
  "overall_trust_score": 82.4,
  "critical_issue_count": 7,
  "warning_issue_count": 18,
  "dashboard_id": "dash_...",
  "dashboard_title": "Data Quality Observability Data Quality Dashboard",
  "enrichment_opportunity_count": 4,
  "artifacts": {
    "dashboard": "/data-quality/runs/run_.../dashboard",
    "excel_report": "/data-quality/reports/run_.../excel?...",
    "remediation": "/data-quality/remediation?..."
  },
  "remediation_summary": {
    "action_count": 9,
    "critical_action_count": 3
  },
  "recommended_actions": [
    {
      "priority": "critical",
      "action_type": "freshness_recovery",
      "title": "Restore freshness for customer"
    }
  ],
  "summary": {
    "profiled_tables": 18,
    "profiled_columns": 243,
    "failed_rules": 5,
    "referential_violations": 2,
    "enrichment_opportunities": 4
  }
}
```

Current backend behavior:

- `dashboard_id`, `dashboard_title`, and `dashboard_chart_count` are written into `quantyx_data_quality_runs.summary_json` when the dashboard agent completes.
- `enrichment_opportunity_count` is written into `quantyx_data_quality_runs.summary_json` when the enrichment discovery agent completes.
- The run summary API now returns these fields directly.
- The run summary API also returns artifact links plus a small remediation preview so the UI can render the next actions without making a second fetch immediately after run completion.

### 4. List Table Quality

```http
GET /data-quality/tables?tenant_id={TENANT_ID}&domain_id=data_quality_observability&run_id={RUN_ID}
```

Response:

```json
{
  "tables": [
    {
      "table_name": "customer",
      "row_count": 100000,
      "trust_score": 71.2,
      "severity": "warning",
      "duplicate_candidate_count": 18,
      "enrichment_opportunity_count": 2
    }
  ]
}
```

### 5. Get Table Detail

```http
GET /data-quality/tables/{table_name}?tenant_id={TENANT_ID}&domain_id=data_quality_observability&run_id={RUN_ID}
```

Response:

```json
{
  "table_name": "customer",
  "trust_score": 71.2,
  "components": {
    "completeness": 78.5,
    "validity": 91.0,
    "uniqueness": 92.0,
    "referential_integrity": 88.0,
    "duplicate_risk": 54.0,
    "freshness": 100.0,
    "stability": 96.0,
    "enrichment_readiness": 90.0
  },
  "trust_component_explanations": {},
  "columns": [],
  "failed_rules": [],
  "duplicate_candidates": [],
  "enrichment_opportunities": []
}
```

Implemented status:

- `GET /data-quality/tables` now includes per-table `duplicate_candidate_count` and `enrichment_opportunity_count`.
- `GET /data-quality/tables/{table_name}` now includes:
  - `components`
  - `failed_rules`
  - `duplicate_candidates`
  - `enrichment_opportunities`

### 6. List Rule Results

```http
GET /data-quality/rules?tenant_id={TENANT_ID}&domain_id=data_quality_observability&run_id={RUN_ID}&status=failed
```

Response:

```json
{
  "rules": [
    {
      "rule_id": "dq_rule_...",
      "rule_type": "referential_integrity",
      "source_text": "orders.customer_id must exist in customer.customer_id",
      "executor_kind": "deterministic_sql",
      "execution_plan": {
        "validation_sql": "SELECT ...",
        "sample_sql": "SELECT ..."
      },
      "severity": "critical",
      "table_name": "orders",
      "column_name": "customer_id",
      "reference_table": "customer",
      "reference_column": "customer_id",
      "status": "failed",
      "violation_count": 842,
      "violation_pct": 0.84
    }
  ]
}
```

Implemented status:

- Plain-English user rules are now persisted with:
  - `source_text`
  - `executor_kind`
  - `execution_plan`
- The backend stores canonical structured rule JSON as the execution source of truth.
- Execution remains backend-driven and SQL-backed; Python executor code is not stored as rule data.

### 6A. List Duplicate Candidates

```http
GET /data-quality/duplicates?tenant_id={TENANT_ID}&domain_id=data_quality_observability&run_id={RUN_ID}
```

Response:

```json
{
  "duplicates": [
    {
      "candidate_id": "dqdup_...",
      "table_name": "customer",
      "duplicate_type": "exact_key_duplicate",
      "match_columns_json": ["customer_id"],
      "confidence": 0.99,
      "candidate_record_count": 4,
      "sample_rows_json": [],
      "cluster_json": {},
      "review_status": "needs_review"
    }
  ]
}
```

### 6B. List Freshness and Stability Results

```http
GET /data-quality/freshness?tenant_id={TENANT_ID}&domain_id=data_quality_observability&run_id={RUN_ID}
```

Response:

```json
{
  "freshness": [
    {
      "table_name": "customer",
      "freshness_column": "updated_at",
      "latest_timestamp": "2026-04-18T10:00:00Z",
      "freshness_lag_days": 9.0,
      "freshness_score": 55.0,
      "freshness_status": "stale",
      "baseline_quality_run_id": "dqrun_prev",
      "baseline_row_count": 90000,
      "row_count_change_pct": 33.33,
      "baseline_completeness_score": 95.0,
      "completeness_score_change": -15.0,
      "stability_status": "changed",
      "stability_issues": ["row_count_change_pct>20", "completeness_score_change>10"]
    }
  ]
}
```

### 6C. Explainable Evidence APIs

All DQ metrics, charts, and issue counts should support drill-through to the backing evidence.

Implemented endpoints:

```http
GET /data-quality/evidence/missingness?tenant_id={TENANT_ID}&run_id={RUN_ID}&table_name={TABLE}&column_name={COLUMN}
GET /data-quality/evidence/rules/{rule_id}?tenant_id={TENANT_ID}
GET /data-quality/evidence/duplicates/{candidate_id}?tenant_id={TENANT_ID}
GET /data-quality/evidence/freshness/{table_name}?tenant_id={TENANT_ID}&run_id={RUN_ID}
GET /data-quality/evidence/enrichment/{proposal_id}?tenant_id={TENANT_ID}
```

Behavior:

- missingness evidence returns backing source rows for null/blank records
- rule evidence returns persisted rule metadata plus sample/backing evidence rows when available
- duplicate evidence returns cluster metadata plus backing rows for exact duplicate candidates
- freshness evidence returns current vs baseline comparison payload
- enrichment evidence returns proposed/staged rows and source references

This is the backend path that supports UI drill-through for counts like:

- `290 missing records`
- `842 referential integrity violations`
- `18 duplicate candidates`
- `3 stale tables`

### 6D. Remediation Actions

```http
GET /data-quality/remediation?tenant_id={TENANT_ID}&domain_id=data_quality_observability&run_id={RUN_ID}
```

Response:

```json
{
  "summary": {
    "action_count": 9,
    "critical_action_count": 3,
    "warning_action_count": 5,
    "info_action_count": 1
  },
  "actions": [
    {
      "priority": "critical",
      "action_type": "missingness_backfill",
      "title": "Backfill missing values in customer.email",
      "table_name": "customer",
      "column_name": "email",
      "issue_summary": "email is 35.0% null and 0.0% blank.",
      "recommended_action": "Backfill or enrich customer.email before publishing downstream records.",
      "owner_hint": "Data steward",
      "evidence_type": "missingness",
      "evidence_path": "/data-quality/evidence/missingness?...",
      "trust_component": "completeness"
    }
  ]
}
```

Behavior:

- remediation is derived server-side from persisted trust components, failed rules, duplicate candidates, freshness/stability findings, and enrichment opportunities
- each remediation row carries an explainable evidence path so the UI can drill into the backing rows or artifact
- the dashboard now includes a `Recommended Actions` section
- the Excel report now includes a `Recommended Actions` sheet
- workspace remediation answers now read from this backend-derived action list

### 7. Download Excel Report

```http
GET /data-quality/reports/{run_id}/excel?tenant_id={TENANT_ID}&domain_id=data_quality_observability
```

Response:

- `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- `Content-Disposition: attachment; filename="data_quality_{run_id}.xlsx"`

Implementation status:

- The backend generates the workbook on demand from persisted data-quality tables.
- No raw source data is exported by default; the report contains profiling summaries, column quality metrics, rule definitions, latest rule execution results, and stored violation samples from `quantyx_data_quality_rule_results.sample_rows_json`.
- Each download writes a metadata row to `quantyx_data_quality_reports` with `report_type=excel`, the generated file name, MIME type, and summary counts.
- Current report sheets:
  - `Executive Summary`
  - `Trust Scorecard`
  - `Table Quality`
  - `Column Quality`
  - `Validation Rules`
  - `Rule Violations`
  - `Freshness`
  - `Duplicates`
  - `Recommended Actions`
- The workbook now also includes enrichment export sheets when staged overlay artifacts exist:
  - `Enrichment Summary`
  - `Staged Enrichment`
  - one `Published {table}` sheet per enriched table
- Enriched cells are color-coded in the workbook:
  - green for deterministic approved fills
  - blue for LLM-approved fills
  - yellow for deferred rows
- In `Published {table}` sheets, the original row context and enriched target value appear in the same row grid, with the enriched target cell highlighted.
- The workbook is rendered from DB artifacts at API-call time. It is not currently stored as a binary file in object storage; `storage_uri` remains optional for a later persisted-download implementation.

### 7A. Get Dashboard for Run

```http
GET /data-quality/runs/{run_id}/dashboard
```

Response:

```json
{
  "run_id": "run_...",
  "dashboard_id": "db_...",
  "dashboard_type": "data_quality",
  "title": "Data Quality Observability Data Quality Dashboard",
  "quality_score": 82.4,
  "quality_gate_passed": false,
  "chart_plan": []
}
```

Implementation status:

- The dashboard is generated automatically during the DQ workflow by `DataQualityDashboardAgent`.
- The persisted dashboard uses `dashboard_type = data_quality`.
- Current chart plan sections:
  - Data Trust Score by Table
  - Columns with Highest Missingness
  - Validation Rule Failures
  - Referential Integrity Violations
  - Duplicate Risk by Table
  - Freshness Lag by Table

### 8. List Enrichment Opportunities

```http
GET /data-quality/enrichment/opportunities?tenant_id={TENANT_ID}&domain_id=data_quality_observability&run_id={RUN_ID}
```

Response:

```json
{
  "opportunities": [
    {
      "opportunity_id": "dq_enrich_...",
      "table_name": "customer",
      "target_column": "state",
      "source_columns": ["pincode", "country"],
      "missing_count": 1240,
      "confidence": 0.87,
      "question": "Can we use existing row context to propose missing customer.state values from pincode and country?",
      "status": "needs_user_approval"
    }
  ]
}
```

Current backend behavior:

- Enrichment opportunities are discovered automatically during the DQ workflow by `DataEnrichmentOpportunityAgent`.
- Current deterministic discovery focuses on location-style columns and normalization candidates:
  - `country` from `country_code`, `state`, `postal_code`
  - `country_code` from `country`
  - `state` from `postal_code` plus optional `country`
  - `state_code` from `state`
  - `city` from `postal_code` or `state` plus country context
- Sensitive columns such as emails, phones, names, account/payment identifiers are excluded from discovery.
- Discovered opportunities are persisted to `quantyx_data_quality_enrichment_opportunities` with `status=needs_user_approval`.
- These opportunities are now treated as LLM/context-completion candidates, not internet lookups.

### 9. Approve Enrichment Research

```http
POST /data-quality/enrichment/opportunities/{opportunity_id}/approve-research
```

Request:

```json
{
  "tenant_id": "VC_101",
  "approved_by": "ui:user",
  "max_records": 500
}
```

Response:

```json
{
  "opportunity_id": "dq_enrich_...",
  "status": "proposal_generated",
  "proposal_id": "dq_enrich_prop_...",
  "matched_count": 480,
  "unmatched_count": 20
}
```

Current backend behavior:

- `approve-research` is implemented as an immediate backend proposal-generation step.
- It resolves the original source connection, fetches rows with missing target values plus supporting source columns, and builds row-level proposals.
- Proposal generation is:
  - deterministic exact-match from same-table non-missing examples when possible
  - LLM-based context inference for unresolved rows
- It creates a row in `quantyx_data_quality_enrichment_proposals` and updates the opportunity status to `proposal_generated`.

### 10. Review Enrichment Proposal

```http
GET /data-quality/enrichment/proposals/{proposal_id}
```

Response:

```json
{
  "proposal_id": "dq_enrich_prop_...",
  "opportunity_id": "dq_enrich_...",
  "status": "proposed",
  "matched_count": 480,
  "unmatched_count": 20,
  "source_references": [],
  "sample_proposed_values": [],
  "summary": {
    "total_candidate_rows": 500,
    "confidence_buckets": {
      "auto_approve": 220,
      "high_confidence": 180,
      "needs_review": 80
    },
    "grouped_values": [
      {
        "proposed_value": "Karnataka",
        "row_count": 140
      }
    ]
  }
}
```

Current backend behavior:

- Proposal detail is backed directly by `quantyx_data_quality_enrichment_proposals`.
- `proposed_values_json` now stores row-level proposal entries with row reference, source values, proposed value, confidence, rationale, and method.
- `source_references_json` records deterministic and LLM evidence metadata for the proposal build.
- The read API returns confidence buckets, grouped values, and sample rows so the UI can support bulk approval rather than row-by-row approval.

### 11. Approve Enrichment Application

Initial implementation should not write back to source tables.

Instead, approving application should create one of:

- export patch file
- remediation task list
- staged enrichment overlay table

```http
POST /data-quality/enrichment/proposals/{proposal_id}/approve-application
```

Request:

```json
{
  "tenant_id": "VC_101",
  "approved_by": "data_steward:user",
  "application_mode": "staged_overlay",
  "approval_scope": "high_confidence",
  "min_confidence": 0.85,
  "reason": "Reviewed postal reference matches"
}
```

Response:

```json
{
  "proposal_id": "dq_enrich_prop_...",
  "status": "approved_for_staging",
  "approval_scope": "high_confidence",
  "confidence_threshold": 0.85,
  "approved_row_count": 400,
  "deferred_row_count": 80,
  "staged_artifact_id": "dq_stage_..."
}
```

Current backend behavior:

- Approving application updates proposal status to `approved_for_staging` and records `approved_by` / `approved_at`.
- It does not write back to source tables.
- Approval is proposal-level and threshold-based, not row-by-row.
- Supported scopes:
  - `deterministic_only`
  - `high_confidence`
  - `all`
- The backend now persists a staged overlay artifact in `quantyx_agent_event_artifacts` linked to the proposal run.
- The artifact stores:
  - proposal metadata
  - approval policy and threshold
  - approved row payload
  - deferred row payload
  - summary samples

### 11A. Get Staged Overlay Artifact

```http
GET /data-quality/enrichment/proposals/{proposal_id}/staged-artifact
```

Response:

```json
{
  "artifact_id": "artifact_...",
  "event_id": "event_...",
  "logical_event_id": "dq_stage::dq_enrich_prop_...",
  "run_id": "run_...",
  "proposal_id": "dq_enrich_prop_...",
  "status": "approved_for_staging",
  "approved_row_count": 400,
  "deferred_row_count": 80,
  "approval_scope": "high_confidence",
  "confidence_threshold": 0.85,
  "raw_json": {}
}
```

Current backend behavior:

- The UI can fetch the exact persisted staged overlay artifact by `proposal_id`.
- This avoids needing event-id knowledge on the UI side.
- `raw_json` contains the approved rows, deferred rows, proposal metadata, and summary samples used by the report/export flow.

---

## UI Flow

### Automatic Flow

1. User selects `Data Quality Observability` domain pack.
2. UI starts `/workspace/deployments` as usual.
3. UI streams `/agentic/runs/{run_id}/stream`.
4. UI shows data-quality-specific progress steps.
5. UI opens generated data quality dashboard when run completes.
6. UI exposes Excel report download.
7. UI shows top critical issues and enrichment opportunities.

### Manual Review Flow

#### Rule Interpretation Review Before First Execution

This is the preferred governance-friendly flow for plain-English validation rules.

Flow:

1. User submits plain-English validation rules during deployment or later through semantic intake.
2. Backend stores the raw rule text and extracts candidate structured rules.
3. Backend classifies interpreted rules into:
   - `accepted_auto`
   - `needs_review`
   - `unsupported`
4. UI opens a `Rule Interpretation Review` step before full rule execution.
5. User reviews only the ambiguous or low-confidence rules.
6. Backend activates the reviewed rule set.
7. Then the DQ run executes using the approved interpretation set.

Preferred execution order:

- submit rules
- interpret rules
- review ambiguous rules
- approve reviewed rule set
- execute rules

Current backend behavior:

- the first DQ deployment run now pauses in `awaiting_rule_review` when any extracted rule lands in `needs_review` or `unsupported`
- no validation rules execute in that case, including auto-accepted rules
- `quantyx_data_quality_runs.status` and the outer run status both move to `awaiting_rule_review`
- the run summary exposes:
  - `rule_review_required`
  - `review_queue_pending_count`
  - `active_rule_count`
  - `needs_review_rule_count`
  - `unsupported_rule_count`
  - `workflow_status`
- once review is complete, UI calls the dedicated resume endpoint and the workflow continues from:
  - approved rule execution
  - enrichment discovery
  - trust scoring
  - dashboard generation
  - final run completion

Manual review / resume APIs:

- `GET /data-quality/rules/review-queue?tenant_id={tenant_id}&domain_id=data_quality_observability&run_id={run_id}`
- `GET /data-quality/rules/{rule_id}/review`
- `POST /data-quality/rules/{rule_id}/review`
- `POST /data-quality/runs/{run_id}/resume-after-rule-review`

Recommended UI orchestration:

1. Start deployment as usual.
2. Poll or stream the run until it reaches `awaiting_rule_review`.
3. Open the rule review queue immediately.
4. Let the user approve, edit, or reject each reviewable rule.
5. When the queue is empty, enable `Start Validation Run`.
6. Call `POST /data-quality/runs/{run_id}/resume-after-rule-review`.
7. Continue normal run progress and artifact rendering.

UI requirements for the review screen:

- show summary counts:
  - total submitted
  - auto-accepted
  - needs review
  - unsupported
- allow the user to proceed with accepted rules while explicitly reviewing ambiguous ones
- avoid exposing internal rule engine terms such as `rule_type` or `executor_kind` as primary UI controls

#### Rule Detail Drawer / Modal

For each ambiguous or low-confidence rule, the UI should open a detail drawer or modal that shows:

- source text
- structured interpretation
- SQL preview
- confidence
- ambiguity explanation
- user action buttons

SQL preview requirement:

- SQL preview should always be present in the rule review experience
- the backend should attempt to generate the preview with the LLM first
- if the LLM preview is missing, invalid, or fails validation, backend should fall back to deterministic SQL compilation where supported
- if neither path can produce executable preview SQL, the rule should remain reviewable but must be marked clearly as `preview_unavailable`
- the SQL preview shown to the user should be the candidate execution plan, not hidden backend-only metadata

Recommended user actions:

- `Accept`
- `Edit text`
- `Confirm mapping`
- `Reject`

The purpose of this step is to correct interpretation before execution rather than after a misleading DQ run has already completed.

#### Enrichment Review After Run

1. User opens `Enrichment Opportunities`.
2. User reviews why a column is enrichable.
3. User approves LLM-based proposal generation for a specific opportunity.
4. Backend fetches source rows plus same-table examples and creates staged proposals.
5. User reviews proposed values, confidence buckets, and source provenance.
6. User approves staging/export.
7. Source data writeback remains a later controlled feature.

---

## Context-Driven Validation Rules

The user should be able to provide validation rules in plain English during deployment or later through semantic intake.

Examples:

- "Customer email must be present and match an email pattern."
- "Invoice amount must be greater than or equal to zero."
- "Order date cannot be in the future."
- "Each order.customer_id must exist in customer.customer_id."
- "Status must be one of Open, Closed, Cancelled."
- "If country is India, pincode must be six digits."

Backend behavior:

1. LLM extracts candidate rules.
2. Deterministic resolver maps table/column references.
3. Rule validator checks referenced tables/columns exist.
4. Interpreted rules are classified into:
   - `accepted_auto`
   - `needs_review`
   - `unsupported`
5. Preferred product flow: ambiguous or low-confidence rules are reviewed before first execution.
6. Accepted rules are activated into the execution set.
7. Then valid rules are executed.
8. Results are included in report and dashboard.

The UI should not ask users to select internal rule types unless they are in an advanced admin screen.

Preferred manual-governance UI behavior:

- show a batch review summary first
- let users open a rule detail drawer/modal for ambiguous rules
- show source text, structured interpretation, SQL preview, confidence, and ambiguity explanation
- let users accept, edit, confirm mapping, or reject before rule execution starts

Current backend status:

- low-confidence rules are now classified into reviewable statuses during rule extraction
- active rules execute immediately
- reviewable rules are persisted but skipped until approved
- backend now exposes:
  - `GET /data-quality/rules/review-queue`
  - `GET /data-quality/rules/{rule_id}/review`
  - `POST /data-quality/rules/{rule_id}/review`
- approve/edit/reject is now supported in backend, and approved rules can be executed after review
- the fully productized "pause deployment before first execution until review completes" UI flow is still a later orchestration step

---

## Referential Integrity Requirements

The workflow must support explicit and inferred referential integrity checks.

Explicit context rule:

```text
orders.customer_id must exist in customer.customer_id
```

Generated rule:

```json
{
  "rule_type": "referential_integrity",
  "table_name": "orders",
  "column_name": "customer_id",
  "reference_table": "customer",
  "reference_column": "customer_id",
  "severity": "critical"
}
```

Metrics:

- checked row count
- orphan row count
- orphan percentage
- null foreign key count
- referenced key duplicate count
- sample orphan keys

Dashboard:

- worst relationships by orphan percentage
- critical referential failures
- relationship health map

---

## Enrichment Safety Model

Data enrichment is powerful and risky.
It must be explicitly governed from the beginning.

### Allowed Without External Lookup

- derive missing state from existing pincode using an already configured local reference table
- normalize casing or whitespace in staged output
- identify missing values and ask user questions

### Requires User Approval

- geocoding
- generating proposed values for missing fields
- staging enrichment overlays

### Not Allowed Initially

- direct source table mutation
- sending PII outside the governed database/LLM execution path
- enrichment based on untrusted web pages without provenance
- overwriting existing non-null values
- applying fuzzy duplicate merges automatically

### Provenance Requirements

Every enrichment proposal must include:

- source method / model metadata
- lookup timestamp
- input fields used
- confidence
- matched/unmatched counts
- sample proposed values
- approval trail

---

## Dashboard Requirements

Data quality dashboards should use the same dashboard and chart persistence layer, but must be clearly typed.

Required metadata:

```json
{
  "dashboard_type": "data_quality",
  "domain_id": "data_quality_observability",
  "source_run_id": "run_...",
  "quality_run_id": "dqrun_..."
}
```

Recommended charts:

- Overall Trust Score
- Table Trust Score Ranking
- Critical Rule Failures
- Missingness by Column
- Tables with Most Rows Containing Nulls
- Referential Integrity Failures
- Duplicate Risk
- Freshness Lag
- Enrichment Opportunities

Dashboard should answer:

- Can this data be trusted?
- Which tables need attention first?
- Which rules are failing?
- What missing values are most damaging?
- Which relationships are broken?
- What can be enriched safely?

Explainability requirements:

- Every dashboard/chart/score/issue count must be explainable.
- If the UI shows an aggregate like `290 missing records`, the backend must be able to return the underlying evidence rows that produced that number.
- Every visual should support drill-through or linked evidence for:
  - source table
  - source column
  - rule or detection logic used
  - sample rows
  - full underlying row set through API pagination or export
- The dashboard layer must not produce opaque counts without a path to the backing artifacts.
- Explainability applies to:
  - trust scores
  - missingness counts
  - rule failures
  - referential integrity violations
  - duplicate candidates
  - freshness/stability findings
  - enrichment proposals

Backend expectation:

- each chart/issue metric should be traceable to persisted artifacts or staged evidence
- APIs should support fetching both:
  - aggregate summary
  - underlying detailed rows
- report/dashboard/workspace responses should carry enough identifiers to open the underlying evidence view

---

## Excel Report Requirements

The Excel report is not just a dump.
It should be a steward-friendly working document.

Design:

- executive summary first
- one row per issue where useful
- severity, owner, recommendation columns
- filters enabled
- consistent coloring for severity
- short explanations, not raw JSON
- separate technical columns for IDs and rule references

Suggested columns for issue sheets:

- severity
- table_name
- column_name
- rule_type
- issue_summary
- violation_count
- violation_pct
- sample_values
- recommended_action
- owner
- status
- source_rule_id

Implemented workbook additions:

- `Trust Scorecard`
- `Freshness`
- `Duplicates`

---

## Workspace Conversation Behavior

After deployment, workspace conversation should answer questions using data quality artifacts.

Examples:

- "Summarize the critical data quality issues."
- "Why did customer get a warning trust score?"
- "Show columns with more than 20 percent missing values."
- "Which referential integrity rule has the most violations?"
- "What can be enriched safely?"
- "Create a remediation plan for the top five issues."

Implementation:

- load active `quality_run_id` for tenant/domain/run
- retrieve table/column/rule/enrichment artifacts
- include dashboard/report links in response context
- support explainable drill-through to underlying evidence rows when the user asks why a count/score/chart point exists
- avoid generating SQL against business facts unless the user asks for raw evidence

---

## Implementation Phases

### 55A. Workflow Routing

Implement:

- pack capability detection
- `workflow_kind=data_quality`
- route from existing agentic entrypoint to data quality orchestrator
- event stream naming for DQ agents

Acceptance:

- `POST /workspace/deployments` with `domain_id=data_quality_observability` starts a data quality workflow
- non-DQ packs continue to use the existing workflow

### 55B. Dedicated Quality Storage

Implement:

- data quality run table
- table artifact table
- column artifact table
- rule table
- rule result table
- report metadata table

Acceptance:

- profiling output is flattened into queryable quality artifacts
- artifacts are idempotent by `quality_run_id + table + column`

### 55C. Profiling and Missingness Agents

Implement:

- DQ profiling agent
- missingness analysis agent
- table and column quality summaries

Acceptance:

- report shows row counts, null counts, blank counts, null percentages, and completeness scores

### 55D. Validation and Referential Integrity

Implement:

- rule extraction from context and pack
- deterministic rule validation
- SQL execution for validity checks
- referential integrity checks

Acceptance:

- context rule `orders.customer_id must exist in customer.customer_id` produces a rule and result
- failed rules appear in API/report/dashboard

### 55E. Trust Scoring

Implement:

- configurable score weights
- table trust scores
- column trust scores
- severity bands

Acceptance:

- trust scores explain component contributions
- low-quality tables are ranked correctly

### 55F. Excel Report

Implement:

- workbook generation
- report artifact persistence
- report download endpoint

Acceptance:

- a completed DQ run produces downloadable `.xlsx`

### 55G. Data Quality Dashboard

Implement:

- DQ dashboard composition
- DQ chart generation from quality artifacts
- dashboard type/source metadata

Acceptance:

- a completed DQ run produces a dashboard separate from business dashboards

### 55H. Enrichment Opportunity Discovery

Implement:

- identify generic missing location/reference fields
- generate enrichment questions
- persist opportunities

Acceptance:

- missing `state` with available `pincode` creates a reviewable opportunity

### 55I. Approved LLM-Based Enrichment Proposal Generation

Implement:

- approval endpoint
- staged proposal generation from source row context
- provenance capture
- enrichment proposal storage

Acceptance:

- staged proposal generation runs only after explicit approval
- proposed values are staged, not applied directly

### 55J. Workspace Integration

Implement:

- conversation context loader for DQ artifacts
- DQ-specific response templates
- report/dashboard links in workspace answers

Acceptance:

- user can ask "what are the top data quality issues" after deployment and receive artifact-grounded answers

Backend status:

- Implemented a DQ-specific workspace response path for `data_quality_observability`.
- Workspace conversation now answers from persisted DQ artifacts instead of the metric planner when the deployment run is DQ-scoped.
- Response payload includes DQ artifact links for:
  - run summary
  - dashboard
  - Excel report
  - table list
  - rule list
  - remediation
  - enrichment opportunities
- Workspace payload now also includes:
  - `remediation_summary`
  - `recommended_actions` preview
- Initial supported intents:
  - top issues / summary
  - missingness by table
  - trust explanation for a named table
  - referential integrity failures
  - duplicate candidate summaries
  - freshness and stability summaries
  - enrichment opportunities
  - remediation plan

### 55K. Freshness and Stability

Implemented:

- Added `FreshnessAndStabilityAgent` into the DQ workflow graph.
- Freshness now persists as first-class table monitoring output using:
  - current run freshness metadata from profiling
  - comparison against the previous completed DQ run for the same tenant/domain
- Stability currently tracks:
  - row count change percent vs previous run
  - completeness score change vs previous run
- Monitoring results are persisted into table artifact `summary_json` under:
  - `freshness_analysis`
  - `stability_analysis`
- Run summary now includes:
  - `stale_table_count`
  - `tables_without_freshness_column_count`
  - `stability_issue_count`
- Added API:
  - `GET /data-quality/freshness`
- Excel report now includes a `Freshness` sheet.
- Dashboard freshness view now includes freshness/stability-derived rows.
- Workspace conversation can answer stale/stability questions from persisted artifacts.

### 55L. Trust Score Expansion

Implemented:

- Added deterministic trust recomputation from persisted quality artifacts.
- Trust now updates persisted table scores using:
  - completeness
  - validity rule outcomes
  - referential integrity rule outcomes
  - exact/fuzzy duplicate signals
  - freshness
  - stability
  - enrichment readiness
- Run summary `average_table_trust_score` is now recomputed from the final persisted table trust scores.
- Table detail API exposes:
  - expanded `components`
  - `trust_component_explanations`
- Excel report includes a `Trust Scorecard` sheet with per-table component breakdown.
- Dashboard trust scorecard now uses persisted trust/component values.

### 55M. Explainable Drill-Through

Implemented:

- Added evidence APIs for:
  - missingness
  - rule failures
  - duplicates
  - freshness/stability
  - enrichment proposals
- This provides the backend contract for explainable dashboard/chart counts.
- The UI can now link aggregate counts to underlying evidence rows or staged artifacts.

---

## Testing Plan

Unit tests:

- workflow routing by pack metadata
- rule extraction mapping to internal rule types
- rule validation rejects missing columns
- referential integrity SQL generation
- trust score component calculation
- enrichment opportunity detection
- report workbook sheet generation

API tests:

- deployment starts DQ workflow
- run summary endpoint
- table list/detail endpoints
- rule result endpoint
- report download endpoint
- enrichment opportunity approval endpoint

Integration tests:

- sample schema with missing values
- sample schema with orphan foreign keys
- sample schema with invalid email/pincode/status values
- sample schema with duplicate customer records
- sample context rules
- completed dashboard and report artifacts

Regression tests:

- non-DQ domain deployments still use standard workflow
- DQ metrics do not enter business KPI generation
- no internet/provider enrichment call is required for this phase
- PII columns are excluded from LLM-based enrichment proposal generation

---

## Remaining Gaps

1. Uploaded rule files are still future work.
2. Low-confidence or ambiguous rule-review workflow is not fully productized yet; the doc still uses `pending_review`, but the full review lifecycle remains later.
3. Persisted binary report storage is still later; Excel is generated on demand and report metadata is stored, but the workbook binary is not yet written to object storage or local artifact storage.
4. Optional CSV-per-sheet export is still later.
5. Source-data writeback remains intentionally deferred; approved enrichment currently creates staged artifacts and enriched report outputs, not direct source-table updates.
6. Advanced enrichment types such as latitude/longitude from full address remain later.
7. Question-centric enrichment review UX is still lighter than the final product shape; current backend exposes opportunities, proposals, staged artifacts, and evidence APIs.

---

## Success Criteria

This phase is complete when:

1. `data_quality_observability` runs through a dedicated data quality agentic graph.
2. Existing deployment and agentic run APIs remain the UI entrypoint.
3. Data profiling produces queryable table and column quality artifacts.
4. Context-provided validation rules are extracted, validated, executed, and reported.
5. Referential integrity checks are executed and surfaced.
6. A detailed Excel report is generated for each completed data quality run.
7. A data quality dashboard is generated from quality artifacts.
8. Missing/enrichment opportunities are identified and presented as user questions.
9. LLM-based staged enrichment proposal generation requires explicit approval and captures provenance.
10. Workspace conversations can answer questions over the completed data quality run.
