from __future__ import annotations

import json
import logging
import re
import urllib.request
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from services.ai.charts import build_chart_payload, infer_chart_type
from services.ai.config import Settings

if TYPE_CHECKING:
    from services.ai.catalog import MetricCatalog


logger = logging.getLogger(__name__)
_MONTH_NAME_TO_NUMBER = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_FISCAL_YEAR_START_MONTH = 4


def _quarter_bounds(year_no: int, quarter_no: int) -> tuple[date, date]:
    quarter_start_month = ((quarter_no - 1) * 3) + 1
    start_of_quarter = date(year_no, quarter_start_month, 1)
    if quarter_no == 4:
        start_of_next_quarter = date(year_no + 1, 1, 1)
    else:
        start_of_next_quarter = date(year_no, quarter_start_month + 3, 1)
    end_of_quarter = start_of_next_quarter - timedelta(days=1)
    return start_of_quarter, end_of_quarter


def _fiscal_quarter_bounds(fiscal_year_start: int, quarter_no: int) -> tuple[date, date]:
    # Assumes fiscal year starts on April 1 and ends on March 31 of the following year.
    fiscal_months = {
        1: (fiscal_year_start, 4),
        2: (fiscal_year_start, 7),
        3: (fiscal_year_start, 10),
        4: (fiscal_year_start + 1, 1),
    }
    year_no, month_no = fiscal_months[quarter_no]
    start_of_quarter = date(year_no, month_no, 1)
    if quarter_no == 4:
        start_of_next_quarter = date(fiscal_year_start + 1, 4, 1)
    else:
        next_year_no, next_month_no = fiscal_months[quarter_no + 1]
        start_of_next_quarter = date(next_year_no, next_month_no, 1)
    end_of_quarter = start_of_next_quarter - timedelta(days=1)
    return start_of_quarter, end_of_quarter


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _infer_base_table_from_metric_sql(sql: str | None) -> str | None:
    text = (sql or "").strip()
    if not text:
        return None
    match = re.search(r"\bfrom\s+([a-zA-Z0-9_.\"]+)", text, re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).strip().replace('"', "")
    return token.split(".")[-1] if token else None


def _detect_time_grain(question: str, filters: list[dict[str, Any]]) -> str | None:
    question_l = (question or "").lower()
    if "month wise" in question_l or "month-wise" in question_l:
        return "month"
    if " by day" in question_l or "daily" in question_l:
        return "day"
    if " by week" in question_l or "weekly" in question_l:
        return "week"
    if " by month" in question_l or "monthly" in question_l:
        return "month"
    if any(flt.get("operator") in {"=", ">=", "<="} and str(flt.get("field", "")).lower() in {"process_date", "pdate", "date_day", "date"} for flt in filters):
        return "day"
    return None


def _normalize_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _is_identifier_dimension(name: str | None) -> bool:
    normalized = _normalize_name(name).replace(" ", "_")
    if not normalized:
        return False
    return (
        normalized == "id"
        or normalized.endswith("_id")
        or normalized.endswith("_key")
        or normalized.endswith("_code")
        or normalized in {"entity_id", "sap_id", "uuid", "guid"}
    )


def _is_date_like(value: object) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False
    return False


def parse_exact_date_filters(question: str, allowed_dimensions: list[str] | None) -> list[dict[str, Any]]:
    if not question or not allowed_dimensions:
        return []
    allowed_lookup = {_normalize_name(dim): dim for dim in allowed_dimensions}
    date_field = None
    for candidate in ("process_date", "pdate", "date_day", "date"):
        resolved = allowed_lookup.get(_normalize_name(candidate))
        if resolved:
            date_field = resolved
            break
    if not date_field:
        return []
    patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}-[A-Za-z]{3}-\d{4})\b",
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b",
        r"\b([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})\b",
    ]
    format_map = {
        patterns[0]: ("%Y-%m-%d",),
        patterns[1]: ("%d-%b-%Y",),
        patterns[2]: ("%d %b %Y", "%d %B %Y"),
        patterns[3]: ("%b %d, %Y", "%B %d, %Y"),
    }
    filters: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, question):
            raw_value = match.group(1)
            parsed = None
            for fmt in format_map[pattern]:
                try:
                    parsed = datetime.strptime(raw_value, fmt).date().isoformat()
                    break
                except ValueError:
                    continue
            if not parsed or parsed in seen:
                continue
            seen.add(parsed)
            filters.append({"field": date_field, "operator": "=", "value": parsed, "value_type": "date"})
    return filters


