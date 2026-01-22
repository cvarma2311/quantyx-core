# quantyx-core-services: Architectural Deep Dive

This document provides a detailed view of the code architecture for `quantyx-core-services`, focusing on modularity, scalability, and automation.

---

## 1. Modular Code Structure

The key to a scalable and maintainable platform is a modular code structure. The `services` directory will be organized as follows to ensure a clean separation of concerns.

```
services/
├── api/
│   ├── main.py         # FastAPI app, endpoints (/query, /metrics)
│   └── schemas.py      # Pydantic models for API requests & responses
│
└── ai/
    ├── engine.py       # Main orchestrator for the AI engine
    │
    ├── data_source/
    │   ├── base.py     # Abstract `DataSource` class
    │   ├── postgres.py # `PostgresDataSource` implementation
    │   └── factory.py  # Creates data source instances from config
    │
    ├── semantic_layer/
    │   ├── loader.py   # Loads all metric definitions from YAML files
    │   ├── models.py   # Pydantic models for Metric, Dimension, etc.
    │   └── catalog.py  # `MetricCatalog` class for lookups
    │
    ├── query_builder/
    │   ├── resolver.py # NLQ -> Structured Query (LLM-powered)
    │   └── sql_generator.py # Structured Query -> Safe SQL
    │
    └── inference_engine/
        ├── base.py     # Abstract `InferenceTask` class
        ├── contribution_analysis.py # Concrete inference task
        └── pace_analysis.py         # Concrete inference task
```

### Component Responsibilities:

-   **`api`**: Handles all web-facing interactions. It knows nothing about how queries are built or executed; it only deals with HTTP requests and responses.

-   **`data_source`**: This is a critical abstraction for scalability. The rest of the application will never interact directly with a database driver. It will ask the `DataSource` factory for a connection to a specific domain, and the factory will provide an object that conforms to the `DataSource` interface (e.g., `get_schema()`, `execute_query()`). To add a new database type (e.g., Snowflake, BigQuery), we only need to add a new implementation here.

-   **`semantic_layer`**: This is the "brain" of the platform.
    -   `loader.py`: On startup, this module will scan the `contracts/metrics/` directory and load all `.yml` files into the `MetricCatalog`. This is how new domains are automatically discovered.
    -   `catalog.py`: Provides a single, unified interface to the entire semantic model of the organization, across all domains.

-   **`query_builder`**: This is where the core "AI" logic resides.
    -   `resolver.py`: Takes a natural language question (e.g., "Why is sales down in Tenali?"). It uses an LLM, guided by the information in the `MetricCatalog`, to translate this into a machine-readable structured query like:
        ```json
        {
          "metric": "sales_vs_target_achievement_pct",
          "dimensions": ["region", "sales_area"],
          "filters": [{"column": "sales_area", "operator": "=", "value": "Tenali"}]
        }
        ```
    -   `sql_generator.py`: A highly secure and robust module that takes the structured query and generates a safe, performant SQL query. It enforces all guardrails (SBU filters, timeouts, read-only).

-   **`inference_engine`**: A plug-in system for proactive insights. New inference capabilities (e.g., anomaly detection) can be added by simply creating a new class that inherits from `InferenceTask`.

---

## 2. Scalability: Onboarding a New Domain

The modular architecture makes onboarding a new domain (e.g., "Manufacturing") a straightforward, configuration-driven process.

**Step 1: Data Modeling (dbt)**
A data engineer models the new domain's data in dbt, creating the necessary staging, dimension, and fact tables. This is the only manual modeling step.

**Step 2: Define Semantics (YAML)**
The engineer then creates a new YAML file, `contracts/metrics/manufacturing.yml`, to define the semantics for this new domain.

```yaml
# contracts/metrics/manufacturing.yml
domain: manufacturing
data_source: production_db_postgres

dimensions:
  - name: plant
    sql: '{{ source("manufacturing_dims", "dim_plant") }}.plant_name'
  - name: production_line
    sql: '{{ source("manufacturing_dims", "dim_line") }}.line_id'

metrics:
  - name: production_output_units
    description: "Total units produced."
    type: sum
    sql: '{{ ref("fact_production_output") }}.units_produced'
```

**Step 3: Run the Application**
On the next startup, the `semantic_layer.loader` will automatically discover and load `manufacturing.yml`. The `MetricCatalog` will be updated, and the AI Query Engine will immediately be able to answer questions about the new domain, like "What was the production output for plant A vs plant B last week?". No code changes are required in the core AI service.

---

## 3. Automation: The "Document-Driven" Flow

To further accelerate the onboarding process, we can introduce a "document-driven" workflow using a high-level manifest and code generation.

### The Semantic Manifest

