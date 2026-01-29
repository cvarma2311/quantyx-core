# Phase K: Onboarding Demo Script

Goal: provide a runnable demo that shows the full onboarding flow end-to-end.

## Script
- `onboarding_demo.py`
- Accepts domain + connection inputs via environment variables
- Runs the API flow sequentially
- Logs every request and response for debugging and handoff

---

## Demo flow

1) **Scan connection**
   - `POST /onboard/scan-connection`
   - Uses multi-connection payload

2) **Ontology mapping**
   - `POST /onboard/map`
   - Uses the schema/tables returned from scan

3) **Entities + hierarchies**
   - `GET /entities` for review

4) **Infer facts/dims**
   - `POST /onboard/infer-models`
   - Uses scan outputs

5) **Suggested metrics**
   - `POST /metrics/suggested?persist=true`

6) **Promote a metric**
   - `PATCH /metrics/{metric_id}`

7) **Apply contracts**
   - `POST /contracts/apply`

---

## Inputs

Environment variables:
- `QUANTYX_API_BASE` (default `http://127.0.0.1:8000`)
- `QUANTYX_DOMAIN` (default `manufacturing`)
- `QUANTYX_TENANT` (default `x_mfg`)
- `DEMO_TABLES` (required; comma-separated table names)

Connection details:
- `DEMO_DB_HOST`
- `DEMO_DB_PORT`
- `DEMO_DB_NAME`
- `DEMO_DB_USER`
- `DEMO_DB_PASSWORD`
- `DEMO_DB_SCHEMA`

---

## Acceptance criteria
- Running the script completes without error.
- Each step logs the request + response payload.
- The script exits early if `DEMO_TABLES` is not provided.
- At least one metric is promoted and the catalog is reloaded.
