# Phase AB: Ask/NL Query Resolution + Semantic Binding (Derived Metrics Included)

Goal: restrict the Ask API to accept only `question` and `tenant_id`, then
resolve that NL question into semantic intent (facts, dimensions, metrics,
entities, hierarchies) and bind it to a queryable target (including derived
metrics registered in Phase AA).

This phase defines the Ask resolution architecture, semantic binding rules, and
the minimum data contracts needed to make NL → SQL deterministic.

---

## 1) API Contract (Restricted Ask)

**POST /query**

Request:
```json
{
  "tenant_id": "tenant_a",
  "question": "Top 5 sales areas by sales volume for MS in Q2 FY 2024-2025."
}
```

Response (unchanged shape, but generated only from NL):
```json
{
  "metrics": ["total_sales_volume_tmt"],
  "dimensions": ["sales_area_name"],
  "sql": "SELECT sales_area_name, SUM(sales_tmt) AS total_sales_volume_tmt FROM ...",
  "rows": [{"sales_area_name": "Tenali", "total_sales_volume_tmt": 123.4}],
  "semantic_validation": {...},
  "lineage": {...}
}
```

**Hard rule:** If the request includes any fields other than `tenant_id` and
`question`, return `400` with a clear error.

---

## 2) Architecture Overview (NL → Semantic → Query Target)

### 2.1 Pipeline stages
1) **Scope resolution**
   - Resolve active domain and default scope from tenant (Phase R/U).
   - Scope includes connection/database/schema/tables if tenant uses scoped
     onboarding (Phase N/Q).

2) **NL preprocessing**
   - Normalize time phrases (e.g., "this month", "Q2 FY 2024-2025").
   - Extract Top-N intent, comparisons, and thresholds.

3) **Semantic parsing**
   - Identify candidate metrics, dimensions, entities, hierarchies, filters.
   - Use glossary terms + ontology + hierarchy rules for mapping.

4) **Semantic binding**
   - Bind extracted candidates to canonical semantic objects:
     - Metrics → `quantyx_metrics_registry`
     - Dimensions → semantic contract / dataset model
     - Entities + Hierarchies → entity/hierarchy overrides
   - Resolve ambiguity by confidence + fallback prompts.

5) **Derived metric binding (Phase AA integration)**
   - If metric is derived from a flow node, locate the `current` registry row
     in `quantyx_flow_node_data_registry`.
   - Use its query target metadata + schema to bind the metric to a physical
     dataset.

6) **Query planning**
   - Assemble query plan (single fact, multi-fact joins per Phase H).
   - Apply hierarchy rollups and entity mappings.

7) **SQL generation and execution**
   - Generate SQL with resolved query target.
   - Execute via engine PyIceberg and return results.

---

## 2.2 Example Walkthrough (What Question)

Question:
> "What were the top 5 products by sales volume in Secunderabad last week?"

Assumptions:
- Today = 2026-02-19
- "last week" = 2026-02-09 to 2026-02-15

Step-by-step:
1) **Scope resolution**
   - Resolve `domain_id` from tenant registry.
   - Resolve default connection scope if required.
2) **NL preprocessing**
   - intent = top-N
   - metric term = "sales volume"
   - dimension term = "products"
   - location term = "Secunderabad"
   - time range = 2026-02-09..2026-02-15
3) **Semantic parsing**
   - metric candidates: `total_sales_volume_tmt`, `industry_sales_tmt`
   - dimension candidates: `product_name`, `sales_area_name`
4) **Semantic binding**
   - metric = `total_sales_volume_tmt`
   - group-by dimension = `product_name`
   - filter = `sales_area_name = "Secunderabad"`
   - time filter = calendar date between 2026-02-09 and 2026-02-15
5) **Derived metric binding (Phase AA)**
   - If derived: resolve `quantyx_flow_node_data_registry` current row,
     use `pyiceberg_table_fqn` or `minio_path`, and stored `semantic_binding`.
6) **Query planning**
   - select metric aggregation, group by product, apply filters, limit 5.
7) **SQL generation & execution**
   - build SQL and execute via engine.
8) **Response**
   - return metrics, dimensions, rows, explain payload, lineage.

---

## 2.3 Phase Dependencies (Data Sources Used by Ask)

Ask depends on upstream phases for specific inputs:

- **Phase A (Industry Packs + Ontology)**
  - Source: `packs/<industry>/ontology.yml`
  - Used for entity types, hierarchies, and default mappings.

- **Phase L (Business Context Intake)**
  - APIs: `POST /context/ingest`, `POST /context/extract`
  - Tables: `quantyx_glossary_terms`, `quantyx_context_extractions`
  - Used for glossary synonyms, abbreviations, and custom hierarchies.

- **Phase N/Q (Connection-Scoped Onboarding)**
  - APIs: `/onboard/map`, `/entities`, `/hierarchies`
  - Tables: `quantyx_entity_overrides`, `quantyx_hierarchy_overrides`
  - Used for scoped entity + hierarchy resolution.

