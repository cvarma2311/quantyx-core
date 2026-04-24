from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile
import json
import re

from services.ai.config import Settings
from services.ai.connection_registry import resolve_database_credentials_cached
from services.ai.db import run_query
from services.ai.data_quality_remediation import derive_data_quality_remediation_plan
from services.ai.data_quality_rules import _build_date_range_predicate_parts
from services.ai.data_quality_store import (
    create_quality_report_metadata,
    list_quality_duplicate_candidates,
    list_quality_enrichment_opportunities,
    get_quality_run_by_run_id,
    get_quality_table_detail,
    list_quality_rules,
    list_quality_tables,
)

EXCEL_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STYLE_DEFAULT = 0
STYLE_HEADER = 1
STYLE_ENRICH_APPROVED_DETERMINISTIC = 2
STYLE_ENRICH_APPROVED_LLM = 3
STYLE_ENRICH_DEFERRED = 4
STYLE_ENRICH_REJECTED = 5
STYLE_VALIDATION_FAILED = 6


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def _trim_cell(value: Any, limit: int = 32000) -> str:
    text = _stringify(value)
    if len(text) <= limit:
        return text
    return text[: limit - 15] + "... [truncated]"


def _safe_file_part(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return clean[:80] or "data_quality"


def _sheet_name(name: str, used: set[str]) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"
    candidate = clean
    suffix = 2
    while candidate.lower() in used:
        suffix_text = f" {suffix}"
        candidate = f"{clean[:31 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    used.add(candidate.lower())
    return candidate


def _col_name(index: int) -> str:
    name = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _cell(value: Any, style: int = STYLE_DEFAULT) -> dict[str, Any]:
    return {"value": value, "style": style}


def _cell_parts(value: Any) -> tuple[Any, int]:
    if isinstance(value, dict) and "value" in value:
        return value.get("value"), int(value.get("style") or STYLE_DEFAULT)
    return value, STYLE_DEFAULT


def _worksheet_xml(rows: list[list[Any]]) -> str:
    xml_rows: list[str] = []
    for row_idx, row in enumerate(rows, start=1):
        cells: list[str] = []
        for col_idx, value in enumerate(row, start=1):
            ref = f"{_col_name(col_idx)}{row_idx}"
            cell_value, style = _cell_parts(value)
            text = escape(_trim_cell(cell_value))
            style_attr = f' s="{style}"' if style else ""
            cells.append(f'<c r="{ref}"{style_attr} t="inlineStr"><is><t>{text}</t></is></c>')
        xml_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        "</worksheet>"
    )


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets>"
        "</workbook>"
    )


def _workbook_rels(sheet_count: int) -> str:
    rels = [
        f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        for idx in range(1, sheet_count + 1)
    ]
    rels.append(
        f'<Relationship Id="rId{sheet_count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(rels)}'
        "</Relationships>"
    )


def _content_types(sheet_count: int) -> str:
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for idx in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheets}"
        "</Types>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="7">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFD9E2F3"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFC6E0B4"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFBDD7EE"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFFE699"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF4CCCC"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFCE4D6"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="7">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="4" borderId="0" xfId="0" applyFill="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="5" borderId="0" xfId="0" applyFill="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="6" borderId="0" xfId="0" applyFill="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="7" borderId="0" xfId="0" applyFill="1"/>'
        '</cellXfs>'
        "</styleSheet>"
    )


def build_xlsx_workbook(sheets: list[tuple[str, list[list[Any]]]]) -> bytes:
    used_names: set[str] = set()
    named_sheets = [(_sheet_name(name, used_names), rows or [["No data"]]) for name, rows in sheets]
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(named_sheets)))
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/workbook.xml", _workbook_xml([name for name, _ in named_sheets]))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(named_sheets)))
        archive.writestr("xl/styles.xml", _styles_xml())
        for idx, (_, rows) in enumerate(named_sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{idx}.xml", _worksheet_xml(rows))
    return buffer.getvalue()


def _header_row(headers: list[Any]) -> list[dict[str, Any]]:
    return [_cell(item, STYLE_HEADER) for item in headers]


def _list_staged_overlay_artifacts(settings: Settings, run_id: str) -> list[dict[str, Any]]:
    try:
        return run_query(
            settings,
            """
            SELECT artifact_id, event_id, agent_name, stage_name, raw_json, created_at
              FROM public.quantyx_agent_event_artifacts
             WHERE run_id = %s
               AND agent_name = 'DataEnrichmentApplicationAgent'
               AND stage_name = 'staged_overlay'
             ORDER BY created_at DESC
            """,
            [run_id],
        )
    except Exception:
        return []


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _fetch_table_rows(
    settings: Settings,
    *,
    connection_id: str | None,
    schema_name: str,
    table_name: str,
    column_names: list[str],
) -> list[dict[str, Any]]:
    connection_id = str(connection_id or "").strip()
    if not connection_id or not column_names:
        return []
    scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)
    if not scoped_conn:
        return []
    select_columns = ['ctid::text AS "__row_ref"'] + [f"{_qident(col)} AS {_qident(col)}" for col in column_names]
    try:
        return run_query(
            settings,
            f"""
            SELECT {", ".join(select_columns)}
              FROM {_qident(schema_name)}.{_qident(table_name)}
            """,
            [],
            scoped_conn=scoped_conn,
            statement_timeout_ms=120000,
        )
    except Exception:
        return []


