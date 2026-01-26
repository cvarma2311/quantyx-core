# Enterprise Operations Intelligence - A Product Journey

This story explains how a generic, productized Quantyx platform supports any
industry while remaining explainable and configuration-driven.

---

## 1) The enterprise arrives

A new enterprise wants operational intelligence across sales, production,
logistics, or supply chain. They expect the system to understand their business
without custom code.

Quantyx responds with a clear prerequisite:
- Install an industry pack (ontology + templates + policies)
- Connect to data
- Build dbt models

The platform stays generic. The industry pack provides domain context.

---

## 2) Onboarding in days, not months

Once connected, Quantyx scans the schema and detects:
- measures
- time columns
- entity candidates

It bootstraps dbt staging and marts, then auto-generates baseline metrics.

Users see a "Suggested Metrics" list with confidence scores. They can:
- approve
- edit logic
- rename
- hide

Trust grows because the system is explainable and governed.

---

## 3) The Ask experience

Operators ask:
- "Why are sales down in Region X?"
- "Which plants are below target this month?"

The AI engine resolves the question against the metric catalog and produces:
- an answer
- drivers
- evidence
- recommended actions

Everything is traceable to the metrics and dbt marts.

---

## 4) Insights become proactive

The system starts generating insights without prompts:
- unusual dips
- missed targets
- peer anomalies

Insights are ranked by impact and confidence, then shown in the UI with
supporting evidence and a clear action path.

---

## 5) Planning and decisions

Once trust is established, operators move to planning:
- simulate scenarios
- compare outcomes
- optimize constraints

Quantyx never changes architecture to do this. It only adds operators and
scenario engines on top of the same governed data layer.

---

## 6) Why this works across industries

- The core platform is generic and stable
- Industry packs supply domain-specific ontology and templates
- Metrics are auto-detected but user-correctable
- dbt ensures clean, auditable truth
- AI decisions are explainable and reproducible

---

## 7) The product promise

Quantyx does not deliver dashboards. It delivers decisions.

Every industry sees the same product:
- Ask
- Explain
- Act
- Learn

The difference is only in the industry pack, not the core.
