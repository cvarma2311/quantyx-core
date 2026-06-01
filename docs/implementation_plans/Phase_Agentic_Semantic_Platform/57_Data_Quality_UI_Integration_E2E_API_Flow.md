# Phase 57: Data Quality UI Integration E2E API Flow

This guide is for UI developers integrating the implemented data quality workflow end to end.

It focuses on:

- the deployment run flow
- the minimal APIs needed to render and reload a run
- the structured APIs the UI should call for review, enrichment, evidence, dashboard, and report actions
- the multi-table stage/join/filter/final-dataset and lineage flows
- the run-history, rerun-as-monitor, trend, anomaly, issue, and readiness flows
- example requests and responses for the main cases

The intended UI model is:

- the deployment run remains conversation/timeline style
- structured DQ APIs back the cards, tasks, tables, evidence drawers, and action flows inside that run

This guide now also covers the monitor rerun flow:

- start a fresh deployment
- fetch all existing runs for the same `tenant_id + domain_id`
- let the user pick a run from history
- rerun that run with `trend_mode=monitor`
- render lineage and trend chains across the old and new runs

## 1. High-Level UI Model

For a DQ run, the UI should treat the backend in two layers:

1. Conversation/timeline shell
   - `GET /agentic/runs/{run_id}/stream`
   - `GET /agentic/runs/{run_id}/events`
   - `GET /agentic/runs/{run_id}/chat`

2. Structured DQ state and actions
   - `GET /data-quality/runs/{run_id}/hydration`
   - `GET /data-quality/runs/{run_id}`
   - review APIs
   - enrichment APIs
   - evidence APIs
   - dashboard/report APIs

Recommended rule:

- initial load/reload: use timeline + hydration
- everything else: lazy load on click/open/action

## 2. Minimal Initial Load Pattern

When the user opens a DQ deployment run, the UI should usually call only:

1. `GET /agentic/runs/{run_id}/events` or `GET /agentic/runs/{run_id}/chat`
2. `GET /data-quality/runs/{run_id}/hydration`

That is enough to render:

- deployment trace
- workflow status banner
- paused rule review state
- top pending enrichment questions
- lineage summary card
- trend summary card
- business-term trend card
- readiness card
- anomaly summary card
- issue summary card
- remediation summary
- report/dashboard/action links

Use lazy APIs only when the user drills into a section.

## 2A. Run History for a Tenant + Domain

When the UI needs to show existing deployment runs for a selected tenant/domain, call:

```http
GET /workspace/deployments?tenant_id=VC_101&domain_id=data_quality_observability&limit=100
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_count": 2,
  "runs": [
    {
      "run_id": "run_dq_002",
      "status": "completed",
      "created_at": "2026-04-25T12:00:00Z",
      "updated_at": "2026-04-25T12:11:00Z",
      "completed_at": "2026-04-25T12:11:00Z",
      "display_name": "Data Quality Observability Deployment v4",
      "version_no": 4,
      "trend_mode": "monitor",
      "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2",
      "trend_scope_label": "Primary CDR Reconciliation",
      "parent_run_id": "run_dq_001",
      "rerun_root_run_id": "run_dq_001"
    },
    {
      "run_id": "run_dq_001",
      "status": "completed",
      "created_at": "2026-04-24T12:00:00Z",
      "updated_at": "2026-04-24T12:09:00Z",
      "completed_at": "2026-04-24T12:09:00Z",
      "display_name": "Data Quality Observability Deployment v3",
      "version_no": 3,
      "trend_mode": "monitor",
      "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2",
      "trend_scope_label": "Primary CDR Reconciliation",
      "parent_run_id": null,
      "rerun_root_run_id": "run_dq_001"
    }
  ]
}
```

UI guidance:

- use `runs` as the primary list
- sort by `created_at` descending if the backend order must be reinforced client-side
- show:
  - `run_id`
  - `status`
  - `created_at`
  - `completed_at`
  - `display_name`
  - `version_no`
- optionally show monitor metadata:
  - `trend_mode`
  - `trend_scope_label`
  - `parent_run_id`
  - `rerun_root_run_id`

## 3. Start a Data Quality Deployment

Use the existing deployment entrypoint.

### Request

```http
POST /workspace/deployments
Content-Type: application/json
```

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "connection_id": "conn_lpg",
  "database": "analytics",
  "schema_name": "public",
  "mode": "full",
  "pause_for_rule_review": true,
  "context_text": "Validate orders.customer_id against customer.customer_id. Customer email must be present and valid."
}
```

### Response

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "display_name": "Data Quality Observability Deployment v3",
  "version_no": 3,
  "status": "queued",
  "workflow_kind": "data_quality",
  "job_id": "job_001"
}
```

### UI behavior

- store `run_id`
- start timeline streaming immediately
- begin polling or fetching hydration

## 3A. Rerun an Existing Deployment as Monitor

When the user selects an existing run and wants trend analysis, call:

```http
POST /workspace/deployments/{run_id}/rerun
Content-Type: application/json
```

```json
{
  "trend_mode": "monitor"
}
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_002",
  "display_name": "Data Quality Observability Deployment v4",
  "version_no": 4,
  "status": "queued",
  "workflow_kind": "data_quality",
  "job_id": "job_002",
  "source_run_id": "run_dq_001"
}
```

UI behavior:

- treat the response `run_id` as a new run
- load its timeline and hydration exactly like a fresh deployment
- after completion:
  - fetch run lineage
  - fetch trend APIs
  - refresh run history

## 4. Stream or Load the Run Trace

The deployment run is still timeline-first.

### Option A: live progress

```http
GET /agentic/runs/{run_id}/stream
```

Server-sent events example:

```text
data: {"agent_name":"DataQualitySchemaAgent","status":"completed","message":"Schema profiling complete"}

data: {"agent_name":"DataQualityRuleAgent","status":"needs_review","message":"Rule review required","stage_name":"awaiting_rule_review"}
```

### Option B: reload timeline

```http
GET /agentic/runs/{run_id}/events?limit=200
```

Example response:

```json
{
  "events": [
    {
      "event_id": "evt_001",
      "agent_name": "DataQualitySchemaAgent",
      "status": "completed",
      "message": "Schema profiling complete",
      "stage_name": "schema",
      "created_at": "2026-04-18T10:00:00Z",
      "artifacts": {}
    },
    {
      "event_id": "evt_002",
      "agent_name": "DataQualityRuleAgent",
      "status": "needs_review",
      "message": "Rule review required",
      "stage_name": "awaiting_rule_review",
      "created_at": "2026-04-18T10:01:00Z",
      "artifacts": {
        "raw_json": {
          "rule_review_required": true,
          "review_queue_pending_count": 2
        }
      }
    }
  ],
  "paging": {
    "limit": 200,
    "returned": 2
  }
}
```

### Optional chat-log replay

```http
GET /agentic/runs/{run_id}/chat?limit=50
```

Use this when the UI prefers a message-thread style replay instead of raw event cards.

## 5. Hydrate the DQ Run in One Call

This is the main DQ reload payload.

### Request

```http
GET /data-quality/runs/{run_id}/hydration
```

### Response

