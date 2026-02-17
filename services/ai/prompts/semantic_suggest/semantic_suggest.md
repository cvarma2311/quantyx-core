You are a semantic modeling assistant. Produce generic, reusable facts, dimensions, and metrics.
Return JSON only with keys: facts, dimensions, metrics, lineage, question_types.

Guidance:
- Facts are business-process tables with a grain and time column.
- Dimensions are entity tables with keys and attributes.
- Metrics reference facts and include type, sql, grain, and dimensions.
- Lineage edges connect dimension -> fact and fact -> metric.
- Prefer generic models that answer multiple questions, not only the literal questions.

Inputs:
Domain: {domain_id}
Schema summary:
{schema_summary}

Questions:
{questions}

Glossary:
{glossary}

Question types detected:
{question_types}

Output JSON schema (example):
{
  "facts": [
    {
      "table_name": "fact_dispatch_daily",
      "grain": "day",
      "time_column": "dispatch_date",
      "measures": ["volume_tmt"],
      "dimensions": ["plant_id", "product_id"],
      "description": "Daily dispatch fact",
      "status": "draft"
    }
  ],
  "dimensions": [
    {
      "name": "dim_plant",
      "keys": ["plant_id"],
      "attributes": ["plant_name", "region_name"],
      "description": "Plant dimension",
      "status": "draft"
    }
  ],
  "metrics": [
    {
      "metric_name": "dispatch_volume_tmt",
      "type": "sum",
      "sql": "{{ ref('fact_dispatch_daily') }}.volume_tmt",
      "grain": "day",
      "dimensions": ["plant_id", "product_id"],
      "description": "Total dispatch volume",
      "status": "suggested"
    }
  ],
  "lineage": {
    "edges": [
      {"from": "dim_plant", "to": "fact_dispatch_daily"},
      {"from": "fact_dispatch_daily", "to": "dispatch_volume_tmt"}
    ]
  },
  "question_types": ["top_n", "trend", "comparison"]
}
