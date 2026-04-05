from __future__ import annotations

import json
import logging
import os
import traceback
import urllib.request
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from services.ai.config import Settings
from services.ai.semantic_layer.overrides_loader import load_hierarchy_overrides_all

_hs_logger = logging.getLogger("quantyx.hierarchy_store")


def _conn(settings: Settings):
    return psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )



def _candidate_level_order() -> list[str]:
    return [
        "country",
        "state",
        "zone",
        "region",
        "sales_area",
        "area",
        "territory",
        "location",
        "location_name",
        "city",
        "sap_id",
        "site_id",
        "site",
        "outlet_id",
        "outlet_name",
    ]


def _geo_level_order() -> list[str]:
    return ["country", "state", "zone", "region", "sales_area", "area", "territory", "city", "location", "location_name", "sap_id", "site_id", "site"]


def _location_ops_order() -> list[str]:
    return ["zone", "region", "sales_area", "location", "location_name", "sap_id", "site_id", "site", "outlet_id", "outlet_name"]


def _product_level_order() -> list[str]:
    return ["product_family", "product_category", "product_grp", "product_group", "product_type", "product_name", "sku", "sku_name"]


def _channel_level_order() -> list[str]:
    return ["channel_group", "channel", "sub_channel", "trade_channel", "trade_type", "customer_segment", "customer_name"]


def _customer_level_order() -> list[str]:
    return ["customer_group", "customer_segment", "customer_type", "customer_name", "customer_id"]


def _organization_level_order() -> list[str]:
    return ["business_unit", "division", "department", "team", "manager", "owner", "operator", "location_name", "site_id"]


def _context_tokens(lower_context: str) -> set[str]:
    return {part for part in lower_context.replace("/", " ").replace("-", " ").replace(",", " ").split() if part}


def _family_score(lower_context: str, labels: list[str]) -> float:
    tokens = _context_tokens(lower_context)
    if not tokens:
        return 0.0
    label_tokens = {token for label in labels for token in label.lower().replace("_", " ").split() if token}
    overlap = tokens & label_tokens
    return float(len(overlap))


def _candidate_orders(lower_context: str) -> list[tuple[str, list[str], str, float]]:
    candidates = [
        ("primary", _candidate_level_order(), "Primary", 0.72),
        ("geo", _geo_level_order(), "Geography", 0.70),
        ("ops", _location_ops_order(), "Operational", 0.68),
        ("product", _product_level_order(), "Product", 0.69 + min(_family_score(lower_context, ["product", "sku", "fuel", "grade"]), 2.0) * 0.04),
        ("channel", _channel_level_order(), "Channel", 0.67 + min(_family_score(lower_context, ["channel", "trade", "retail", "distribution"]), 2.0) * 0.04),
        ("customer", _customer_level_order(), "Customer", 0.67 + min(_family_score(lower_context, ["customer", "account", "buyer", "segment"]), 2.0) * 0.04),
        ("org", _organization_level_order(), "Organization", 0.66 + min(_family_score(lower_context, ["organization", "business", "team", "manager", "owner"]), 2.0) * 0.04),
    ]
    return candidates


def _collect_dimension_columns(table: dict[str, Any]) -> list[str]:
    all_cols: list[str] = []
    for key in ("dimensions", "dimension_columns", "string_columns", "categorical_columns", "columns"):
        vals = table.get(key) or []
        if isinstance(vals, list):
            all_cols.extend([str(v.get("name") if isinstance(v, dict) else v or "").strip() for v in vals])
    dedup_cols = []
    seen = set()
    for col in all_cols:
        lc = col.lower()
        if col and lc not in seen:
            seen.add(lc)
            dedup_cols.append(col)
    return dedup_cols


def _normalized_level_token(value: str) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("/", " ")
        .replace("-", " ")
        .replace(",", " ")
        .replace("__", "_")
        .replace(" ", "_")
    )


