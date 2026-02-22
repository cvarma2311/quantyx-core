from __future__ import annotations

from typing import Any


def _norm_term(value: str) -> str:
    return value.strip().lower()


def merge_extractions(agent_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "abbreviations": [],
        "synonyms": [],
        "hierarchies": [],
        "metric_candidates": [],
        "question_intents": [],
        "_sources": {},
    }

    abbrev_seen: set[str] = set()
    synonym_seen: set[str] = set()
    hierarchy_seen: set[str] = set()
    metric_seen: set[str] = set()
    question_seen: set[str] = set()

    for agent in agent_payloads:
        agent_name = agent.get("agent_name") or "unknown"
        payload = agent.get("payload") or {}

        for entry in payload.get("abbreviations", []):
            if isinstance(entry, str):
                abbr = entry
                entry = {"abbr": abbr}
            else:
                abbr = entry.get("abbr")
            if not abbr:
                continue
            key = _norm_term(abbr)
            if key in abbrev_seen:
                continue
            abbrev_seen.add(key)
            merged["abbreviations"].append(entry)
            merged["_sources"].setdefault("abbreviations", {}).setdefault(abbr, []).append(agent_name)

        for entry in payload.get("synonyms", []):
            if isinstance(entry, str):
                term = entry
                entry = {"term": term}
            else:
                term = entry.get("term")
            if not term:
                continue
            key = _norm_term(term)
            if key in synonym_seen:
                continue
            synonym_seen.add(key)
            merged["synonyms"].append(entry)
            merged["_sources"].setdefault("synonyms", {}).setdefault(term, []).append(agent_name)

        for entry in payload.get("hierarchies", []):
            if isinstance(entry, str):
                name = entry
                entry = {"name": name, "levels": []}
            else:
                name = entry.get("name")
            if not name:
                continue
            key = _norm_term(name)
            if key in hierarchy_seen:
                continue
            hierarchy_seen.add(key)
            merged["hierarchies"].append(entry)
            merged["_sources"].setdefault("hierarchies", {}).setdefault(name, []).append(agent_name)

        for entry in payload.get("metric_candidates", []):
            if isinstance(entry, str):
                metric_name = entry
                table = None
            else:
                metric_name = entry.get("metric_name")
                table = entry.get("table")
            if not metric_name:
                continue
            key = f"{_norm_term(metric_name)}::{_norm_term(table or '')}"
            if key in metric_seen:
                continue
            metric_seen.add(key)
            merged["metric_candidates"].append(entry)
            merged["_sources"].setdefault("metric_candidates", {}).setdefault(metric_name, []).append(agent_name)

        for entry in payload.get("question_intents", []):
            if isinstance(entry, str):
                question = entry
                entry = {"question": question}
            else:
                question = entry.get("question")
            if not question:
                continue
            key = _norm_term(question)
            if key in question_seen:
                continue
            question_seen.add(key)
            merged["question_intents"].append(entry)
            merged["_sources"].setdefault("question_intents", {}).setdefault(question, []).append(agent_name)

    return merged
