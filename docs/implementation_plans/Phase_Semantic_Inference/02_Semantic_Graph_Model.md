# Phase 2: Semantic Graph Model

## Objective
Define a graph schema for concepts, metrics, dimensions, models, columns, synonyms, joins, and rules, with confidence and provenance.

## Node Types
- **Concept**: Business idea (Plant, Region, Production)
- **Metric**: Computable KPI (`production_mt`)
- **Dimension**: Group-by field (`region`, `process_date`)
- **Model**: Fact/dim tables, views
- **Column**: Physical column with datatype
- **Synonym**: Alias to a concept
- **TimeGrain**: day, week, month
- **Rule**: Deterministic heuristic definition

## Edge Types
- `concept → metric`
- `concept → dimension`
- `synonym → concept`
- `metric → model`
- `dimension → column`
- `model ↔ model` (join)
- `rule → metric/dimension/timegrain`

## Required Edge Attributes
- `confidence` (0–1)
- `source` (`rule|llm|user_confirmed|imported`)
- `created_at`, `updated_at`
- Optional `evidence` (question_id, user_id)

## Storage (Postgres)
### `semantic_nodes`
- `node_id` (PK)
- `node_type`
- `name`
- `normalized_name`
- `domain_id`
- `metadata` (JSON)
- `confidence`

### `semantic_edges`
- `edge_id` (PK)
- `src_node_id`
- `dst_node_id`
- `edge_type`
- `confidence`
- `source`
- `metadata` (JSON)
- `created_at`
- `updated_at`

### `semantic_usage`
- `question_hash`
- `question_text`
- `resolved_metric`
- `resolved_dimensions`
- `intent`
- `created_at`

## Graph Resolution Algorithms
- Concept match: token similarity + synonyms
- Edge traversal: max confidence path
- Join resolution: shortest join path with highest confidence

## Success Metrics
- High-confidence edge coverage for top 20 metrics
- Join paths resolved deterministically for 80% of metric+dim combos

