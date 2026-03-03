# Phase 02: Semantic Graph + Ontology Bootstrapping

## Objective
Generate ontology + glossary + join graph from agent outputs and context text, then persist semantic graph.

## Agents
- **Ontology Agent**: proposes entity types + relationships
- **Glossary Agent**: extracts terms + synonyms
- **Join Agent**: detects joins across tables

## Inputs
- Schema graph
- Context text
- Optional: known glossary/metrics

## Outputs
- Semantic nodes (concepts, metrics, dimensions)
- Semantic edges (concept↔metric, concept↔dimension, joins)

## Deliverables
- `semantic_nodes`
- `semantic_edges`
- `semantic_usage`

## Notes
- Validate all LLM edges against schema.
- Confidence scores required for all edges.
 - Parallelism: Ontology + Glossary can run concurrently after Context; Join can run in parallel with Metric.
