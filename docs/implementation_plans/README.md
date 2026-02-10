# V2 Productized Implementation Plans

This folder breaks the V2 productized roadmap into phase-by-phase plans. Each
phase is designed to be implementable independently, while keeping a clear
dependency order.

## Recommended order

1) Phase A - Foundation for Productized Onboarding
   - `Phase_A_Foundation_Onboarding.md`

2) Phase B - Schema Scan and Auto-Detection
   - `Phase_B_Schema_Scan_Auto_Detect.md`

3) Phase C - Metric Editing and Contract Apply
   - `Phase_C_Metric_Edit_Contracts.md`

4) Phase D - Explore and Semantic APIs
   - `Phase_D_Explore_Semantic_APIs.md`

5) Phase E - Governance and Audit
   - `Phase_E_Governance_Audit.md`

6) Phase F - Insights and Actions
   - `Phase_F_Insights_Actions.md`

7) Phase G - Scenarios (Planning)
   - `Phase_G_Scenarios.md`

8) Phase H - Multi-Table Expansion
   - `Phase_H_Multi_Table_Expansion.md`

9) Phase J - Anomaly Detection
   - `Phase_J_Anomaly_Detection.md`

10) Phase I - Hardening and Productization
11) Phase N - Connection-Scoped Onboarding + Multi-Context Apply
   - `Phase_I_Hardening_Productization.md`
12) Phase O - Automated dbt Manifest (Backend-Only)
   - `Phase_O_Automated_Dbt_Manifest.md`
13) Phase P - Automated dbt Scaffolding (LLM-Assisted, Human Review)
   - `Phase_P_Automated_Dbt_Scaffolding.md`
14) Phase S - Async Onboarding Jobs (Scan, Map, Infer, Metrics)
   - `Phase_S_Async_Onboarding_Jobs.md`
15) Phase T - Semantic Layer Enhancement (Logical Data Management)
   - `Phase_T_Semantic_Layer_Enhancement.md`

## Dependencies (summary)

- Phase A is required before Phase B–D (industry packs + ontology loader).
- Phase B is required before Phase C (auto-metric suggestions).
- Phase C is required before Phase D (metrics/datasets must exist to explore).
- Phase E can run in parallel with Phase F, but both benefit from Phase D.
- Phases E/F/G rely on `artifacts/quantyx_tables.sql` (public.quantyx_* tables).
- Phase G depends on stable metrics and datasets (Phase C/D).
- Phase H depends on query planner foundations (Phase D/E).
- Phase J depends on Phase F (insights storage) and Phase D (time-series access).
- Phase I can begin after Phases D/E are stable.
