# Domain Ontology Creation Guide (Hybrid)

This guide explains how to build a domain ontology using a hybrid approach:
base industry packs + automated mapping + human confirmation.

## Why hybrid?
- Packs provide a strong default starting point.
- Schema scan + rules/LLM can propose mappings quickly.
- Human review prevents costly misalignment.

---

## 1) Start from a base industry pack

Each domain has a base pack:
- `packs/manufacturing/ontology.yml`
- `packs/energy_distribution/ontology.yml`
- `packs/logistics/ontology.yml`

Each pack defines:
- entity types (facility, product, customer, etc.)
- example column hints
- hierarchies (e.g., division → plant → line)

---

## 2) Run schema scan

API:
```
POST /onboard/scan
```

Purpose:
- Discover tables + columns + types.
- Feed into mapping and metric suggestions.

---

## 3) Auto-map schema to ontology

API:
```
POST /onboard/map?domain_id=manufacturing&use_llm=true
```

Purpose:
- Match customer columns to ontology entity types.
- Return confidence scores.
- Flag low-confidence candidates for review.
- Use LLM suggestions when enabled.

---

## 4) Human review + overrides

APIs:
- `PATCH /entities/{entity_id}?domain_id=...&tenant_id=...`
- `PATCH /hierarchies/{hierarchy_name}?domain_id=...&tenant_id=...`

Purpose:
- Correct join keys, rename entities, or adjust hierarchies.
- Store overrides in `quantyx_entity_overrides` and `quantyx_hierarchy_overrides`.

---

## 5) Optional: LLM-assisted refinement

If enabled, the LLM can:
- Suggest entity mappings from column names and sample values.
- Propose hierarchy levels and synonyms.

The LLM does not replace human approval. It provides suggestions only.

---

## 6) What “good” looks like

Checklist:
- All key entities have a join key.
- All hierarchies match customer’s operating model.
- Low-confidence mappings are reviewed and corrected.
- Metrics reference these entities consistently.

---

## Ontology template (minimal)

```yaml
entity_types:
  facility:
    description: Physical manufacturing facility
    join_key: plant_name
    examples: [plant, facility, site]

hierarchies:
  operations:
    description: Operations rollup
    levels: [division, plant, line]
```

---

## Operational flow summary

1) Base pack → 2) Schema scan → 3) Auto-map → 4) Human overrides → 5) Apply

This ensures fast onboarding with low risk.
