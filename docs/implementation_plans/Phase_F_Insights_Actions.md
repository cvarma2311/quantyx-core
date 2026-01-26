# Phase F: Insights and Actions

Goal: proactive intelligence and decision loop.

## Current state
- Insights endpoints and action loop endpoints implemented.
- Variance insight generator added.

## Deliverables
1) **Insight generation operators**
   - Variance, driver, anomaly, pace

2) **Insights feed**
   - `/insights` and `/insights/{id}`
   - Persist to `public.quantyx_insight_events`

3) **Action loop**
   - `/actions` endpoints
   - Persist to `public.quantyx_actions`
   - Feedback capture in `public.quantyx_action_feedback`

## Acceptance criteria
- At least one automated insight per domain
- Action feedback stored in DB

## Database prerequisites
- Run `artifacts/quantyx_tables.sql` to create:
  `public.quantyx_insight_events`, `public.quantyx_actions`,
  `public.quantyx_action_feedback`.