def _rule_failure_column_map(rule: dict[str, Any]) -> list[str]:
    rule_type = str(rule.get("rule_type") or "").strip().lower()
    condition = rule.get("condition_json") or {}
    if rule_type in {
        "not_null",
        "not_blank",
        "email_pattern",
        "numeric_min",
        "numeric_max",
        "allowed_values",
        "regex_pattern",
        "date_range",
        "numeric_range",
        "length",
        "null_pct_threshold",
        "unique",
    }:
        column = str(rule.get("column_name") or "").strip()
        return [column] if column else []
    if rule_type == "referential_integrity":
        column = str(rule.get("column_name") or "").strip()
        return [column] if column else []
    if rule_type == "conditional_required":
        required_column = str(condition.get("required_column") or "").strip()
        return [required_column] if required_column else []
    if rule_type == "cross_column_consistency":
        left_column = str(condition.get("left_column") or "").strip()
        right_column = str(condition.get("right_column") or "").strip()
        return [item for item in [left_column, right_column] if item]
    if rule_type == "composite_unique":
        return [str(item).strip() for item in (condition.get("columns") or []) if str(item).strip()]
    return []


def _build_rule_failure_row_ref_query(rule: dict[str, Any], schema_name: str) -> tuple[str | None, list[Any]]:
    rule_type = str(rule.get("rule_type") or "").strip().lower()
    table_name = str(rule.get("table_name") or "").strip()
    if not table_name:
        return None, []
    schema = _qident(schema_name or "public")
    table = _qident(table_name)
    col = _qident(rule.get("column_name"))
    condition = rule.get("condition_json") or {}
    params: list[Any] = []

    if rule_type == "referential_integrity":
        parent_table = _qident(rule.get("reference_table"))
        parent_col = _qident(rule.get("reference_column"))
        sql = f"""
        SELECT child.ctid::text AS __row_ref
          FROM {schema}.{table} child
          LEFT JOIN {schema}.{parent_table} parent
            ON child.{col} = parent.{parent_col}
         WHERE child.{col} IS NOT NULL
           AND parent.{parent_col} IS NULL
        """
        return sql, params
    if rule_type == "not_null":
        return f'SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NULL', params
    if rule_type == "not_blank":
        predicate = f"{col} IS NULL OR btrim({col}::text) = ''"
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {predicate}", params
    if rule_type == "email_pattern":
        pattern = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
        params = [pattern]
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col}::text !~ %s", params
    if rule_type == "numeric_min":
        params = [condition.get("min_value", 0)]
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col} < %s", params
    if rule_type == "numeric_max":
        params = [condition.get("max_value")]
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col} > %s", params
    if rule_type == "allowed_values":
        params = [[str(item) for item in (condition.get("allowed_values") or [])]]
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NOT NULL AND NOT ({col}::text = ANY(%s))", params
    if rule_type == "regex_pattern":
        params = [str(condition.get("pattern") or "").strip()]
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NOT NULL AND {col}::text !~ %s", params
    if rule_type == "date_range":
        predicates, notes = _build_date_range_predicate_parts(col, condition)
        if notes and not predicates:
            return None, []
        predicate = " OR ".join(f"({item})" for item in predicates) or "false"
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {predicate}", params
    if rule_type == "numeric_range":
        min_value = condition.get("min_value")
        max_value = condition.get("max_value")
        if min_value is None and max_value is None:
            return None, []
        clauses: list[str] = []
        if min_value is not None:
            clauses.append(f"{col} < %s")
            params.append(min_value)
        if max_value is not None:
            clauses.append(f"{col} > %s")
            params.append(max_value)
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NOT NULL AND ({' OR '.join(clauses)})", params
    if rule_type == "length":
        predicates: list[str] = []
        if condition.get("exact_length") is not None:
            predicates.append("length({col}::text) != %s")
            params.append(condition.get("exact_length"))
        if condition.get("min_length") is not None:
            predicates.append("length({col}::text) < %s")
            params.append(condition.get("min_length"))
        if condition.get("max_length") is not None:
            predicates.append("length({col}::text) > %s")
            params.append(condition.get("max_length"))
        if not predicates:
            return None, []
        predicate = " OR ".join(item.format(col=col) for item in predicates)
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NOT NULL AND ({predicate})", params
    if rule_type == "null_pct_threshold":
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {col} IS NULL", params
    if rule_type == "conditional_required":
        when_col = _qident(condition.get("when_column"))
        req_col = _qident(condition.get("required_column"))
        values = [str(item) for item in condition.get("when_values") or []]
        where_when = f"{when_col}::text = ANY(%s)"
        missing = f"{req_col} IS NULL OR btrim({req_col}::text) = ''"
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {where_when} AND ({missing})", [values]
    if rule_type == "cross_column_consistency":
        left = _qident(condition.get("left_column"))
        right = _qident(condition.get("right_column"))
        op = str(condition.get("operator") or "").strip()
        if not op:
            return None, []
        predicate = f"{left} IS NOT NULL AND {right} IS NOT NULL AND NOT ({left} {op} {right})"
        return f"SELECT ctid::text AS __row_ref FROM {schema}.{table} WHERE {predicate}", params
    if rule_type == "unique":
        sql = f"""
        SELECT ctid::text AS __row_ref
          FROM {schema}.{table}
         WHERE {col} IS NOT NULL
           AND {col} IN (
                SELECT {col}
                  FROM {schema}.{table}
                 WHERE {col} IS NOT NULL
                 GROUP BY {col}
                HAVING COUNT(*) > 1
           )
        """
        return sql, params
    if rule_type == "composite_unique":
        columns = [_qident(item) for item in (condition.get("columns") or []) if str(item).strip()]
        if len(columns) < 2:
            return None, []
        group_cols = ", ".join(columns)
        join_predicate = " AND ".join([f"src.{item} IS NOT DISTINCT FROM dupes.{item}" for item in columns])
        sql = f"""
        WITH dupes AS (
            SELECT {group_cols}
              FROM {schema}.{table}
             GROUP BY {group_cols}
            HAVING COUNT(*) > 1
        )
        SELECT src.ctid::text AS __row_ref
          FROM {schema}.{table} src
          JOIN dupes
            ON {join_predicate}
        """
        return sql, params
    return None, []