def parse_relative_date_filters(question: str, allowed_dimensions: list[str] | None) -> list[dict[str, Any]]:
    if not question or not allowed_dimensions:
        return []
    allowed_lookup = {_normalize_name(dim): dim for dim in allowed_dimensions}
    date_field = None
    for candidate in ("process_date", "pdate", "date_day", "date"):
        resolved = allowed_lookup.get(_normalize_name(candidate))
        if resolved:
            date_field = resolved
            break
    if not date_field:
        return []
    question_l = question.lower()
    today = date.today()
    quarter_match = re.search(r"\bq([1-4])\s+(\d{4})\b", question_l)
    if quarter_match:
        quarter_no = int(quarter_match.group(1))
        year_no = int(quarter_match.group(2))
        start_of_quarter, end_of_quarter = _quarter_bounds(year_no, quarter_no)
        return [
            {"field": date_field, "operator": ">=", "value": start_of_quarter.isoformat(), "value_type": "date"},
            {"field": date_field, "operator": "<=", "value": end_of_quarter.isoformat(), "value_type": "date"},
        ]
    fiscal_quarter_match = re.search(r"\bq([1-4])\s+fy\s*(\d{4})(?:\s*-\s*(\d{4}))?\b", question_l)
    if fiscal_quarter_match:
        quarter_no = int(fiscal_quarter_match.group(1))
        fiscal_year_start = int(fiscal_quarter_match.group(2))
        start_of_quarter, end_of_quarter = _fiscal_quarter_bounds(fiscal_year_start, quarter_no)
        return [
            {"field": date_field, "operator": ">=", "value": start_of_quarter.isoformat(), "value_type": "date"},
            {"field": date_field, "operator": "<=", "value": end_of_quarter.isoformat(), "value_type": "date"},
        ]
    if "yesterday" in question_l:
        resolved = (today - timedelta(days=1)).isoformat()
        return [{"field": date_field, "operator": "=", "value": resolved, "value_type": "date"}]
    if "today" in question_l:
        return [{"field": date_field, "operator": "=", "value": today.isoformat(), "value_type": "date"}]
    if "last week" in question_l:
        start_of_this_week = today - timedelta(days=today.weekday())
        start_of_last_week = start_of_this_week - timedelta(days=7)
        end_of_last_week = start_of_this_week - timedelta(days=1)
        return [
            {"field": date_field, "operator": ">=", "value": start_of_last_week.isoformat(), "value_type": "date"},
            {"field": date_field, "operator": "<=", "value": end_of_last_week.isoformat(), "value_type": "date"},
        ]
    current_quarter = ((today.month - 1) // 3) + 1
    if "this quarter" in question_l:
        start_of_quarter, end_of_quarter = _quarter_bounds(today.year, current_quarter)
        return [
            {"field": date_field, "operator": ">=", "value": start_of_quarter.isoformat(), "value_type": "date"},
            {"field": date_field, "operator": "<=", "value": end_of_quarter.isoformat(), "value_type": "date"},
        ]
    if "last quarter" in question_l or "past quarter" in question_l:
        quarter_no = current_quarter - 1
        year_no = today.year
        if quarter_no == 0:
            quarter_no = 4
            year_no -= 1
        start_of_quarter, end_of_quarter = _quarter_bounds(year_no, quarter_no)
        return [
            {"field": date_field, "operator": ">=", "value": start_of_quarter.isoformat(), "value_type": "date"},
            {"field": date_field, "operator": "<=", "value": end_of_quarter.isoformat(), "value_type": "date"},
        ]
    month_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{4})\b",
        question_l,
    )
    if month_match:
        month_no = _MONTH_NAME_TO_NUMBER.get(month_match.group(1))
        year_no = int(month_match.group(2))
        if month_no:
            start_of_month = date(year_no, month_no, 1)
            if month_no == 12:
                start_of_next_month = date(year_no + 1, 1, 1)
            else:
                start_of_next_month = date(year_no, month_no + 1, 1)
            end_of_month = start_of_next_month - timedelta(days=1)
            return [
                {"field": date_field, "operator": ">=", "value": start_of_month.isoformat(), "value_type": "date"},
                {"field": date_field, "operator": "<=", "value": end_of_month.isoformat(), "value_type": "date"},
            ]
    months_match = re.search(r"\blast\s+(\d+)\s+months\b", question_l)
    if months_match:
        months_back = max(1, int(months_match.group(1)))
        start_of_current_month = today.replace(day=1)
        year_no = start_of_current_month.year
        month_no = start_of_current_month.month
        for _ in range(months_back - 1):
            if month_no == 1:
                year_no -= 1
                month_no = 12
            else:
                month_no -= 1
        start_of_window = date(year_no, month_no, 1)
        return [{"field": date_field, "operator": ">=", "value": start_of_window.isoformat(), "value_type": "date"}]
    if "last three months" in question_l:
        start_of_current_month = today.replace(day=1)
        year_no = start_of_current_month.year
        month_no = start_of_current_month.month
        for _ in range(2):
            if month_no == 1:
                year_no -= 1
                month_no = 12
            else:
                month_no -= 1
        start_of_window = date(year_no, month_no, 1)
        return [{"field": date_field, "operator": ">=", "value": start_of_window.isoformat(), "value_type": "date"}]
    if "this month" in question_l:
        month_start = today.replace(day=1).isoformat()
        return [{"field": date_field, "operator": ">=", "value": month_start, "value_type": "date"}]
    if "this year" in question_l:
        year_start = today.replace(month=1, day=1).isoformat()
        return [{"field": date_field, "operator": ">=", "value": year_start, "value_type": "date"}]
    return []