- **Phase C/D (Metric + Dataset Catalog)**
  - APIs: `/metrics`, `/datasets`
  - Tables: `quantyx_metrics_registry`, dataset contracts
  - Used for metric definitions and dataset availability.

- **Phase AA (Flow Node Data Registry)**
  - Table: `quantyx_flow_node_data_registry`
  - Used to bind derived metrics to query targets + schema.

- **Phase R/U (Tenant/Scope Resolution)**
  - Used to resolve tenant domain + default scope without query params.

---

## 2.4 Low-Level Data + API Map (Ask Runtime Inputs)

This section lists the exact tables, columns, and upstream APIs that feed Ask.
Ask reads these directly from the DB or on-disk contracts at runtime.

### 2.4.1 Tenant + Scope Resolution
Tables:
- `public.quantyx_tenant_domains`
  - `tenant_id`, `domain_id`, `status`
- `public.quantyx_tenant_scopes` (if implemented in Phase U)
  - `tenant_id`, `default_connection_id`, `default_database`, `default_schema`, `default_tables`

APIs that populate:
- `POST /tenant/domain`
- `GET /tenant/domain`

### 2.4.2 Glossary + Ontology + Hierarchy
Tables / Files:
- `public.quantyx_glossary_terms`
  - `term`, `synonyms`, `abbreviation`, `canonical`, `source_context_id`
- `public.quantyx_entity_overrides`
  - `tenant_id`, `connection_id`, `database`, `schema`, `entity_id`, `join_key`, `description`
- `public.quantyx_hierarchy_overrides`
  - `tenant_id`, `connection_id`, `database`, `schema`, `hierarchy_name`, `levels`, `description`
- `public.quantyx_context_scope_active` (Phase AD)
  - active context selection for hierarchy resolution (multiple active contexts)
- `packs/<industry>/ontology.yml`

APIs that populate:
- `POST /context/ingest`, `POST /context/extract`, `POST /context/apply`
- `POST /onboard/map`
- `PATCH /entities/{entity_id}`
- `PATCH /hierarchies/{hierarchy_name}`

### 2.4.3 Metrics + Datasets
Tables / Contracts:
- `public.quantyx_metrics_registry`
  - `metric_id`, `definition_sql`, `status`, `grain`, `metadata`
- `contracts/datasets/*.yml` or DB‑stored dataset contract
  - dataset name, dimensions, grain, source model

APIs that populate:
- `POST /metrics`, `PATCH /metrics/{id}`
- `POST /metrics/suggested`
- `POST /contracts/apply`
- `GET /datasets`, `GET /metrics`

### 2.4.4 Derived Metric Binding (Phase AA)
Table:
- `public.quantyx_flow_node_data_registry`
  - `artifact_key`, `is_current`, `data_schema`, `pyiceberg_table_fqn`, `minio_path`
  - `semantic_binding`, `binding_status`, `binding_errors`

Written by:
- flow builder output writer (pipeline process)
- binding worker (Phase AB write-time binding)

### 2.4.5 Query Audit + Explainability
Table:
- `public.quantyx_query_audit`
  - `question`, `resolved_metrics`, `resolved_dimensions`, `resolved_filters`,
    `sql_hash`, `runtime_ms`, `asked_by`

API:
- `/query` (Ask)

---

## 2.5 Semantic Parsing (Detailed Implementation)

### 2.5.1 Normalization
- lowercase + trim
- normalize time phrases (this month, last week, Q2 FY 2024-2025)
- strip punctuation and extra whitespace

### 2.5.2 Phrase extraction (rule-based)
Input sources:
- glossary terms + synonyms
- ontology entity names + hierarchy levels
- metric aliases from `quantyx_metrics_registry.metadata.aliases`

Output candidates:
- metrics: [{metric_id, confidence, source}]
- dimensions: [{dimension_name, confidence, source}]
- entities: [{entity_id, confidence, source}]
- hierarchy_levels: [{hierarchy_name, level, confidence}]

### 2.5.3 LLM fallback
Inputs:
- question
- top candidate lists from rule-based parsing
- glossary + ontology snippets
Outputs:
- ranked candidates + confidence + rationale
Rules:
- if confidence < threshold, return ambiguity error
- never auto-bind to a low‑confidence candidate

---

## 3) Semantic Binding Rules (Key Concepts)

### 3.0 LLM Usage (When Needed)
Use LLMs as a fallback or assistive layer when rule-based matching is
insufficient or ambiguous. LLM calls must be bounded and deterministic:
- Inputs: question, glossary terms, ontology entities/hierarchies,
  candidate metrics/dimensions from registry + schema.
- Outputs: ranked candidates with confidence + rationale.
- Fallback: if confidence < threshold, return ambiguity error rather than guess.

### 3.1 Metrics
Priority order for metric resolution:
1) Exact metric name match (case-insensitive).
2) Glossary synonyms → metric alias map.
3) LLM-assisted match with confidence threshold.

