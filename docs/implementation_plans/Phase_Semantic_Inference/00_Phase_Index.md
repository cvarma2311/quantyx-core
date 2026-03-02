# Phase Semantic Inference: Phase Index

This index shows where Phases 01–09 fit and how they stack.

## Phase Map

1. **Phase 01: Core Principle (Determinism First)**
   - Establish deterministic-first resolution and LLM fallback rules.

2. **Phase 02: Semantic Graph Model**
   - Define graph nodes/edges and confidence/provenance.

3. **Phase 03: Deterministic Resolution Pipeline**
   - Implement cache → rules → graph → SQL path.

4. **Phase 04: Learning Loop (LLM Promotion)**
   - Persist LLM resolutions into graph with validation.

5. **Phase 05: Diagnostic / “Why” Inference**
   - Root-cause pipeline: resolve → compute → explain.

6. **Phase 06: API + Storage Evolution**
   - API behaviors, persistence, metrics, migration path.

7. **Phase 07: SQL Templates + Data Models**
   - DDL and SQL templates for deterministic and diagnostic queries.

8. **Phase 08: LLM Context → Graph (Input/Output/Recompute)**
   - 08a: LLM input payload (context bundle)
   - 08b: LLM output schema + table mapping
   - 08c: Recompute + versioning when context changes

9. **Phase 09: Pre‑Aggregations + Cache Orchestration**
   - Cube‑style rollups and refresh orchestration for fast queries

## Recommended Order of Execution
1. Phase 01 → Phase 02 → Phase 03
2. Phase 04 (to reduce LLM over time)
3. Phase 07 (codify SQL templates + data models)
4. Phase 05 (diagnostic inference)
5. Phase 08 (LLM input/output + recompute hardening)
6. Phase 09 (rollups + cache orchestration)
7. Phase 06 (API + migration hardening)

## Notes
- Ontology, glossary, metric registry, and join hints can be **derived from context text** via LLM and validated against schema scan results.
- Phase 07 can be started early if you need SQL templates for engineering.
- Phase 05 depends on Phase 03 + Phase 07.
- Phase 06 spans all phases and should be updated as each is implemented.

