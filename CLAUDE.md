e# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Quantyx-Core is an **AI-native Operations Intelligence platform** — a dbt-first, contract-driven decision intelligence system that answers "what is happening, why is it happening, and what to do next" through natural language Q&A over operational PostgreSQL databases. It supports multiple industry verticals (Manufacturing, LPG Production/Distribution, Petroleum Refinery, Energy Distribution, Logistics) through configuration packs rather than code forks.

## Running the API

```bash
source .env
uvicorn services.api.main:app --reload --port 8787
```

## Running Tests

```bash
pytest tests/
pytest tests/test_quality_gate.py       # quality gate logic
pytest tests/test_semantic_extraction.py
pytest tests/test_validators.py
```

## LangGraph Studio (Local Dev UI)

```bash
export LANGGRAPH_STUDIO_ENABLED=true
export LANGGRAPH_STUDIO_PORT=2024
langgraph dev --port 2024
# Access at http://127.0.0.1:2024
```

## dbt Commands

```bash
dbt run        # Build models
dbt test       # Run tests
dbt compile    # Parse and validate
dbt debug      # Check connection
```

## Database Schema Setup

```bash
bash scripts/create_quantyx_tables.sh    # Initial setup
bash scripts/apply_agentic_tables.sh     # Apply schema updates
```

## Python Version

Use Python **3.10 or 3.11** — Python 3.12 is not compatible with dbt.

## Architecture

### Layered System

```
Client/UI → FastAPI (services/api/) → AI Decision Engine (services/ai/) → Semantic/Dataset Layer → PostgreSQL + dbt
```

### Key Modules in `services/ai/`

- **`agentic_orchestrator.py`** — LangGraph state machine coordinating multi-agent workflows. The central control plane for agentic runs.
- **`agentic_agents.py`** — Individual agent implementations (each workflow step: scan, extract, map, infer, certify, query, chart, insight).
- **`semantic_layer/`** — Loads and resolves semantic meaning from YAML contracts and industry packs.
- **`metrics_registry.py`** — Metric inference, registration, and retrieval.
- **`catalog.py`** — Loads metric catalogs from packs and contracts.
- **`resolver.py` / `semantic_graph_resolver.py`** — Translates natural language questions into metric queries.
- **`sql_builder.py`** — Dynamic SQL generation from semantic resolution.
- **`charts.py` / `chart_inference.py`** — Chart type inference and spec generation.
- **`quality_gate.py`** — Validates LLM outputs and query results before returning to client.
- **`db.py`** — PostgreSQL connection pooling (read-only access to operational data).
- **`jobs_store.py`** — Background async job tracking.

### `services/api/main.py`

Single FastAPI app file with 200+ routes. Key route groups:
- `/agentic/` — Agentic run management and streaming (`GET /agentic/runs/{run_id}/stream`)
- `/chat/` — Conversational interface (`GET /chat/{chat_id}/stream`)
- `/onboarding/` — Context ingest, schema scan, entity mapping
- `/metrics/`, `/dimensions/`, `/facts/` — Semantic object management
- `/charts/`, `/insights/`, `/scenarios/` — Analytics outputs

### Semantic Contracts (`contracts/`)

YAML files define metrics, joins, and business rules. Business meaning lives here — AI reasons over these contracts, not raw schemas.

### Industry Packs (`packs/{domain}/`)

Each domain pack contains:
- `ontology.yml` — Entity hierarchies
- `datasets.yml` — Curated data views
- `metric_templates.yml` — Domain metric templates
- `policies.yml` — Business rules and guardrails

### Per-Tenant dbt Projects (`dbt_projects/`)

Auto-generated per-tenant dbt configs. Manifests are stored in `quantyx_dbt_manifest` and `quantyx_dbt_config` tables in PostgreSQL.

### Quantyx Metadata Tables

Defined in `artifacts/quantyx_tables.sql`. These tables (prefixed `quantyx_`) store query audit logs, insight events, scenarios, jobs, semantic models, contexts, and agentic run state — all in the same PostgreSQL instance as the operational data.

## Key Architectural Principles

1. **Contracts over code** — Business meaning lives in YAML, not Python logic.
2. **dbt owns data truth** — All joins, transformations, and correlations happen in dbt. AI never reads raw schemas directly.
3. **Explainability first** — Every answer is traceable to metrics, datasets, and queries.
4. **Industry packs, not custom code** — Domains are configurations, not forks.
5. **Incremental path** — Analytics → Explain → Predict → Scenario → Optimize.

## Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Purpose |
|---|---|
| `DEMO_DB_*` | Database connection (HOST, PORT, NAME, USER, PASSWORD, SCHEMA) |
| `OPENAI_API_KEY` | LLM API key |
| `OPENAI_MODEL` | Default `gpt-4o-mini` |
| `DBT_MANIFEST_PATH` | Path to dbt manifest JSON |
| `DBT_PROJECT_BASE` | Base dir for per-tenant dbt projects |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | LangSmith API key |
| `JOB_WORKER_ENABLED` | Enable background job worker |
| `LANGGRAPH_STUDIO_ENABLED` | Enable local LangGraph dev UI |

## Demo Scripts

```bash
python3 scripts/demo_lpg_end_to_end.py           # Full onboarding + analytics flow
python3 scripts/demo_workspace_deployment_lpg.py  # Workspace deployment
python3 scripts/smoke_agentic_chat.py             # Agentic chat smoke test
```

The end-to-end demo flow: Context Ingest → Extract → Schema Scan → Context Apply → Entity Mapping → Model Inference → Metric Suggestion → Certification → Query & Analysis.