```json
{
  "run": {
    "quality_run_id": "dqrun_001",
    "run_id": "run_dq_001",
    "tenant_id": "VC_101",
    "domain_id": "data_quality_observability",
    "connection_id": "conn_001",
    "database_name": "analytics",
    "schema_name": "public",
    "status": "awaiting_rule_review",
    "overall_trust_score": 82.4,
    "critical_issue_count": 2,
    "warning_issue_count": 5,
    "active_rule_count": 3,
    "needs_review_rule_count": 2,
    "unsupported_rule_count": 0,
    "rejected_rule_count": 0,
    "rule_review_required": true,
    "review_queue_pending_count": 2,
    "workflow_status": "awaiting_rule_review",
    "stale_table_count": 0,
    "tables_without_freshness_column_count": 0,
    "stability_issue_count": 0,
    "enrichment_opportunity_count": 4,
    "external_lookup_opportunity_count": 0,
    "remediation_action_count": 5,
    "critical_remediation_action_count": 2,
    "issue_count": 3,
    "open_issue_count": 3,
    "overdue_issue_count": 1,
    "artifacts": {
      "run_summary": "/data-quality/runs/run_dq_001",
      "issues": "/data-quality/issues?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
      "rule_review_queue": "/data-quality/rules/review-queue?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
      "resume_after_rule_review": "/data-quality/runs/run_dq_001/resume-after-rule-review",
      "enrichment_questions": "/data-quality/enrichment/questions?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001"
    },
    "remediation_summary": {
      "action_count": 5,
      "critical_action_count": 2
    },
    "recommended_actions": [
      {
        "priority": "critical",
        "action_type": "missingness_backfill",
        "title": "Backfill missing values in customer.email"
      }
    ],
    "summary": {
      "workflow_status": "awaiting_rule_review"
    },
    "created_at": "2026-04-22T09:00:00Z",
    "completed_at": null
  },
  "pending_tasks": {
    "workflow_status": "awaiting_rule_review",
    "requires_attention": true,
    "rule_review": {
      "rule_count": 2,
      "needs_review_count": 2,
      "unsupported_count": 0,
      "top_items": [
        {
          "rule_id": "dq_rule_101",
          "table_name": "orders",
          "column_name": "status",
          "rule_type": "allowed_values",
          "severity": "warning",
          "confidence": 0.62,
          "status": "needs_review",
          "source_text": "Order status should be valid",
          "sql_preview_status": "ready",
          "sql_preview_source": "llm"
        }
      ]
    },
    "enrichment_questions": {
      "question_count": 4,
      "pending_answer_count": 2,
      "proposal_ready_count": 1,
      "deferred_count": 1,
      "rejected_count": 0,
      "top_items": []
    },
    "lineage": {
      "lineage_row_count": 12,
      "final_dataset_member_count": 8,
      "rejected_row_count": 3,
      "join_exception_row_count": 1,
      "top_items": [
        {
          "row_lineage_id": "dqlin_b3JkZXJzfCgwLDEp_a1b2c3d4",
          "source_table": "orders",
          "source_row_ref": "(0,1)",
          "decoded_lineage": "orders -> (0,1)",
          "transition_count": 2,
          "stage_count": 3,
          "rejected_count": 0,
          "join_exception_count": 0,
          "latest_stage_name": "final_dataset_projection",
          "final_state": "final_dataset_member",
          "final_dataset_member": true,
          "evidence_path": "/data-quality/lineage/dqlin_b3JkZXJzfCgwLDEp_a1b2c3d4/journey?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001"
        }
      ]
    },
    "issues": {
      "issue_count": 3,
      "open_issue_count": 3,
      "overdue_issue_count": 1,
      "critical_issue_count": 1,
      "top_items": [
        {
          "issue_id": "dqissue_001",
          "title": "Join exceptions detected in primary_cdr_reconciliation",
          "severity": "critical",
          "status": "open",
          "owner_id": "domain_owner",
          "age_days": 4,
          "overdue": true,
          "evidence_path": "/data-quality/evidence/joins/dqjoin_001?tenant_id=VC_101&domain_id=data_quality_observability"
        }
      ]
    },
    "remediation": {
      "summary": {
        "action_count": 5,
        "critical_action_count": 2
      },
      "top_actions": [
        {
          "priority": "critical",
          "title": "Backfill missing values in customer.email"
        }
      ]
    }
  },
  "artifact_links": {
    "run_summary": "/data-quality/runs/run_dq_001",
    "dashboard": "/data-quality/runs/run_dq_001/dashboard",
    "excel_report": "/data-quality/reports/run_dq_001/excel?tenant_id=VC_101&domain_id=data_quality_observability",
    "csv_report": "/data-quality/reports/run_dq_001/csv?tenant_id=VC_101&domain_id=data_quality_observability"
  }
}
```

### UI behavior

Use this payload to render:

- status banner
- pending review cards
- top enrichment questions
- trend summary card
- business-term trend card
- readiness card
- anomaly summary card
- issue register summary card
- lineage summary card
- remediation preview
- report/dashboard buttons

Important `pending_tasks` blocks currently available in the live payload:

- `rule_review`
- `enrichment_questions`
- `lineage`
- `trends`
- `business_terms`
- `readiness`
- `anomalies`
- `issues`
- `remediation`

## 6. Get the Run Summary

Use this when the UI needs the run summary alone, or wants a smaller refresh after completion.

### Request

```http
GET /data-quality/runs/{run_id}
```

### Response

```json
{
  "quality_run_id": "dqrun_001",
  "run_id": "run_dq_001",
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "connection_id": "conn_001",
  "database_name": "analytics",
  "schema_name": "public",
  "status": "completed",
  "overall_trust_score": 82.4,
  "critical_issue_count": 7,
  "warning_issue_count": 18,
  "dashboard_id": "dash_001",
  "dashboard_title": "Data Quality Observability Data Quality Dashboard",
  "dashboard_chart_count": 7,
  "duplicate_candidate_count": 18,
  "exact_duplicate_candidate_count": 12,
  "fuzzy_duplicate_candidate_count": 6,
  "active_rule_count": 25,
  "needs_review_rule_count": 0,
  "unsupported_rule_count": 0,
  "rejected_rule_count": 0,
  "rule_review_required": false,
  "review_queue_pending_count": 0,
  "workflow_status": "completed",
  "dataset_stage_count": 5,
  "join_stage_count": 1,
  "filter_stage_count": 1,
  "total_rejected_row_count": 2880,
  "final_dataset_row_count": 97120,
  "final_dataset_readiness_status": "ready",
  "lineage_edge_count": 6421,
  "stale_table_count": 1,
  "tables_without_freshness_column_count": 0,
  "stability_issue_count": 1,
  "enrichment_opportunity_count": 4,
  "external_lookup_opportunity_count": 0,
  "remediation_action_count": 9,
  "critical_remediation_action_count": 3,
  "artifacts": {
    "run_summary": "/data-quality/runs/run_dq_001",
    "dashboard": "/data-quality/runs/run_dq_001/dashboard",
    "excel_report": "/data-quality/reports/run_dq_001/excel?tenant_id=VC_101&domain_id=data_quality_observability",
    "csv_report": "/data-quality/reports/run_dq_001/csv?tenant_id=VC_101&domain_id=data_quality_observability",
    "stages": "/data-quality/stages?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "joins": "/data-quality/joins?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "rejected_records": "/data-quality/rejected-records?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "final_dataset": "/data-quality/final-dataset?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "final_dataset_rows": "/data-quality/final-dataset/rows?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "lineage": "/data-quality/lineage?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "tables": "/data-quality/tables?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "rules": "/data-quality/rules?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "rule_review_queue": "/data-quality/rules/review-queue?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "resume_after_rule_review": "/data-quality/runs/run_dq_001/resume-after-rule-review",
    "duplicates": "/data-quality/duplicates?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "remediation": "/data-quality/remediation?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "enrichment_opportunities": "/data-quality/enrichment/opportunities?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001",
    "enrichment_questions": "/data-quality/enrichment/questions?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001"
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
    "enrichment_opportunities": 4,
    "dataset_stage_count": 5,
    "join_stage_count": 1,
    "filter_stage_count": 1,
    "total_rejected_row_count": 2880,
    "final_dataset_row_count": 97120,
    "lineage_edge_count": 6421,
    "workflow_status": "completed"
  },
  "created_at": "2026-04-22T09:00:00Z",
  "completed_at": "2026-04-22T09:05:00Z"
}
```