def _build_validation_failure_map(
    settings: Settings,
    *,
    connection_id: str | None,
    schema_name: str,
    rules: list[dict[str, Any]],
) -> dict[str, dict[str, set[str]]]:
    connection_id = str(connection_id or "").strip()
    if not connection_id:
        return {}
    scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)
    if not scoped_conn:
        return {}
    failure_map: dict[str, dict[str, set[str]]] = {}
    for rule in rules:
        if str(rule.get("result_status") or "").strip().lower() != "failed":
            continue
        table_name = str(rule.get("table_name") or "").strip()
        affected_columns = _rule_failure_column_map(rule)
        if not table_name or not affected_columns:
            continue
        sql, params = _build_rule_failure_row_ref_query(rule, schema_name)
        if not sql:
            continue
        try:
            rows = run_query(settings, sql, params, scoped_conn=scoped_conn, statement_timeout_ms=120000)
        except Exception:
            continue
        table_map = failure_map.setdefault(table_name, {})
        for row in rows:
            row_ref = str(row.get("__row_ref") or "").strip()
            if not row_ref:
                continue
            table_map.setdefault(row_ref, set()).update(affected_columns)
    return failure_map


def _all_data_sheets(
    settings: Settings,
    *,
    run_row: dict[str, Any],
    table_details: list[dict[str, Any]],
    failed_rules: list[dict[str, Any]],
) -> list[tuple[str, list[list[Any]]]]:
    connection_id = str(run_row.get("connection_id") or "").strip()
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    failure_map = _build_validation_failure_map(
        settings,
        connection_id=connection_id,
        schema_name=schema_name,
        rules=failed_rules,
    )
    sheets: list[tuple[str, list[list[Any]]]] = []
    for detail in table_details:
        table_name = str(detail.get("table_name") or "").strip()
        column_names = [str(row.get("column_name") or "").strip() for row in (detail.get("columns") or []) if str(row.get("column_name") or "").strip()]
        if not table_name or not column_names:
            continue
        source_rows = _fetch_table_rows(
            settings,
            connection_id=connection_id,
            schema_name=schema_name,
            table_name=table_name,
            column_names=column_names,
        )
        if not source_rows:
            continue
        rows: list[list[Any]] = [_header_row(["Row Ref", *column_names])]
        table_failures = failure_map.get(table_name, {})
        for source_row in source_rows:
            row_ref = str(source_row.get("__row_ref") or "").strip()
            failed_columns = table_failures.get(row_ref, set())
            rows.append(
                [
                    row_ref,
                    *[
                        _cell(source_row.get(column_name), STYLE_VALIDATION_FAILED)
                        if column_name in failed_columns
                        else source_row.get(column_name)
                        for column_name in column_names
                    ],
                ]
            )
        sheets.append((f"All Data {table_name}", rows))
    return sheets


