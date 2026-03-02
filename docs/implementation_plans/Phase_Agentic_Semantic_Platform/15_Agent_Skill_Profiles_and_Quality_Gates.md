# Phase 15: Agent Skill Profiles + Quality Gates

## Objective
Make each agent highly specialized, outcome‑focused, and business‑aware. Ensure all outputs are validated and only high‑confidence outputs are promoted.

---

## 1) Skill Profiles (Per Agent)

### Schema Agent
- **Role:** Data modeling expert
- **Goal:** Identify fact/dimension tables with high precision
- **Success Criteria:**
  - Fact table must contain numeric measures + time column
  - Dimension table must contain keys + descriptive attributes

### Profiling Agent
- **Role:** Data profiling specialist
- **Goal:** Detect grain, cardinality, and measures vs dimensions
- **Success Criteria:**
  - Correct grain detection for ≥ 90% of facts
  - Accurate time column detection

### Context Agent
- **Role:** Domain analyst
- **Goal:** Extract business entities, hierarchies, and relationships
- **Success Criteria:**
  - All key business terms mapped to schema columns

### Glossary Agent
- **Role:** Terminology specialist
- **Goal:** Generate terms + synonyms + abbreviations
- **Success Criteria:**
  - Synonyms validated by schema or glossary references

### Join Agent
- **Role:** Data integration specialist
- **Goal:** Propose valid join paths
- **Success Criteria:**
  - Joins are validated by PK/FK or data overlap

### Metric Agent
- **Role:** KPI modeler
- **Goal:** Build accurate metric formulas
- **Success Criteria:**
  - Metrics must reference existing numeric columns

### Dashboard Story Agent
- **Role:** BI analyst + storyteller
- **Goal:** Produce dashboard story arcs
- **Success Criteria:**
  - At least 1 KPI, 1 trend, 1 breakdown per dashboard

### Governance Agent
- **Role:** QA/approval
- **Goal:** Track feedback + adjust confidence
- **Success Criteria:**
  - Low‑confidence outputs require review

---

## 2) Quality Gates

All agent outputs must pass:

1) **Schema Validation**
   - Columns exist
   - Types compatible

2) **Confidence Thresholds**
   - Only edges with confidence ≥ 0.7 auto‑promoted

3) **Consistency Check**
   - No conflicting metrics/dimensions for same concept

4) **Review Requirement**
   - Low confidence outputs require manual approval

---

## 3) Feedback Loop

- User confirms → confidence ↑
- User rejects → confidence ↓
- Conflicting edges → flagged for review

---

## 4) Outputs

- Validated semantic graph
- Confidence‑scored edges
- Audit trail of changes