Trend-related fields on the live run-summary payload also include:

- `trend_mode`
- `trend_scope_key`
- `trend_scope_label`
- `baseline_run_id`
- `trend_row_count`
- `improved_metric_count`
- `worsened_metric_count`
- `business_term_group_count`
- `worsened_business_term_count`
- `readiness_trend_status`
- `baseline_readiness_status`
- `certification_blocker_count`
- `residual_anomaly_count`
- `anomaly_count`
- `critical_anomaly_count`
- `issue_count`
- `open_issue_count`
- `overdue_issue_count`

And the `artifacts` block can include:

- `trends`
- `business_term_trends`
- `anomalies`
- `issues`
- `run_lineage`

## 6.1 Multi-table stage, join, final dataset, and lineage surfaces

For multi-table runs, the UI should treat these as first-class product surfaces:

- dataset stages
- join health
- rejected records
- final dataset summary
- final surviving rows
- lineage overview
- row journey

Recommended lazy-load order:

1. `GET /data-quality/stages?...`
2. `GET /data-quality/joins?...`
3. `GET /data-quality/rejected-records?...`
4. `GET /data-quality/final-dataset?...`
5. `GET /data-quality/final-dataset/rows?...`
6. `GET /data-quality/lineage?...`
7. `GET /data-quality/lineage/{row_lineage_id}/journey?...`

These should usually be opened from:

- hydration cards
- dashboard drill-through
- Excel/report links

## 6B. Trends, Business Terms, Anomalies, and Readiness

These are the main observability surfaces once a run belongs to a monitor chain.

Important behavior:

- if `baseline_run_id` is `null`
- or `trend_row_count = 0`

then the run is acting as the baseline and there may be nothing to compare yet.

### 6B.1 List all trend rows for a run

```http
GET /data-quality/trends?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2",
  "baseline_run_id": "run_dq_000",
  "summary": {
    "trend_row_count": 14,
    "improved_metric_count": 8,
    "worsened_metric_count": 2,
    "unchanged_metric_count": 4,
    "baseline_metric_count": 0,
    "changed_metric_count": 0
  },
  "cards": [
    {
      "card_key": "overall_trust_score",
      "title": "Overall Trust Score",
      "value": 71.4,
      "note": 76.2,
      "delta_value": -4.8,
      "delta_pct": -6.3,
      "trend_status": "worsened",
      "evidence_path": "/data-quality/trends?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001&object_type=run&object_key=__run__&metric_name=overall_trust_score"
    }
  ],
  "chart_plan": [
    {
      "chart_key": "trend_status_distribution",
      "chart_type": "column",
      "title": "Trend Status Distribution",
      "subtitle": "Metric rows grouped by trend status",
      "summary": {
        "total_count": 14,
        "largest_bucket": 8
      },
      "x_field": "category",
      "y_field": "value",
      "series_fields": ["value"],
      "rows": [
        {
          "category": "improved",
          "value": 8,
          "evidence_path": "/data-quality/trends?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001&trend_status=improved"
        }
      ]
    }
  ],
  "groups": {
    "tables": {
      "count": 4,
      "summary": {
        "trend_row_count": 4,
        "improved_metric_count": 2,
        "worsened_metric_count": 1,
        "baseline_metric_count": 0,
        "unchanged_metric_count": 1,
        "changed_metric_count": 0
      },
      "rows": []
    }
  },
  "trends": [
    {
      "object_type": "table",
      "object_key": "network_cdr_data",
      "object_name": "network_cdr_data",
      "metric_name": "trust_score",
      "previous_value_num": 76.2,
      "previous_display_value": 76.2,
      "current_value_num": 71.4,
      "current_display_value": 71.4,
      "delta_value": -4.8,
      "delta_pct": -6.3,
      "trend_status": "worsened",
      "directionality": "higher_better",
      "evidence_path": "/data-quality/trends/tables/network_cdr_data?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001"
    }
  ]
}
```

Use this for:

- trend summary cards
- status and object-type charts
- top improved / worsened delta charts
- grouped table / rule / stage sections
- filtered drill-through views
- anomaly and readiness correlation

The UI should treat this as the primary chart-ready contract:

- `cards` -> summary cards
- `chart_plan` -> render directly with the chart component layer
- `groups` -> tab or panel slices without client-side regrouping
- `trends` -> detail rows and modals

### 6B.2 Table-specific trend view

```http
GET /data-quality/trends/tables/network_cdr_data?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

### 6B.3 Rule-specific trend view

```http
GET /data-quality/trends/rules/{rule_logical_key}?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

### 6B.4 Stage-specific trend view

```http
GET /data-quality/trends/stages/{stage_logical_key}?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

### 6B.5 Run-summary trend view

```http
GET /data-quality/trends/run-summary?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

### 6B.6 Final-dataset trend view

