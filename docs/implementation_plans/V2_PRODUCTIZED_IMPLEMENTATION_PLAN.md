# V2 Productized Implementation Plan

This document captures the current implementation status and the gaps needed to
fully realize `artifacts/V2_API.md` and `artifacts/V2_PRODUCT_PREREQUISITES.md`.
It is structured phase-by-phase with concrete deliverables.

---

## 0) Current implementation snapshot

Implemented (partial):
- dbt staging + marts for HPCL sales/targets/industry
- Core metric catalog in `contracts/metrics/core_metrics.yml`
- FastAPI service with `/query`, `/metrics`, `/schema`, `/health`
- OpenAI resolver + SQL builder + guardrails
- Multi-metric support for single-table metrics
- Documentation: Phase 1–5 guides, architecture and API docs updated

Missing or incomplete:
- Industry pack infrastructure (ontology + templates + policies)
- Onboarding pipeline (scan → map → generate → suggest → certify)
- API endpoints in `V2_API.md` beyond Ask/Query
- Metric lifecycle management (suggested/draft/certified)
- Governance endpoints (lineage, audit)
- Scenario and decision endpoints

---

## Phase A: Foundation for Productized Onboarding

Goal: introduce industry pack structure and prerequisites for any domain.

Deliverables:
1) **Industry pack structure**
   - `packs/<industry>/` folder with `ontology.yml`, `datasets.yml`, `metric_templates.yml`, `policies.yml`
   - Example: `packs/energy_distribution/`

2) **Ontology loader**
   - `services/ai/semantic_layer/loaders/ontology_loader.py`
   - Load entity types + hierarchies from pack

3) **Metric lifecycle registry**
   - Table or YAML registry with status: suggested/draft/certified/deprecated
   - API to list by status

4) **Doc updates**
   - Add “Industry pack checklist” appendix

Acceptance criteria:
- A new pack can be added without code changes
- Ontology is loaded and visible via `/entities`

---

## Phase B: Schema Scan and Auto-Detection Pipeline

Goal: implement `V2_PRODUCT_PREREQUISITES.md` auto-detection and suggested metrics.

Deliverables:
1) **Schema scan service**
   - `POST /onboard/scan`
   - Return table/column profiles (type, null rate, cardinality)

2) **Measure detection rules**
   - Implement pattern-based measure classifier
   - Output candidate measures with inferred units

3) **Entity and grain detection**
   - Map columns to ontology types with confidence score
   - Flag low-confidence matches for review

4) **Time semantics detection**
   - Identify primary date column and fiscal hints

5) **Suggested metric generator**
   - Generate baseline metrics from additive measures
   - Mark status = suggested

Acceptance criteria:
- Onboarding scan returns structured suggestions
- Suggested metrics exposed via `GET /metrics/suggested`

---

## Phase C: Contract Apply and Metric Editing

Goal: allow users to correct logic or add metrics after auto-detection.

Deliverables:
1) **Metric edit API**
   - `PATCH /metrics/{id}` for SQL, description, grain, status

2) **Metric create API**
   - `POST /metrics` to add new metric

3) **Contract validation**
   - `POST /contracts/validate` (YAML schema validation)

4) **Contract apply**
   - `POST /contracts/apply`
   - Reload catalog in API

Acceptance criteria:
- Suggested metric can be promoted to certified
- Custom metric can be added without code change

---

## Phase D: Semantic Layer and Explore APIs

Goal: fulfill Explore endpoints in `V2_API.md`.

Deliverables:
1) **Datasets registry**
   - `contracts/datasets/*.yml` per pack
   - `/datasets` endpoint

2) **Metric catalog endpoint**
   - `/metrics` returns status, owner, version

3) **Entities endpoint**
   - `/entities` returns hierarchy from ontology

Acceptance criteria:
- UI can browse datasets, metrics, and entities

---

## Phase E: Governance and Audit

Goal: implement lineage and audit for explainability.

Deliverables:
1) **Lineage builder**
   - Metric → dataset → dbt model mapping
   - `/governance/lineage`

2) **Query audit log**
   - `query_audit` table
   - Log question, metrics, SQL hash, runtime

3) **Policies endpoint**
   - `/policies` returns active policy filters

Acceptance criteria:
- Every query is auditable
- Lineage returns dbt model dependencies

---

## Phase F: Insights and Actions

Goal: proactive intelligence and decision loop.

Deliverables:
1) **Insight generation operators**
   - Variance, driver, anomaly, pace

2) **Insights feed**
   - `/insights` and `/insights/{id}`

3) **Action loop**
   - `/actions` endpoints
   - Feedback capture

Acceptance criteria:
- At least one automated insight per domain
- Action feedback stored in DB

---

## Phase G: Scenarios (Planning)

Goal: scenario creation and comparison endpoints.

Deliverables:
1) **Scenario tables**
   - `scenario`, `scenario_inputs`, `scenario_outputs`

2) **Scenario endpoints**
   - `/scenarios`, `/scenarios/{id}/run`, `/scenarios/compare`

Acceptance criteria:
- Scenario runs produce stored outputs

---

## Phase H: Multi-table and Multi-metric Expansion

Goal: support complex metrics and joins beyond single-table.

Deliverables:
1) **Multi-table query builder**
   - Query plan with join graph

2) **Unified fact models**
   - dbt intermediate models for cross-domain metrics

Acceptance criteria:
- Queries spanning multiple facts succeed with guardrails

---

## Phase I: Hardening and Productization

Goal: operational readiness for multiple tenants.

Deliverables:
- RBAC and tenant scoping
- Rate limiting
- Monitoring dashboards
- Release/versioning for contracts

---

## Appendix: Gaps vs `V2_API.md`

Required endpoints not yet implemented:
- `/context/*`
- `/onboard/*`
- `/datasets`, `/entities`
- `/insights/*`
- `/scenarios/*`
- `/actions/*`
- `/governance/*`
- `/policies`
- `/contracts/*`

---

## Appendix: Gaps vs `V2_PRODUCT_PREREQUISITES.md`

Missing prerequisites in code:
- Industry pack loader
- Schema scan + metric suggestion pipeline
- Metric lifecycle registry
- Metric editing workflow