def detect_detail_intent(question: str) -> bool:
    question_l = (question or "").lower()
    detail_markers = (
        "show raw records",
        "show records",
        "raw records",
        "top 20 records",
        "top 10 records",
        "record level",
        "detail table",
        "details for",
    )
    return any(marker in question_l for marker in detail_markers)


def bind_metric(metric_candidates: list[str], available_metrics: list[str]) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    if not metric_candidates:
        return None, warnings
    normalized_lookup = {_normalize_name(name): name for name in available_metrics}
    available_tokens = {name: set(_normalize_name(name).split()) for name in available_metrics}
    best_metric = None
    best_score = 0.0
    for candidate in metric_candidates:
        normalized_candidate = _normalize_name(candidate)
        if not normalized_candidate:
            continue
        if normalized_candidate in normalized_lookup:
            return normalized_lookup[normalized_candidate], warnings
        candidate_tokens = set(normalized_candidate.split())
        for metric_name, metric_tokens in available_tokens.items():
            overlap = len(candidate_tokens & metric_tokens)
            if not overlap:
                continue
            score = overlap / max(len(candidate_tokens), 1)
            if normalized_candidate in _normalize_name(metric_name):
                score += 0.5
            if score > best_score:
                best_score = score
                best_metric = metric_name
    if best_metric:
        warnings.append(f"metric_bound:{metric_candidates[0]}->{best_metric}")
        return best_metric, warnings
    # Registry is empty or no match found — fall back to accepting the first
    # non-empty candidate as a raw-column metric so chart followup queries don't
    # hard-fail when the metric catalog hasn't been populated yet.
    if not available_metrics and metric_candidates:
        first = next((c for c in metric_candidates if _normalize_name(c)), None)
        if first:
            warnings.append(f"metric_raw_column_passthrough:{first}")
            return first, warnings
    return None, warnings