```http
GET /data-quality/trends/final-dataset?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

### 6B.7 Business-term grouped trends

```http
GET /data-quality/trends/business-terms?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "summary": {
    "business_term_group_count": 2,
    "worsened_business_term_count": 1,
    "improved_business_term_count": 1,
    "unmatched_trend_row_count": 1
  },
  "groups": [
    {
      "business_term": "Subscriber Identity",
      "normalized_term": "subscriber identity",
      "trend_row_count": 3,
      "worsened_metric_count": 1,
      "improved_metric_count": 1,
      "affected_object_count": 2,
      "top_metrics": "trust_score, violation_count",
      "evidence_path": "/data-quality/trends/business-terms?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001&term=subscriber%20identity"
    }
  ]
}
```

### 6B.5 List anomalies

```http
GET /data-quality/anomalies?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "summary": {
    "anomaly_count": 2,
    "critical_anomaly_count": 1,
    "high_anomaly_count": 1,
    "repeated_anomaly_count": 2
  },
  "anomalies": [
    {
      "anomaly_id": "dqanom_001",
      "title": "Overall trust score dropped materially",
      "severity": "critical",
      "object_type": "run",
      "object_key": "__run__",
      "anomaly_type": "trust_score_drop",
      "evidence_path": "/data-quality/trends?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001&object_type=run&object_key=__run__"
    }
  ]
}
```

### 6B.6 Readiness / certification summary

There is no separate readiness endpoint right now. The UI should read readiness from:

1. `GET /data-quality/runs/{run_id}/hydration`
   - `pending_tasks.readiness`
2. `GET /data-quality/runs/{run_id}`
   - `readiness_trend_status`
   - `baseline_readiness_status`
   - `certification_blocker_count`
   - `residual_anomaly_count`
3. `GET /data-quality/runs/{run_id}/dashboard`
   - `publish_readiness` section

Hydration readiness card example:

```json
{
  "run_id": "run_dq_001",
  "baseline_run_id": "run_dq_000",
  "current_readiness_status": "warning",
  "previous_readiness_status": "blocked",
  "readiness_trend_status": "improved",
  "current_final_row_count": 12110,
  "previous_final_row_count": 11840,
  "final_row_count_delta": 270,
  "final_row_count_delta_pct": 2.28,
  "certification_blocker_count": 1,
  "open_issue_count": 3,
  "residual_anomaly_count": 2,
  "critical_anomaly_count": 1,
  "blocker_titles": [
    "Join exceptions detected in primary_cdr_reconciliation"
  ],
  "evidence_path_template": "/data-quality/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id=run_dq_001"
}
```

Use this for:

- certification/readiness card
- publish gating banners
- monitor rerun comparisons

## 6A. Issue Register APIs

Use these when the UI needs stewardship actions beyond the hydration summary card.

### List current-run issues

```http
GET /data-quality/issues?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

### Get one issue

```http
GET /data-quality/issues/{issue_id}
```

### Assign an issue

```http
POST /data-quality/issues/{issue_id}/assign
Content-Type: application/json

{
  "owner_id": "data_steward",
  "assigned_by": "ui:user"
}
```

### Update issue status

```http
POST /data-quality/issues/{issue_id}/status
Content-Type: application/json

{
  "status": "in_progress",
  "updated_by": "ui:user",
  "note": "Assigned to steward queue"
}
```

Supported issue statuses:

- `open`
- `in_progress`
- `deferred`
- `resolved`
- `accepted_risk`

These APIs are the source of truth for:

- issue register grids
- steward work queue
- overdue / SLA breach views
- issue cards opened from hydration or dashboard

## 7. Rule Review Flow Before Execution

This is the governance-first path.

### 7.1 Get the review queue

```http
GET /data-quality/rules/review-queue?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "summary": {
    "rule_count": 2,
    "needs_review_count": 2,
    "unsupported_count": 0
  },
  "rules": [
    {
      "rule_id": "dq_rule_101",
      "table_name": "orders",
      "column_name": "status",
      "rule_type": "allowed_values",
      "severity": "warning",
      "confidence": 0.62,
      "status": "needs_review",
      "source_text": "Order status should be valid",
      "execution_plan_json": {
        "sql_preview_status": "ready",
        "sql_preview_source": "llm"
      }
    }
  ]
}
```

### 7.2 Open a single rule review item

```http
GET /data-quality/rules/dq_rule_101/review?tenant_id=VC_101
```

Example response:

```json
{
  "rule_id": "dq_rule_101",
  "run_id": "run_dq_001",
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "rule_type": "allowed_values",
  "severity": "warning",
  "table_name": "orders",
  "column_name": "status",
  "source_text": "Order status should be valid",
  "condition_json": {
    "allowed_values": [],
    "ambiguity_reason": "Allowed values were not stated"
  },
  "executor_kind": "deterministic_sql",
  "execution_plan": {
    "sql_preview": {
      "validation_sql": "SELECT status FROM orders WHERE status IS NOT NULL"
    },
    "sql_preview_status": "ready",
    "sql_preview_source": "llm"
  },
  "sql_preview": {
    "validation_sql": "SELECT status FROM orders WHERE status IS NOT NULL"
  },
  "sql_preview_status": "ready",
  "sql_preview_source": "llm",
  "confidence": 0.62,
  "rule_status": "needs_review",
  "reviewed_by": null,
  "reviewed_at": null,
  "review_notes": null,
  "result": null
}
```

### 7.2.1 Rule statuses and allowed transitions

The backend persists rule state in the rule row itself. For UI purposes, the important statuses are:

- `active`
  - the rule is approved for execution
  - this is the steady-state after auto-accept or manual approve
- `needs_review`
  - the rule is ambiguous, low-confidence, or preview-unavailable and is waiting for user review
- `unsupported`
  - the extracted rule could not be mapped to a supported executable form and needs user correction or rejection
- `rejected`
  - the user explicitly rejected the rule and it will not execute

What the UI will normally see:

- in `GET /data-quality/rules/review-queue`
  - only `needs_review` and `unsupported` rules are returned in the queue
- in `GET /data-quality/rules/{rule_id}/review`
  - `rule_status` can be any of:
    - `active`
    - `needs_review`
    - `unsupported`
    - `rejected`

Allowed review actions in `POST /data-quality/rules/{rule_id}/review`:

- `approve`
- `reject`
- `edit`

Status transitions:

- `needs_review` + `approve` -> `active`
- `unsupported` + `approve` -> `active`
- `needs_review` + `reject` -> `rejected`
- `unsupported` + `reject` -> `rejected`
- `needs_review` + `edit` -> usually reclassified to:
  - `active` if the edited rule is now executable and safe
  - `needs_review` if ambiguity still remains
  - `unsupported` is internally normalized back to `needs_review` after edit so the queue stays reviewable

Important UI point:

- after manual approval, the rule does **not** move to a separate `approved` status
- it moves to `active`
- that is the status to treat as approved-and-runnable

### 7.3 Approve, reject, or edit a rule

Approve with edits:

```http
POST /data-quality/rules/dq_rule_101/review
Content-Type: application/json
```

```json
{
  "tenant_id": "VC_101",
  "reviewed_by": "ui:user",
  "action": "approve",
  "review_notes": "Allowed values confirmed by steward",
  "condition_json": {
    "allowed_values": ["CREATED", "SHIPPED", "CANCELLED"]
  }
}
```

Example response:

```json
{
  "rule_id": "dq_rule_101",
  "status": "active",
  "stored_rule": {
    "rule_id": "dq_rule_101",
    "status": "active"
  },
  "execution": null
}
```

Reject example:

```json
{
  "tenant_id": "VC_101",
  "reviewed_by": "ui:user",
  "action": "reject",
  "review_notes": "This rule is out of scope"
}
```

### 7.4 Resume the paused run

Only call this when the review queue is fully resolved.

```http
POST /data-quality/runs/run_dq_001/resume-after-rule-review
Content-Type: application/json
```

```json
{
  "requested_by": "ui:user"
}
```

Example response:

```json
{
  "run_id": "run_dq_001",
  "status": "queued",
  "job_id": "job_resume_001",
  "resume_mode": "after_rule_review"
}
```

### UI rule-review pattern

1. start deployment
2. stream timeline
3. if run enters `awaiting_rule_review`, open review queue
4. review each item
5. when no `needs_review` or `unsupported` rules remain, enable `Start Validation Run`
6. call resume endpoint
7. continue streaming until completed

## 8. Tables, Rules, Duplicates, and Freshness

These are the main summary/detail APIs after or during run completion.

## 8A. Multi-table stages and joins

### 8A.1 List dataset stages

