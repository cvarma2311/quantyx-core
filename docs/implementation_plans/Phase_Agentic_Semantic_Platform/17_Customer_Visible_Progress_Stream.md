# Phase 17: Customer‑Visible Progress Stream (Cube‑Style)

## Objective
Provide a Cube‑style chat experience: minimal reasoning, step updates, and artifact summaries—without exposing chain‑of‑thought.

---

## Design Principles
- **Summarized, safe updates only**
- **Step‑based lifecycle**: Scan → Model → Reports → Dashboard
- **Clear artifacts**: list of models, reports, dashboards created
- Optional **“See details”** toggle (non‑reasoning logs only)
- **No reasoning trace** shown to customers (internal chain‑of‑thought is never exposed)
- Customers can provide **additional context via chat**; backend refreshes semantic models, views, and dashboards.
 - Initial onboarding baseline is produced **live from schema only**; context is applied later for refinement.

---

## Stream Event Schema

```json
{
  "run_id": "run_123",
  "message_type": "summary", 
  "step": "Modeling",
  "status": "in_progress", 
  "message": "Created semantic model with 5 metrics and 8 dimensions.",
  "artifacts": {
    "metrics": ["production_mt", "productivity"],
    "dimensions": ["region", "plant", "process_date"]
  }
}
```

## Live Implementation Notes
- Summary stream is written to `quantyx_agent_chat_log`.
- Messages are emitted for schema scan, profiling, metrics, rollups, and dashboard creation.

---

## Example Customer Stream (Minimal)

1) **Scan**
   - "Scanning schema for 8 tables..."
   - "Detected 4 facts, 12 dimensions"

2) **Model**
   - "Semantic model created"
   - "Metrics: Production (MT), Productivity"
   - "Dimensions: Region, Plant, Date"

3) **Reports**
   - "Generated 5 reports"
   - "Top reports: Production Trend, Rejection Rates, Sales Summary"

4) **Dashboard**
   - "Dashboard created: LPG Ops Overview"

---

## Example Stream (With Artifacts)

```
✅ Semantic Model Created
- Metrics: production_mt, productivity, sales_volume
- Dimensions: region, plant, process_date

✅ Reports Created (5)
- Production Trend (line)
- Top Plants by Rejections (bar)
- Sales by Region (bar)

✅ Dashboard Published
- LPG Operations Overview
```

---

## What is NOT Shown
- No chain‑of‑thought
- No raw LLM prompts
- No internal reasoning

---

## Success Criteria
- User understands progress without noise
- Summaries align with actual artifacts produced