def bind_metrics(
    metric_candidates: list[str],
    available_metrics: list[str],
) -> tuple[list[str], list[str]]:
    """
    Like bind_metric but returns ALL matched metrics (not just the best one).
    Each candidate is resolved independently using the same token-overlap logic.
    Returns (bound_metrics, warnings).
    """
    warnings: list[str] = []
    if not metric_candidates:
        return [], warnings
    normalized_lookup = {_normalize_name(name): name for name in available_metrics}
    available_tokens = {name: set(_normalize_name(name).split()) for name in available_metrics}
    bound: list[str] = []
    seen: set[str] = set()
    for candidate in metric_candidates:
        normalized_candidate = _normalize_name(candidate)
        if not normalized_candidate:
            continue
        # Exact match
        if normalized_candidate in normalized_lookup:
            resolved = normalized_lookup[normalized_candidate]
            if resolved not in seen:
                bound.append(resolved)
                seen.add(resolved)
            continue
        # Token-overlap match
        best_metric: str | None = None
        best_score = 0.0
        candidate_tokens = set(normalized_candidate.split())
        for metric_name, metric_tokens in available_tokens.items():
            overlap = len(candidate_tokens & metric_tokens)
            if not overlap:
                continue
            score = overlap / max(len(candidate_tokens), 1)
            if normalized_candidate in _normalize_name(metric_name):
                score += 0.5
            if score > best_score:
                best_score = score
                best_metric = metric_name
        if best_metric and best_metric not in seen:
            bound.append(best_metric)
            seen.add(best_metric)
            if best_metric != candidate:
                warnings.append(f"metric_bound:{candidate}->{best_metric}")
        elif not available_metrics:
            # Raw-column passthrough when catalog is empty
            if candidate not in seen:
                bound.append(candidate)
                seen.add(candidate)
                warnings.append(f"metric_raw_column_passthrough:{candidate}")
    return bound, warnings


def bind_dimensions(
    dimension_candidates: list[str],
    allowed_dimensions: list[str],
) -> tuple[list[str], list[str], list[str]]:
    allowed_lookup = {_normalize_name(name): name for name in allowed_dimensions}
    bound: list[str] = []
    rejected: list[str] = []
    warnings: list[str] = []
    for candidate in dimension_candidates:
        normalized_candidate = _normalize_name(candidate)
        if not normalized_candidate:
            continue
        if _is_identifier_dimension(candidate):
            rejected.append(candidate)
            continue
        matched = allowed_lookup.get(normalized_candidate)
        if not matched:
            for allowed_name in allowed_dimensions:
                normalized_allowed = _normalize_name(allowed_name)
                if normalized_candidate in normalized_allowed or normalized_allowed in normalized_candidate:
                    matched = allowed_name
                    break
        if not matched:
            rejected.append(candidate)
            continue
        if matched not in bound:
            if matched != candidate:
                warnings.append(f"dimension_bound:{candidate}->{matched}")
            bound.append(matched)
    return bound, rejected, warnings