```http
GET /data-quality/stages?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "stages": [
    {
      "stage_id": "dqstage_001",
      "stage_seq": 1,
      "stage_name": "source_profile_orders",
      "stage_type": "source_profile",
      "input_row_count": 100000,
      "output_row_count": 100000,
      "rejected_row_count": 0,
      "summary_json": {
        "measurement_status": "measured",
        "evidence_path": "/data-quality/evidence/stages/dqstage_001?tenant_id=VC_101&domain_id=data_quality_observability"
      }
    },
    {
      "stage_id": "dqstage_002",
      "stage_seq": 2,
      "stage_name": "orders_to_customer_customer_id",
      "stage_type": "join_validation",
      "input_row_count": 100000,
      "output_row_count": 98200,
      "rejected_row_count": 1800,
      "summary_json": {
        "measurement_status": "measured",
        "evidence_path": "/data-quality/evidence/stages/dqstage_002?tenant_id=VC_101&domain_id=data_quality_observability"
      }
    }
  ]
}
```

### 8A.2 List join artifacts

```http
GET /data-quality/joins?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "joins": [
    {
      "join_artifact_id": "dqjoin_001",
      "join_name": "orders_to_customer_customer_id",
      "left_table": "orders",
      "right_table": "customer",
      "join_type": "reference_lookup",
      "matched_row_count": 98200,
      "unmatched_left_row_count": 1800,
      "unmatched_right_row_count": 0,
      "duplicate_match_count": 0,
      "summary_json": {
        "measurement_status": "measured",
        "evidence_path": "/data-quality/evidence/joins/dqjoin_001?tenant_id=VC_101&domain_id=data_quality_observability"
      }
    }
  ]
}
```

### 8A.3 List rejected records

```http
GET /data-quality/rejected-records?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "stage_id": null,
  "rejected_records": [
    {
      "outcome_id": "dqout_001",
      "stage_id": "dqstage_002",
      "stage_name": "orders_to_customer_customer_id",
      "outcome_type": "rejected",
      "row_lineage_id": "dqlin_b3JkZXJzfCgwLDE1KQ_a1b2c3d4",
      "row_ref": "(0,15)",
      "source_table": "orders",
      "reason_code": "join_unmatched_left",
      "reason_detail": "No customer match"
    }
  ]
}
```

### 8A.4 Final dataset summary and rows

```http
GET /data-quality/final-dataset?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "final_dataset": {
    "artifact_id": "dqfinal_001",
    "final_stage_name": "final_dataset_projection",
    "final_row_count": 97120,
    "total_rejected_row_count": 2880,
    "readiness_status": "ready",
    "summary_json": {
      "measurement_status": "derived",
      "lineage_enabled": true
    }
  }
}
```

```http
GET /data-quality/final-dataset/rows?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

UI usage:

- summary card from `/final-dataset`
- row table from `/final-dataset/rows`
- drill-through path from stage or dashboard sections

## 8B. Lineage overview and row journey

### 8B.1 List lineage overview rows

```http
GET /data-quality/lineage?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "summary": {
    "lineage_row_count": 12,
    "final_dataset_member_count": 8,
    "rejected_row_count": 3,
    "join_exception_row_count": 1
  },
  "rows": [
    {
      "row_lineage_id": "dqlin_b3JkZXJzfCgwLDEp_a1b2c3d4",
      "source_table": "orders",
      "source_row_ref": "(0,1)",
      "decoded_lineage": "orders -> (0,1)",
      "transition_count": 2,
      "stage_count": 3,
      "rejected_count": 0,
      "join_exception_count": 0,
      "latest_stage_name": "final_dataset_projection",
      "final_state": "final_dataset_member",
      "final_dataset_member": true,
      "evidence_path": "/data-quality/lineage/dqlin_b3JkZXJzfCgwLDEp_a1b2c3d4/journey?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001"
    }
  ]
}
```

### 8B.2 Open a UI-friendly lineage journey

```http
GET /data-quality/lineage/dqlin_b3JkZXJzfCgwLDE1KQ_a1b2c3d4/journey?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "run_id": "run_dq_001",
  "row_lineage_id": "dqlin_b3JkZXJzfCgwLDE1KQ_a1b2c3d4",
  "source": {
    "source_table": "orders",
    "source_row_ref": "(0,15)",
    "decoded_lineage": "orders|(0,15)"
  },
  "summary": {
    "step_count": 2,
    "transition_count": 1,
    "outcome_count": 1,
    "final_dataset_member": false,
    "final_state": "join_unmatched_left"
  },
  "journey": [
    {
      "step_index": 1,
      "stage_id": "dqstage_001",
      "stage_seq": 1,
      "stage_name": "source_profile_orders",
      "stage_type": "source_profile",
      "state": "entered",
      "status_category": "progressed",
      "display_label": "Entered source_profile_orders"
    },
    {
      "step_index": 2,
      "stage_id": "dqstage_002",
      "stage_seq": 2,
      "stage_name": "orders_to_customer_customer_id",
      "stage_type": "join_validation",
      "state": "join_unmatched_left",
      "status_category": "rejected",
      "display_label": "Rejected by left-side join mismatch in orders_to_customer_customer_id"
    }
  ]
}
```

### 8B.3 Open the raw lineage trace when needed

```http
GET /data-quality/lineage/dqlin_b3JkZXJzfCgwLDE1KQ_a1b2c3d4?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Use this only for:

- engineering/debug tooling
- audit inspection
- lower-level trace rendering

For user-facing lineage journey UI, prefer `/journey`.

### 8.1 List table summaries

```http
GET /data-quality/tables?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "tables": [
    {
      "table_name": "customer",
      "row_count": 100000,
      "trust_score": 71.2,
      "completeness_score": 78.5,
      "freshness_score": 100.0,
      "duplicate_risk_score": 54.0,
      "severity": "warning",
      "duplicate_candidate_count": 18,
      "enrichment_opportunity_count": 2,
      "summary": {}
    }
  ]
}
```

### 8.2 Get one table detail

```http
GET /data-quality/tables/customer?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "quality_run_id": "dqrun_001",
  "run_id": "run_dq_001",
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "table_name": "customer",
  "row_count": 100000,
  "trust_score": 71.2,
  "completeness_score": 78.5,
  "freshness_score": 100.0,
  "duplicate_risk_score": 54.0,
  "severity": "warning",
  "components": {
    "completeness": 78.5,
    "validity": 91.0,
    "referential_integrity": 88.0,
    "duplicate_risk": 54.0,
    "freshness": 100.0
  },
  "trust_component_explanations": {
    "duplicate_risk": "High duplicate candidate volume is pulling down trust for this table."
  },
  "summary": {
    "trust_components": {
      "completeness": 78.5,
      "validity": 91.0,
      "referential_integrity": 88.0,
      "duplicate_risk": 54.0,
      "freshness": 100.0
    }
  },
  "columns": [
    {
      "column_name": "email",
      "column_alias": "email",
      "null_pct": 17.4,
      "completeness_score": 82.6
    }
  ],
  "failed_rules": [
    {
      "rule_id": "dqr_001",
      "rule_type": "email_pattern",
      "table_name": "customer",
      "column_name": "email",
      "severity": "warning"
    }
  ],
  "duplicate_candidates": [
    {
      "candidate_id": "dqdup_001",
      "table_name": "customer",
      "duplicate_type": "exact_key_duplicate",
      "confidence": 0.99,
      "candidate_record_count": 4
    }
  ],
  "enrichment_opportunities": [
    {
      "opportunity_id": "dq_enrich_001",
      "table_name": "customer",
      "target_column": "state",
      "confidence": 0.87
    }
  ]
}
```

