# Phase 19: System Architecture (Agentic Semantic Platform)

## Objective
Provide a clear end‑to‑end architecture diagram for the multi‑agent semantic platform, including optional LangGraph orchestration.

---

## Architecture Diagram (Mermaid)

```mermaid
flowchart TB
  subgraph UI
    A[Schema Selection UI]
    B[Progress Stream]
    C[NL Chat]
    D[Dashboard UI]
    E[SQL Editor]
  end

  subgraph API
    F["/agentic/runs"]
    G["/query"]
    H["/charts/{id}"]
    I["/dashboards"]
    J["/views/query"]
    K["/semantic/*"]
    L1["/chat"]
    L2["/rollups"]
  end

  subgraph Orchestration
    L[Agent Orchestrator]
    M[(LangGraph optional)]
  end

  subgraph Agents
    S1[Schema Agent]
    S2[Profiling Agent]
    S3[Context Agent]
    S4[Glossary Agent]
    S5[Join Agent]
    S6[Metric Agent]
    S7[Semantic Model Agent]
    S8[Rollup Planner Agent]
    S9[Chart Planner Agent]
    S10[Dashboard Story Agent]
    S10a[Planning Agent]
    S11[Quality Gate Agent]
    S12[Ontology Agent]
  end

  subgraph Storage
    T1[(quantyx_semantic_nodes)]
    T2[(quantyx_semantic_edges)]
    T3[(quantyx_rollup_registry)]
    T4[(quantyx_dashboard_specs)]
    T5[(quantyx_agent_run_events)]
    T6[(quantyx_agent_chat_log)]
    T7[(quantyx_chat_requests)]
  end

  A --> F --> L --> S1
  L --> S2
  L --> S3
  S2 --> S5
  S2 --> S6
  S2 --> S7
  S3 --> S12
  S12 --> S4
  S6 --> S8
  S5 --> S11
  S12 --> S11
  S8 --> S9
  S11 --> S9
  S9 --> S10
  L --> S10a

  S1 --> T1
  S2 --> T1
  S3 --> T1
  S4 --> T1
  S5 --> T2
  S6 --> T2
  S7 --> T1
  S8 --> T3
  S10 --> T4
  S10a --> T5
  S11 --> T5
  S12 --> T2
  L --> T6

  G --> T1
  G --> T2
  G --> T3
  G --> H
  L1 --> T7

  D --> I --> T4
  E --> J

  L <--> M
  B <-- F
  C --> G
```

---

## Sequence Diagram (Mermaid)

```mermaid
sequenceDiagram
  actor User
  participant UI
  participant API
  participant Orchestrator
  participant Agents
  participant DB

  User->>UI: Select connection + tables
  UI->>API: POST /agentic/runs
  API->>Orchestrator: enqueue agentic run
  Orchestrator->>Agents: execute LangGraph workflow
  Agents->>DB: read schema + profile data
  Agents-->>API: emit progress events
  API-->>UI: stream /agentic/runs/{run_id}/stream

  Agents->>DB: write semantic graph + rollups (parallel branches)
  Agents->>DB: ChartPlannerAgent ranks chart candidates
  Agents->>DB: DashboardAgent builds charts + dashboard spec
  Orchestrator-->>API: run completed
  API-->>UI: status completed

  Note over Agents: Agent-to-agent validation (live)
  Agents->>DB: JoinAgent checks uniqueness on join keys
  Agents-->>Orchestrator: Confidence updated based on SchemaAgent response

  User->>UI: Ask NL question
  UI->>API: POST /chat (sync or async)
  API->>DB: resolve + run SQL
  API-->>UI: response + chart_id
  UI->>API: GET /charts/{chart_id}
  API-->>UI: chart payload + data
```

---

## Notes
- **LangGraph optional**: use if we need explicit agent graph orchestration.
- **Agent Orchestrator** can be our existing job system + event stream.
- **All outputs persist into quantyx_* tables**.
- **Agent-to-agent interactions are live**: JoinAgent issues SchemaAgent uniqueness checks and records request/response in `quantyx_agent_run_events`.