def interpret_workspace_query(
    *,
    question: str,
    metric_catalog: "MetricCatalog",
    allowed_dimensions: list[str],
    glossary: list[dict] | None,
    settings: Settings,
) -> dict[str, Any]:
    logger.info(
        "workspace.query_plan.interpret.start | question_chars=%s metric_count=%s dimension_count=%s mode=%s",
        len(question or ""),
        len(metric_catalog.metrics),
        len(allowed_dimensions),
        settings.workspace_query_plan_mode,
    )
    fallback_plan: dict[str, Any] = {
        "intent": "detail_query" if detect_detail_intent(question) else "analytic_query",
        "metric_candidates": [],
        "dimensions": [],
        "filters": [],
        "chart_intent": None,
        "response_mode": "table_only" if detect_detail_intent(question) else "chart_plus_table",
        "sort": [],
    }
    # Strip the appended chart context block before sending to the resolver so
    # that embedded JSON fragments are not mistakenly extracted as dimension names.
    _chart_ctx_sep = "\n\nChart context:"
    question_for_resolver = (
        question.split(_chart_ctx_sep)[0].strip()
        if _chart_ctx_sep in question
        else question
    )
    try:
        from services.ai.resolver import resolve_question

        resolved = resolve_question(
            question_for_resolver,
            metric_catalog,
            settings,
            allowed_metrics=list(metric_catalog.metrics.keys()),
            allowed_dimensions=allowed_dimensions,
            glossary=glossary,
        )
        fallback_plan["metric_candidates"] = resolved.get("metrics") or []
        fallback_plan["dimensions"] = resolved.get("dimensions") or []
        fallback_plan["filters"] = [
            item if isinstance(item, dict) else item.model_dump()
            for item in (resolved.get("filters") or [])
        ]
    except Exception:
        pass
    lower_question = question_for_resolver.lower()
    by_match = re.search(r"\bby\s+(.+?)(?:\s+for\b|\s+on\b|$)", lower_question)
    if by_match:
        parts = re.split(r",| and ", by_match.group(1))
        requested_dims = [part.strip() for part in parts if part.strip()]
        if requested_dims:
            fallback_plan["dimensions"] = requested_dims + [
                dim for dim in fallback_plan["dimensions"] if dim not in requested_dims
            ]
    if "productivity" in lower_question and not fallback_plan["metric_candidates"]:
        fallback_plan["metric_candidates"] = ["productivity", "total_productivity"]
    if len(fallback_plan["dimensions"]) >= 2:
        fallback_plan["chart_intent"] = "grouped_bar"
    mode = (settings.workspace_query_plan_mode or "auto").strip().lower()
    logger.info("workspace.query_plan.interpret.fallback | plan=%s", json.dumps(fallback_plan, default=str))
    if mode == "off" or not settings.openai_api_key:
        logger.info(
            "workspace.query_plan.interpret.output | source=fallback mode=%s llm_used=%s",
            mode,
            bool(settings.openai_api_key and mode != "off"),
        )
        return fallback_plan
    system_prompt = (
        "You convert analytics questions into a structured query plan. "
        "Return JSON only with keys: intent, metric_candidates, dimensions, filters, chart_intent, response_mode, sort. "
        "Use only names present in the provided metric and dimension lists. "
        "Do not include identifier dimensions such as id or *_id unless the user explicitly asks for record-level detail. "
        "Preserve all requested breakdown dimensions. "
        "If a date is explicitly stated, emit an '=' filter in ISO date format when possible."
    )
    payload = {
        "model": settings.workspace_query_plan_model or settings.openai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question_for_resolver,
                        "available_metrics": list(metric_catalog.metrics.keys()),
                        "available_dimensions": allowed_dimensions,
                        "output_schema": {
                            "intent": "analytic_query|detail_query|trend_query",
                            "metric_candidates": ["metric_name"],
                            "dimensions": ["dimension_name"],
                            "filters": [{"field": "dimension_name", "operator": "=", "value": "value"}],
                            "chart_intent": "bar|line|table|grouped_bar",
                            "response_mode": "chart_plus_table|table_only",
                            "sort": [{"field": "metric_name", "direction": "desc"}],
                        },
                    }
                ),
            },
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.workspace_query_plan_timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
        raw_plan = json.loads(body["choices"][0]["message"]["content"])
        raw_plan["fallback_plan"] = fallback_plan
        logger.info(
            "workspace.query_plan.interpret.output | source=llm intent=%s chart_intent=%s dimensions=%s filters=%s",
            raw_plan.get("intent"),
            raw_plan.get("chart_intent"),
            raw_plan.get("dimensions"),
            raw_plan.get("filters"),
        )
        return raw_plan
    except Exception:
        logger.exception("workspace.query_plan.interpret.llm_failed | mode=%s", mode)
        if mode == "on":
            raise
        logger.info("workspace.query_plan.interpret.output | source=fallback_after_llm_failure")
        return fallback_plan


