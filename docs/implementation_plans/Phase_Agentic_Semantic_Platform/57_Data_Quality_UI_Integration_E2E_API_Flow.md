# Phase 57: Data Quality UI Integration E2E API Flow

This guide is for UI developers integrating the implemented data quality workflow end to end.

It focuses on:

- the deployment run flow
- the minimal APIs needed to render and reload a run
- the structured APIs the UI should call for review, enrichment, evidence, dashboard, and report actions
- example requests and responses for the main cases

The intended UI model is:

- the deployment run remains conversation/timeline style
- structured DQ APIs back the cards, tasks, tables, evidence drawers, and action flows inside that run

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
- remediation summary
- report/dashboard/action links

Use lazy APIs only when the user drills into a section.

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
    "artifacts": {
      "run_summary": "/data-quality/runs/run_dq_001",
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
    "excel_report": "/data-quality/reports/run_dq_001/excel?tenant_id=VC_101&domain_id=data_quality_observability"
  }
}
```

### UI behavior

Use this payload to render:

- status banner
- pending review cards
- top enrichment questions
- remediation preview
- report/dashboard buttons

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
    "workflow_status": "completed"
  },
  "created_at": "2026-04-22T09:00:00Z",
  "completed_at": "2026-04-22T09:05:00Z"
}
```

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
2. `GET /agentic/runs/{run_id}/stream`
3. `GET /data-quality/runs/{run_id}/hydration`
4. when run completes:
   - `GET /data-quality/runs/{run_id}`
   - `GET /data-quality/runs/{run_id}/dashboard`
   - `GET /data-quality/reports/{run_id}/excel?...`
5. lazy on click:
   - tables
   - rules
   - duplicates
   - freshness
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

## 14. Recommended UI Integration Plan

### Call immediately

- `POST /workspace/deployments`
- `GET /agentic/runs/{run_id}/stream` or `GET /agentic/runs/{run_id}/events`
- `GET /data-quality/runs/{run_id}/hydration`

### Call when run completes or refreshes

- `GET /data-quality/runs/{run_id}`
- `GET /data-quality/runs/{run_id}/dashboard`

### Call when user opens a panel

- `GET /data-quality/tables`
- `GET /data-quality/tables/{table_name}`
- `GET /data-quality/rules`
- `GET /data-quality/duplicates`
- `GET /data-quality/freshness`
- `GET /data-quality/remediation`
- `GET /data-quality/enrichment/questions`

### Call when user performs an action

- `POST /data-quality/rules/{rule_id}/review`
- `POST /data-quality/runs/{run_id}/resume-after-rule-review`
- `POST /data-quality/enrichment/questions/{opportunity_id}/answer`
- `POST /data-quality/enrichment/proposals/{proposal_id}/approve-application`

### Call only for drill-through or export

- evidence APIs
- `GET /data-quality/enrichment/proposals/{proposal_id}`
- `GET /data-quality/enrichment/proposals/{proposal_id}/staged-artifact`
- `GET /data-quality/reports/{run_id}/excel`

## 15. Important Product Rules for UI

- Keep deployment trace conversation-style.
- Use structured DQ APIs as the source of truth for cards and actions.
- Do not load evidence APIs eagerly.
- Do not require the user to approve enrichment row by row.
- Do not expose backend internals like `executor_kind` as a primary control.
- Do not assume source-table writeback exists; it is intentionally out of scope.
- Prefer `GET /data-quality/runs/{run_id}/hydration` for reload instead of many upfront DQ calls.

## 16. Current Scope Boundaries

Implemented:

- deployment entrypoint through workspace deployments
- timeline/events/chat shell
- DQ hydration endpoint
- rule-review pause and resume flow
- table/rule/duplicate/freshness/remediation APIs
- explainable evidence APIs
- dashboard API
- Excel export
- question-centric enrichment
- proposal review and staged overlay artifact flow

Still deferred or later:

- uploaded rule files
- CSV-per-sheet exports
- source-table writeback
- latitude/longitude enrichment from full address