def _fetch_overlay_source_rows(
    settings: Settings,
    *,
    connection_id: str | None,
    schema_name: str,
    table_name: str,
    target_column: str,
    source_columns: list[str],
    row_refs: list[str],
) -> dict[str, dict[str, Any]]:
    connection_id = str(connection_id or "").strip()
    if not connection_id or not row_refs:
        return {}
    scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)
    if not scoped_conn:
        return {}
    columns = []
    seen: set[str] = set()
    for column in [*source_columns, target_column]:
        col = str(column or "").strip()
        if not col or col in seen:
            continue
        seen.add(col)
        columns.append(col)
    select_columns = ['ctid::text AS "__row_ref"'] + [f"{_qident(col)} AS {_qident(col)}" for col in columns]
    try:
        rows = run_query(
            settings,
            f"""
            SELECT {", ".join(select_columns)}
              FROM {_qident(schema_name)}.{_qident(table_name)}
             WHERE ctid::text = ANY(%s)
            """,
            [row_refs],
            scoped_conn=scoped_conn,
            statement_timeout_ms=30000,
        )
    except Exception:
        return {}
    return {str(row.get("__row_ref")): row for row in rows if row.get("__row_ref")}


def _enrichment_style(method: str | None, bucket: str) -> int:
    if bucket == "deferred":
        return STYLE_ENRICH_DEFERRED
    if bucket == "rejected":
        return STYLE_ENRICH_REJECTED
    if str(method or "").strip().lower() == "deterministic_exact_match":
        return STYLE_ENRICH_APPROVED_DETERMINISTIC
    return STYLE_ENRICH_APPROVED_LLM


def _alias_display(physical_name: Any, alias_name: Any) -> str:
    physical = str(physical_name or "").strip()
    alias = str(alias_name or "").strip()
    if not alias or alias == physical:
        return alias or physical
    return f"{alias} ({physical})"