def validate_workspace_query_plan(
    *,
    question: str,
    raw_plan: dict[str, Any],
    metric_catalog: "MetricCatalog",
    allowed_dimensions: list[str],
    explicit_metrics: list[str] | None = None,
    explicit_dimensions: list[str] | None = None,
) -> dict[str, Any]:
    # Strip appended chart context block so it doesn't pollute time-grain detection
    # or date filter parsing (e.g. "by Month" in chart title triggers month grain).
    _chart_ctx_sep = "\n\nChart context:"
    question_clean = question.split(_chart_ctx_sep)[0].strip() if _chart_ctx_sep in question else question
    detail_intent = (raw_plan.get("intent") == "detail_query") or detect_detail_intent(question_clean)
    metric_candidates = list(explicit_metrics or []) + list(raw_plan.get("metric_candidates") or raw_plan.get("metrics") or [])
    # Resolve ALL requested metrics (multi-metric comparison support)
    all_metric_names, metric_warnings = bind_metrics(metric_candidates, list(metric_catalog.metrics.keys()))
    # Primary metric for backward-compatible code paths
    metric_name = all_metric_names[0] if all_metric_names else None
    dimension_candidates = list(explicit_dimensions or []) + list(raw_plan.get("dimensions") or [])
    if detail_intent:
        allowed_lookup = {_normalize_name(name): name for name in allowed_dimensions}
        bound_dimensions = []
        rejected_dimensions = []
        dimension_warnings = []
        for candidate in dimension_candidates:
            normalized_candidate = _normalize_name(candidate)
            matched = allowed_lookup.get(normalized_candidate)
            if matched and matched not in bound_dimensions:
                bound_dimensions.append(matched)
            elif candidate:
                rejected_dimensions.append(candidate)
    else:
        bound_dimensions, rejected_dimensions, dimension_warnings = bind_dimensions(dimension_candidates, allowed_dimensions)
    raw_filters = [
        item if isinstance(item, dict) else item.model_dump()
        for item in (raw_plan.get("filters") or [])
    ]
    date_filters = parse_exact_date_filters(question_clean, allowed_dimensions)
    relative_date_filters = parse_relative_date_filters(question_clean, allowed_dimensions)
    if date_filters:
        raw_filters = [flt for flt in raw_filters if str(flt.get("field", "")).lower() not in {"process_date", "pdate", "date_day", "date"}]
        raw_filters.extend(date_filters)
        logger.info("workspace.query_plan.bound_date_filter | source=exact filters=%s", date_filters)
    elif relative_date_filters:
        raw_filters = [flt for flt in raw_filters if str(flt.get("field", "")).lower() not in {"process_date", "pdate", "date_day", "date"}]
        raw_filters.extend(relative_date_filters)
        logger.info("workspace.query_plan.bound_date_filter | source=relative filters=%s", relative_date_filters)
    warnings = metric_warnings + dimension_warnings
    rejected_metrics: list[str] = []
    if metric_name:
        metric_norm = _normalize_name(metric_name)
        conflicting_dimensions: list[str] = []
        filtered_dimensions: list[str] = []
        for dim in bound_dimensions:
            dim_norm = _normalize_name(dim)
            if not detail_intent and dim_norm and (dim_norm == metric_norm or dim_norm in metric_norm or metric_norm in dim_norm):
                conflicting_dimensions.append(dim)
                continue
            filtered_dimensions.append(dim)
        if conflicting_dimensions:
            bound_dimensions = filtered_dimensions
            warnings.extend([f"candidate_measure_dimension_conflict:{item}" for item in conflicting_dimensions])
            rejected_dimensions.extend(conflicting_dimensions)
    bound_dimensions = _dedupe_preserve(bound_dimensions)
    if rejected_dimensions:
        warnings.extend([f"identifier_dimension_rejected:{item}" for item in rejected_dimensions if _is_identifier_dimension(item)])
        warnings.extend([f"dimension_not_found_rejected:{item}" for item in rejected_dimensions if not _is_identifier_dimension(item)])
        for item in rejected_dimensions:
            logger.info("workspace.query_plan.rejected_dimension | dimension=%s detail_intent=%s", item, detail_intent)
    chart_type = raw_plan.get("chart_intent") or ("grouped_bar" if len(bound_dimensions) >= 2 else "bar")
    if len(bound_dimensions) >= 2 and chart_type not in {"grouped_bar", "stacked_bar", "line", "area", "stacked_area", "table", "bar"}:
        warnings.append(f"chart_intent_fallback:{chart_type}->grouped_bar")
        chart_type = "grouped_bar"
    if detail_intent:
        chart_type = "table"
    time_grain = raw_plan.get("time_grain") or _detect_time_grain(question_clean, raw_filters)
    if (
        not detail_intent
        and time_grain == "month"
        and "process_month" not in bound_dimensions
        and any(dim in allowed_dimensions for dim in {"process_date", "pdate", "date_day", "date"})
    ):
        bound_dimensions = ["process_month"] + [dim for dim in bound_dimensions if dim not in {"process_date", "pdate", "date_day", "date"}]
        warnings.append("time_grain_bound_to_month_dimension:process_month")
    metric_obj = metric_catalog.metrics.get(metric_name) if metric_name else None
    base_table = _infer_base_table_from_metric_sql(metric_obj.sql if metric_obj else None)
    filter_columns = [
        {
            "column": flt.get("field"),
            "operator": flt.get("operator"),
            "value": flt.get("value"),
            "value_type": flt.get("value_type") or ("date" if str(flt.get("field", "")).lower() in {"process_date", "pdate", "date_day", "date"} else "text"),
        }
        for flt in raw_filters
    ]
    dimension_objects = [
        {"column": dim, "semantic_role": "identifier" if _is_identifier_dimension(dim) else "business_dimension"}
        for dim in bound_dimensions
    ]
    validated = {
        "intent": "detail_query" if detail_intent else (raw_plan.get("intent") or "analytic_query"),
        "metric_name": metric_name,
        "metric_names": all_metric_names,  # full list for multi-metric queries
        "metric_source": "registry_metric" if metric_obj else None,
        "metric_sql": metric_obj.sql if metric_obj else None,
        "base_table": base_table,
        "dimensions": bound_dimensions,
        "dimension_objects": dimension_objects,
        "filters": raw_filters,
        "filter_objects": filter_columns,
        "chart_type": chart_type,
        "response_mode": "table_only" if detail_intent else (raw_plan.get("response_mode") or "chart_plus_table"),
        "sort": raw_plan.get("sort") or [],
        "time_grain": time_grain,
        "disallowed_dimensions_removed": _dedupe_preserve(rejected_dimensions),
        "rejected_candidates": {
            "dimensions": _dedupe_preserve(rejected_dimensions),
            "filters": [],
            "metrics": rejected_metrics if metric_name else metric_candidates,
        },
        "validation_warnings": warnings,
    }
    logger.info(
        "workspace.query_plan.validate.output | intent=%s metric=%s dimensions=%s filters=%s chart_type=%s warnings=%s",
        validated.get("intent"),
        validated.get("metric_name"),
        validated.get("dimensions"),
        validated.get("filters"),
        validated.get("chart_type"),
        validated.get("validation_warnings"),
    )
    return validated


