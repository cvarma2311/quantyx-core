# Phase G: Scenarios (Planning)

Goal: scenario creation and comparison endpoints.

## Current state
- Scenario endpoints implemented.

## Deliverables
1) **Scenario tables**
   - `public.quantyx_scenario`
   - `public.quantyx_scenario_inputs`
   - `public.quantyx_scenario_outputs`

2) **Scenario endpoints**
   - `/scenarios`, `/scenarios/{id}/run`, `/scenarios/compare`

## Acceptance criteria
- Scenario runs produce stored outputs

## Database prerequisites
- Run `artifacts/quantyx_tables.sql` to create:
  `public.quantyx_scenario`, `public.quantyx_scenario_inputs`,
  `public.quantyx_scenario_outputs`.
