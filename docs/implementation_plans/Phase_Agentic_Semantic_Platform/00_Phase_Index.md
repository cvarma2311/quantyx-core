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

22. **Phase 24: Tenant/Domain Deployment Run + Conversational Workspace**
   - Enforce one canonical deployment run per tenant/domain and persist workspace-scoped chat conversations with analytics artifacts.

23. **Phase 25: Tenant-First Chat Entry and History APIs**
   - Add tenant/domain discovery, scan/deployment readiness, and conversation history APIs with SSE-first chat entry.

24. **Phase 26: Workspace UI Sequential API Flow**
   - Define end-to-end UI call order (new tenant and existing tenant paths) with sequence diagrams and canonical payload rules.

25. **Phase 27: Agentic Dashboard and Chart Title Generation**
   - Enforce contextual, agent-generated titles for dashboards/charts with deterministic fallback, overrides, and refresh consistency.

26. **Phase 28: Ontology-Driven Executive KPI Dashboards**
   - Prevent invalid code/id aggregations and enforce ontology-driven, executive KPI chart generation with semantic quality gates.

27. **Phase 29: Semantic Role Classification and Measure Eligibility**
   - Classify columns by semantic role and enforce hard measure eligibility before metric generation.

28. **Phase 30: Template-First KPI Metric Generation**
   - Prioritize domain template KPIs and constrain fallback metric generation to validated measures.

29. **Phase 31: KPI Chart Planner and SQL Semantic Safety**
   - Restrict chart planning to approved KPI metrics and prevent SQL fallback to invalid aggregations.

30. **Phase 32: Executive KPI Quality Gates and Regression**
   - Enforce dashboard KPI composition, anti-pattern checks, and regression protections.

31. **Phase 34: Agent Artifact Persistence and Conversation Intelligence**
   - Make every agent persist durable scoped artifacts and make workspace conversations use those persisted artifacts as the semantic intelligence source of truth.

32. **Phase 35: KPI-First Record-Aware Auto Dashboard Generation**
   - Make agents prefer strong business KPI columns and real record evidence so auto dashboards generate the expected day/month trend and operational breakdown charts automatically.

33. **Phase 36: Context-Text-First LLM Metric Interpretation and Validation**
   - Make `context_text` the primary human-authored business input for metric creation, with LLM proposal, deterministic validation, provenance persistence, and downstream KPI/chart prioritization.

34. **Phase 37: LLM-First KPI Family Proposal and Broad Dashboard Composition**
   - Make metrics, charts, and dashboards LLM-first over validated semantic artifacts, enforce aligned KPI-family derivation, and allow broader high-confidence dashboard coverage.

35. **Phase 38: Anomaly Investigation and Action Intelligence**
   - Add an LLM-assisted anomaly investigation agent that detects meaningful business anomalies, identifies high-signal investigative areas, generates multiple evidence-backed why-hypotheses, and persists descriptive plus prescriptive action insights for workspace reuse.

36. **Phase 39: LLM-First Workspace Conversation Query Interpretation and Safe Compilation**
   - Make workspace conversation query understanding LLM-first, then validate and compile deterministically so filters, dimensions, chart intent, and SQL stay aligned with the user question.

37. **Phase 40: Context-Driven Cross-Table Dashboard Composition and Titling**
   - Make dashboard title generation and dashboard composition derive from the full KPI/chart context across all scoped tables, not from a single picked table, and allow broader high-value chart coverage beyond the current small-chart cap.

38. **Phase 41: Chart Conversation, Drill-Down, and Follow-Up Visual Analytics**
   - Make every chart conversational so users can ask follow-up questions, apply filters, drill into dimensions, and get new SQL-backed charts derived from the selected chart context.

## Dependencies
- Phases 01–03 required for baseline NL queries.
- Phase 04 required for performance parity with Cube‑style rollups.
- Phase 05 can run after 02 (semantic graph ready).
- Phase 22 depends on Phase 11 (streaming/chat logs), Phase 12 (storage), and Phase 20 (orchestration behavior).
- Phase 23 depends on Phase 05 (dashboard generation), Phase 11/22 (staged stream + artifacts), and Phase 20 (orchestration behavior).
- Phase 24 depends on Phase 11/22 (run events and artifacts), Phase 12 (storage), and Phase 23 for dashboard-linked insights continuity.
- Phase 25 depends on Phase 24 (conversation/deployment model) and Phase 11/22 for SSE and run event consistency.
- Phase 26 depends on Phases 24 and 25 (workspace APIs) and standardizes UI integration sequencing.
- Phase 27 depends on Phase 05/23 (dashboard and refresh flows) and Phase 24+ for consistent workspace/API exposure.
- Phase 28 depends on Phases 02/05/15/23/27 and hardens KPI semantics, metric eligibility, and dashboard business quality.
- Phase 29 depends on Phases 02/15/28 and establishes semantic-role foundations.
- Phase 30 depends on Phases 02/10/28/29 and operationalizes template-first KPI metrics.
- Phase 31 depends on Phases 03/05/28/29/30 and hardens planner + SQL execution safety.
- Phase 32 depends on Phases 15/23/28/29/30/31 and finalizes quality gate + regression controls.
- Phase 34 depends on Phases 12/20/22/24/25 and makes persisted deployment artifacts the sole semantic intelligence input for workspace conversations.
- Phase 35 depends on Phases 29/30/31/32/34 and makes auto dashboards KPI-first and record-aware instead of first-column heuristic driven.
- Phase 36 depends on Phases 24/29/30/34/35 and makes deployment context text a first-class LLM input for validated metric creation and KPI prioritization.
- Phase 37 depends on Phases 35 and 36 and extends the same LLM-first, validation-backed approach to KPI-family derivation, chart proposal, and broad dashboard composition.
- Phase 38 depends on Phases 24/34/35/36/37 and adds anomaly investigation, multi-hypothesis why-analysis, and action intelligence over persisted semantic and raw-evidence artifacts.
- Phase 39 depends on Phases 24/31/34/36/37 and hardens workspace conversation query interpretation with LLM-first plan extraction, deterministic validation, and safe SQL/chart compilation.
- Phase 40 depends on Phases 27/31/35/36/37/39 and broadens dashboard composition from single-table heuristics to context-driven, cross-table dashboard intelligence with improved title synthesis and larger, value-ranked chart sets.
- Phase 41 depends on Phases 24/31/33/34/39/40 and extends workspace conversation into chart-scoped follow-up analysis, safe SQL refinement, drill-down charts, and chart-aware artifact persistence.