def _level_aliases() -> dict[str, list[str]]:
    return {
        "zone": ["zone"],
        "region": ["region"],
        "sales_area": ["sales_area", "salesarea", "sales_area_name", "sales_area_code"],
        "location_name": ["location_name", "location", "outlet", "outlet_name", "site_name"],
        "sap_id": ["sap_id", "sap", "outlet_id", "outlet_code"],
        "site_id": ["site_id", "site"],
        "product_grp": ["product_grp", "product_group", "product", "product_type", "fuel_type", "product_name"],
    }


def _find_profiled_column_match(
    raw_level: str,
    table_map: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None, str | None]:
    normalized = _normalized_level_token(raw_level)
    aliases = _level_aliases()
    candidate_tokens = [normalized]
    for canonical, values in aliases.items():
        if normalized == canonical or normalized in values:
            candidate_tokens = [canonical, *values]
            break
    matches: list[tuple[str, str, str]] = []
    for table_name, profile in table_map.items():
        columns = _collect_dimension_columns(profile)
        for column in columns:
            column_token = _normalized_level_token(column)
            if column_token in candidate_tokens or any(token == column_token for token in candidate_tokens):
                matches.append((table_name, column, column))
                break
    if not matches:
        return None, None, None
    prioritized = sorted(
        matches,
        key=lambda item: (
            0 if item[1] in {"zone", "region", "sales_area", "location_name", "sap_id", "site_id", "product_grp"} else 1,
            item[0],
            item[1],
        ),
    )
    table_name, column, level_id = prioritized[0]
    return table_name, column, level_id


def _levels_from_order(table_name: str, dedup_cols: list[str], order: list[str]) -> list[dict[str, Any]]:
    level_rows: list[dict[str, Any]] = []
    used = set()
    for level_name in order:
        matched = next((col for col in dedup_cols if col.lower() == level_name and col.lower() not in used), None)
        if not matched and level_name == "location":
            matched = next((col for col in dedup_cols if col.lower() in {"location_name", "location"} and col.lower() not in used), None)
        if matched:
            used.add(matched.lower())
            level_rows.append(
                {
                    "level_id": matched,
                    "column": matched,
                    "label": matched.replace("_", " ").title(),
                    "table": table_name,
                }
            )
    return level_rows


