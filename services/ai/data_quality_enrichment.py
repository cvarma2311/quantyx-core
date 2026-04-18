from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from collections import Counter
import json
import logging
import os
import urllib.request
import uuid

from services.ai.config import Settings
from services.ai.db import ScopedConnection, run_query

logger = logging.getLogger(__name__)


LOCATION_ALIASES: dict[str, set[str]] = {
    "country": {"country"},
    "country_code": {"country_code", "countrycode", "iso_country", "iso_country_code"},
    "state": {"state", "province", "region"},
    "state_code": {"state_code", "province_code", "region_code"},
    "city": {"city", "town"},
    "postal_code": {"postal_code", "postcode", "pincode", "zip", "zip_code"},
}

GENERIC_LABEL_ALIASES: dict[str, set[str]] = {
    "status": {"status", "status_label", "status_name"},
    "gender": {"gender", "gender_label", "gender_name", "sex"},
    "category": {"category", "category_label", "category_name"},
    "type": {"type", "type_label", "type_name"},
}

CODE_SUFFIXES = ("_code", "code", "_id", "id")
LABEL_SUFFIXES = ("_label", "_name", "_text", "_desc", "_description", "label", "name", "text", "desc", "description")

TEMPORAL_TARGET_PATTERNS: dict[str, set[str]] = {
    "year": {"year"},
    "month": {"month"},
    "month_name": {"month_name"},
    "quarter": {"quarter", "qtr"},
    "day_of_week": {"day_of_week", "weekday"},
    "week_of_year": {"week_of_year", "week_num", "week_number"},
}

COLUMN_ALIAS_OVERRIDES = {
    "postcode": "postal_code",
    "pincode": "postal_code",
    "zip": "postal_code",
    "zip_code": "postal_code",
    "province": "state",
    "province_code": "state_code",
    "region": "state",
    "region_code": "state_code",
    "countrycode": "country_code",
    "iso_country": "country",
    "iso_country_code": "country_code",
    "status_label": "status",
    "status_name": "status",
    "gender_label": "gender",
    "gender_name": "gender",
    "sex": "gender",
}

COUNTRY_LABEL_MAP = {
    "us": "United States",
    "usa": "United States",
    "united states of america": "United States",
    "united states": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "india": "India",
}

STATE_LABEL_MAP = {
    "ca": "California",
    "ny": "New York",
    "tx": "Texas",
    "mh": "Maharashtra",
    "ka": "Karnataka",
}

STATUS_LABEL_MAP = {
    "a": "Active",
    "active": "Active",
    "i": "Inactive",
    "inactive": "Inactive",
    "p": "Pending",
    "pending": "Pending",
    "closed": "Closed",
}

GENDER_LABEL_MAP = {
    "m": "Male",
    "male": "Male",
    "f": "Female",
    "female": "Female",
    "o": "Other",
    "other": "Other",
}

SENSITIVE_TOKENS = {
    "email",
    "phone",
    "mobile",
    "name",
    "first_name",
    "last_name",
    "ssn",
    "tax",
    "account",
    "payment",
    "card",
    "iban",
}


def _normalize_column_name(name: str | None) -> str:
    return str(name or "").strip().lower()


def canonical_column_alias(name: str | None) -> str:
    normalized = _normalize_column_name(name)
    if not normalized:
        return ""
    if normalized in COLUMN_ALIAS_OVERRIDES:
        return COLUMN_ALIAS_OVERRIDES[normalized]
    role = _classify_location_role(normalized)
    if role:
        return role
    generic_role = _generic_label_role(normalized)
    if generic_role:
        return generic_role
    temporal_kind = _temporal_target_kind(normalized)
    if temporal_kind:
        return temporal_kind
    return normalized


def canonical_column_aliases(columns: list[str] | None) -> list[str]:
    aliases: list[str] = []
    for column in columns or []:
        alias = canonical_column_alias(column)
        aliases.append(alias or str(column or "").strip())
    return aliases


