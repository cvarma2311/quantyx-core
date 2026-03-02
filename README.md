# quantyx-core-services

## Run the API

Set the environment variables required for your environment, then start the server:

```bash
export QUANTYX_API_BASE=http://localhost:8787
export QUANTYX_DOMAIN=manufacturing
export QUANTYX_TENANT=x_mfg
export DEMO_DB_HOST=127.0.0.1
export DEMO_DB_PORT=5432
export DEMO_DB_NAME=your_db
export DEMO_DB_USER=your_user
export DEMO_DB_PASSWORD=your_password
export DEMO_DB_SCHEMA=public
export DEMO_TABLES=table_one,table_two
export DEMO_CONTEXT_TEXT="SBU = Strategic Business Unit. Sales org is Zone > Region > Sales Area."
# or use a file
export DEMO_CONTEXT_FILE=./artifacts/demo_business_context.txt

uvicorn services.api.main:app --reload --port 8787
```

If you use an `.env` file locally, load it before starting:

```bash
source .env
uvicorn services.api.main:app --reload --port 8787
```

## LangGraph Studio (Local Dev UI)

LangGraph Studio is local-only and requires no API key.

```bash
export LANGGRAPH_STUDIO_ENABLED=true
export LANGGRAPH_STUDIO_PORT=2024
langgraph dev --port 2024
```

Open:
```
http://127.0.0.1:2024
```

## Stream Progress (Your UI)

Agent run stream:
```
GET /agentic/runs/{run_id}/stream
```

Chat stream:
```
GET /chat/{chat_id}/stream
```
