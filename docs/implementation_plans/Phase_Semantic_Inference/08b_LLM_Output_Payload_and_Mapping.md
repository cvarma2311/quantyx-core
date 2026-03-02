# Phase 8b: LLM Output Payload + Graph Mapping

## Objective
Define the expected LLM output schema and how each section maps to semantic graph tables.

---

## LLM Output Payload

```json
{
  "ontology": {
    "entities": ["plant", "region", "sales_area"],
    "hierarchies": ["zone > region > sales_area > plant"]
  },
  "glossary": [
    {"term": "Plant", "synonyms": ["sap_id", "plant_id", "filling facility"]},
    {"term": "Region", "synonyms": ["ROName", "region"]}
  ],
  "metrics": [
    {"metric_name": "production_mt", "formula": "(production_14_2kg*14.2 + production_19kg*19)/1000"}
  ],
  "join_hints": [
    {"left_table": "fact_lpg_plant_operations", "right_table": "dim_plants", "left_key": "sap_id", "right_key": "sap_id"}
  ]
}
```

---

## Mapping to Tables

### Ontology
- Entities → `semantic_nodes` (type=concept)
- Hierarchies → `semantic_edges` (type=concept_hierarchy)

### Glossary
- Term → `semantic_nodes` (type=concept, if missing)
- Synonyms → `semantic_nodes` (type=synonym)
- Synonym → Concept edges (`synonym_concept`)

### Metrics
- Metric → `semantic_nodes` (type=metric)
- Metric → Model edges (`metric_model`) after validation

### Join Hints
- Join edges → `semantic_edges` (type=model_join)

---

## Validation Gate (Before Insert)
- Column exists in schema
- Metric formula uses valid columns
- Join keys exist in both tables
- Names normalized

Failed items are logged and dropped.

