# Phase 16: Agent‑to‑Agent Conversation Protocol

## Objective
Enable structured, low‑latency agent‑to‑agent conversations to validate outputs and improve semantic quality without introducing non‑deterministic chatter.

---

## When Agents Talk
Structured conversations are allowed only for:
- Join validation
- Metric formula validation
- Glossary synonym verification
- Dashboard feasibility checks

---

## Conversation Rules
- **No free‑form chat**
- Must use structured payloads
- Each question must have a deterministic expected answer type

---

## Conversation Payload Schema

### Request
```json
{
  "from_agent": "JoinAgent",
  "to_agent": "SchemaAgent",
  "question": "Is sap_id unique in dim_plants?",
  "expected_answer_type": "boolean",
  "context": {
    "table": "dim_plants",
    "column": "sap_id"
  }
}
```

### Response
```json
{
  "from_agent": "SchemaAgent",
  "to_agent": "JoinAgent",
  "answer": true,
  "confidence": 0.92,
  "evidence": "Distinct count equals row count"
}
```

---

## Orchestration
- Conversations are recorded in `quantyx_agent_run_events`.
- Responses may adjust confidence of semantic edges.
 - JoinAgent requests SchemaAgent uniqueness checks for join keys (first N joins).

---

## Success Criteria
- Joins validated > 80%
- Metrics invalidation rate reduced
- Latency impact < 10%