### 8.3 List rules

```http
GET /data-quality/rules?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001&status=failed
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "rules": [
    {
      "rule_id": "dq_rule_201",
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
      "rule_status": "active",
      "result": {
        "status": "failed",
        "violation_count": 842,
        "violation_pct": 0.84
      }
    }
  ]
}
```

### 8.4 List duplicate candidates

```http
GET /data-quality/duplicates?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

### 8.5 List freshness/stability rows

```http
GET /data-quality/freshness?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

## 9. Explainable Evidence APIs

Every dashboard count or issue should drill to evidence.

### 9.1 Missingness evidence

```http
GET /data-quality/evidence/missingness?tenant_id=VC_101&run_id=run_dq_001&table_name=customer&column_name=email&limit=100&offset=0
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "run_id": "run_dq_001",
  "table_name": "customer",
  "column_name": "email",
  "column_alias": "email",
  "issue_type": "missingness",
  "row_count": 290,
  "rows": [
    {
      "customer_id": "C101",
      "email": null,
      "country": "US"
    }
  ]
}
```

### 9.2 Rule evidence

```http
GET /data-quality/evidence/rules/dq_rule_201?tenant_id=VC_101
```

### 9.3 Duplicate evidence

```http
GET /data-quality/evidence/duplicates/dqdup_001?tenant_id=VC_101
```

### 9.4 Freshness evidence

```http
GET /data-quality/evidence/freshness/customer?tenant_id=VC_101&run_id=run_dq_001
```

### 9.5 Enrichment evidence

```http
GET /data-quality/evidence/enrichment/dq_enrich_prop_001?tenant_id=VC_101
```

### UI behavior

These APIs are lazy drill-through calls. Do not load them all upfront.

Use them when the user clicks:

- `290 missing records`
- a failed rule row
- a duplicate cluster row
- a stale table badge
- an enrichment proposal sample

## 10. Remediation API

Use this when the UI needs a full recommended-actions view.

```http
GET /data-quality/remediation?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
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
      "evidence_path": "/data-quality/evidence/missingness?tenant_id=VC_101&run_id=run_dq_001&table_name=customer&column_name=email",
      "trust_component": "completeness"
    }
  ]
}
```

## 11. Dashboard and Excel

### 11.1 Get dashboard

```http
GET /data-quality/runs/run_dq_001/dashboard
```

Example response:

```json
{
  "run_id": "run_dq_001",
  "dashboard_id": "dash_001",
  "dashboard_type": "data_quality",
  "title": "Data Quality Observability Data Quality Dashboard",
  "name": "Data Quality Observability Data Quality Dashboard",
  "description": "System-generated dashboard summarizing trust, missingness, validation failures, referential integrity, duplicate risk, and freshness.",
  "status": "active",
  "quality_score": 82.4,
  "quality_gate_passed": false,
  "summary_view": {
    "title": "Executive Summary",
    "summary": {
      "quality_score": 82.4,
      "critical_issue_count": 7,
      "failed_rule_count": 5,
      "duplicate_candidate_count": 18,
      "recommended_action_count": 9,
      "critical_recommended_action_count": 3,
      "run_id": "run_dq_001",
      "dashboard_type": "data_quality"
    },
    "rows": [
      {
        "metric_key": "quality_score",
        "label": "Quality Score",
        "value": 82.4,
        "note": "quality gate failed",
        "evidence_path": null
      }
    ]
  },
  "chart_plan": [
    {
      "title": "Executive Summary",
      "chart_key": "executive_summary",
      "chart_type": "summary_cards",
      "data_source": "quantyx_data_quality_run_summary",
      "summary": {
        "quality_score": 82.4,
        "critical_issue_count": 7,
        "failed_rule_count": 5,
        "duplicate_candidate_count": 18,
        "recommended_action_count": 9,
        "critical_recommended_action_count": 3,
        "run_id": "run_dq_001",
        "dashboard_type": "data_quality"
      },
      "display_columns": [
        {
          "field": "metric_key",
          "label": "Metric Key"
        },
        {
          "field": "label",
          "label": "Label"
        },
        {
          "field": "value",
          "label": "Value"
        },
        {
          "field": "note",
          "label": "Note"
        },
        {
          "field": "evidence_path",
          "label": "Evidence Path"
        }
      ],
      "rows": [
        {
          "metric_key": "quality_score",
          "label": "Quality Score",
          "value": 82.4,
          "note": "quality gate failed",
          "evidence_path": null
        }
      ]
    },
    {
      "title": "Columns with Highest Missingness",
      "chart_key": "missingness_heatmap",
      "chart_type": "table_heatmap",
      "data_source": "quantyx_data_quality_column_artifacts",
      "summary": {
        "column_count": 3
      },
      "display_columns": [
        {
          "field": "column_name",
          "label": "Physical Column"
        },
        {
          "field": "column_alias",
          "label": "Semantic Alias"
        },
        {
          "field": "evidence_path",
          "label": "Evidence Path"
        }
      ],
      "rows": [
        {
          "table_name": "customer",
          "column_name": "email",
          "column_alias": "email",
          "null_pct": 17.4,
          "completeness_score": 82.6,
          "evidence_path": "/data-quality/evidence/missingness?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001&table_name=customer&column_name=email"
        }
      ]
    },
    {
      "title": "Quality Trends",
      "chart_key": "quality_trends",
      "chart_type": "table",
      "data_source": "quantyx_data_quality_trends",
      "summary": {
        "trend_row_count": 14,
        "improved_metric_count": 8,
        "worsened_metric_count": 2
      },
      "rows": [
        {
          "object_type": "table",
          "object_name": "network_cdr_data",
          "metric_name": "trust_score",
          "previous_value_num": 76.2,
          "current_value_num": 71.4,
          "delta_value": -4.8,
          "delta_pct": -6.3,
          "trend_status": "worsened",
          "evidence_path": "/data-quality/trends/tables/network_cdr_data?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001"
        }
      ]
    },
    {
      "title": "Publish Readiness",
      "chart_key": "publish_readiness",
      "chart_type": "summary_cards",
      "data_source": "quantyx_data_quality_final_dataset_artifacts",
      "summary": {
        "current_readiness_status": "ready",
        "previous_readiness_status": "warning",
        "readiness_trend_status": "improved",
        "certification_blocker_count": 1
      },
      "rows": [
        {
          "metric_key": "current_readiness_status",
          "label": "Current Readiness",
          "value": "ready",
          "note": "Improved from warning",
          "evidence_path": "/data-quality/final-dataset?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001"
        }
      ]
    },
    {
      "title": "Business Term Trends",
      "chart_key": "business_term_trends",
      "chart_type": "table",
      "data_source": "quantyx_data_quality_trends",
      "summary": {
        "business_term_group_count": 2,
        "worsened_business_term_count": 1
      },
      "rows": [
        {
          "business_term": "Subscriber Identity",
          "trend_row_count": 3,
          "worsened_metric_count": 1,
          "improved_metric_count": 1,
          "evidence_path": "/data-quality/trends/business-terms?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001&term=subscriber%20identity"
        }
      ]
    }
  ],
  "charts": [],
  "created_at": "2026-04-22T09:05:00Z",
  "updated_at": "2026-04-22T09:05:00Z"
}
```