def _hierarchy_candidates_for_table(
    *,
    tenant_id: str,
    domain_id: str,
    table_name: str,
    dedup_cols: list[str],
    lower_context: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for suffix, order, label, confidence in _candidate_orders(lower_context):
        levels = _levels_from_order(table_name, dedup_cols, order)
        if len(levels) < 2:
            continue
        hierarchy_id = f"hier_{domain_id}_{table_name}_{suffix}"
        candidates.append(
            {
                "hierarchy_id": hierarchy_id,
                "tenant_id": tenant_id,
                "domain_id": domain_id,
                "name": f"{table_name.replace('_', ' ').title()} {label} Hierarchy",
                "description": (
                    f"{label} hierarchy inferred from profiled dimensions and business context."
                    if lower_context
                    else f"{label} hierarchy inferred from profiled dimensions."
                ),
                "base_scope_json": {"schema_name": "public", "base_table": table_name},
                "levels_json": levels,
                "join_path_json": [],
                "preferred": False,
                "confidence_score": confidence,
                "provenance_json": {
                    "source": "deterministic_bootstrap",
                    "candidate_family": suffix,
                    "context_text_present": bool(lower_context),
                },
                "validation_status": "approved",
            }
        )
    return candidates


def _profiling_table_map(profiling_stats: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        str(table.get("name") or "").strip(): table
        for table in ((profiling_stats or {}).get("tables") or [])
        if str(table.get("name") or "").strip()
    }


def _join_hierarchy_candidates(
    *,
    tenant_id: str,
    domain_id: str,
    profiling_stats: dict[str, Any] | None,
    join_edges: list[dict[str, Any]] | None,
    lower_context: str,
) -> list[dict[str, Any]]:
    tables = _profiling_table_map(profiling_stats)
    candidates: list[dict[str, Any]] = []
    for edge in join_edges or []:
        left_table = str(edge.get("left_table") or "").strip()
        right_table = str(edge.get("right_table") or "").strip()
        left_key = str(edge.get("left_key") or "").strip()
        right_key = str(edge.get("right_key") or "").strip()
        if not left_table or not right_table or not left_key or not right_key:
            continue
        for anchor_table, dim_table, anchor_key, dim_key in (
            (left_table, right_table, left_key, right_key),
            (right_table, left_table, right_key, left_key),
        ):
            anchor_profile = tables.get(anchor_table) or {}
            dim_profile = tables.get(dim_table) or {}
            dim_cols = _collect_dimension_columns(dim_profile)
            if len(dim_cols) < 2:
                continue
            for suffix, order, label, confidence in _candidate_orders(lower_context):
                levels = _levels_from_order(dim_table, dim_cols, order)
                if len(levels) < 2:
                    continue
                hierarchy_id = f"hier_{domain_id}_{anchor_table}_{dim_table}_{suffix}"
                candidates.append(
                    {
                        "hierarchy_id": hierarchy_id,
                        "tenant_id": tenant_id,
                        "domain_id": domain_id,
                        "name": f"{anchor_table.replace('_', ' ').title()} to {dim_table.replace('_', ' ').title()} {label} Hierarchy",
                        "description": f"{label} hierarchy inferred through validated join from {anchor_table} to {dim_table}.",
                        "base_scope_json": {
                            "schema_name": "public",
                            "base_table": anchor_table,
                            "joined_table": dim_table,
                        },
                        "levels_json": levels,
                        "join_path_json": [
                            {
                                "left_table": anchor_table,
                                "left_key": anchor_key,
                                "right_table": dim_table,
                                "right_key": dim_key,
                                "relationship": edge.get("relationship"),
                                "confidence": edge.get("confidence"),
                            }
                        ],
                        "preferred": False,
                        "confidence_score": min(0.9, float(confidence) + 0.06),
                        "provenance_json": {
                            "source": "join_aware_bootstrap",
                            "candidate_family": suffix,
                            "anchor_table": anchor_table,
                            "dimension_table": dim_table,
                        },
                        "validation_status": "approved",
                    }
                )
    return candidates


def _annotate_hierarchy_navigation(hierarchies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in hierarchies:
        levels = item.get("levels_json") or []
        suggested_paths = []
        for idx, level in enumerate(levels[:-1]):
            current_id = str((level or {}).get("level_id") or "").strip()
            next_level = levels[idx + 1] or {}
            next_id = str(next_level.get("level_id") or "").strip()
            if not current_id or not next_id:
                continue
            suggested_paths.append(
                {
                    "source_level_id": current_id,
                    "target_level_id": next_id,
                    "action_type": "drill_down",
                    "reason": "preferred next level from approved business hierarchy",
                }
            )
        item["provenance_json"] = {
            **(item.get("provenance_json") or {}),
            "suggested_paths": suggested_paths,
        }
    return hierarchies


def _hierarchies_from_overrides(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    profiling_stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows = load_hierarchy_overrides_all(settings, tenant_id, domain_id) or []
    table_map = _profiling_table_map(profiling_stats)
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        levels = [str(v).strip() for v in (row.get("levels") or []) if str(v).strip()]
        if len(levels) < 2:
            continue
        hierarchy_name = str(row.get("hierarchy_name") or f"override_{idx}").strip()
        level_rows = []
        unresolved_levels: list[str] = []
        base_table: str | None = None
        for level in levels:
            matched_table, matched_column, matched_level_id = _find_profiled_column_match(level, table_map)
            if not matched_column:
                unresolved_levels.append(level)
                continue
            if not base_table:
                base_table = matched_table
            level_rows.append(
                {
                    "level_id": matched_level_id,
                    "column": matched_column,
                    "label": level.replace("_", " ").title(),
                    "table": matched_table,
                }
            )
        deduped_rows = []
        seen_level_ids = set()
        for level_row in level_rows:
            level_id = str(level_row.get("level_id") or "").strip()
            if not level_id or level_id in seen_level_ids:
                continue
            seen_level_ids.add(level_id)
            deduped_rows.append(level_row)
        level_rows = deduped_rows
        if len(level_rows) < 2:
            continue
        all_resolved = not unresolved_levels
        out.append(
            {
                "hierarchy_id": f"override_{domain_id}_{hierarchy_name}",
                "tenant_id": tenant_id,
                "domain_id": domain_id,
                "name": hierarchy_name,
                "description": row.get("description") or "Customer-provided hierarchy override",
                "base_scope_json": {
                    "connection_id": row.get("connection_id"),
                    "database_name": row.get("database_name"),
                    "schema_name": row.get("schema_name"),
                    "base_table": base_table,
                },
                "levels_json": level_rows,
                "join_path_json": [],
                "preferred": True if idx == 1 and all_resolved else False,
                "confidence_score": 0.95 if all_resolved else 0.74,
                "provenance_json": {
                    "source": "hierarchy_override",
                    "hierarchy_group": row.get("hierarchy_group"),
                    "artifact_key": row.get("artifact_key"),
                    "unresolved_levels": unresolved_levels,
                    "normalized_from_override": True,
                },
                "validation_status": "approved",
            }
        )
    return out


def _llm_enabled(settings: Settings) -> bool:
    return bool(getattr(settings, "openai_api_key", None))


def _llm_rank_hierarchies(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    context_text: str | None,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not _llm_enabled(settings) or not candidates:
        return None
    model = os.getenv("AGENTIC_HIERARCHY_MODEL", getattr(settings, "openai_model", "gpt-4o-mini"))
    timeout_sec = int(os.getenv("AGENTIC_HIERARCHY_TIMEOUT_SEC", "30"))
    system_prompt = (
        "You are a semantic data modeler ranking business hierarchies for chart drill paths. "
        "Return JSON only with keys: ranked_hierarchy_ids, reasons, preferred_hierarchy_ids. "
        "Rules: prefer hierarchies that best match the business context, use practical drill paths, "
        "and avoid over-valuing purely technical ids unless they are clearly business-relevant endpoints."
    )
    payload = {
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "context_text": str(context_text or "")[:8000],
        "candidates": [
            {
                "hierarchy_id": item.get("hierarchy_id"),
                "name": item.get("name"),
                "description": item.get("description"),
                "base_scope": item.get("base_scope_json") or {},
                "levels": [
                    {
                        "level_id": level.get("level_id"),
                        "label": level.get("label"),
                    }
                    for level in (item.get("levels_json") or [])
                    if isinstance(level, dict)
                ],
            }
            for item in candidates
        ],
    }
    request_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        parsed = json.loads(content) if content else {}
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _apply_hierarchy_ranking(
    candidates: list[dict[str, Any]],
    ranking: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    if not isinstance(ranking, dict):
        for idx, item in enumerate(candidates):
            item["preferred"] = idx == 0
        return candidates
    ranked_ids = [str(v).strip() for v in (ranking.get("ranked_hierarchy_ids") or []) if str(v).strip()]
    preferred_ids = {str(v).strip() for v in (ranking.get("preferred_hierarchy_ids") or []) if str(v).strip()}
    reasons = ranking.get("reasons") or {}
    order_map = {hid: idx for idx, hid in enumerate(ranked_ids)}
    ranked = sorted(
        candidates,
        key=lambda item: (
            order_map.get(str(item.get("hierarchy_id") or ""), 9999),
            0 if item.get("preferred") else 1,
            str(item.get("name") or ""),
        ),
    )
    for idx, item in enumerate(ranked):
        hid = str(item.get("hierarchy_id") or "")
        item["preferred"] = hid in preferred_ids or (not preferred_ids and idx == 0)
        item["confidence_score"] = max(float(item.get("confidence_score") or 0.0), 0.82 if item["preferred"] else 0.72)
        item["provenance_json"] = {
            **(item.get("provenance_json") or {}),
            "ranking_source": "llm" if ranking else "deterministic_bootstrap",
            "ranking_reason": reasons.get(hid) if isinstance(reasons, dict) else None,
        }
    return ranked


def derive_business_hierarchies(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    profiling_stats: dict[str, Any] | None,
    context_text: str | None,
    join_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    tables = (profiling_stats or {}).get("tables") or []
    hierarchies: list[dict[str, Any]] = []
    lower_context = str(context_text or "").lower()
    override_hierarchies = _hierarchies_from_overrides(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        profiling_stats=profiling_stats,
    )
    hierarchies.extend(override_hierarchies)
    for table in tables:
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        dedup_cols = _collect_dimension_columns(table)
        hierarchies.extend(
            _hierarchy_candidates_for_table(
                tenant_id=tenant_id,
                domain_id=domain_id,
                table_name=table_name,
                dedup_cols=dedup_cols,
                lower_context=lower_context,
            )
        )
    hierarchies.extend(
        _join_hierarchy_candidates(
            tenant_id=tenant_id,
            domain_id=domain_id,
            profiling_stats=profiling_stats,
            join_edges=join_edges,
            lower_context=lower_context,
        )
    )
    deduped: list[dict[str, Any]] = []
    seen_ids = set()
    seen_level_signatures = set()
    for item in hierarchies:
        hid = str(item.get("hierarchy_id") or "")
        levels = tuple(str((level or {}).get("level_id") or "") for level in (item.get("levels_json") or []))
        signature = (str((item.get("base_scope_json") or {}).get("base_table") or ""), levels)
        if hid in seen_ids or signature in seen_level_signatures:
            continue
        seen_ids.add(hid)
        seen_level_signatures.add(signature)
        deduped.append(item)
    if deduped and not any(bool(item.get("preferred")) for item in deduped):
        deduped[0]["preferred"] = True
    return _annotate_hierarchy_navigation(deduped)


def upsert_business_hierarchies(settings: Settings, hierarchies: list[dict[str, Any]]) -> None:
    _hs_logger.info("hierarchy_store.upsert.start | count=%s", len(hierarchies))
    if not hierarchies:
        _hs_logger.info("hierarchy_store.upsert.skip | reason=empty_list")
        return
    sql = """
        INSERT INTO public.quantyx_business_hierarchies
          (hierarchy_id, tenant_id, domain_id, name, description, base_scope_json, levels_json,
           join_path_json, preferred, confidence_score, provenance_json, validation_status, created_at, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, %s, now(), now())
        ON CONFLICT (hierarchy_id) DO UPDATE
           SET name = EXCLUDED.name,
               description = EXCLUDED.description,
               base_scope_json = EXCLUDED.base_scope_json,
               levels_json = EXCLUDED.levels_json,
               join_path_json = EXCLUDED.join_path_json,
               preferred = EXCLUDED.preferred,
               confidence_score = EXCLUDED.confidence_score,
               provenance_json = EXCLUDED.provenance_json,
               validation_status = EXCLUDED.validation_status,
               updated_at = now()
    """
    conn = _conn(settings)
    try:
        with conn.cursor() as cur:
            for item in hierarchies:
                _hs_logger.debug(
                    "hierarchy_store.upsert.row | hierarchy_id=%s tenant_id=%s domain_id=%s name=%s preferred=%s",
                    item.get("hierarchy_id"), item.get("tenant_id"), item.get("domain_id"),
                    item.get("name"), item.get("preferred"),
                )
                cur.execute(
                    sql,
                    [
                        item["hierarchy_id"],
                        item["tenant_id"],
                        item["domain_id"],
                        item["name"],
                        item.get("description"),
                        json.dumps(item.get("base_scope_json") or {}),
                        json.dumps(item.get("levels_json") or []),
                        json.dumps(item.get("join_path_json") or []),
                        bool(item.get("preferred")),
                        item.get("confidence_score"),
                        json.dumps(item.get("provenance_json") or {}),
                        item.get("validation_status") or "approved",
                    ],
                )
        conn.commit()
        _hs_logger.info("hierarchy_store.upsert.committed | count=%s", len(hierarchies))
    except Exception:
        _hs_logger.error(
            "hierarchy_store.upsert.failed | count=%s traceback=%s",
            len(hierarchies), traceback.format_exc(),
        )
        conn.rollback()
        raise
    finally:
        conn.close()


def list_business_hierarchies(settings: Settings, tenant_id: str, domain_id: str | None) -> list[dict[str, Any]]:
    sql = """
        SELECT hierarchy_id, tenant_id, domain_id, name, description, base_scope_json, levels_json,
               join_path_json, preferred, confidence_score, provenance_json, validation_status
          FROM public.quantyx_business_hierarchies
         WHERE tenant_id = %s
           AND (%s IS NULL OR domain_id = %s)
         ORDER BY preferred DESC, updated_at DESC, name ASC
    """
    conn = _conn(settings)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [tenant_id, domain_id, domain_id])
            rows = cur.fetchall() or []
        return [dict(r) for r in rows]
    finally:
        conn.close()


def ensure_business_hierarchies(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    profiling_stats: dict[str, Any] | None,
    context_text: str | None,
    join_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    _hs_logger.info(
        "hierarchy_store.ensure.start | tenant_id=%s domain_id=%s join_edges=%s profiled_tables=%s",
        tenant_id,
        domain_id,
        len(join_edges or []),
        len((profiling_stats or {}).get("tables") or []),
    )
    try:
        existing = list_business_hierarchies(settings, tenant_id, domain_id)
    except Exception:
        _hs_logger.error(
            "hierarchy_store.ensure.list_existing_failed | tenant_id=%s domain_id=%s traceback=%s",
            tenant_id, domain_id, traceback.format_exc(),
        )
        existing = []
    _hs_logger.info(
        "hierarchy_store.ensure.existing_check | tenant_id=%s domain_id=%s existing_count=%s",
        tenant_id, domain_id, len(existing),
    )
    if existing:
        _hs_logger.info(
            "hierarchy_store.ensure.returning_existing | tenant_id=%s domain_id=%s count=%s",
            tenant_id, domain_id, len(existing),
        )
        return existing
    try:
        derived = derive_business_hierarchies(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            profiling_stats=profiling_stats,
            context_text=context_text,
            join_edges=join_edges,
        )
    except Exception:
        _hs_logger.error(
            "hierarchy_store.ensure.derive_failed | tenant_id=%s domain_id=%s traceback=%s",
            tenant_id, domain_id, traceback.format_exc(),
        )
        derived = []
    _hs_logger.info(
        "hierarchy_store.ensure.derived | tenant_id=%s domain_id=%s derived_count=%s",
        tenant_id, domain_id, len(derived),
    )
    if not derived:
        _hs_logger.warning(
            "hierarchy_store.ensure.no_candidates | tenant_id=%s domain_id=%s — skipping upsert",
            tenant_id, domain_id,
        )
        return []
    try:
        ranking = _llm_rank_hierarchies(
            settings,
            tenant_id=tenant_id,
            domain_id=domain_id,
            context_text=context_text,
            candidates=derived,
        )
        _hs_logger.info(
            "hierarchy_store.ensure.ranking_done | tenant_id=%s domain_id=%s ranking_count=%s",
            tenant_id, domain_id, len(ranking or []),
        )
        derived = _apply_hierarchy_ranking(derived, ranking)
    except Exception:
        _hs_logger.warning(
            "hierarchy_store.ensure.ranking_failed | tenant_id=%s domain_id=%s traceback=%s — proceeding without ranking",
            tenant_id, domain_id, traceback.format_exc(),
        )
    try:
        upsert_business_hierarchies(settings, derived)
        _hs_logger.info(
            "hierarchy_store.ensure.upsert_done | tenant_id=%s domain_id=%s upserted_count=%s",
            tenant_id, domain_id, len(derived),
        )
    except Exception:
        _hs_logger.error(
            "hierarchy_store.ensure.upsert_failed | tenant_id=%s domain_id=%s traceback=%s",
            tenant_id, domain_id, traceback.format_exc(),
        )
        return derived
    final = list_business_hierarchies(settings, tenant_id, domain_id)
    _hs_logger.info(
        "hierarchy_store.ensure.complete | tenant_id=%s domain_id=%s final_count=%s",
        tenant_id, domain_id, len(final),
    )
    return final