If multiple metrics match, apply:
- domain priority
- dataset compatibility
- recent usage / popularity (optional)

### 3.2 Dimensions
Dimensions must exist in the selected dataset or in the resolved flow node
schema. If dimension not found:
- If entity name is detected, map to entity join key and alias as dimension.
- Otherwise mark as unresolved and return explain message.

### 3.3 Entities & Hierarchies
Entity mapping uses:
- `quantyx_entity_overrides` (scoped)
- domain ontology from packs (seeded)

Hierarchy rollups:
- If the question mentions hierarchy level (e.g. "Region"), map to hierarchy
  level fields and apply group-by.

---

## 4) Derived Metrics (Phase AA Binding)

### 4.1 When a metric is derived
Derived metric means:
- Metric is sourced from a flow node output rather than a static dataset.
- The flow node output exists in `quantyx_flow_node_data_registry`.

### 4.2 Binding steps
1) Resolve metric → flow node:
   - `quantyx_metrics_registry.metadata.flow_node_id`
   - Or `metric_definition.source_type = "flow_node"`
2) Fetch the `current` registry row using:
   - `artifact_key = flow_id::node_id`
3) Bind query target:
   - `pyiceberg_table_fqn` (preferred)
   - else `iceberg_catalog + namespace + table`
   - else `minio_path`
4) Use `data_schema` for column validation and NL grounding.

### 4.3 Fallback if no registry row
If no registry row exists:
- return 409 with message: "derived metric not materialized"
- include `flow_id` / `node_id` in explain response

---

## 5) Write-Time Semantic Binding (Flow Node Registry)

Goal: bind schema + semantic objects **when a row is written** to
`quantyx_flow_node_data_registry` so Ask never does heavy binding at runtime.

### 5.1 New columns
Add to `public.quantyx_flow_node_data_registry`:
- `semantic_binding JSONB` (resolved metrics/dimensions/entities/hierarchies)
- `binding_status TEXT` (`pending` | `bound` | `failed`)
- `binding_errors JSONB` (structured errors)
- `binding_version TEXT` (binding logic version)

### 5.2 Binding lifecycle (async)
1) Insert registry row with `binding_status = "pending"`.
2) Enqueue binding job with `row_id` (or `artifact_key` + `version_no`).
3) Worker loads row, resolves binding from:
   - `data_schema`, `transform_sql`, `metadata`, `source_artifact_keys`
   - metrics registry, ontology, entity overrides, hierarchies
4) Write `semantic_binding`, set `binding_status = "bound"`.
5) On error, set `binding_status = "failed"` + `binding_errors`.

### 5.3 JSONB shape (example)
```json
{
  "dimensions": [
    {"name": "sales_area_name", "source_column": "sales_area_name", "confidence": 0.92}
  ],
  "metrics": [
    {"name": "total_sales_volume_tmt", "source": "registry", "definition_sql": "..."}
  ],
  "entities": [
    {"entity_id": "organizational_unit", "join_key": "sales_area_name"}
  ],
  "hierarchies": [
    {"name": "sales_org", "levels": ["zone","region","sales_area"]}
  ],
  "binding_inputs": {
    "data_schema_hash": "sha256:...",
    "source_artifact_keys": ["flow_x::node_y"]
  }
}
```

### 5.4 Ask runtime behavior
- If `binding_status = "bound"`, Ask uses stored binding directly.
- If `binding_status = "pending"`, Ask returns **200** with partial response:
  - no `sql` or `rows`
  - include `semantic_validation` message: "binding in progress"
- If `binding_status = "failed"`, Ask returns binding errors and remediation hints.

---

## 6) Required Data Contracts

### 6.1 Metrics registry contract
Metrics must include:
- `metric_id`
- `definition_sql`
- `grain`
- `status`
- `metadata.source_type`: `dataset` | `flow_node`
- `metadata.flow_node_id` (when `flow_node`)

### 6.2 Flow node data registry contract (Phase AA)
Must provide:
- `tenant_id`, `domain_id`, `artifact_key`, `is_current`
- `minio_path` or `pyiceberg_table_fqn`
- `data_schema`

---

## 7) Error Handling + Explainability

### 7.1 Errors
- Missing metric → 400 with suggested alternatives
- Ambiguous metric → 409 with candidate list
- Missing derived dataset → 409 with remediation hint

### 7.2 Explain payload
Always include:
- resolved metric(s)
- resolved dimensions
- applied hierarchy level
- source dataset or flow node
- query target (catalog/table/path)

---

## 8) Acceptance Criteria

- Ask API accepts only `tenant_id` and `question`.
- NL can resolve metrics, dimensions, entities, hierarchies with deterministic
  binding rules.
- Derived metrics resolve to flow node registry targets (Phase AA).
- Explain payload includes semantic binding details.
- Ambiguity returns actionable errors, not silent failures.
- Flow node registry rows store precomputed `semantic_binding` JSONB.
- Ask does not perform heavy binding at runtime.
