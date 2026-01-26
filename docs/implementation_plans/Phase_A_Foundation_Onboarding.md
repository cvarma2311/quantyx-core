# Phase A: Foundation for Productized Onboarding

Goal: introduce industry pack structure and prerequisites for any domain.

## Current state
- Architecture and prerequisites docs updated to emphasize industry packs.
- No pack structure or loaders implemented in code.

## Deliverables
1) **Industry pack structure**
   - Create `packs/<industry>/` folders with:
     - `ontology.yml`
     - `datasets.yml`
     - `metric_templates.yml`
     - `policies.yml`
   - Example packs: `energy_distribution`, `manufacturing`, `logistics`

2) **Ontology loader**
   - `services/ai/semantic_layer/loaders/ontology_loader.py`
   - Loads entity types + hierarchies from pack

3) **Metric lifecycle registry**
   - Registry table or YAML store
   - Metric status: suggested/draft/certified/deprecated

4) **Doc updates**
   - Add industry pack checklist appendix

5) **Ontology mapping API**
   - `POST /onboard/map` for rule-based mapping
   - confidence scoring + low-confidence bucket

## Acceptance criteria
- New industry pack can be added without code change
- Ontology appears in `/entities`

## Status
- Pack scaffolding added under `packs/`
- Ontology loader added at `services/ai/semantic_layer/loaders/ontology_loader.py`
