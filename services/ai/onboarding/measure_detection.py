from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_NUMERIC_TYPES = {"integer", "bigint", "smallint", "numeric", "double precision", "real"}
_DATE_TYPES = {"date", "timestamp", "timestamp without time zone", "timestamp with time zone"}

_MEASURE_RULES = [
    ("quantity", ["_qty", "_units"]),
    ("volume", ["_tmt", "_tons", "_kl", "_kg"]),
    ("time", ["_hours", "_minutes", "_mins"]),
    ("money", ["_amount", "_cost", "_price", "_value"]),
    ("count", ["_count", "_cnt"]),
]

_NON_ADDITIVE_HINTS = {"rate", "avg", "mean", "pct", "percent", "ratio", "share"}
_UNIT_HINTS = {
    "tmt": ["_tmt", "tmt"],
    "tons": ["_tons", "tons"],
    "kg": ["_kg", "kg"],
    "kl": ["_kl", "kl"],
    "hours": ["_hours", "hours", "_hrs", "hrs"],
    "minutes": ["_minutes", "minutes", "_mins", "mins"],
    "count": ["_count", "_cnt", "count"],
}


def detect_measures(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = []
    logger.debug("measure_detection: start | tables=%s", len(tables))
    for table in tables:
        for col in table["columns"]:
            name = col["name"]
            data_type = col["data_type"].lower()
            if data_type not in _NUMERIC_TYPES:
                continue

            measure_type = "number"
            confidence = 0.6
            unit = None
            for label, patterns in _MEASURE_RULES:
                if any(name.lower().endswith(p) for p in patterns):
                    measure_type = label
                    confidence = 0.9
                    break

            for unit_name, patterns in _UNIT_HINTS.items():
                if any(p in name.lower() for p in patterns):
                    unit = unit_name
                    break

            additive = True
            if any(hint in name.lower() for hint in _NON_ADDITIVE_HINTS):
                additive = False
                confidence = min(confidence, 0.7)

            suggestions.append(
                {
                    "table": table["table"],
                    "column": name,
                    "data_type": col["data_type"],
                    "measure_type": measure_type,
                    "additive": additive,
                    "confidence": confidence,
                    "unit": unit,
                }
            )

    logger.debug("measure_detection: complete | measures=%s", len(suggestions))
    return suggestions


def detect_time_columns(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = []
    logger.debug("measure_detection: time_columns start | tables=%s", len(tables))
    for table in tables:
        for col in table["columns"]:
            if col["data_type"].lower() in _DATE_TYPES:
                suggestions.append({"table": table["table"], "column": col["name"]})
    logger.debug("measure_detection: time_columns complete | cols=%s", len(suggestions))
    return suggestions