A data engineer would create a `semantic_manifest.yml` for a new data source. This file describes the tables and columns at a high level.

```yaml
# semantic_manifest.yml
domain_name: logistics
source_schema: raw_logistics
tables:
  - name: trips
    primary_key: trip_id
    columns:
      - name: trip_id
        data_type: string
        is_dimension: true
      - name: distance_km
        data_type: number
        is_measure: true
      - name: trip_duration_hours
        data_type: number
        is_measure: true
      - name: origin_depot
        data_type: string
        is_dimension: true
```

### The Code Generator

A CLI tool (`python -m tools.generate --manifest semantic_manifest.yml`) would parse this manifest and bootstrap the project:

1.  **Generate dbt Models:**
    -   It would create a basic `stg_logistics_trips.sql` model in `dbt/models/staging/` with column selection and casting.
    -   It would generate a `schema.yml` with basic `not_null` tests for the primary key.

2.  **Generate Metric Definitions:**
    -   It would create a `contracts/metrics/logistics.yml` file.
    -   For every column marked `is_measure: true`, it would pre-generate a set of standard metrics (`sum`, `avg`, `min`, `max`).
    -   For every column marked `is_dimension: true`, it would create a dimension definition.

### The Human-in-the-Loop

This automated generation provides a massive head start. A data analyst would then take over:

-   **Refine dbt Models:** Add more complex business logic, joins, and transformations to the generated dbt models.
-   **Enrich Metrics:** Add more meaningful business descriptions to the generated metrics, define more complex metrics, and remove any that are not needed.

This approach combines the speed of automation with the precision of human expertise, making the process of onboarding new domains extremely efficient while maintaining high quality.

---

## 4. Handling Correlated & Cross-Domain Data

The architecture is designed not just to handle new, isolated domains, but also to integrate and correlate data across different domains. This is critical for generating deep, contextual insights.

Let's consider an example: We have the existing **HPCL Sales** data, and we want to correlate it with new **Customer Satisfaction Score** data.

### Step 1: Model the Connection in the Data Layer (dbt)

The first step is to model the relationship between these concepts in the data transformation layer.

1.  **Stage the New Data:** A new dbt model, `stg_customer_satisfaction.sql`, is created from the new source table.
2.  **Create a Unified Fact Table:** This is the most important step. A data engineer creates a new dbt model (e.g., `fact_sales_area_performance`) that **joins** the sales data with the satisfaction data on a common grain, like `sales_area` and `month`.

    ```sql
    -- in dbt/models/marts/facts/fact_sales_area_performance.sql
    SELECT
      sales.date_month,
      sales.sales_area_id,
      sales.total_sales_volume,
      sales.target_achievement_pct,
      satisfaction.avg_satisfaction_score
    FROM {{ ref('fact_hpcl_sales_monthly') }} AS sales
    LEFT JOIN {{ ref('stg_customer_satisfaction') }} AS satisfaction
      ON sales.sales_area_id = satisfaction.sales_area_id
      AND sales.date_month = satisfaction.date_month
    ```
    This creates a single, "wide" table containing measures from both domains.

### Step 2: Define the New Semantics (YAML)

With the data connected, you simply describe the new metrics in the semantic layer. A new file, `contracts/metrics/customer_satisfaction.yml`, would be created:

```yaml
# contracts/metrics/customer_satisfaction.yml
domain: customer_experience

metrics:
  - name: average_satisfaction_score
    description: "The average customer satisfaction score for a given period."
    type: average
    sql: '{{ ref("fact_sales_area_performance") }}.avg_satisfaction_score'
```

### Step 3: Let the AI Engine Do the Work (No Code Change)

No changes are needed in the core AI service code. When a business user asks a correlated question like:

> "What is the relationship between sales achievement and customer satisfaction in the South zone?"

The AI engine will:
1.  **Resolve Metrics:** Identify the two metrics requested: `sales_vs_target_achievement_pct` and `average_satisfaction_score`.
2.  **Look up in Catalog:** The `MetricCatalog` will see that both metrics are available from the same underlying dbt model, `fact_sales_area_performance`.
3.  **Generate SQL:** The `sql_generator` will create a single, efficient SQL query against the unified table to retrieve both metrics.

### Guiding Philosophy for Cross-Domain Analysis

-   **dbt's Role (The "How"):** Join, clean, and transform data from different sources into unified, queryable tables. **dbt connects the data.**
-   **Semantic Layer's Role (The "What"):** Describe the business concepts available in the tables that dbt created. **The semantic layer connects the business logic.**
-   **AI Engine's Role (The "Action"):** Use the semantic definitions to intelligently answer questions, without needing to know the complexity of the underlying data joins.

This separation of concerns ensures that as your data landscape grows in complexity, the system remains scalable, maintainable, and easy to extend.