def _published_enrichment_sheets(
    settings: Settings,
    *,
    run_row: dict[str, Any],
    staged_artifacts: list[dict[str, Any]],
) -> list[tuple[str, list[list[Any]]]]:
    connection_id = str(run_row.get("connection_id") or "").strip()
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    grouped: dict[str, dict[str, Any]] = {}
    for artifact in staged_artifacts:
        raw = artifact.get("raw_json") or {}
        table_name = str(raw.get("table_name") or "").strip()
        target_column = str(raw.get("target_column") or "").strip()
        target_column_alias = str(raw.get("target_column_alias") or target_column).strip() or target_column
        approved_rows = [row for row in (raw.get("approved_rows") or []) if isinstance(row, dict)]
        if not table_name or not target_column or not approved_rows:
            continue
        source_columns = []
        source_column_alias_map: dict[str, str] = {}
        raw_source_aliases = raw.get("source_column_aliases") or []
        for row in approved_rows:
            row_aliases = row.get("source_column_aliases") or []
            for key in (row.get("source_values") or {}).keys():
                key_text = str(key or "").strip()
                if key_text and key_text not in source_columns:
                    source_columns.append(key_text)
                if key_text and key_text not in source_column_alias_map:
                    alias_idx = source_columns.index(key_text) if key_text in source_columns else -1
                    alias_value = None
                    if alias_idx >= 0 and alias_idx < len(row_aliases):
                        alias_value = row_aliases[alias_idx]
                    elif alias_idx >= 0 and alias_idx < len(raw_source_aliases):
                        alias_value = raw_source_aliases[alias_idx]
                    source_column_alias_map[key_text] = str(alias_value or key_text)
        entry = grouped.setdefault(
            table_name,
            {
                "target_column": target_column,
                "target_column_alias": target_column_alias,
                "source_columns": source_columns[:],
                "source_column_alias_map": dict(source_column_alias_map),
                "rows": [],
            },
        )
        if not entry.get("target_column_alias"):
            entry["target_column_alias"] = target_column_alias
        for column in source_columns:
            if column not in entry["source_columns"]:
                entry["source_columns"].append(column)
            entry["source_column_alias_map"].setdefault(column, source_column_alias_map.get(column, column))
        for row in approved_rows:
            row_copy = dict(row)
            row_copy["proposal_id"] = raw.get("proposal_id")
            row_copy["approval_scope"] = raw.get("approval_scope")
            entry["rows"].append(row_copy)

    sheets: list[tuple[str, list[list[Any]]]] = []
    for table_name, entry in grouped.items():
        target_column = str(entry.get("target_column") or "")
        target_column_alias = str(entry.get("target_column_alias") or target_column)
        source_columns = [str(col) for col in (entry.get("source_columns") or []) if str(col).strip()]
        source_column_alias_map = entry.get("source_column_alias_map") or {}
        approved_rows = [row for row in (entry.get("rows") or []) if isinstance(row, dict)]
        row_refs = [str(row.get("row_ref") or "").strip() for row in approved_rows if str(row.get("row_ref") or "").strip()]
        source_row_map = _fetch_overlay_source_rows(
            settings,
            connection_id=connection_id,
            schema_name=schema_name,
            table_name=table_name,
            target_column=target_column,
            source_columns=source_columns,
            row_refs=row_refs,
        )
        headers = [
            "Row Ref",
            *[_alias_display(column, source_column_alias_map.get(column)) for column in source_columns],
            f"Original {_alias_display(target_column, target_column_alias)}",
            f"Enriched {_alias_display(target_column, target_column_alias)}",
            "Confidence",
            "Method",
            "Proposal ID",
        ]
        rows: list[list[Any]] = [_header_row(headers)]
        for row in approved_rows:
            row_ref = str(row.get("row_ref") or "").strip()
            fetched = source_row_map.get(row_ref) or {}
            source_values = row.get("source_values") or {}
            method = row.get("method")
            style = _enrichment_style(method, "approved")
            rows.append(
                [
                    row_ref,
                    *[fetched.get(column, source_values.get(column)) for column in source_columns],
                    fetched.get(target_column),
                    _cell(row.get("proposed_value"), style),
                    row.get("confidence"),
                    row.get("method"),
                    row.get("proposal_id"),
                ]
            )
        sheets.append((f"Published {table_name}", rows))
    return sheets


