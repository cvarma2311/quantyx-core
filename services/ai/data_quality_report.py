from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile
import re

from services.ai.config import Settings
from services.ai.connection_registry import resolve_database_credentials_cached
from services.ai.db import run_query
from services.ai.data_quality_anomalies import build_quality_anomaly_payload, summarize_data_quality_anomalies
from services.ai.data_quality_remediation import derive_data_quality_remediation_plan
from services.ai.data_quality_issues import build_quality_issue_payload, summarize_quality_issues
from services.ai.data_quality_rules import _build_date_range_predicate_parts
from services.ai.data_quality_stages import fetch_final_dataset_rows_tool, fetch_stage_snapshot_rows_tool, parse_lineage_id
from services.ai.data_quality_trends import build_business_term_trend_payload, build_readiness_trend_payload, summarize_trends
from services.ai.data_quality_store import (
    create_quality_report_metadata,
    get_quality_final_dataset_artifact,
    list_quality_duplicate_candidates,
    list_quality_enrichment_opportunities,
    list_quality_dataset_stages,
    list_quality_lineage_edges,
    list_quality_join_artifacts,
    list_quality_stage_row_outcomes,
    get_quality_run_by_run_id,
    get_quality_table_detail,
    list_quality_anomalies,
    list_quality_issues,
    list_quality_trends,
    list_quality_rules,
    list_quality_tables,
)
from services.ai.glossary import fetch_glossary_terms

EXCEL_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_ZIP_MIME_TYPE = "application/zip"
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
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            item_text = _stringify(item)
            if item_text:
                parts.append(f"{key}={item_text}")
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(item for item in (_stringify(item) for item in value) if item)
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


def build_csv_zip_bundle(sheets: list[tuple[str, list[list[Any]]]]) -> bytes:
    used_names: set[str] = set()
    named_sheets = [(_sheet_name(name, used_names), rows or [["No data"]]) for name, rows in sheets]
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for idx, (sheet_name, rows) in enumerate(named_sheets, start=1):
            csv_buffer = StringIO()
            writer = csv.writer(csv_buffer, lineterminator="\n")
            for row in rows:
                writer.writerow([_trim_cell(_cell_parts(value)[0]) for value in row])
            file_name = f"{idx:02d}_{_safe_file_part(sheet_name)}.csv"
            archive.writestr(file_name, csv_buffer.getvalue().encode("utf-8"))
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


