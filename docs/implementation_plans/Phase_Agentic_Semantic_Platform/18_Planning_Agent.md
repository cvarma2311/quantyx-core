# Phase 18: Planning Agent (Safe Reasoning Summary)

## Objective
Provide a user‑visible “reasoning” output as a **safe, high‑level plan** without exposing chain‑of‑thought. The planning agent outputs a deterministic step list used for UI transparency.

---

## Planning Agent Output Schema

```json
{
  "plan_id": "plan_123",
  "run_id": "run_123",
  "steps": [
    "Inspect schema + detect fact tables",
    "Generate glossary + metrics",
    "Build semantic model",
    "Create 3–5 reports",
    "Publish dashboard"
  ],
  "status": "ready"
}
```

---

## Where It Appears in UI
- Displayed as **“Plan”** or **“Reasoning Summary”**
- Updated as steps complete
- No internal chain‑of‑thought

---

## Execution Flow
1. Planning agent runs immediately after schema selection
2. Plan is stored in `quantyx_agent_chat_log`
3. Streaming progress references plan steps
4. Plan also emitted in `quantyx_agent_run_events` as PlanningAgent summary

---

## Success Criteria
- Users see a clear plan of action
- No sensitive reasoning exposed