def build_data_quality_excel_report(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
) -> tuple[bytes, str, dict[str, Any]]:
    run = get_quality_run_by_run_id(settings, run_id)
    if not run:
        raise ValueError("Data quality run not found")
    if str(run.get("tenant_id")) != str(tenant_id) or str(run.get("domain_id")) != str(domain_id):
        raise ValueError("Data quality run does not match tenant/domain")

    tables = list_quality_tables(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=500)
    rules = list_quality_rules(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=500)
    duplicates = list_quality_duplicate_candidates(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=500)
    opportunities = list_quality_enrichment_opportunities(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=500)
    staged_artifacts = _list_staged_overlay_artifacts(settings, run_id)
    published_sheets = _published_enrichment_sheets(settings, run_row=run, staged_artifacts=staged_artifacts)
    table_details = [
        detail
        for table in tables
        if (detail := get_quality_table_detail(settings, tenant_id=tenant_id, domain_id=domain_id, table_name=table.get("table_name"), run_id=run_id))
    ]
    columns = [column for detail in table_details for column in detail.get("columns") or []]
    failed_rules = [rule for rule in rules if rule.get("result_status") == "failed"]
    all_data_sheets = _all_data_sheets(
        settings,
        run_row=run,
        table_details=table_details,
        failed_rules=failed_rules,
    )
    remediation_plan = derive_data_quality_remediation_plan(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        tables=tables,
        table_details=table_details,
        rules=rules,
        duplicates=duplicates,
        opportunities=opportunities,
        limit=50,
    )
    freshness_rows = []
    for row in tables:
        summary_json = row.get("summary_json") or {}
        freshness = summary_json.get("freshness_analysis") or {}
        stability = summary_json.get("stability_analysis") or {}
        freshness_rows.append(
            {
                "table_name": row.get("table_name"),
                "freshness_column": freshness.get("freshness_column"),
                "latest_timestamp": freshness.get("latest_timestamp"),
                "freshness_lag_days": freshness.get("freshness_lag_days"),
                "freshness_status": freshness.get("freshness_status"),
                "row_count_change_pct": stability.get("row_count_change_pct"),
                "completeness_score_change": stability.get("completeness_score_change"),
                "stability_status": stability.get("stability_status"),
                "stability_issues": stability.get("stability_issues") or [],
            }
        )
    approved_overlay_rows = [
        row
        for artifact in staged_artifacts
        for row in ((artifact.get("raw_json") or {}).get("approved_rows") or [])
        if isinstance(row, dict)
    ]
    deferred_overlay_rows = [
        row
        for artifact in staged_artifacts
        for row in ((artifact.get("raw_json") or {}).get("deferred_rows") or [])
        if isinstance(row, dict)
    ]

    summary = {
        "run_id": run_id,
        "quality_run_id": run.get("quality_run_id"),
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "table_count": len(tables),
        "column_count": len(columns),
        "rule_count": len(rules),
        "failed_rule_count": len(failed_rules),
        "duplicate_candidate_count": len(duplicates),
        "stale_table_count": len([row for row in freshness_rows if row.get("freshness_status") == "stale"]),
        "stability_issue_count": len([row for row in freshness_rows if row.get("stability_status") == "changed"]),
        "overall_trust_score": run.get("overall_trust_score"),
        "staged_overlay_artifact_count": len(staged_artifacts),
        "approved_enrichment_row_count": len(approved_overlay_rows),
        "deferred_enrichment_row_count": len(deferred_overlay_rows),
        "published_enrichment_sheet_count": len(published_sheets),
        "all_data_sheet_count": len(all_data_sheets),
        "remediation_action_count": (remediation_plan.get("summary") or {}).get("action_count", 0),
        "critical_remediation_action_count": (remediation_plan.get("summary") or {}).get("critical_action_count", 0),
    }
    sheets = [
        (
            "Legend",
            [
                _header_row(["Category", "Meaning", "Color"]),
                ["Validation Failure", _cell("Cell failed one or more validation rules in the raw data export sheet.", STYLE_VALIDATION_FAILED), "light orange"],
                ["Enrichment Approved (Deterministic)", _cell("Approved deterministic enrichment value.", STYLE_ENRICH_APPROVED_DETERMINISTIC), "green"],
                ["Enrichment Approved (LLM)", _cell("Approved LLM-derived enrichment value.", STYLE_ENRICH_APPROVED_LLM), "blue"],
                ["Enrichment Deferred", _cell("Deferred enrichment proposal.", STYLE_ENRICH_DEFERRED), "yellow"],
                ["Enrichment Rejected", _cell("Rejected enrichment proposal.", STYLE_ENRICH_REJECTED), "red"],
            ],
        ),
        (
            "Executive Summary",
            [
                _header_row(["Metric", "Value"]),
                ["Run ID", run_id],
                ["Quality Run ID", run.get("quality_run_id")],
                ["Tenant", tenant_id],
                ["Domain", domain_id],
                ["Status", run.get("status")],
                ["Overall Trust Score", run.get("overall_trust_score")],
                ["Tables Profiled", len(tables)],
                ["Columns Profiled", len(columns)],
                ["Validation Rules", len(rules)],
                ["Failed Rules", len(failed_rules)],
                ["Duplicate Candidates", len(duplicates)],
                ["Stale Tables", len([row for row in freshness_rows if row.get("freshness_status") == "stale"])],
                ["Stability Issues", len([row for row in freshness_rows if row.get("stability_status") == "changed"])],
                ["Staged Overlay Artifacts", len(staged_artifacts)],
                ["Approved Enrichment Rows", len(approved_overlay_rows)],
                ["Deferred Enrichment Rows", len(deferred_overlay_rows)],
                ["Published Enrichment Sheets", len(published_sheets)],
                ["All Data Sheets", len(all_data_sheets)],
                ["Recommended Actions", (remediation_plan.get("summary") or {}).get("action_count", 0)],
                ["Critical Recommended Actions", (remediation_plan.get("summary") or {}).get("critical_action_count", 0)],
                ["Run Summary", run.get("summary_json") or {}],
            ],
        ),
        (
            "Trust Scorecard",
            [
                _header_row([
                    "Table",
                    "Trust Score",
                    "Completeness",
                    "Validity",
                    "Uniqueness",
                    "Referential Integrity",
                    "Freshness",
                    "Duplicate Risk",
                    "Severity",
                    "Trust Components",
                    "Explanations",
                ]),
                *[
                    [
                        row.get("table_name"),
                        row.get("trust_score"),
                        row.get("completeness_score"),
                        row.get("validity_score"),
                        row.get("uniqueness_score"),
                        row.get("referential_integrity_score"),
                        row.get("freshness_score"),
                        row.get("duplicate_risk_score"),
                        row.get("severity"),
                        (row.get("summary_json") or {}).get("trust_components") or {},
                        (row.get("summary_json") or {}).get("trust_component_explanations") or {},
                    ]
                    for row in tables
                ],
            ],
        ),
        (
            "Table Quality",
            [
                _header_row(["Table", "Rows", "Trust Score", "Completeness", "Freshness", "Duplicate Risk", "Severity", "Summary"]),
                *[
                    [
                        row.get("table_name"),
                        row.get("row_count"),
                        row.get("trust_score"),
                        row.get("completeness_score"),
                        row.get("freshness_score"),
                        row.get("duplicate_risk_score"),
                        row.get("severity"),
                        row.get("summary_json") or {},
                    ]
                    for row in tables
                ],
            ],
        ),
        (
            "Column Quality",
            [
                _header_row(["Table", "Column", "Type", "Null Count", "Null %", "Blank Count", "Blank %", "Distinct Count", "Distinct Ratio", "Completeness", "Trust Score", "Flags"]),
                *[
                    [
                        row.get("table_name"),
                        row.get("column_name"),
                        row.get("data_type"),
                        row.get("null_count"),
                        row.get("null_pct"),
                        row.get("blank_count"),
                        row.get("blank_pct"),
                        row.get("distinct_count"),
                        row.get("distinct_ratio"),
                        row.get("completeness_score"),
                        row.get("column_trust_score"),
                        row.get("quality_flags_json") or {},
                    ]
                    for row in columns
                ],
            ],
        ),
        (
            "Validation Rules",
            [
                _header_row(["Rule ID", "Type", "Severity", "Table", "Column", "Reference Table", "Reference Column", "Rule Status", "Result Status", "Checked Rows", "Violations", "Violation %", "Error", "Condition"]),
                *[
                    [
                        row.get("rule_id"),
                        row.get("rule_type"),
                        row.get("severity"),
                        row.get("table_name"),
                        row.get("column_name"),
                        row.get("reference_table"),
                        row.get("reference_column"),
                        row.get("status"),
                        row.get("result_status"),
                        row.get("checked_row_count"),
                        row.get("violation_count"),
                        row.get("violation_pct"),
                        row.get("error_message"),
                        row.get("condition_json") or {},
                    ]
                    for row in rules
                ],
            ],
        ),
        (
            "Rule Violations",
            [
                _header_row(["Rule ID", "Type", "Table", "Column", "Violation Count", "Violation %", "Sample Rows"]),
                *[
                    [
                        row.get("rule_id"),
                        row.get("rule_type"),
                        row.get("table_name"),
                        row.get("column_name"),
                        row.get("violation_count"),
                        row.get("violation_pct"),
                        row.get("sample_rows_json") or [],
                    ]
                    for row in failed_rules
                ],
            ],
        ),
        (
            "Freshness",
            [
                _header_row(["Table", "Freshness Column", "Latest Timestamp", "Lag Days", "Freshness Status", "Row Count Change %", "Completeness Change", "Stability Status", "Stability Issues"]),
                *[
                    [
                        row.get("table_name"),
                        row.get("freshness_column"),
                        row.get("latest_timestamp"),
                        row.get("freshness_lag_days"),
                        row.get("freshness_status"),
                        row.get("row_count_change_pct"),
                        row.get("completeness_score_change"),
                        row.get("stability_status"),
                        row.get("stability_issues") or [],
                    ]
                    for row in freshness_rows
                ],
            ],
        ),
        (
            "Duplicates",
            [
                _header_row(["Candidate ID", "Table", "Duplicate Type", "Match Columns", "Confidence", "Candidate Records", "Review Status", "Sample Rows", "Cluster"]),
                *[
                    [
                        row.get("candidate_id"),
                        row.get("table_name"),
                        row.get("duplicate_type"),
                        row.get("match_columns_json") or [],
                        row.get("confidence"),
                        row.get("candidate_record_count"),
                        row.get("review_status"),
                        row.get("sample_rows_json") or [],
                        row.get("cluster_json") or {},
                    ]
                    for row in duplicates
                ],
            ],
        ),
        (
            "Enrichment Summary",
            [
                _header_row(["Metric", "Value"]),
                ["Overlay Artifact Count", len(staged_artifacts)],
                ["Approved Rows", len(approved_overlay_rows)],
                ["Deferred Rows", len(deferred_overlay_rows)],
                ["Approved Deterministic", len([row for row in approved_overlay_rows if str(row.get("method") or "").strip().lower() == "deterministic_exact_match"])],
                ["Approved LLM", len([row for row in approved_overlay_rows if str(row.get("method") or "").strip().lower() != "deterministic_exact_match"])],
            ],
        ),
        (
            "Recommended Actions",
            [
                _header_row([
                    "Priority",
                    "Action Type",
                    "Title",
                    "Table",
                    "Column",
                    "Issue Summary",
                    "Recommended Action",
                    "Owner Hint",
                    "Evidence Type",
                    "Evidence Path",
                    "Trust Component",
                    "Metric Value",
                    "Metric Unit",
                ]),
                *[
                    [
                        row.get("priority"),
                        row.get("action_type"),
                        row.get("title"),
                        row.get("table_name"),
                        row.get("column_name"),
                        row.get("issue_summary"),
                        row.get("recommended_action"),
                        row.get("owner_hint"),
                        row.get("evidence_type"),
                        row.get("evidence_path"),
                        row.get("trust_component"),
                        row.get("metric_value"),
                        row.get("metric_unit"),
                    ]
                    for row in remediation_plan.get("actions") or []
                ],
            ],
        ),
        (
            "Staged Enrichment",
            [
                _header_row(["Bucket", "Artifact ID", "Proposal ID", "Table", "Target Column", "Target Alias", "Source Columns", "Source Aliases", "Row Ref", "Proposed Value", "Confidence", "Method", "Approval Scope", "Source Values"]),
                *[
                    [
                        _cell("approved", _enrichment_style(row.get("method"), "approved")),
                        artifact.get("artifact_id"),
                        (artifact.get("raw_json") or {}).get("proposal_id"),
                        (artifact.get("raw_json") or {}).get("table_name") or row.get("table_name"),
                        (artifact.get("raw_json") or {}).get("target_column") or row.get("target_column"),
                        (artifact.get("raw_json") or {}).get("target_column_alias") or row.get("target_column_alias") or row.get("target_column"),
                        list((row.get("source_values") or {}).keys()),
                        row.get("source_column_aliases") or (artifact.get("raw_json") or {}).get("source_column_aliases") or [],
                        row.get("row_ref"),
                        _cell(row.get("proposed_value"), _enrichment_style(row.get("method"), "approved")),
                        row.get("confidence"),
                        row.get("method"),
                        (artifact.get("raw_json") or {}).get("approval_scope"),
                        row.get("source_values") or {},
                    ]
                    for artifact in staged_artifacts
                    for row in ((artifact.get("raw_json") or {}).get("approved_rows") or [])
                    if isinstance(row, dict)
                ],
                *[
                    [
                        _cell("deferred", _enrichment_style(row.get("method"), "deferred")),
                        artifact.get("artifact_id"),
                        (artifact.get("raw_json") or {}).get("proposal_id"),
                        (artifact.get("raw_json") or {}).get("table_name") or row.get("table_name"),
                        (artifact.get("raw_json") or {}).get("target_column") or row.get("target_column"),
                        (artifact.get("raw_json") or {}).get("target_column_alias") or row.get("target_column_alias") or row.get("target_column"),
                        list((row.get("source_values") or {}).keys()),
                        row.get("source_column_aliases") or (artifact.get("raw_json") or {}).get("source_column_aliases") or [],
                        row.get("row_ref"),
                        _cell(row.get("proposed_value"), _enrichment_style(row.get("method"), "deferred")),
                        row.get("confidence"),
                        row.get("method"),
                        (artifact.get("raw_json") or {}).get("approval_scope"),
                        row.get("source_values") or {},
                    ]
                    for artifact in staged_artifacts
                    for row in ((artifact.get("raw_json") or {}).get("deferred_rows") or [])
                    if isinstance(row, dict)
                ],
            ],
        ),
        *all_data_sheets,
        *published_sheets,
    ]
    workbook = build_xlsx_workbook(sheets)
    file_name = f"data_quality_{_safe_file_part(run_id)}.xlsx"
    report_id = create_quality_report_metadata(
        settings,
        quality_run_id=str(run.get("quality_run_id")),
        run_id=run_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        report_type="excel",
        file_name=file_name,
        mime_type=EXCEL_MIME_TYPE,
        summary_json=summary,
    )
    if report_id:
        summary["report_id"] = report_id
    return workbook, file_name, summary