def compile_workspace_query_plan(
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str | None,
    validated_plan: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    metric_name = validated_plan.get("metric_name")
    # Use the full metric_names list when present (multi-metric queries)
    metric_names = validated_plan.get("metric_names") or ([metric_name] if metric_name else [])
    compiled = {
        "question": None,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "run_id": run_id,
        "metrics": metric_names,
        "dimensions": validated_plan.get("dimensions") or [],
        "filters": validated_plan.get("filters") or [],
        "limit": limit,
        "explain": False,
    }
    logger.info(
        "workspace.query_plan.compile.output | tenant=%s domain=%s metric=%s metrics=%s dimensions=%s filters=%s limit=%s",
        tenant_id,
        domain_id,
        metric_name,
        metric_names,
        compiled.get("dimensions"),
        compiled.get("filters"),
        limit,
    )
    return compiled


def conversation_plan_diagnostics(
    *,
    raw_llm_plan: dict[str, Any],
    validated_plan: dict[str, Any],
    compiled_sql_preview: str | None = None,
) -> dict[str, Any]:
    return {
        "raw_llm_plan": raw_llm_plan,
        "validated_plan": validated_plan,
        "validation_warnings": validated_plan.get("validation_warnings") or [],
        "rejected_candidates": validated_plan.get("rejected_candidates") or {},
        "compiled_sql_preview": compiled_sql_preview,
    }


def workspace_chart_title(metric_name: str | None, dimensions: list[str]) -> str:
    if metric_name and dimensions:
        return (
            f"{str(metric_name).replace('_', ' ').title()} by "
            f"{' and '.join(str(dim).replace('_', ' ').title() for dim in dimensions[:2])}"
        )
    if metric_name:
        return f"{str(metric_name).replace('_', ' ').title()} Trend"
    return "Data Trend"


def build_workspace_chart(
    *,
    rows: list[dict[str, Any]],
    metric_name: str | None,
    dimensions: list[str],
    response_mode: str | None = None,
    preferred_chart_type: str | None = None,
    metric_names: list[str] | None = None,
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    from services.ai.charts import build_multi_metric_chart_payload

    warnings: list[str] = []
    requested = str(preferred_chart_type or "").strip().lower()
    if response_mode == "table_only":
        warnings.append("chart_intent_fallback:table_only->table")
        return "table", None, warnings

    # Multi-metric path: 2+ distinct metrics requested
    effective_metric_names = metric_names or ([metric_name] if metric_name else [])
    if len(effective_metric_names) > 1 and rows:
        payload = build_multi_metric_chart_payload(rows, effective_metric_names, dimensions, chart_type=requested or None)
        chart_type = payload["chart_type"]
        return chart_type, payload, warnings

    if not rows or not metric_name or not dimensions:
        warnings.append("chart_intent_fallback:insufficient_chart_inputs->table")
        return "table", None, warnings
    if len(dimensions) == 1:
        first_values = [row.get(dimensions[0]) for row in rows[:10]]
        is_time_series = any(_is_date_like(value) for value in first_values if value is not None)
        if requested in {"line", "area", "stacked_area", "bar", "horizontal_bar"}:
            if requested in {"line", "area", "stacked_area"} and not is_time_series:
                warnings.append("chart_type_transform_rejected:line_requires_time_dimension")
            else:
                return requested, build_chart_payload(requested, rows, metric_name, dimensions), warnings
        if requested in {"pie", "donut"}:
            if is_time_series:
                warnings.append("chart_type_transform_rejected:pie_requires_categorical_dimension")
            else:
                return requested, build_chart_payload(requested, rows, metric_name, dimensions), warnings
        chart_type = infer_chart_type(dimensions, rows, [metric_name])
        if not chart_type:
            warnings.append("chart_intent_fallback:unknown_single_dimension_shape->table")
            return "table", None, warnings
        return chart_type, build_chart_payload(chart_type, rows, metric_name, dimensions), warnings
    if len(dimensions) > 2:
        warnings.append("chart_intent_fallback:multi_breakdown_gt_2->table")
        return "table", None, warnings
    first_dim, second_dim = dimensions[0], dimensions[1]
    first_values = [row.get(first_dim) for row in rows[:10]]
    if any(_is_date_like(value) for value in first_values if value is not None):
        chart_type = "line"
        if requested in {"bar", "grouped_bar", "stacked_bar"}:
            chart_type = requested
        elif requested in {"area", "stacked_area"}:
            chart_type = requested
        elif requested in {"pie", "donut", "horizontal_bar"}:
            warnings.append("chart_type_transform_rejected:pie_requires_single_categorical_dimension")
        return chart_type, build_chart_payload(chart_type, rows, metric_name, dimensions), warnings
    series_names = [str(value) for value in dict.fromkeys(row.get(second_dim) for row in rows if row.get(second_dim) is not None)]
    if not series_names:
        warnings.append("chart_intent_fallback:no_series_values->table")
        return "table", None, warnings
    grouped_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        category = str(row.get(first_dim))
        series_name = str(row.get(second_dim))
        if category not in grouped_rows:
            grouped_rows[category] = {"category": category}
        grouped_rows[category][series_name] = row.get(metric_name)
    if requested in {"grouped_bar", "stacked_bar", "bar"}:
        chosen = "grouped_bar" if requested in {"grouped_bar", "bar"} else "stacked_bar"
        return chosen, build_chart_payload(chosen, rows, metric_name, dimensions), warnings
    if requested in {"pie", "donut", "horizontal_bar", "line", "area", "stacked_area"}:
        warnings.append("chart_type_transform_rejected:requested_shape_incompatible_with_multi_series_breakdown")
    return "grouped_bar", build_chart_payload("grouped_bar", rows, metric_name, dimensions), warnings
