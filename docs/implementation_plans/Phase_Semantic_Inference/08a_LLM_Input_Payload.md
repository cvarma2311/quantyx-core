# Phase 8a: LLM Input Payload (Context Bundle)

## Objective
Define the exact payload sent to the LLM and the minimal fields required to generate ontology, glossary, metrics, and join hints.

---

## Input Payload (Context Bundle)

```json
{
  "tenant_id": "VC_101",
  "domain_id": "lpg_production_distribution",
  "context_text": "<detailed application description + table/column meanings>",
  "schema_summary": {
    "tables": [
      {
        "name": "fact_lpg_plant_operations",
        "columns": [
          {"name": "sap_id", "type": "text"},
          {"name": "region", "type": "text"},
          {"name": "process_date", "type": "date"},
          {"name": "production_14_2kg", "type": "numeric"},
          {"name": "production_19kg", "type": "numeric"}
        ]
      }
    ]
  },
  "known_metrics": [
    {"metric_name": "production_mt", "sql": "(production_14_2kg*14.2 + production_19kg*19)/1000"}
  ],
  "known_glossary": [
    {"term": "Plant", "synonyms": ["sap_id", "plant_id"]}
  ],
  "rules": {
    "time_columns": ["process_date"],
    "default_time_grain": "day"
  }
}
```

---

## Required Fields
- `context_text`
- `schema_summary.tables[].name`
- `schema_summary.tables[].columns[].name`

## Optional Fields (Improve Accuracy)
- `known_metrics`
- `known_glossary`
- `rules`

---

## How It Is Used
- `context_text` drives semantic interpretation.
- `schema_summary` validates output.
- `known_metrics` and `known_glossary` anchor LLM output to canonical names.

