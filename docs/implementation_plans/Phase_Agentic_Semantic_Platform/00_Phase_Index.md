# Phase: Agentic Semantic Platform (Multi‑Agent + Auto Dashboards)

Goal: Use multiple agents to extract semantics from schemas, build a deterministic semantic layer, and auto‑generate analytical dashboards with story‑driven charts. Mirror Cube‑style semantics + query speed while keeping NL resolution deterministic‑first.

## Phase Map

1. **Phase 01: Agentic Intake + Schema Understanding**
   - Agents ingest schema + context; produce normalized schema graph.

2. **Phase 02: Semantic Graph + Ontology Bootstrapping**
   - Build graph nodes/edges (concepts, metrics, dimensions, joins).

3. **Phase 03: Deterministic Query Planner**
   - Cache → rules → graph → SQL. LLM as fallback.

4. **Phase 04: Rollups + Cache Orchestration**
   - Cube‑style pre‑aggregations, rollup registry, refresh jobs.

5. **Phase 05: Auto‑Dashboard Story Engine**
   - Agents produce narrative dashboards + chart recommendations.

6. **Phase 06: NL Chat API + Embedding Integration**
   - Chat‑style query endpoint, response streaming + chart payloads.

7. **Phase 07: Learning Loop + Governance**
   - User feedback → semantic updates; approvals + audit.

8. **Phase 10: Semantic Model Generation (Cube‑Style Concepts)**
   - Auto‑generate measures, dimensions, joins, segments, time grains, rollups.

9. **Phase 11: Streaming Progress + Chat Logs**
   - Stream multi‑agent lifecycle updates and persist chat logs.

10. **Phase 12: Storage Model**
   - Backend tables required for agent runs, graph, rollups, dashboards.

11. **Phase 13: Public API Specs**
   - REST endpoints for agentic runs, semantic graph, queries, dashboards.

12. **Phase 14: View Explorer + SQL Editor**
   - APIs to list views, show schema, and run SQL queries.

13. **Phase 15: Agent Skill Profiles + Quality Gates**
   - Define agent specialization, success criteria, and validation gates.

14. **Phase 16: Agent‑to‑Agent Conversation Protocol**
   - Structured, low‑latency validation conversations between agents.

15. **Phase 17: Customer‑Visible Progress Stream**
   - Minimal reasoning, step‑based progress, artifact summaries.

16. **Phase 18: Planning Agent (Safe Reasoning Summary)**
   - High‑level plan shown to users instead of chain‑of‑thought.

17. **Phase 19: System Architecture**
   - End‑to‑end architecture diagram with optional LangGraph orchestration.

18. **Phase 20: LangGraph Orchestration**
   - Explicit agent graph, shared state, retries, and error handling.

19. **Phase 21: UI-to-API Flow (End-to-End)**
   - Ordered UI call sequence from schema selection to chat completion.

20. **Phase 22: Agent Metadata Summary + Inference Stream Compaction**
   - Add staged raw/summary/inference event lifecycle, HTML-friendly metadata, and payload compaction.

21. **Phase 23: Dashboard Refresh + Composite Insights**
   - Add dashboard refresh lifecycle, chart data recompute, and dashboard-wide summary/inference persistence + APIs.

## Dependencies
- Phases 01–03 required for baseline NL queries.
- Phase 04 required for performance parity with Cube‑style rollups.
- Phase 05 can run after 02 (semantic graph ready).
- Phase 22 depends on Phase 11 (streaming/chat logs), Phase 12 (storage), and Phase 20 (orchestration behavior).
- Phase 23 depends on Phase 05 (dashboard generation), Phase 11/22 (staged stream + artifacts), and Phase 20 (orchestration behavior).
