# Phase AF: Async Context Apply (Jobs)

Goal: make `/context/apply` asynchronous to avoid client timeouts when applying
large extractions (glossary, entities, hierarchies, metrics).

---

## 1) Why

Context apply can write hundreds of rows across multiple tables, causing
timeouts for synchronous clients. Async jobs ensure:
- no client timeout
- consistent progress tracking
- retry and auditability

---

## 2) API Additions

### 2.1 Async apply endpoint

`POST /context/apply/async`

Payload (same as `/context/apply`):
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "manufacturing",
  "extraction_id": "ext_123",
  "apply": { "entities": true, "hierarchies": true, "glossary": true, "metrics": true }
}
```

Response:
```json
{ "job_id": "job_ctx_apply_123", "status": "queued" }
```

Poll:
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

Result:
```json
{
  "job_id": "job_ctx_apply_123",
  "status": "completed",
  "result": { "status": "applied", "updated": { "entities": 4, "hierarchies": 2, "metrics": 8 } }
}
```

---

## 3) Job Worker Support

Add job type:
- `context_apply`

Worker executes:
1) Validate extraction + tenant scope
2) Run `apply_extractions(...)`
3) Auto‑activate context
4) Return ContextApplyResponse payload

---

## 4) Acceptance Criteria

- `/context/apply/async` returns `202` with `job_id`
- Job result matches synchronous apply output
- Large context applies complete without client timeouts