def _fetch_table_rows_by_row_refs(
    settings: Settings,
    *,
    connection_id: str | None,
    schema_name: str,
    table_name: str,
    column_names: list[str],
    row_refs: list[str],
) -> list[dict[str, Any]]:
    connection_id = str(connection_id or "").strip()
    if not connection_id or not column_names or not row_refs:
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
             WHERE ctid::text = ANY(%s)
            """,
            [row_refs],
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


def _failed_rule_detail_sheets(
    settings: Settings,
    *,
    run_row: dict[str, Any],
    table_details: list[dict[str, Any]],
    failed_rules: list[dict[str, Any]],
) -> list[tuple[str, list[list[Any]]]]:
    connection_id = str(run_row.get("connection_id") or "").strip()
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    if not connection_id:
        return []
    table_detail_map = {
        str(detail.get("table_name") or "").strip(): detail
        for detail in table_details
        if str(detail.get("table_name") or "").strip()
    }
    sheets: list[tuple[str, list[list[Any]]]] = []
    for index, rule in enumerate(failed_rules, start=1):
        table_name = str(rule.get("table_name") or "").strip()
        if not table_name:
            continue
        detail = table_detail_map.get(table_name) or {}
        column_names = [
            str(row.get("column_name") or "").strip()
            for row in (detail.get("columns") or [])
            if str(row.get("column_name") or "").strip()
        ]
        if not column_names:
            continue
        sql, params = _build_rule_failure_row_ref_query(rule, schema_name)
        if not sql:
            continue
        scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)
        if not scoped_conn:
            continue
        try:
            failure_rows = run_query(
                settings,
                sql,
                params,
                scoped_conn=scoped_conn,
                statement_timeout_ms=120000,
            )
        except Exception:
            continue
        row_refs = [str(row.get("__row_ref") or "").strip() for row in failure_rows if str(row.get("__row_ref") or "").strip()]
        if not row_refs:
            continue
        source_rows = _fetch_table_rows_by_row_refs(
            settings,
            connection_id=connection_id,
            schema_name=schema_name,
            table_name=table_name,
            column_names=column_names,
            row_refs=row_refs,
        )
        if not source_rows:
            continue
        source_row_map = {str(row.get("__row_ref") or "").strip(): row for row in source_rows if str(row.get("__row_ref") or "").strip()}
        affected_columns = set(_rule_failure_column_map(rule))
        rule_label = str(rule.get("rule_label") or rule.get("rule_type") or "rule").strip() or "rule"
        sheet_rows: list[list[Any]] = [
            _header_row(["Rule Field", "Value"]),
            ["Rule ID", rule.get("rule_id")],
            ["Rule Label", rule_label],
            ["Rule Type", rule.get("rule_type")],
            ["Severity", rule.get("severity")],
            ["Table", table_name],
            ["Column", rule.get("column_name")],
            ["Reference Table", rule.get("reference_table")],
            ["Reference Column", rule.get("reference_column")],
            ["Violation Count", rule.get("violation_count")],
            ["Violation %", rule.get("violation_pct")],
            ["Source Text", rule.get("source_text")],
            ["Rule Detail", _flatten_mapping(rule.get("condition_json") or {})],
            [],
            _header_row(["Row Ref", *column_names]),
        ]
        for row_ref in row_refs:
            source_row = source_row_map.get(row_ref)
            if not source_row:
                continue
            sheet_rows.append(
                [
                    row_ref,
                    *[
                        _cell(source_row.get(column_name), STYLE_VALIDATION_FAILED)
                        if column_name in affected_columns
                        else source_row.get(column_name)
                        for column_name in column_names
                    ],
                ]
            )
        sheet_title = f"Rule {index:02d} {rule_label}"
        sheets.append((sheet_title, sheet_rows))
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


def _flatten_mapping(mapping: Any, *, item_sep: str = "; ", kv_sep: str = "=") -> str:
    if not isinstance(mapping, dict):
        return _stringify(mapping)
    parts: list[str] = []
    for key, value in mapping.items():
        text = _flatten_value(value)
        if text:
            parts.append(f"{key}{kv_sep}{text}")
    return item_sep.join(parts)


def _flatten_sequence(values: Any, *, item_sep: str = ", ") -> str:
    if not isinstance(values, list):
        return _stringify(values)
    parts = [text for text in (_flatten_value(item) for item in values) if text]
    return item_sep.join(parts)


def _flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return _flatten_mapping(value)
    if isinstance(value, list):
        return _flatten_sequence(value)
    return _stringify(value)


def _sample_rows_summary(rows: Any, *, max_rows: int = 3) -> str:
    if not isinstance(rows, list):
        return _flatten_value(rows)
    snippets: list[str] = []
    for row in rows[:max_rows]:
        snippets.append(_flatten_value(row))
    extra = max(0, len(rows) - max_rows)
    if extra:
        snippets.append(f"+{extra} more")
    return " | ".join(item for item in snippets if item)


def _table_summary_text(summary_json: dict[str, Any]) -> str:
    freshness = summary_json.get("freshness_analysis") or {}
    stability = summary_json.get("stability_analysis") or {}
    parts = [
        f"freshness_status={freshness.get('freshness_status')}" if freshness.get("freshness_status") else "",
        f"freshness_lag_days={freshness.get('freshness_lag_days')}" if freshness.get("freshness_lag_days") is not None else "",
        f"stability_status={stability.get('stability_status')}" if stability.get("stability_status") else "",
        f"row_count_change_pct={stability.get('row_count_change_pct')}" if stability.get("row_count_change_pct") is not None else "",
    ]
    return "; ".join(item for item in parts if item)


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


def _stage_snapshot_sheets(
    settings: Settings,
    *,
    run_row: dict[str, Any],
    dataset_stages: list[dict[str, Any]],
) -> list[tuple[str, list[list[Any]]]]:
    connection_id = str(run_row.get("connection_id") or "").strip()
    schema_name = str(run_row.get("schema_name") or "public").strip() or "public"
    if not connection_id:
        return []
    scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name)
    if not scoped_conn:
        return []
    sheets: list[tuple[str, list[list[Any]]]] = []
    for stage in dataset_stages:
        stage_type = str(stage.get("stage_type") or "").strip()
        if stage_type not in {"source_profile", "join_validation", "filter"}:
            continue
        snapshot_rows = fetch_stage_snapshot_rows_tool(
            settings,
            scoped_conn=scoped_conn,
            schema_name=schema_name,
            stage=stage,
            limit=1200,
            offset=0,
        )
        if not snapshot_rows:
            continue
        headers = list(snapshot_rows[0].keys())
        rows: list[list[Any]] = [
            _header_row(headers),
            *[[row.get(header) for header in headers] for row in snapshot_rows],
        ]
        sheets.append((f"Stage {stage.get('stage_seq')} {stage.get('stage_name')}", rows))
    return sheets


def _lineage_overview_rows(
    *,
    run_id: str,
    tenant_id: str,
    domain_id: str,
    dataset_stages: list[dict[str, Any]],
    final_dataset: dict[str, Any],
    lineage_edges: list[dict[str, Any]],
    row_outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stage_by_id = {str(row.get("stage_id") or ""): row for row in dataset_stages if str(row.get("stage_id") or "").strip()}
    final_stage_name = str(final_dataset.get("final_stage_name") or "").strip()
    lineage_ids: set[str] = set()
    lineage_ids.update(str(row.get("row_lineage_id") or "").strip() for row in lineage_edges)
    lineage_ids.update(str(row.get("row_lineage_id") or "").strip() for row in row_outcomes)
    lineage_ids.discard("")
    rows: list[dict[str, Any]] = []
    for row_lineage_id in sorted(lineage_ids):
        parsed = parse_lineage_id(row_lineage_id)
        source_table = None
        source_row_ref = None
        decoded_lineage = row_lineage_id
        if parsed:
            parts = parsed.get("parts") or []
            decoded_lineage = " -> ".join(str(part) for part in parts if str(part).strip()) or row_lineage_id
            if len(parts) >= 2:
                source_table = parts[0]
                source_row_ref = parts[1]
        edge_rows = [row for row in lineage_edges if str(row.get("row_lineage_id") or "") == row_lineage_id]
        outcome_rows = [row for row in row_outcomes if str(row.get("row_lineage_id") or "") == row_lineage_id]
        latest_stage_name = None
        latest_stage_seq = -1
        for row in edge_rows:
            for stage_id_key, stage_name_key in (("from_stage_id", "from_stage_name"), ("to_stage_id", "to_stage_name")):
                stage_id = str(row.get(stage_id_key) or "")
                if not stage_id:
                    continue
                stage = stage_by_id.get(stage_id) or {}
                stage_name = str(row.get(stage_name_key) or stage.get("stage_name") or "").strip()
                stage_seq = int(stage.get("stage_seq") or -1)
                if stage_seq >= latest_stage_seq:
                    latest_stage_seq = stage_seq
                    latest_stage_name = stage_name or latest_stage_name
        for row in outcome_rows:
            stage_id = str(row.get("stage_id") or "")
            stage = stage_by_id.get(stage_id) or {}
            stage_name = str(row.get("stage_name") or stage.get("stage_name") or "").strip()
            stage_seq = int(stage.get("stage_seq") or -1)
            if stage_seq >= latest_stage_seq:
                latest_stage_seq = stage_seq
                latest_stage_name = stage_name or latest_stage_name
        final_dataset_member = bool(final_stage_name and latest_stage_name == final_stage_name)
        reason_codes = [str(row.get("reason_code") or "").strip() for row in outcome_rows if str(row.get("reason_code") or "").strip()]
        if final_dataset_member:
            final_state = "final_dataset_member"
        elif reason_codes:
            final_state = reason_codes[-1]
        elif edge_rows:
            final_state = str(edge_rows[-1].get("edge_type") or "transition")
        else:
            final_state = "tracked"
        rows.append(
            {
                "row_lineage_id": row_lineage_id,
                "source_table": source_table,
                "source_row_ref": source_row_ref,
                "decoded_lineage": decoded_lineage,
                "transition_count": len(edge_rows),
                "rejected_count": sum(1 for row in outcome_rows if str(row.get("outcome_type") or "").strip() == "rejected"),
                "join_exception_count": sum(1 for row in outcome_rows if str(row.get("outcome_type") or "").strip() == "join_exception"),
                "latest_stage_name": latest_stage_name,
                "final_state": final_state,
                "final_dataset_member": final_dataset_member,
                "evidence_path": f"/data-quality/lineage/{row_lineage_id}?tenant_id={tenant_id}&domain_id={domain_id}&run_id={run_id}",
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            0 if row.get("final_dataset_member") else 1,
            -(int(row.get("rejected_count") or 0) + int(row.get("join_exception_count") or 0)),
            -(int(row.get("transition_count") or 0)),
            str(row.get("source_table") or ""),
            str(row.get("source_row_ref") or ""),
        ),
    )


def _build_data_quality_report_sheet_bundle(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
) -> tuple[list[tuple[str, list[list[Any]]]], dict[str, Any]]:
    run = get_quality_run_by_run_id(settings, run_id)
    if not run:
        raise ValueError("Data quality run not found")
    if str(run.get("tenant_id")) != str(tenant_id) or str(run.get("domain_id")) != str(domain_id):
        raise ValueError("Data quality run does not match tenant/domain")

    tables = list_quality_tables(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    rules = list_quality_rules(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    duplicates = list_quality_duplicate_candidates(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    dataset_stages = list_quality_dataset_stages(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    join_artifacts = list_quality_join_artifacts(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    lineage_edges = list_quality_lineage_edges(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=4000)
    stage_row_outcomes = list_quality_stage_row_outcomes(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=4000)
    final_dataset = get_quality_final_dataset_artifact(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id) or {}
    opportunities = list_quality_enrichment_opportunities(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    trends = list_quality_trends(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=4000)
    try:
        glossary_terms = fetch_glossary_terms(settings, tenant_id, domain_id)
    except Exception:
        glossary_terms = []
    business_term_trends = build_business_term_trend_payload(
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
        trends=trends,
        glossary_terms=glossary_terms,
    )
    anomalies = list_quality_anomalies(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    issues = list_quality_issues(settings, tenant_id=tenant_id, domain_id=domain_id, run_id=run_id, limit=1200)
    staged_artifacts = _list_staged_overlay_artifacts(settings, run_id)
    published_sheets = _published_enrichment_sheets(settings, run_row=run, staged_artifacts=staged_artifacts)
    stage_snapshot_sheets = _stage_snapshot_sheets(settings, run_row=run, dataset_stages=dataset_stages)
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
    failed_rule_detail_sheets = _failed_rule_detail_sheets(
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
        dataset_stages=dataset_stages,
        row_outcomes=stage_row_outcomes,
        trends=trends,
        limit=50,
    )
    trend_summary = summarize_trends(trends)
    anomaly_summary = summarize_data_quality_anomalies(anomalies)
    anomaly_rows = [build_quality_anomaly_payload(row) for row in anomalies]
    issue_summary = summarize_quality_issues(issues)
    issue_rows = [build_quality_issue_payload(row) for row in issues]
    readiness_summary = build_readiness_trend_payload(
        run_id=run_id,
        baseline_run_id=str(run.get("baseline_run_id") or (run.get("summary_json") or {}).get("baseline_run_id") or "").strip() or None,
        final_dataset=final_dataset,
        trends=trends,
        issues=issues,
        anomalies=anomalies,
    )
    steward_queue_rows = [
        row for row in issue_rows if str(row.get("status") or "").strip().lower() in {"open", "in_progress", "deferred"}
    ]
    steward_queue_rows.sort(
        key=lambda row: (
            0 if row.get("overdue") else 1,
            0 if str(row.get("severity") or "") == "critical" else 1 if str(row.get("severity") or "") == "high" else 2,
            -(int(row.get("age_days") or 0)),
            str(row.get("owner_id") or ""),
        )
    )
    overdue_issue_rows = [row for row in steward_queue_rows if row.get("overdue")]
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
    rejected_records = [row for row in stage_row_outcomes if str(row.get("outcome_type") or "").strip() == "rejected"]
    join_exceptions = [row for row in stage_row_outcomes if str(row.get("outcome_type") or "").strip() == "join_exception"]
    filter_rejections = [row for row in rejected_records if str(row.get("reason_code") or "").strip() == "filter_rejected"]
    connection_id = str(run.get("connection_id") or "").strip()
    schema_name = str(run.get("schema_name") or "public").strip() or "public"
    scoped_conn = resolve_database_credentials_cached(settings, connection_id, schema_name) if connection_id else None
    final_dataset_rows, final_dataset_basis_stage = fetch_final_dataset_rows_tool(
        settings,
        scoped_conn=scoped_conn,
        schema_name=schema_name,
        stages=dataset_stages,
        final_dataset=final_dataset,
        limit=1200,
        offset=0,
    )

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
        "dataset_stage_count": len(dataset_stages),
        "join_artifact_count": len(join_artifacts),
        "lineage_edge_count": len(lineage_edges),
        "rejected_record_count": len(rejected_records),
        "filter_rejection_count": len(filter_rejections),
        "join_exception_count": len(join_exceptions),
        "final_dataset_row_count": final_dataset.get("final_row_count"),
        "final_dataset_readiness_status": final_dataset.get("readiness_status"),
        "stale_table_count": len([row for row in freshness_rows if row.get("freshness_status") == "stale"]),
        "stability_issue_count": len([row for row in freshness_rows if row.get("stability_status") == "changed"]),
        "overall_trust_score": run.get("overall_trust_score"),
        "staged_overlay_artifact_count": len(staged_artifacts),
        "approved_enrichment_row_count": len(approved_overlay_rows),
        "deferred_enrichment_row_count": len(deferred_overlay_rows),
        "published_enrichment_sheet_count": len(published_sheets),
        "stage_snapshot_sheet_count": len(stage_snapshot_sheets),
        "all_data_sheet_count": len(all_data_sheets),
        "failed_rule_detail_sheet_count": len(failed_rule_detail_sheets),
        "trend_row_count": trend_summary.get("trend_row_count", 0),
        "improved_metric_count": trend_summary.get("improved_metric_count", 0),
        "worsened_metric_count": trend_summary.get("worsened_metric_count", 0),
        "business_term_group_count": (business_term_trends.get("summary") or {}).get("business_term_group_count", 0),
        "worsened_business_term_count": (business_term_trends.get("summary") or {}).get("worsened_business_term_count", 0),
        "anomaly_count": anomaly_summary.get("anomaly_count", 0),
        "critical_anomaly_count": anomaly_summary.get("critical_anomaly_count", 0),
        "certification_blocker_count": readiness_summary.get("certification_blocker_count", 0),
        "readiness_trend_status": readiness_summary.get("readiness_trend_status"),
        "remediation_action_count": (remediation_plan.get("summary") or {}).get("action_count", 0),
        "critical_remediation_action_count": (remediation_plan.get("summary") or {}).get("critical_action_count", 0),
        "issue_count": issue_summary.get("issue_count", 0),
        "open_issue_count": issue_summary.get("open_issue_count", 0),
        "overdue_issue_count": issue_summary.get("overdue_issue_count", 0),
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
                ["Dataset Stages", len(dataset_stages)],
                ["Join Artifacts", len(join_artifacts)],
                ["Lineage Edges", len(lineage_edges)],
                ["Rejected Records", len(rejected_records)],
                ["Filter Rejections", len(filter_rejections)],
                ["Join Exceptions", len(join_exceptions)],
                ["Final Dataset Rows", final_dataset.get("final_row_count")],
                ["Final Dataset Readiness", final_dataset.get("readiness_status")],
                ["Readiness Trend", readiness_summary.get("readiness_trend_status")],
                ["Certification Blockers", readiness_summary.get("certification_blocker_count", 0)],
                ["Stale Tables", len([row for row in freshness_rows if row.get("freshness_status") == "stale"])],
                ["Stability Issues", len([row for row in freshness_rows if row.get("stability_status") == "changed"])],
                ["Staged Overlay Artifacts", len(staged_artifacts)],
                ["Approved Enrichment Rows", len(approved_overlay_rows)],
                ["Deferred Enrichment Rows", len(deferred_overlay_rows)],
                ["Published Enrichment Sheets", len(published_sheets)],
                ["Stage Snapshot Sheets", len(stage_snapshot_sheets)],
                ["All Data Sheets", len(all_data_sheets)],
                ["Failed Rule Detail Sheets", len(failed_rule_detail_sheets)],
                ["Trend Rows", trend_summary.get("trend_row_count", 0)],
                ["Improved Metrics", trend_summary.get("improved_metric_count", 0)],
                ["Worsened Metrics", trend_summary.get("worsened_metric_count", 0)],
                ["Business Term Groups", (business_term_trends.get("summary") or {}).get("business_term_group_count", 0)],
                ["Worsened Business Terms", (business_term_trends.get("summary") or {}).get("worsened_business_term_count", 0)],
                ["Anomalies", anomaly_summary.get("anomaly_count", 0)],
                ["Critical Anomalies", anomaly_summary.get("critical_anomaly_count", 0)],
                ["Open Issues", issue_summary.get("open_issue_count", 0)],
                ["Overdue Issues", issue_summary.get("overdue_issue_count", 0)],
                ["Recommended Actions", (remediation_plan.get("summary") or {}).get("action_count", 0)],
                ["Critical Recommended Actions", (remediation_plan.get("summary") or {}).get("critical_action_count", 0)],
                ["Workflow Status", (run.get("summary_json") or {}).get("workflow_status") or run.get("status")],
            ],
        ),
        (
            "Certification Summary",
            [
                _header_row(["Metric", "Value"]),
                ["Current Readiness Status", readiness_summary.get("current_readiness_status")],
                ["Previous Readiness Status", readiness_summary.get("previous_readiness_status")],
                ["Readiness Trend Status", readiness_summary.get("readiness_trend_status")],
                ["Baseline Run ID", readiness_summary.get("baseline_run_id")],
                ["Certification Blocker Count", readiness_summary.get("certification_blocker_count", 0)],
                ["Open Issue Count", readiness_summary.get("open_issue_count", 0)],
                ["Residual Anomaly Count", readiness_summary.get("residual_anomaly_count", 0)],
                ["Critical Anomaly Count", readiness_summary.get("critical_anomaly_count", 0)],
            ],
        ),
        (
            "Publish Readiness",
            [
                _header_row(["Field", "Value", "Note"]),
                ["Current Readiness", readiness_summary.get("current_readiness_status"), f"baseline: {readiness_summary.get('previous_readiness_status') or 'n/a'}"],
                ["Readiness Trend", readiness_summary.get("readiness_trend_status"), f"baseline run: {readiness_summary.get('baseline_run_id') or 'n/a'}"],
                ["Current Final Rows", readiness_summary.get("current_final_row_count"), None],
                ["Previous Final Rows", readiness_summary.get("previous_final_row_count"), None],
                ["Final Row Delta", readiness_summary.get("final_row_count_delta"), readiness_summary.get("final_row_count_delta_pct")],
                ["Certification Blockers", readiness_summary.get("certification_blocker_count", 0), _flatten_sequence(readiness_summary.get("blocker_titles") or [])],
                ["Residual Anomalies", readiness_summary.get("residual_anomaly_count", 0), f"{readiness_summary.get('critical_anomaly_count', 0)} critical"],
            ],
        ),
        (
            "Quality Trends",
            [
                _header_row([
                    "Object Type",
                    "Object Key",
                    "Object Name",
                    "Metric",
                    "Previous Value",
                    "Current Value",
                    "Delta",
                    "Delta %",
                    "Trend Status",
                    "Directionality",
                ]),
                *[
                    [
                        row.get("object_type"),
                        row.get("object_key"),
                        row.get("object_name"),
                        row.get("metric_name"),
                        row.get("previous_value_num") if row.get("previous_value_num") is not None else row.get("previous_value_text"),
                        row.get("current_value_num") if row.get("current_value_num") is not None else row.get("current_value_text"),
                        row.get("delta_value"),
                        row.get("delta_pct"),
                        row.get("trend_status"),
                        row.get("directionality"),
                    ]
                    for row in trends
                ],
            ],
        ),
        (
            "Business Term Trends",
            [
                _header_row([
                    "Business Term",
                    "Definition",
                    "Trend Rows",
                    "Worsened",
                    "Improved",
                    "Affected Objects",
                    "Top Metrics",
                    "Evidence Path",
                ]),
                *[
                    [
                        row.get("business_term"),
                        row.get("definition"),
                        row.get("trend_row_count"),
                        row.get("worsened_metric_count"),
                        row.get("improved_metric_count"),
                        row.get("affected_objects"),
                        row.get("top_metrics"),
                        row.get("evidence_path"),
                    ]
                    for row in (business_term_trends.get("rows") or [])
                ],
            ],
        ),
        (
            "Rule Trends",
            [
                _header_row([
                    "Rule Key",
                    "Rule Name",
                    "Metric",
                    "Previous Value",
                    "Current Value",
                    "Delta",
                    "Delta %",
                    "Trend Status",
                ]),
                *[
                    [
                        row.get("object_key"),
                        row.get("object_name"),
                        row.get("metric_name"),
                        row.get("previous_value_num") if row.get("previous_value_num") is not None else row.get("previous_value_text"),
                        row.get("current_value_num") if row.get("current_value_num") is not None else row.get("current_value_text"),
                        row.get("delta_value"),
                        row.get("delta_pct"),
                        row.get("trend_status"),
                    ]
                    for row in trends
                    if str(row.get("object_type") or "") == "rule"
                ],
            ],
        ),
        (
            "Stage Trends",
            [
                _header_row([
                    "Stage Key",
                    "Stage Name",
                    "Metric",
                    "Previous Value",
                    "Current Value",
                    "Delta",
                    "Delta %",
                    "Trend Status",
                ]),
                *[
                    [
                        row.get("object_key"),
                        row.get("object_name"),
                        row.get("metric_name"),
                        row.get("previous_value_num") if row.get("previous_value_num") is not None else row.get("previous_value_text"),
                        row.get("current_value_num") if row.get("current_value_num") is not None else row.get("current_value_text"),
                        row.get("delta_value"),
                        row.get("delta_pct"),
                        row.get("trend_status"),
                    ]
                    for row in trends
                    if str(row.get("object_type") or "") == "stage"
                ],
            ],
        ),
        (
            "Final Dataset Trends",
            [
                _header_row([
                    "Metric",
                    "Previous Value",
                    "Current Value",
                    "Delta",
                    "Delta %",
                    "Trend Status",
                ]),
                *[
                    [
                        row.get("metric_name"),
                        row.get("previous_value_num") if row.get("previous_value_num") is not None else row.get("previous_value_text"),
                        row.get("current_value_num") if row.get("current_value_num") is not None else row.get("current_value_text"),
                        row.get("delta_value"),
                        row.get("delta_pct"),
                        row.get("trend_status"),
                    ]
                    for row in trends
                    if str(row.get("object_type") or "") == "final_dataset"
                ],
            ],
        ),
        (
            "Anomaly Summary",
            [
                _header_row(["Metric", "Value"]),
                ["Anomaly Count", anomaly_summary.get("anomaly_count", 0)],
                ["Critical Anomaly Count", anomaly_summary.get("critical_anomaly_count", 0)],
                ["High Anomaly Count", anomaly_summary.get("high_anomaly_count", 0)],
                ["Repeated Anomaly Count", anomaly_summary.get("repeated_anomaly_count", 0)],
            ],
        ),
        (
            "Anomalies",
            [
                _header_row([
                    "Anomaly ID",
                    "Anomaly Type",
                    "Title",
                    "Severity",
                    "Object Type",
                    "Object Key",
                    "Object Name",
                    "Baseline Run ID",
                    "Previous Value",
                    "Current Value",
                    "Delta",
                    "Delta %",
                    "Evidence Path",
                ]),
                *[
                    [
                        row.get("anomaly_id"),
                        row.get("anomaly_type"),
                        row.get("title"),
                        row.get("severity"),
                        row.get("object_type"),
                        row.get("object_key"),
                        row.get("object_name"),
                        row.get("baseline_run_id"),
                        row.get("previous_value_num") if row.get("previous_value_num") is not None else row.get("previous_value_text"),
                        row.get("current_value_num") if row.get("current_value_num") is not None else row.get("current_value_text"),
                        row.get("delta_value"),
                        row.get("delta_pct"),
                        row.get("evidence_path"),
                    ]
                    for row in anomaly_rows
                ],
            ],
        ),
        (
            "Issue Register",
            [
                _header_row([
                    "Issue ID",
                    "Issue Type",
                    "Title",
                    "Severity",
                    "Status",
                    "Owner",
                    "Age Days",
                    "Due At",
                    "Overdue",
                    "Table",
                    "Column",
                    "Stage ID",
                    "Recommendation",
                    "Evidence Path",
                ]),
                *[
                    [
                        row.get("issue_id"),
                        row.get("issue_type"),
                        row.get("title"),
                        row.get("severity"),
                        row.get("status"),
                        row.get("owner_id"),
                        row.get("age_days"),
                        row.get("due_at"),
                        row.get("overdue"),
                        row.get("table_name"),
                        row.get("column_name"),
                        row.get("stage_id"),
                        row.get("recommendation"),
                        row.get("evidence_path"),
                    ]
                    for row in issue_rows
                ],
            ],
        ),
        (
            "Steward Work Queue",
            [
                _header_row([
                    "Owner",
                    "Severity",
                    "Issue",
                    "Status",
                    "Age Days",
                    "Due At",
                    "Overdue",
                    "Evidence Path",
                ]),
                *[
                    [
                        row.get("owner_id"),
                        row.get("severity"),
                        row.get("title"),
                        row.get("status"),
                        row.get("age_days"),
                        row.get("due_at"),
                        row.get("overdue"),
                        row.get("evidence_path"),
                    ]
                    for row in steward_queue_rows
                ],
            ],
        ),
        (
            "SLA Breaches",
            [
                _header_row([
                    "Owner",
                    "Severity",
                    "Issue",
                    "Age Days",
                    "Due At",
                    "Evidence Path",
                ]),
                *[
                    [
                        row.get("owner_id"),
                        row.get("severity"),
                        row.get("title"),
                        row.get("age_days"),
                        row.get("due_at"),
                        row.get("evidence_path"),
                    ]
                    for row in overdue_issue_rows
                ],
            ],
        ),
        (
            "Stage Waterfall",
            [
                _header_row(["Stage Seq", "Stage Name", "Stage Type", "Input Rows", "Output Rows", "Rejected Rows", "Measurement Status", "Evidence Path", "Details"]),
                *[
                    [
                        row.get("stage_seq"),
                        row.get("stage_name"),
                        row.get("stage_type"),
                        row.get("input_row_count"),
                        row.get("output_row_count"),
                        row.get("rejected_row_count"),
                        (row.get("summary_json") or {}).get("measurement_status"),
                        (row.get("summary_json") or {}).get("evidence_path"),
                        _flatten_mapping(
                            {
                                "output_dataset": row.get("output_dataset"),
                                "input_tables": _flatten_sequence(row.get("input_tables") or []),
                                "measurement_error": (row.get("summary_json") or {}).get("measurement_error"),
                            }
                        ),
                    ]
                    for row in dataset_stages
                ],
            ],
        ),
        (
            "Join Health",
            [
                _header_row(["Join Name", "Left Table", "Right Table", "Join Type", "Matched Rows", "Unmatched Left", "Unmatched Right", "Duplicate Matches", "Evidence Path", "Source", "Sample Matches", "Sample Unmatched Left", "Sample Unmatched Right"]),
                *[
                    [
                        row.get("join_name"),
                        row.get("left_table"),
                        row.get("right_table"),
                        row.get("join_type"),
                        row.get("matched_row_count"),
                        row.get("unmatched_left_row_count"),
                        row.get("unmatched_right_row_count"),
                        row.get("duplicate_match_count"),
                        (row.get("summary_json") or {}).get("evidence_path"),
                        (row.get("summary_json") or {}).get("source"),
                        _sample_rows_summary((row.get("summary_json") or {}).get("sample_matches") or []),
                        _sample_rows_summary((row.get("summary_json") or {}).get("sample_unmatched_left_rows") or []),
                        _sample_rows_summary((row.get("summary_json") or {}).get("sample_unmatched_right_rows") or []),
                    ]
                    for row in join_artifacts
                ],
            ],
        ),
        (
            "Lineage Overview",
            [
                _header_row([
                    "Row Lineage ID",
                    "Source Table",
                    "Source Row Ref",
                    "Decoded Lineage",
                    "Transitions",
                    "Rejected",
                    "Join Exceptions",
                    "Latest Stage",
                    "Final State",
                    "Final Dataset Member",
                    "Evidence Path",
                ]),
                *[
                    [
                        row.get("row_lineage_id"),
                        row.get("source_table"),
                        row.get("source_row_ref"),
                        row.get("decoded_lineage"),
                        row.get("transition_count"),
                        row.get("rejected_count"),
                        row.get("join_exception_count"),
                        row.get("latest_stage_name"),
                        row.get("final_state"),
                        row.get("final_dataset_member"),
                        row.get("evidence_path"),
                    ]
                    for row in _lineage_overview_rows(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        domain_id=domain_id,
                        dataset_stages=dataset_stages,
                        final_dataset=final_dataset,
                        lineage_edges=lineage_edges,
                        row_outcomes=stage_row_outcomes,
                    )
                ],
            ],
        ),
        (
            "Filter Impact",
            [
                _header_row(["Stage Seq", "Stage Name", "Table", "Expression", "Input Rows", "Output Rows", "Rejected Rows", "Rejected %", "Evidence Path"]),
                *[
                    [
                        row.get("stage_seq"),
                        row.get("stage_name"),
                        row.get("output_dataset"),
                        ((row.get("expression") or {}).get("expression_text")),
                        row.get("input_row_count"),
                        row.get("output_row_count"),
                        row.get("rejected_row_count"),
                        (
                            round((float(row.get("rejected_row_count") or 0) / float(row.get("input_row_count") or 1)) * 100.0, 2)
                            if row.get("input_row_count") not in (None, 0) and row.get("rejected_row_count") is not None
                            else None
                        ),
                        (row.get("summary_json") or {}).get("evidence_path"),
                    ]
                    for row in dataset_stages
                    if str(row.get("stage_type") or "").strip() == "filter"
                ],
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
                    "Stability",
                    "Enrichment Readiness",
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
                        ((row.get("summary_json") or {}).get("trust_components") or {}).get("stability"),
                        ((row.get("summary_json") or {}).get("trust_components") or {}).get("enrichment_readiness"),
                        _flatten_mapping((row.get("summary_json") or {}).get("trust_component_explanations") or {}),
                    ]
                    for row in tables
                ],
            ],
        ),
        (
            "Table Quality",
            [
                _header_row(["Table", "Rows", "Trust Score", "Completeness", "Freshness", "Duplicate Risk", "Severity", "Table Summary"]),
                *[
                    [
                        row.get("table_name"),
                        row.get("row_count"),
                        row.get("trust_score"),
                        row.get("completeness_score"),
                        row.get("freshness_score"),
                        row.get("duplicate_risk_score"),
                        row.get("severity"),
                        _table_summary_text(row.get("summary_json") or {}),
                    ]
                    for row in tables
                ],
            ],
        ),
        (
            "Column Quality",
            [
                _header_row(["Table", "Column", "Type", "Null Count", "Null %", "Blank Count", "Blank %", "Distinct Count", "Distinct Ratio", "Completeness", "Trust Score", "Is Sparse", "Is Very Sparse", "Semantic Role"]),
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
                        (row.get("quality_flags_json") or {}).get("is_sparse"),
                        (row.get("quality_flags_json") or {}).get("is_very_sparse"),
                        (row.get("quality_flags_json") or {}).get("semantic_role"),
                    ]
                    for row in columns
                ],
            ],
        ),
        (
            "Validation Rules",
            [
                _header_row(["Rule ID", "Type", "Severity", "Table", "Column", "Reference Table", "Reference Column", "Rule Status", "Result Status", "Checked Rows", "Violations", "Violation %", "Error", "Source Text", "Rule Detail"]),
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
                        row.get("source_text"),
                        _flatten_mapping(row.get("condition_json") or {}),
                    ]
                    for row in rules
                ],
            ],
        ),
        (
            "Rule Violations",
            [
                _header_row(["Rule ID", "Type", "Table", "Column", "Violation Count", "Violation %", "Sample Evidence"]),
                *[
                    [
                        row.get("rule_id"),
                        row.get("rule_type"),
                        row.get("table_name"),
                        row.get("column_name"),
                        row.get("violation_count"),
                        row.get("violation_pct"),
                        _sample_rows_summary(row.get("sample_rows_json") or []),
                    ]
                    for row in failed_rules
                ],
            ],
        ),
        *failed_rule_detail_sheets,
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
                        _flatten_sequence(row.get("stability_issues") or []),
                    ]
                    for row in freshness_rows
                ],
            ],
        ),
        (
            "Duplicates",
            [
                _header_row(["Candidate ID", "Table", "Duplicate Type", "Match Columns", "Confidence", "Candidate Records", "Review Status", "Sample Evidence", "Duplicate Groups"]),
                *[
                    [
                        row.get("candidate_id"),
                        row.get("table_name"),
                        row.get("duplicate_type"),
                        _flatten_sequence(row.get("match_columns_json") or []),
                        row.get("confidence"),
                        row.get("candidate_record_count"),
                        row.get("review_status"),
                        _sample_rows_summary(row.get("sample_rows_json") or []),
                        (row.get("cluster_json") or {}).get("duplicate_group_count"),
                    ]
                    for row in duplicates
                ],
            ],
        ),
        (
            "Rejected Records",
            [
                _header_row(["Outcome ID", "Stage ID", "Stage Name", "Row Lineage ID", "Row Ref", "Source Table", "Source Key", "Reason Code", "Reason Detail", "Row Snapshot"]),
                *[
                    [
                        row.get("outcome_id"),
                        row.get("stage_id"),
                        row.get("stage_name"),
                        row.get("row_lineage_id"),
                        row.get("row_ref"),
                        row.get("source_table"),
                        _flatten_mapping(row.get("source_key_json") or {}),
                        row.get("reason_code"),
                        row.get("reason_detail"),
                        _flatten_mapping(row.get("row_data_json") or {}),
                    ]
                    for row in rejected_records
                ],
            ],
        ),
        (
            "Final Dataset",
            [
                _header_row(["Metric", "Value"]),
                ["Artifact ID", final_dataset.get("artifact_id")],
                ["Final Stage Name", final_dataset.get("final_stage_name")],
                ["Basis Stage Name", (final_dataset_basis_stage or {}).get("stage_name")],
                ["Final Row Count", final_dataset.get("final_row_count")],
                ["Total Rejected Row Count", final_dataset.get("total_rejected_row_count")],
                ["Readiness Status", final_dataset.get("readiness_status")],
                ["Measurement Status", (final_dataset.get("summary_json") or {}).get("measurement_status")],
                ["Lineage Enabled", (final_dataset.get("summary_json") or {}).get("lineage_enabled")],
                [],
                _header_row(list(final_dataset_rows[0].keys()) if final_dataset_rows else ["No Rows"]),
                *[
                    [row.get(header) for header in final_dataset_rows[0].keys()]
                    for row in final_dataset_rows
                ],
            ],
        ),
        (
            "Join Exceptions",
            [
                _header_row(["Outcome ID", "Stage ID", "Stage Name", "Row Lineage ID", "Row Ref", "Source Table", "Source Key", "Reason Code", "Reason Detail", "Row Snapshot"]),
                *[
                    [
                        row.get("outcome_id"),
                        row.get("stage_id"),
                        row.get("stage_name"),
                        row.get("row_lineage_id"),
                        row.get("row_ref"),
                        row.get("source_table"),
                        _flatten_mapping(row.get("source_key_json") or {}),
                        row.get("reason_code"),
                        row.get("reason_detail"),
                        _flatten_mapping(row.get("row_data_json") or {}),
                    ]
                    for row in join_exceptions
                ],
            ],
        ),
        *stage_snapshot_sheets,
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
                        _flatten_mapping(row.get("source_values") or {}),
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
                        _flatten_mapping(row.get("source_values") or {}),
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
    return sheets, summary


def build_data_quality_excel_report(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
) -> tuple[bytes, str, dict[str, Any]]:
    sheets, summary = _build_data_quality_report_sheet_bundle(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
    )
    workbook = build_xlsx_workbook(sheets)
    file_name = f"data_quality_{_safe_file_part(run_id)}.xlsx"
    report_id = create_quality_report_metadata(
        settings,
        quality_run_id=str(summary.get("quality_run_id") or ""),
        run_id=run_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        report_type="excel",
        file_name=file_name,
        mime_type=EXCEL_MIME_TYPE,
        summary_json=summary,
    )
    summary_with_report = dict(summary)
    if report_id:
        summary_with_report["report_id"] = report_id
    return workbook, file_name, summary_with_report


def build_data_quality_csv_report(
    settings: Settings,
    *,
    tenant_id: str,
    domain_id: str,
    run_id: str,
) -> tuple[bytes, str, dict[str, Any]]:
    sheets, summary = _build_data_quality_report_sheet_bundle(
        settings,
        tenant_id=tenant_id,
        domain_id=domain_id,
        run_id=run_id,
    )
    archive = build_csv_zip_bundle(sheets)
    file_name = f"data_quality_{_safe_file_part(run_id)}_csv_sheets.zip"
    report_id = create_quality_report_metadata(
        settings,
        quality_run_id=str(summary.get("quality_run_id") or ""),
        run_id=run_id,
        tenant_id=tenant_id,
        domain_id=domain_id,
        report_type="csv_zip",
        file_name=file_name,
        mime_type=CSV_ZIP_MIME_TYPE,
        summary_json=summary,
    )
    summary_with_report = dict(summary)
    if report_id:
        summary_with_report["report_id"] = report_id
    return archive, file_name, summary_with_report