def _normalize_value(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _is_sensitive(name: str | None) -> bool:
    normalized = _normalize_column_name(name)
    return any(token in normalized for token in SENSITIVE_TOKENS)


def _classify_location_role(name: str | None) -> str | None:
    normalized = _normalize_column_name(name)
    if not normalized or _is_sensitive(normalized):
        return None
    for role, aliases in LOCATION_ALIASES.items():
        if normalized in aliases:
            return role
    return None


def _generic_label_role(name: str | None) -> str | None:
    normalized = _normalize_column_name(name)
    if not normalized or _is_sensitive(normalized):
        return None
    for role, aliases in GENERIC_LABEL_ALIASES.items():
        if normalized in aliases:
            return role
    return None


def _root_name(name: str | None) -> str:
    normalized = _normalize_column_name(name)
    for suffix in (*CODE_SUFFIXES, *LABEL_SUFFIXES):
        if normalized.endswith(suffix):
            trimmed = normalized[: -len(suffix)]
            if trimmed:
                return trimmed.rstrip("_")
    return normalized


def _find_sibling_columns(profiles: list[dict[str, Any]], target_column: str, *, suffixes: tuple[str, ...]) -> list[str]:
    normalized_target = _normalize_column_name(target_column)
    target_root = _root_name(target_column)
    matches: list[str] = []
    for profile in profiles:
        column_name = str(profile.get("name") or "").strip()
        if not column_name or column_name == target_column:
            continue
        normalized = _normalize_column_name(column_name)
        column_root = _root_name(column_name)
        if column_root != target_root and normalized_target not in normalized and target_root not in normalized:
            continue
        if any(normalized.endswith(suffix) for suffix in suffixes):
            matches.append(column_name)
    return matches


def _find_code_source_columns(profiles: list[dict[str, Any]], target_column: str) -> list[str]:
    return _find_sibling_columns(profiles, target_column, suffixes=CODE_SUFFIXES)


def _find_label_source_columns(profiles: list[dict[str, Any]], target_column: str) -> list[str]:
    return _find_sibling_columns(profiles, target_column, suffixes=LABEL_SUFFIXES)


def _derive_full_name_source_columns(profile_names: set[str], target_column: str) -> list[str]:
    target = _normalize_column_name(target_column)
    if target not in {"full_name", "customer_name", "person_name", "display_name"}:
        return []
    if {"first_name", "last_name"} <= profile_names:
        return ["first_name", "last_name"]
    return []


def _temporal_target_kind(name: str | None) -> str | None:
    normalized = _normalize_column_name(name)
    if not normalized:
        return None
    for kind, aliases in TEMPORAL_TARGET_PATTERNS.items():
        if normalized in aliases or normalized.endswith(f"_{kind}"):
            return kind
        for alias in aliases:
            if normalized.endswith(f"_{alias}"):
                return kind
    return None


def _find_temporal_source_columns(profiles: list[dict[str, Any]], target_column: str) -> list[str]:
    target = _normalize_column_name(target_column)
    target_root = _root_name(target_column)
    preferred: list[str] = []
    fallback: list[str] = []
    for profile in profiles:
        column_name = str(profile.get("name") or "").strip()
        if not column_name or column_name == target_column:
            continue
        normalized = _normalize_column_name(column_name)
        data_type = _normalize_column_name(profile.get("data_type"))
        looks_temporal = any(token in normalized for token in ("date", "time", "_at", "timestamp")) or any(
            token in data_type for token in ("date", "time")
        )
        if not looks_temporal:
            continue
        if target_root and target_root != target and target_root in normalized:
            preferred.append(column_name)
        else:
            fallback.append(column_name)
    return preferred[:1] or fallback[:1]


def _missing_count(profile: dict[str, Any]) -> int:
    null_count = int(profile.get("null_count") or 0)
    blank_count = int(profile.get("blank_count") or 0)
    return max(null_count, null_count + blank_count)


def _profiled_columns(profiling: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in profiling.get("tables") or []:
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        for profile in table.get("column_profiles") or []:
            if not isinstance(profile, dict):
                continue
            row = dict(profile)
            row["table_name"] = table_name
            rows.append(row)
    return rows


def _source_columns_for_target(target_role: str, roles: dict[str, list[str]]) -> tuple[list[str], str | None]:
    if target_role == "country":
        if roles.get("country_code"):
            return roles["country_code"][:1], "country_code_normalization"
        if roles.get("state") and roles.get("postal_code"):
            return [roles["state"][0], roles["postal_code"][0]], "postal_context_inference"
        if roles.get("state"):
            return roles["state"][:1], "location_hierarchy_inference"
        if roles.get("postal_code"):
            return roles["postal_code"][:1], "postal_context_inference"
    if target_role == "country_code":
        if roles.get("country"):
            return roles["country"][:1], "country_code_normalization"
    if target_role == "state":
        if roles.get("postal_code"):
            columns = [roles["postal_code"][0]]
            if roles.get("country"):
                columns.append(roles["country"][0])
            elif roles.get("country_code"):
                columns.append(roles["country_code"][0])
            return columns, "postal_context_inference"
        if roles.get("city") and (roles.get("country") or roles.get("country_code")):
            columns = [roles["city"][0]]
            if roles.get("country"):
                columns.append(roles["country"][0])
            else:
                columns.append(roles["country_code"][0])
            return columns, "location_hierarchy_inference"
    if target_role == "state_code":
        if roles.get("state"):
            return roles["state"][:1], "state_code_normalization"
    if target_role == "city":
        if roles.get("postal_code"):
            columns = [roles["postal_code"][0]]
            if roles.get("country"):
                columns.append(roles["country"][0])
            elif roles.get("country_code"):
                columns.append(roles["country_code"][0])
            return columns, "postal_context_inference"
        if roles.get("state") and (roles.get("country") or roles.get("country_code")):
            columns = [roles["state"][0]]
            if roles.get("country"):
                columns.append(roles["country"][0])
            else:
                columns.append(roles["country_code"][0])
            return columns, "location_hierarchy_inference"
    return [], None


def _question_for(target_column: str, method: str | None, source_columns: list[str]) -> str:
    joined_sources = ", ".join(source_columns)
    if method == "canonical_label_normalization":
        return f"Can we normalize canonical {target_column} labels from {joined_sources}?"
    if method == "code_to_label_derivation":
        return f"Can we derive {target_column} labels from existing code values in {joined_sources}?"
    if method == "cross_column_derivation":
        return f"Can we derive missing {target_column} values from existing row fields {joined_sources}?"
    if method == "temporal_derivation":
        return f"Can we derive missing {target_column} values from existing temporal fields {joined_sources}?"
    if method == "country_code_normalization":
        return f"Can we normalize {target_column} from the existing country values?"
    if method == "state_code_normalization":
        return f"Can we normalize {target_column} from the existing state values?"
    return f"Can we use existing row context to propose missing {target_column} values from {joined_sources}?"


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _llm_mode() -> str:
    return os.getenv("DATA_QUALITY_ENRICHMENT_LLM_MODE", "auto").strip().lower()


def _llm_enabled(settings: Settings | None) -> bool:
    mode = _llm_mode()
    if mode in {"off", "false", "0", "disabled"}:
        return False
    return bool(settings and getattr(settings, "openai_api_key", None))


def _source_signature(row: dict[str, Any], source_columns: list[str]) -> tuple[str, ...]:
    return tuple(str(row.get(column) or "").strip().lower() for column in source_columns)


def _canonical_label_map_for(target_column: str) -> dict[str, str]:
    normalized = _normalize_column_name(target_column)
    if "country" in normalized:
        return COUNTRY_LABEL_MAP
    if "state" in normalized or "province" in normalized or "region" in normalized:
        return STATE_LABEL_MAP
    if "status" in normalized:
        return STATUS_LABEL_MAP
    if "gender" in normalized or normalized == "sex":
        return GENDER_LABEL_MAP
    return {}


def _deterministic_canonical_label_proposals(
    *,
    opportunity: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_columns = [str(item) for item in (opportunity.get("source_columns_json") or []) if str(item).strip()]
    label_map = _canonical_label_map_for(str(opportunity.get("target_column") or ""))
    proposals: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in candidate_rows:
        proposed_value = ""
        source_values = {column: row.get(column) for column in source_columns}
        for column in source_columns:
            raw_value = row.get(column)
            mapped = label_map.get(_normalize_value(raw_value))
            if mapped:
                proposed_value = mapped
                break
        if proposed_value:
            proposals.append(
                {
                    "row_ref": row.get("__row_ref"),
                    "proposed_value": proposed_value,
                    "confidence": 0.97,
                    "rationale": "Canonical label normalization applied from existing source values.",
                    "method": "deterministic_canonical_normalization",
                    "source_values": source_values,
                }
            )
        else:
            unresolved.append(row)
    return proposals, unresolved


def _deterministic_cross_column_derivation(
    *,
    opportunity: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_column = _normalize_column_name(opportunity.get("target_column"))
    source_columns = [str(item) for item in (opportunity.get("source_columns_json") or []) if str(item).strip()]
    proposals: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in candidate_rows:
        source_values = {column: row.get(column) for column in source_columns}
        proposed_value = ""
        if target_column in {"full_name", "customer_name", "person_name", "display_name"}:
            parts = [str(row.get(column) or "").strip() for column in source_columns if str(row.get(column) or "").strip()]
            proposed_value = " ".join(parts).strip()
        if proposed_value:
            proposals.append(
                {
                    "row_ref": row.get("__row_ref"),
                    "proposed_value": proposed_value,
                    "confidence": 0.99,
                    "rationale": "Derived directly from existing row fields.",
                    "method": "deterministic_cross_column_derivation",
                    "source_values": source_values,
                }
            )
        else:
            unresolved.append(row)
    return proposals, unresolved


def _parse_datetime_value(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    if " " in raw and "T" not in raw:
        candidates.append(raw.replace(" ", "T", 1))
    for item in candidates:
        try:
            return datetime.fromisoformat(item)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _temporal_value(kind: str, value: Any) -> str | None:
    parsed = _parse_datetime_value(value)
    if parsed is None:
        return None
    if kind == "year":
        return str(parsed.year)
    if kind == "month":
        return str(parsed.month)
    if kind == "month_name":
        return parsed.strftime("%B")
    if kind == "quarter":
        return f"Q{((parsed.month - 1) // 3) + 1}"
    if kind == "day_of_week":
        return parsed.strftime("%A")
    if kind == "week_of_year":
        return str(int(parsed.strftime("%U")))
    return None


def _deterministic_temporal_derivation(
    *,
    opportunity: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kind = _temporal_target_kind(opportunity.get("target_column"))
    source_columns = [str(item) for item in (opportunity.get("source_columns_json") or []) if str(item).strip()]
    proposals: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in candidate_rows:
        source_values = {column: row.get(column) for column in source_columns}
        proposed_value = None
        for column in source_columns:
            proposed_value = _temporal_value(str(kind or ""), row.get(column))
            if proposed_value is not None:
                break
        if proposed_value:
            proposals.append(
                {
                    "row_ref": row.get("__row_ref"),
                    "proposed_value": proposed_value,
                    "confidence": 0.99,
                    "rationale": "Derived deterministically from a temporal source column.",
                    "method": "deterministic_temporal_derivation",
                    "source_values": source_values,
                }
            )
        else:
            unresolved.append(row)
    return proposals, unresolved


def _fetch_candidate_rows(
    settings: Settings,
    *,
    scoped_conn: ScopedConnection,
    schema_name: str,
    table_name: str,
    target_column: str,
    source_columns: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    select_columns = ['ctid::text AS "__row_ref"']
    for column in [target_column, *source_columns]:
        select_columns.append(f"{_qident(column)} AS {_qident(column)}")
    sql = f"""
        SELECT {", ".join(select_columns)}
          FROM {_qident(schema_name)}.{_qident(table_name)}
         WHERE {_qident(target_column)} IS NULL
            OR NULLIF(BTRIM({_qident(target_column)}::text), '') IS NULL
         LIMIT %s
    """
    return run_query(settings, sql, [max(1, limit)], scoped_conn=scoped_conn, statement_timeout_ms=30000)


def _fetch_example_rows(
    settings: Settings,
    *,
    scoped_conn: ScopedConnection,
    schema_name: str,
    table_name: str,
    target_column: str,
    source_columns: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    select_columns = [f"{_qident(target_column)} AS {_qident(target_column)}"]
    for column in source_columns:
        select_columns.append(f"{_qident(column)} AS {_qident(column)}")
    non_blank_sources = " AND ".join(
        [f"NULLIF(BTRIM({_qident(column)}::text), '') IS NOT NULL" for column in source_columns]
    ) or "TRUE"
    sql = f"""
        SELECT {", ".join(select_columns)}
          FROM {_qident(schema_name)}.{_qident(table_name)}
         WHERE NULLIF(BTRIM({_qident(target_column)}::text), '') IS NOT NULL
           AND {non_blank_sources}
         LIMIT %s
    """
    return run_query(settings, sql, [max(1, limit)], scoped_conn=scoped_conn, statement_timeout_ms=30000)


def _deterministic_proposals(
    *,
    opportunity: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    example_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    method = str(opportunity.get("candidate_method") or "").strip().lower()
    if method == "canonical_label_normalization":
        return _deterministic_canonical_label_proposals(opportunity=opportunity, candidate_rows=candidate_rows)
    if method == "cross_column_derivation":
        return _deterministic_cross_column_derivation(opportunity=opportunity, candidate_rows=candidate_rows)
    if method == "temporal_derivation":
        return _deterministic_temporal_derivation(opportunity=opportunity, candidate_rows=candidate_rows)
    source_columns = [str(item) for item in (opportunity.get("source_columns_json") or []) if str(item).strip()]
    target_column = str(opportunity.get("target_column") or "")
    mapping: dict[tuple[str, ...], set[str]] = {}
    for row in example_rows:
        signature = _source_signature(row, source_columns)
        if not any(signature):
            continue
        target_value = str(row.get(target_column) or "").strip()
        if not target_value:
            continue
        mapping.setdefault(signature, set()).add(target_value)
    deterministic: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in candidate_rows:
        signature = _source_signature(row, source_columns)
        values = mapping.get(signature) or set()
        if len(values) == 1:
            proposed_value = next(iter(values))
            deterministic.append(
                {
                    "row_ref": row.get("__row_ref"),
                    "proposed_value": proposed_value,
                    "confidence": 0.98,
                    "rationale": "Exact match found from existing non-missing rows in the same table.",
                    "method": "deterministic_exact_match",
                    "source_values": {column: row.get(column) for column in source_columns},
                }
            )
        else:
            unresolved.append(row)
    return deterministic, unresolved


def _llm_enrichment_proposals(
    settings: Settings | None,
    *,
    opportunity: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    example_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not candidate_rows or not _llm_enabled(settings):
        return []
    model = os.getenv("DATA_QUALITY_ENRICHMENT_LLM_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("DATA_QUALITY_ENRICHMENT_LLM_TIMEOUT_SEC", "45"))
    target_column = str(opportunity.get("target_column") or "")
    source_columns = [str(item) for item in (opportunity.get("source_columns_json") or []) if str(item).strip()]
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate missing data enrichment proposals using only the provided row context and examples from the same table. "
                    "Return JSON only. Do not use outside knowledge beyond the provided values. "
                    "If a row cannot be inferred with reasonable confidence, omit it. "
                    "Return proposals as objects with row_ref, proposed_value, confidence, and rationale."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "opportunity": {
                            "table_name": opportunity.get("table_name"),
                            "target_column": target_column,
                            "candidate_method": opportunity.get("candidate_method"),
                            "enrichment_type": opportunity.get("candidate_method"),
                            "question": opportunity.get("question"),
                            "source_columns": source_columns,
                        },
                        "examples": [
                            {column: row.get(column) for column in [*source_columns, target_column]}
                            for row in example_rows[:40]
                        ],
                        "missing_rows": [
                            {
                                "row_ref": row.get("__row_ref"),
                                "source_values": {column: row.get(column) for column in source_columns},
                            }
                            for row in candidate_rows[:40]
                        ],
                        "required_response_shape": {
                            "proposals": [
                                {
                                    "row_ref": "(1,1)",
                                    "proposed_value": "CA",
                                    "confidence": 0.84,
                                    "rationale": "Pattern inferred from rows with the same pincode and country context.",
                                }
                            ]
                        },
                    },
                    default=str,
                ),
            },
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        content = ((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
        raw = json.loads(content).get("proposals") or []
        allowed_refs = {str(row.get("__row_ref")) for row in candidate_rows}
        proposals: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            row_ref = str(item.get("row_ref") or "").strip()
            proposed_value = str(item.get("proposed_value") or "").strip()
            if not row_ref or row_ref not in allowed_refs or not proposed_value:
                continue
            try:
                confidence = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            proposals.append(
                {
                    "row_ref": row_ref,
                    "proposed_value": proposed_value,
                    "confidence": max(0.0, min(confidence, 1.0)),
                    "rationale": str(item.get("rationale") or "").strip()[:1000],
                    "method": "llm_context_inference",
                }
            )
        return proposals
    except Exception:
        logger.warning("data_quality.enrichment.llm_generation_failed", exc_info=True)
        if _llm_mode() in {"required", "require", "on"}:
            raise
        return []


def discover_enrichment_opportunities(
    profiling: dict[str, Any],
    *,
    quality_run_id: str,
    run_id: str,
    tenant_id: str,
    domain_id: str,
) -> list[dict[str, Any]]:
    columns = _profiled_columns(profiling)
    by_table: dict[str, list[dict[str, Any]]] = {}
    for row in columns:
        by_table.setdefault(str(row.get("table_name")), []).append(row)

    opportunities: list[dict[str, Any]] = []
    for table_name, profiles in by_table.items():
        profile_names = {_normalize_column_name(profile.get("name")) for profile in profiles if str(profile.get("name") or "").strip()}
        roles: dict[str, list[str]] = {}
        profile_by_column: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            column_name = str(profile.get("name") or "").strip()
            if not column_name or _is_sensitive(column_name):
                continue
            role = _classify_location_role(column_name)
            if role:
                roles.setdefault(role, []).append(column_name)
                profile_by_column[column_name] = profile
        generic_roles: dict[str, list[str]] = {}
        for profile in profiles:
            column_name = str(profile.get("name") or "").strip()
            if not column_name or _is_sensitive(column_name):
                continue
            role = _generic_label_role(column_name)
            if role:
                generic_roles.setdefault(role, []).append(column_name)
                profile_by_column[column_name] = profile
        for target_role, target_columns in roles.items():
            for target_column in target_columns:
                profile = profile_by_column.get(target_column) or {}
                missing_count = _missing_count(profile)
                if missing_count <= 0:
                    continue
                source_columns, method = _source_columns_for_target(target_role, roles)
                source_columns = [column for column in source_columns if column != target_column]
                if not source_columns or not method:
                    continue
                confidence = 0.9 if method.endswith("normalization") else 0.84
                opportunities.append(
                    {
                        "opportunity_id": f"dqeo_{uuid.uuid4().hex[:12]}",
                        "quality_run_id": quality_run_id,
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "table_name": table_name,
                        "target_column": target_column,
                        "target_column_alias": canonical_column_alias(target_column),
                        "source_columns_json": source_columns,
                        "source_column_aliases_json": canonical_column_aliases(source_columns),
                        "missing_count": missing_count,
                        "candidate_method": method,
                        "requires_external_lookup": False,
                        "requires_user_approval": True,
                        "confidence": confidence,
                        "question": _question_for(target_column, method, source_columns),
                        "status": "needs_user_approval",
                    }
                )
        for _, target_columns in generic_roles.items():
            for target_column in target_columns:
                profile = profile_by_column.get(target_column) or {}
                missing_count = _missing_count(profile)
                if missing_count <= 0:
                    continue
                source_columns = _find_code_source_columns(profiles, target_column)[:1]
                method = "code_to_label_derivation" if source_columns else None
                if not source_columns:
                    source_columns = _find_label_source_columns(profiles, target_column)[:1]
                    method = "canonical_label_normalization" if source_columns else None
                if not source_columns or not method:
                    continue
                confidence = 0.92 if method == "code_to_label_derivation" else 0.88
                opportunities.append(
                    {
                        "opportunity_id": f"dqeo_{uuid.uuid4().hex[:12]}",
                        "quality_run_id": quality_run_id,
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "table_name": table_name,
                        "target_column": target_column,
                        "target_column_alias": canonical_column_alias(target_column),
                        "source_columns_json": source_columns,
                        "source_column_aliases_json": canonical_column_aliases(source_columns),
                        "missing_count": missing_count,
                        "candidate_method": method,
                        "requires_external_lookup": False,
                        "requires_user_approval": True,
                        "confidence": confidence,
                        "question": _question_for(target_column, method, source_columns),
                        "status": "needs_user_approval",
                    }
                )
        for profile in profiles:
            target_column = str(profile.get("name") or "").strip()
            if not target_column:
                continue
            missing_count = _missing_count(profile)
            if missing_count <= 0:
                continue
            source_columns = _derive_full_name_source_columns(profile_names, target_column)
            if source_columns:
                opportunities.append(
                    {
                        "opportunity_id": f"dqeo_{uuid.uuid4().hex[:12]}",
                        "quality_run_id": quality_run_id,
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "table_name": table_name,
                        "target_column": target_column,
                        "target_column_alias": canonical_column_alias(target_column),
                        "source_columns_json": source_columns,
                        "source_column_aliases_json": canonical_column_aliases(source_columns),
                        "missing_count": missing_count,
                        "candidate_method": "cross_column_derivation",
                        "requires_external_lookup": False,
                        "requires_user_approval": True,
                        "confidence": 0.98,
                        "question": _question_for(target_column, "cross_column_derivation", source_columns),
                        "status": "needs_user_approval",
                    }
                )
                continue
            if _is_sensitive(target_column):
                continue
            temporal_kind = _temporal_target_kind(target_column)
            if temporal_kind:
                source_columns = _find_temporal_source_columns(profiles, target_column)
                if not source_columns:
                    continue
                opportunities.append(
                    {
                        "opportunity_id": f"dqeo_{uuid.uuid4().hex[:12]}",
                        "quality_run_id": quality_run_id,
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "table_name": table_name,
                        "target_column": target_column,
                        "target_column_alias": canonical_column_alias(target_column),
                        "source_columns_json": source_columns,
                        "source_column_aliases_json": canonical_column_aliases(source_columns),
                        "missing_count": missing_count,
                        "candidate_method": "temporal_derivation",
                        "requires_external_lookup": False,
                        "requires_user_approval": True,
                        "confidence": 0.99,
                        "question": _question_for(target_column, "temporal_derivation", source_columns),
                        "status": "needs_user_approval",
                    }
                )
    opportunities.sort(
        key=lambda row: (
            -int(row.get("missing_count") or 0),
            -float(row.get("confidence") or 0.0),
            str(row.get("table_name") or ""),
            str(row.get("target_column") or ""),
        )
    )
    return opportunities


def build_enrichment_proposal(
    settings: Settings | None,
    opportunity: dict[str, Any],
    *,
    scoped_conn: ScopedConnection | None,
    schema_name: str,
    max_records: int | None = None,
) -> dict[str, Any]:
    missing_count = int(opportunity.get("missing_count") or 0)
    row_limit = max(1, min(int(max_records or 100), 200))
    source_columns = [str(item) for item in (opportunity.get("source_columns_json") or []) if str(item).strip()]
    target_column = str(opportunity.get("target_column") or "")
    target_column_alias = str(opportunity.get("target_column_alias") or canonical_column_alias(target_column))
    source_column_aliases = opportunity.get("source_column_aliases_json") or canonical_column_aliases(source_columns)
    candidate_rows: list[dict[str, Any]] = []
    example_rows: list[dict[str, Any]] = []
    if scoped_conn:
        candidate_rows = _fetch_candidate_rows(
            settings,
            scoped_conn=scoped_conn,
            schema_name=schema_name,
            table_name=str(opportunity.get("table_name") or ""),
            target_column=target_column,
            source_columns=source_columns,
            limit=row_limit,
        )
        example_rows = _fetch_example_rows(
            settings,
            scoped_conn=scoped_conn,
            schema_name=schema_name,
            table_name=str(opportunity.get("table_name") or ""),
            target_column=target_column,
            source_columns=source_columns,
            limit=200,
        )
    deterministic, unresolved = _deterministic_proposals(
        opportunity=opportunity,
        candidate_rows=candidate_rows,
        example_rows=example_rows,
    )
    llm = _llm_enrichment_proposals(
        settings,
        opportunity=opportunity,
        candidate_rows=unresolved,
        example_rows=example_rows,
    )
    llm_by_ref = {str(item.get("row_ref")): item for item in llm if str(item.get("row_ref") or "").strip()}
    for row in unresolved:
        entry = llm_by_ref.get(str(row.get("__row_ref")))
        if not entry:
            continue
        entry["source_values"] = {column: row.get(column) for column in source_columns}
    for entry in deterministic:
        entry["target_column"] = target_column
        entry["target_column_alias"] = target_column_alias
        entry["source_column_aliases"] = source_column_aliases
    proposed_values_json = deterministic + [item for item in llm if item.get("source_values")]
    for entry in proposed_values_json:
        entry.setdefault("target_column", target_column)
        entry.setdefault("target_column_alias", target_column_alias)
        entry.setdefault("source_column_aliases", source_column_aliases)
    matched_count = len(proposed_values_json)
    unmatched_count = max(len(candidate_rows) - matched_count, 0)

    source_references = [
        {
            "provider": "table_exact_match",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "mode": "deterministic",
            "candidate_method": opportunity.get("candidate_method"),
            "target_column_alias": target_column_alias,
            "source_column_aliases": source_column_aliases,
            "matched_count": len(deterministic),
        },
        {
            "provider": "llm_context_inference",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "mode": "llm",
            "candidate_method": opportunity.get("candidate_method"),
            "target_column_alias": target_column_alias,
            "source_column_aliases": source_column_aliases,
            "model": os.getenv("DATA_QUALITY_ENRICHMENT_LLM_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
            if settings and _llm_enabled(settings)
            else None,
            "matched_count": len(proposed_values_json) - len(deterministic),
        },
    ]

    return {
        "proposal_id": f"dqep_{uuid.uuid4().hex[:12]}",
        "opportunity_id": opportunity.get("opportunity_id"),
        "quality_run_id": opportunity.get("quality_run_id"),
        "run_id": opportunity.get("run_id"),
        "tenant_id": opportunity.get("tenant_id"),
        "domain_id": opportunity.get("domain_id"),
        "status": "proposed",
        "table_name": opportunity.get("table_name"),
        "target_column": target_column,
        "target_column_alias": target_column_alias,
        "source_columns_json": source_columns,
        "source_column_aliases_json": source_column_aliases,
        "candidate_method": opportunity.get("candidate_method"),
        "matched_count": matched_count,
        "unmatched_count": unmatched_count if candidate_rows else max(missing_count - matched_count, 0),
        "source_references_json": source_references,
        "proposed_values_json": proposed_values_json,
    }


def summarize_enrichment_proposal(
    proposal: dict[str, Any],
    *,
    sample_limit: int = 20,
    group_limit: int = 20,
) -> dict[str, Any]:
    proposed = [item for item in (proposal.get("proposed_values_json") or []) if isinstance(item, dict)]
    matched_count = int(proposal.get("matched_count") or len(proposed))
    unmatched_count = int(proposal.get("unmatched_count") or 0)
    total_rows = matched_count + unmatched_count
    confidence_buckets = {
        "auto_approve": 0,
        "high_confidence": 0,
        "needs_review": 0,
    }
    method_counts: Counter[str] = Counter()
    groups: dict[str, dict[str, Any]] = {}
    for item in proposed:
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence >= 0.98:
            confidence_buckets["auto_approve"] += 1
        elif confidence >= 0.85:
            confidence_buckets["high_confidence"] += 1
        else:
            confidence_buckets["needs_review"] += 1
        method = str(item.get("method") or "unknown")
        method_counts[method] += 1
        group_key = str(item.get("proposed_value") or "")
        if not group_key:
            continue
        entry = groups.setdefault(
            group_key,
            {"proposed_value": group_key, "row_count": 0, "avg_confidence": 0.0, "methods": Counter(), "sample_source_values": []},
        )
        entry["row_count"] += 1
        entry["avg_confidence"] += confidence
        entry["methods"][method] += 1
        if len(entry["sample_source_values"]) < 3:
            entry["sample_source_values"].append(item.get("source_values") or {})
    grouped_values = []
    for value, entry in groups.items():
        row_count = int(entry["row_count"] or 0)
        grouped_values.append(
            {
                "proposed_value": value,
                "row_count": row_count,
                "avg_confidence": round((entry["avg_confidence"] / row_count), 4) if row_count else 0.0,
                "methods": dict(entry["methods"]),
                "sample_source_values": entry["sample_source_values"],
            }
        )
    grouped_values.sort(key=lambda item: (-int(item.get("row_count") or 0), -float(item.get("avg_confidence") or 0.0), str(item.get("proposed_value") or "")))
    return {
        "total_candidate_rows": total_rows,
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "confidence_buckets": confidence_buckets,
        "method_counts": dict(method_counts),
        "grouped_values": grouped_values[:group_limit],
        "sample_proposed_values": proposed[:sample_limit],
    }


def select_enrichment_rows_for_application(
    proposal: dict[str, Any],
    *,
    approval_scope: str = "high_confidence",
    min_confidence: float | None = None,
) -> dict[str, Any]:
    proposed = [item for item in (proposal.get("proposed_values_json") or []) if isinstance(item, dict)]
    scope = str(approval_scope or "high_confidence").strip().lower()
    threshold = 0.85 if min_confidence is None else float(min_confidence)
    approved: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for item in proposed:
        method = str(item.get("method") or "").strip().lower()
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        allow = False
        if scope == "deterministic_only":
            allow = method == "deterministic_exact_match"
        elif scope == "all":
            allow = True
        else:
            allow = confidence >= threshold
        if allow:
            approved.append(item)
        else:
            deferred.append(item)
    return {
        "approval_scope": scope,
        "confidence_threshold": threshold if scope != "deterministic_only" else None,
        "approved_rows": approved,
        "deferred_rows": deferred,
    }


def build_staged_enrichment_overlay_artifact(
    proposal: dict[str, Any],
    *,
    selection: dict[str, Any],
    approved_by: str,
    application_mode: str,
    reason: str | None = None,
) -> dict[str, Any]:
    approved_rows = [item for item in (selection.get("approved_rows") or []) if isinstance(item, dict)]
    deferred_rows = [item for item in (selection.get("deferred_rows") or []) if isinstance(item, dict)]
    sample_approved = approved_rows[:20]
    sample_deferred = deferred_rows[:20]
    return {
        "artifact_type": "data_quality_staged_overlay",
        "proposal_id": proposal.get("proposal_id"),
        "opportunity_id": proposal.get("opportunity_id"),
        "quality_run_id": proposal.get("quality_run_id"),
        "run_id": proposal.get("run_id"),
        "tenant_id": proposal.get("tenant_id"),
        "domain_id": proposal.get("domain_id"),
        "table_name": ((sample_approved or sample_deferred or [{}])[0].get("table_name") or proposal.get("table_name")),
        "target_column": ((sample_approved or sample_deferred or [{}])[0].get("target_column") or proposal.get("target_column")),
        "target_column_alias": ((sample_approved or sample_deferred or [{}])[0].get("target_column_alias") or proposal.get("target_column_alias")),
        "source_column_aliases": ((sample_approved or sample_deferred or [{}])[0].get("source_column_aliases") or proposal.get("source_column_aliases_json") or []),
        "application_mode": application_mode,
        "approval_scope": selection.get("approval_scope"),
        "confidence_threshold": selection.get("confidence_threshold"),
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "approved_row_count": len(approved_rows),
        "deferred_row_count": len(deferred_rows),
        "approved_rows": approved_rows,
        "deferred_rows": deferred_rows,
        "summary": {
            "sample_approved_values": sample_approved,
            "sample_deferred_values": sample_deferred,
            "source_references": proposal.get("source_references_json") or [],
        },
    }