### 11.2 Download Excel

```http
GET /data-quality/reports/run_dq_001/excel?tenant_id=VC_101&domain_id=data_quality_observability
```

Response:

- content type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- attachment download

Current workbook behavior:

- generated on demand from persisted artifacts
- includes trust, table quality, column quality, validation rules, rule violations, freshness, duplicates, remediation
- includes trend sheets:
  - `Quality Trends`
  - `Rule Trends`
  - `Stage Trends`
  - `Final Dataset Trends`
  - `Business Term Trends`
  - `Certification Summary`
  - `Publish Readiness`
- includes anomaly sheets:
  - `Anomaly Summary`
  - `Anomalies`
- includes issue sheets:
  - `Issue Register`
  - `Steward Work Queue`
  - `SLA Breaches`
- includes enrichment sheets when staged overlays exist
- published enrichment sheets show physical column names and semantic aliases together
- enriched cells are color coded

## 12. Enrichment Flow

The backend uses question-centric UX on top of the existing opportunity/proposal/staging model.

### 12.1 List raw enrichment opportunities

Usually the UI can skip this and use questions instead, but it is still available.

```http
GET /data-quality/enrichment/opportunities?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "opportunities": [
    {
      "opportunity_id": "dq_enrich_001",
      "table_name": "customer",
      "target_column": "state",
      "target_column_alias": "state",
      "source_columns_json": ["pincode", "country"],
      "source_column_aliases_json": ["postal_code", "country"],
      "missing_count": 1240,
      "candidate_method": "postal_context_inference",
      "confidence": 0.87,
      "question": "Can we use existing row context to propose missing customer.state values from pincode and country?",
      "status": "needs_user_approval"
    }
  ]
}
```

### 12.2 Preferred UI API: list enrichment questions

```http
GET /data-quality/enrichment/questions?tenant_id=VC_101&domain_id=data_quality_observability&run_id=run_dq_001
```

Example response:

```json
{
  "tenant_id": "VC_101",
  "domain_id": "data_quality_observability",
  "run_id": "run_dq_001",
  "summary": {
    "question_count": 4,
    "pending_answer_count": 2,
    "proposal_ready_count": 1,
    "deferred_count": 1,
    "rejected_count": 0
  },
  "questions": [
    {
      "question_id": "dq_enrich_001",
      "opportunity_id": "dq_enrich_001",
      "run_id": "run_dq_001",
      "quality_run_id": "dqrun_001",
      "table_name": "customer",
      "target_column": "state",
      "target_column_alias": "state",
      "source_columns_json": ["pincode", "country"],
      "source_column_aliases_json": ["postal_code", "country"],
      "question": "Can we use existing row context to propose missing customer.state values from pincode and country?",
      "missing_count": 1240,
      "candidate_method": "postal_context_inference",
      "confidence": 0.87,
      "status": "pending_answer",
      "available_actions": ["approve", "defer", "reject"],
      "proposal_id": null,
      "proposal_status": null,
      "proposal_summary": null,
      "artifact_links": {
        "proposal": null,
        "answer": "/data-quality/enrichment/questions/dq_enrich_001/answer"
      }
    }
  ]
}
```

### 12.3 Answer a question

Approve example:

```http
POST /data-quality/enrichment/questions/dq_enrich_001/answer
Content-Type: application/json
```

```json
{
  "tenant_id": "VC_101",
  "answer": "approve",
  "approved_by": "ui:user",
  "max_records": 500
}
```

Example response:

```json
{
  "opportunity_id": "dq_enrich_001",
  "status": "proposal_generated",
  "proposal_id": "dq_enrich_prop_001",
  "matched_count": 480,
  "unmatched_count": 20
}
```

Defer example:

```json
{
  "tenant_id": "VC_101",
  "answer": "defer"
}
```

Reject example:

```json
{
  "tenant_id": "VC_101",
  "answer": "reject"
}
```

Reopen example:

```json
{
  "tenant_id": "VC_101",
  "answer": "reopen"
}
```

### 12.4 Get proposal detail

```http
GET /data-quality/enrichment/proposals/dq_enrich_prop_001
```

Example response:

