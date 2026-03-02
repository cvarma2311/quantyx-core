# Phase 06: NL Chat API + Embedding Integration

## Objective
Expose a chat‑style API (similar to Cube Chat API) that resolves NL queries and returns SQL + chart payloads quickly.

## Features
- Streaming responses
- Deterministic + cached results
- Chart payloads in response
- Sync and async modes
 - Chat progress events (step-by-step)

## Deliverables
- `/chat` or `/query/chat` endpoint
- Streaming support + polling
- Integration with dashboards
- `/chat/{chat_id}` poll endpoint
 - `/chat/{chat_id}/events` + `/chat/{chat_id}/stream`
