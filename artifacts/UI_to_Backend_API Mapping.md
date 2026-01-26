# Quantyx UI ↔ Backend API Mapping
React components aligned to Architecture v2.

---

## 0. Frontend mental model (important)

Your frontend is not a dashboard app. It is a decision workspace composed of:

- Context (domain, time, scenario)
- Questions
- Explanations
- Insights
- Actions

So the UI is stateful, context-driven, and explanation-first.

## 1. Global App Shell (Always Present)

React Components
```jsx
<AppShell>
  <TopContextBar />
  <SideNav />
  <MainWorkspace />
  <InsightTray />
</AppShell>
```

Backend APIs

API | Purpose
--- | ---
GET /context/domains | List domain packs
GET /context/scenarios | List scenarios
POST /context/set | Set active context

Backend modules

semantic_layer.catalog  
Scenario context resolver  
Policy loader

Customer interaction

Switch domain (Energy / Manufacturing / Logistics)

Switch scenario (Baseline / Scenario A)

Change time window

Every query downstream uses this context implicitly

## 2. Side Navigation → Product Capabilities

Final Side Menu (recommended)
Ask
Explore
Insights
Scenarios
Decisions
Data & Semantics
Governance
Settings


Each menu maps cleanly to backend modules.

## 3. Ask — Conversational Analytics (Primary)

React Components
```jsx
<AskPage>
  <QuestionInput />
  <QueryHistory />
  <FollowUpSuggestions />
  <ResultPanel />
</AskPage>
```

Backend APIs

API | Method | Purpose
--- | --- | ---
/query | POST | NL → Answer
/query/explain | POST | Why/how explanation
/query/followups | POST | Suggested next questions

Backend modules

query_builder.resolver  
query_builder.planner  
sql_generator  
semantic_layer.catalog  
inference_engine (optional auto-trigger)

Customer interaction

Ask: “Why is production down in Plant A?”

Click follow-ups: “Break down by line”

Inspect explanation & drivers

## 4. Explore — Semantic Discovery (Trust Builder)

React Components
```jsx
<ExplorePage>
  <DatasetBrowser />
  <MetricCatalog />
  <EntityHierarchy />
</ExplorePage>
```

Backend APIs

API | Method | Purpose
--- | --- | ---
/datasets | GET | List datasets
/metrics | GET | List metrics
/entities | GET | Entity hierarchy

Backend modules

semantic_layer.loaders.*  
semantic_layer.catalog  
semantic_layer.lineage

Customer interaction

Browse available metrics

Understand grain & definitions

Build trust before asking questions

This is Tellius “Business View” equivalent.

## 5. Insights — Automated AI Insights (Tellius Core)

React Components
```jsx
<InsightsPage>
  <InsightFeed />
  <InsightCard />
  <InsightEvidence />
</InsightsPage>
```

Backend APIs

API | Method | Purpose
--- | --- | ---
/insights | GET | Ranked insights
/insights/{id} | GET | Insight details
/insights/{id}/explain | GET | Evidence and drivers

Backend modules

inference_engine/*  
insight_ranking  
insight_events

Customer interaction

Review proactive insights

Click “Why?”

Decide whether to act

This is where you beat BI tools.

## 6. Scenarios — Planning (Mini-Kinaxis)

React Components
```jsx
<ScenariosPage>
  <ScenarioList />
  <ScenarioEditor />
  <ScenarioComparison />
</ScenariosPage>
```

Backend APIs

API | Method | Purpose
--- | --- | ---
/scenarios | GET | List scenarios
/scenarios | POST | Create scenario
/scenarios/{id}/run | POST | Recompute
/scenarios/compare | POST | Compare

Backend modules

Scenario engine  
Query planner  
dbt-backed recomputation

Customer interaction

Adjust assumptions

Compare outcomes

Share scenarios

## 7. Decisions — Actions and Feedback (OMP Path)

React Components
```jsx
<DecisionsPage>
  <ActionQueue />
  <ActionDetail />
  <ActionFeedback />
</DecisionsPage>
```

Backend APIs

API | Method | Purpose
--- | --- | ---
/actions | GET | Recommended actions
/actions/{id}/assign | POST | Assign
/actions/{id}/feedback | POST | Worked / didn’t

Backend modules

insight_events  
Action policies  
Feedback loop

Customer interaction

Accept / reject recommendations

Assign owners

Track impact

## 8. Data and Semantics — Power User / Admin

React Components
```jsx
<DataAdminPage>
  <DataSources />
  <DatasetEditor />
  <MetricEditor />
  <EntityEditor />
</DataAdminPage>
```

Backend APIs

API | Method | Purpose
--- | --- | ---
/datasources | GET/POST | Manage sources
/datasets | POST | Create/edit
/metrics | POST | Define metrics
/entities | POST | Define hierarchies

Backend modules

data_source.factory  
contracts/*  
tools/generate.py

Customer interaction

Onboard new domain

Certify metrics

Adjust semantics

## 9. Governance — Trust and Compliance

React Components
```jsx
<GovernancePage>
  <MetricLineage />
  <QueryAudit />
  <PolicyViewer />
</GovernancePage>
```

Backend APIs

API | Method | Purpose
--- | --- | ---
/governance/lineage | GET | Metric lineage
/governance/audit | GET | Query logs
/policies | GET | Active policies

Backend modules

semantic_layer.lineage  
Policy loader  
Audit tables

Customer interaction

Validate numbers

Audit decisions

Regulatory confidence (critical for PSUs)

## 10. Settings — Personalization and Integrations

React Components
```jsx
<SettingsPage>
  <Thresholds />
  <Alerts />
  <Integrations />
</SettingsPage>
```

Backend APIs

API | Method | Purpose
--- | --- | ---
/settings/thresholds | GET/POST | Tune alerts
/integrations | GET/POST | Email/Jira/Teams

---

## 11. One-page summary (for your team)

UI is a reflection of architecture.

- Ask → resolver + planner
- Explore → semantic_layer
- Insights → inference_engine
- Scenarios → planner + dbt
- Decisions → insight_events
- Governance → lineage + audit