```json
{
  "proposal_id": "dq_enrich_prop_001",
  "opportunity_id": "dq_enrich_001",
  "status": "proposed",
  "table_name": "customer",
  "target_column": "state",
  "target_column_alias": "state",
  "source_columns_json": ["pincode", "country"],
  "source_column_aliases_json": ["postal_code", "country"],
  "candidate_method": "postal_context_inference",
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

### 12.5 Approve staged application

Important:

- this does not write back to source data
- it creates a staged overlay artifact only

```http
POST /data-quality/enrichment/proposals/dq_enrich_prop_001/approve-application
Content-Type: application/json
```

```json
{
  "tenant_id": "VC_101",
  "approved_by": "data_steward:user",
  "application_mode": "staged_overlay",
  "approval_scope": "high_confidence",
  "min_confidence": 0.85,
  "reason": "Reviewed postal context inference"
}
```

Example response:

```json
{
  "proposal_id": "dq_enrich_prop_001",
  "status": "approved_for_staging",
  "application_mode": "staged_overlay",
  "approval_scope": "high_confidence",
  "confidence_threshold": 0.85,
  "approved_row_count": 400,
  "deferred_row_count": 80,
  "staged_artifact_id": "artifact_stage_001"
}
```

### 12.6 Fetch staged artifact

```http
GET /data-quality/enrichment/proposals/dq_enrich_prop_001/staged-artifact
```

Example response:

```json
{
  "artifact_id": "artifact_stage_001",
  "event_id": "evt_stage_001",
  "logical_event_id": "dq_stage::dq_enrich_prop_001",
  "run_id": "run_dq_001",
  "proposal_id": "dq_enrich_prop_001",
  "status": "approved_for_staging",
  "summary_raw_text": "Approved 400 rows for staged overlay; deferred 80 rows.",
  "inference_raw_text": "{\"approval_scope\":\"high_confidence\",\"confidence_threshold\":0.85,\"approved_row_count\":400,\"deferred_row_count\":80}",
  "approved_row_count": 400,
  "deferred_row_count": 80,
  "approval_scope": "high_confidence",
  "confidence_threshold": 0.85,
  "raw_json": {
    "approved_rows": [],
    "deferred_rows": []
  }
}
```

## 13. Example End-to-End UI Flow

### Case A: standard DQ run, no rule-review pause

1. `POST /workspace/deployments`
2. optionally `GET /workspace/deployments?tenant_id=...&domain_id=...` to show existing runs
3. `GET /agentic/runs/{run_id}/stream`
4. `GET /data-quality/runs/{run_id}/hydration`
5. when run completes:
   - `GET /data-quality/runs/{run_id}`
   - `GET /data-quality/runs/{run_id}/dashboard`
   - `GET /data-quality/reports/{run_id}/excel?...`
   - `GET /data-quality/reports/{run_id}/csv?...`
6. lazy on click:
   - tables
   - rules
   - duplicates
   - freshness
   - trends
   - business-term trends
   - anomalies
   - issues
   - remediation
   - evidence APIs

### Case B: run pauses for rule review

1. `POST /workspace/deployments` with `pause_for_rule_review=true`
2. stream timeline
3. hydration shows:
   - `workflow_status=awaiting_rule_review`
   - `rule_review_required=true`
4. `GET /data-quality/rules/review-queue`
5. for each item:
   - `GET /data-quality/rules/{rule_id}/review`
   - `POST /data-quality/rules/{rule_id}/review`
6. `POST /data-quality/runs/{run_id}/resume-after-rule-review`
7. continue streaming and then use normal completed-run APIs

### Case C: question-centric enrichment

1. run completes
2. hydration shows pending enrichment questions
3. `GET /data-quality/enrichment/questions`
4. user approves one question:
   - `POST /data-quality/enrichment/questions/{opportunity_id}/answer`
5. proposal becomes available:
   - `GET /data-quality/enrichment/proposals/{proposal_id}`
6. user approves staging:
   - `POST /data-quality/enrichment/proposals/{proposal_id}/approve-application`
7. UI can inspect:
   - `GET /data-quality/enrichment/proposals/{proposal_id}/staged-artifact`
8. final Excel can show enrichment sheets and color-coded staged outputs

### Case D: rerun an existing deployment as monitor

1. `GET /workspace/deployments?tenant_id=...&domain_id=...`
2. user selects an earlier run
3. `POST /workspace/deployments/{run_id}/rerun` with:
   - `{"trend_mode":"monitor"}`
4. use the returned new `run_id`
5. load:
   - timeline/events
   - hydration
6. if paused for rule review:
   - use the normal review/resume flow
7. after completion:
   - `GET /data-quality/trends?...`
   - `GET /data-quality/trends/business-terms?...`
   - `GET /data-quality/anomalies?...`
   - `GET /agentic/runs/{run_id}/lineage`
   - dashboard
   - Excel

## 14. Recommended UI Integration Plan

### Call immediately

- `POST /workspace/deployments`
- `GET /agentic/runs/{run_id}/stream` or `GET /agentic/runs/{run_id}/events`
- `GET /data-quality/runs/{run_id}/hydration`

### Call when run completes or refreshes

- `GET /data-quality/runs/{run_id}`
- `GET /data-quality/runs/{run_id}/dashboard`
- `GET /workspace/deployments?tenant_id=...&domain_id=...` when the UI needs run history

### Call when user opens a panel

- `GET /data-quality/tables`
- `GET /data-quality/tables/{table_name}`
- `GET /data-quality/rules`
- `GET /data-quality/runs/{run_id}/rules/{rule_id}/failed-records`
- `GET /data-quality/runs/{run_id}/rules/{rule_id}/passed-records`
- `GET /data-quality/duplicates`
- `GET /data-quality/freshness`
- `GET /data-quality/trends`
- `GET /data-quality/trends/business-terms`
- `GET /data-quality/anomalies`
- `GET /data-quality/issues`
- `GET /data-quality/remediation`
- `GET /data-quality/enrichment/questions`

### Call when user performs an action

- `POST /data-quality/rules/{rule_id}/review`
- `POST /data-quality/runs/{run_id}/resume-after-rule-review`
- `POST /workspace/deployments/{run_id}/rerun`
- `POST /data-quality/enrichment/questions/{opportunity_id}/answer`
- `POST /data-quality/enrichment/proposals/{proposal_id}/approve-application`

### Call only for drill-through or export

- evidence APIs
- `GET /data-quality/runs/{run_id}/rules/{rule_id}/failed-records`
- `GET /data-quality/runs/{run_id}/rules/{rule_id}/passed-records`
- `GET /data-quality/enrichment/proposals/{proposal_id}`
- `GET /data-quality/enrichment/proposals/{proposal_id}/staged-artifact`
- `GET /data-quality/reports/{run_id}/excel`
- `GET /data-quality/reports/{run_id}/csv`

## 15. Run Lineage Graph

For rerun chains and monitoring chains, the UI should use:

```http
GET /agentic/runs/{run_id}/lineage
```

The response contains:

- `graph`
- `nodes`
- `edges`

Example:

```json
{
  "run_id": "run_dq_002",
  "graph": {
    "root_run_id": "run_dq_001",
    "focus_run_id": "run_dq_002",
    "node_count": 2,
    "edge_count": 1,
    "trend_scope_keys": ["cdr_primary_reconciliation_f8a1c3b0d2"]
  },
  "nodes": [
    {
      "run_id": "run_dq_001",
      "display_name": "Data Quality Observability Deployment v3",
      "status": "completed",
      "version_no": 3,
      "trend_mode": "monitor",
      "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2",
      "trend_scope_label": "Primary CDR Reconciliation",
      "parent_run_id": null,
      "rerun_root_run_id": "run_dq_001",
      "created_at": "2026-04-24T12:00:00Z",
      "is_focus_run": false,
      "is_root_run": true
    },
    {
      "run_id": "run_dq_002",
      "display_name": "Data Quality Observability Deployment v4",
      "status": "completed",
      "version_no": 4,
      "trend_mode": "monitor",
      "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2",
      "trend_scope_label": "Primary CDR Reconciliation",
      "parent_run_id": "run_dq_001",
      "rerun_root_run_id": "run_dq_001",
      "created_at": "2026-04-25T12:00:00Z",
      "is_focus_run": true,
      "is_root_run": false
    }
  ],
  "edges": [
    {
      "lineage_edge_id": "runedge_001",
      "parent_run_id": "run_dq_001",
      "child_run_id": "run_dq_002",
      "edge_type": "rerun_monitor",
      "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2"
    }
  ]
}
```

UI guidance:

- render `nodes` as the graph vertices
- render `edges` as directed links
- use `edge_type` to distinguish:
  - normal reruns
  - monitor reruns
  - baseline resets
- use `trend_scope_key` and `trend_scope_label` to cluster or color monitoring chains
- use `is_focus_run` and `is_root_run` to highlight the current run and the chain origin

## 16. Important Product Rules for UI

- Keep deployment trace conversation-style.
- Use structured DQ APIs as the source of truth for cards and actions.
- Do not load evidence APIs eagerly.
- Do not require the user to approve enrichment row by row.
- Do not expose backend internals like `executor_kind` as a primary control.
- Do not assume source-table writeback exists; it is intentionally out of scope.
- Prefer `GET /data-quality/runs/{run_id}/hydration` for reload instead of many upfront DQ calls.

## 17. Current Scope Boundaries

Implemented:

- deployment entrypoint through workspace deployments
- run history for tenant + domain
- rerun-as-monitor flow
- timeline/events/chat shell
- DQ hydration endpoint
- trend APIs
- business-term trend APIs
- anomaly APIs
- rule-review pause and resume flow
- table/rule/duplicate/freshness/remediation APIs
- explainable evidence APIs
- dashboard API
- issue register APIs
- Excel export
- CSV-per-sheet export
- question-centric enrichment
- proposal review and staged overlay artifact flow

Still deferred or later:

- uploaded rule files
- source-table writeback
- latitude/longitude enrichment from full address
