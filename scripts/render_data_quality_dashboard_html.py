#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root {{
      --bg: #0f172a;
      --panel: #111827;
      --panel-2: #1f2937;
      --line: #334155;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --good: #10b981;
      --warn: #f59e0b;
      --bad: #ef4444;
      --accent: #38bdf8;
      --accent-2: #22c55e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #020617 0%, #0f172a 100%);
      color: var(--text);
    }}
    .page {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      display: grid;
      gap: 16px;
      padding: 24px;
      border: 1px solid var(--line);
      background: rgba(15, 23, 42, 0.88);
      border-radius: 8px;
      margin-bottom: 20px;
    }}
    .hero h1 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
    }}
    .hero .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border: 1px solid var(--line);
      background: rgba(31, 41, 55, 0.9);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 16px;
    }}
    .span-12 {{ grid-column: span 12; }}
    .span-8 {{ grid-column: span 8; }}
    .span-6 {{ grid-column: span 6; }}
    .span-4 {{ grid-column: span 4; }}
    .span-3 {{ grid-column: span 3; }}
    @media (max-width: 1100px) {{
      .span-8, .span-6, .span-4, .span-3 {{ grid-column: span 12; }}
    }}
    .panel {{
      border: 1px solid var(--line);
      background: rgba(17, 24, 39, 0.92);
      border-radius: 8px;
      padding: 16px;
      overflow: hidden;
    }}
    .panel h2, .panel h3 {{
      margin: 0 0 10px;
      font-size: 16px;
    }}
    .panel .sub {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    @media (max-width: 1100px) {{
      .metric-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 680px) {{
      .metric-grid {{ grid-template-columns: 1fr; }}
    }}
    .metric {{
      border: 1px solid var(--line);
      background: rgba(31, 41, 55, 0.88);
      border-radius: 8px;
      padding: 14px;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .metric .value {{
      font-size: 28px;
      font-weight: 700;
      line-height: 1;
    }}
    .metric .note {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
    }}
    .chart-wrap {{
      min-height: 280px;
    }}
    svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .table-wrap {{
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }}
    th, td {{
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      font-size: 13px;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #111827;
      z-index: 1;
      color: #cbd5e1;
      font-weight: 600;
    }}
    td {{
      color: #e2e8f0;
    }}
    .small {{
      color: var(--muted);
      font-size: 12px;
    }}
    .severity-critical, .priority-critical {{ color: var(--bad); font-weight: 700; }}
    .severity-warning, .priority-warning {{ color: var(--warn); font-weight: 700; }}
    .severity-info, .priority-info {{ color: var(--accent); font-weight: 700; }}
    .linkish {{
      color: #7dd3fc;
      word-break: break-all;
      text-decoration: none;
    }}
    .btn {{
      appearance: none;
      border: 1px solid #0ea5e9;
      background: rgba(14, 165, 233, 0.12);
      color: #bae6fd;
      padding: 6px 10px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      white-space: nowrap;
    }}
    .btn:hover {{
      background: rgba(14, 165, 233, 0.2);
    }}
    .chart-action {{
      cursor: pointer;
    }}
    .chart-action:hover rect,
    .chart-action:hover circle,
    .chart-action:hover path {{
      filter: brightness(1.12);
      stroke: #e0f2fe;
      stroke-width: 1;
    }}
    .chart-label-link {{
      fill: #7dd3fc;
      text-decoration: underline;
      cursor: pointer;
    }}
    .summary-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .summary-chip {{
      border: 1px solid var(--line);
      background: rgba(31, 41, 55, 0.75);
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      font-size: 12px;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
    }}
    .legend span {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .swatch {{
      width: 10px;
      height: 10px;
      border-radius: 2px;
      display: inline-block;
    }}
    .trust-layout {{
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 16px;
      align-items: start;
    }}
    @media (max-width: 980px) {{
      .trust-layout {{ grid-template-columns: 1fr; }}
    }}
    .trust-overview {{
      border: 1px solid var(--line);
      background: rgba(31, 41, 55, 0.75);
      border-radius: 8px;
      padding: 16px;
    }}
    .trust-overview .score {{
      font-size: 54px;
      font-weight: 800;
      line-height: 1;
      margin-bottom: 8px;
    }}
    .trust-components {{
      display: grid;
      gap: 10px;
    }}
    .trust-component {{
      border: 1px solid var(--line);
      background: rgba(31, 41, 55, 0.6);
      border-radius: 8px;
      padding: 12px;
    }}
    .trust-component-head {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
      font-size: 12px;
      color: #cbd5e1;
    }}
    .meter {{
      width: 100%;
      height: 10px;
      background: #0f172a;
      border-radius: 999px;
      overflow: hidden;
    }}
    .meter > span {{
      display: block;
      height: 100%;
      border-radius: 999px;
    }}
    .modal {{
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      background: rgba(2, 6, 23, 0.72);
      padding: 24px;
      z-index: 50;
    }}
    .modal.open {{
      display: flex;
    }}
    .modal-card {{
      width: min(1200px, 100%);
      max-height: 88vh;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #0f172a;
      box-shadow: 0 16px 60px rgba(0, 0, 0, 0.45);
    }}
    .modal-head {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 16px;
      border-bottom: 1px solid var(--line);
      background: #111827;
    }}
    .modal-body {{
      padding: 16px;
    }}
    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 16px;
    }}
    .detail-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(17, 24, 39, 0.92);
      padding: 14px;
    }}
    .detail-card h3 {{
      margin: 0 0 10px;
      font-size: 15px;
    }}
    .detail-card.span-12 {{ grid-column: span 12; }}
    .detail-card.span-8 {{ grid-column: span 8; }}
    .detail-card.span-6 {{ grid-column: span 6; }}
    .detail-card.span-4 {{ grid-column: span 4; }}
    @media (max-width: 980px) {{
      .detail-card.span-8, .detail-card.span-6, .detail-card.span-4 {{ grid-column: span 12; }}
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      padding: 14px;
      border: 1px solid var(--line);
      background: rgba(15, 23, 42, 0.88);
      border-radius: 8px;
      color: #cbd5e1;
      font-size: 12px;
      line-height: 1.45;
    }}
  </style>
</head>
<body>
  <div class="page" id="app"></div>
  <div class="modal" id="evidence-modal">
    <div class="modal-card">
      <div class="modal-head">
        <div>
          <div id="modal-title">Evidence</div>
          <div class="small" id="modal-subtitle"></div>
        </div>
        <button class="btn" id="modal-close" type="button">Close</button>
      </div>
      <div class="modal-body" id="modal-body"></div>
    </div>
  </div>
  <script>
    const dashboard = __DASHBOARD_JSON__;
    const API_BASE = "http://localhost:8787";

    function fmtNumber(value, digits = 0) {{
      if (value === null || value === undefined || value === "") return "—";
      const n = Number(value);
      if (Number.isNaN(n)) return String(value);
      return new Intl.NumberFormat("en-US", {{
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
      }}).format(n);
    }}

    function fmtPct(value, digits = 1) {{
      if (value === null || value === undefined || value === "") return "—";
      const n = Number(value);
      if (Number.isNaN(n)) return String(value);
      return `${{fmtNumber(n, digits)}}%`;
    }}

    function severityClass(value) {{
      const key = String(value || "").toLowerCase();
      return key ? `severity-${{key}} priority-${{key}}` : "";
    }}

    function createMetric(label, value, note) {{
      return `
        <div class="metric">
          <div class="label">${{label}}</div>
          <div class="value">${{value}}</div>
          <div class="note">${{note || ""}}</div>
        </div>
      `;
    }}

    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}

    function buildEvidenceButton(path) {{
      return `<button class="btn evidence-btn" type="button" data-path="${{escapeHtml(path)}}">View Evidence</button>`;
    }}

    function defaultEvidencePath(section, row) {{
      if (row && row.evidence_path) return row.evidence_path;
      const tableName = row && row.table_name ? encodeURIComponent(row.table_name) : null;
      if (section.chart_key === "data_trust_scorecard" && tableName) {{
        return `/data-quality/tables/${{tableName}}?tenant_id=${{encodeURIComponent(dashboard.tenant_id || "")}}&domain_id=${{encodeURIComponent(dashboard.domain_id || "")}}&run_id=${{encodeURIComponent(dashboard.run_id || "")}}`;
      }}
      if (section.chart_key === "freshness_and_stability" && row && row.table_name) {{
        return `/data-quality/evidence/freshness/${{tableName}}?tenant_id=${{encodeURIComponent(dashboard.tenant_id || "")}}&domain_id=${{encodeURIComponent(dashboard.domain_id || "")}}&run_id=${{encodeURIComponent(dashboard.run_id || "")}}`;
      }}
      return null;
    }}

    function tableHtml(columns, rows) {{
      const cols = (columns || []).map((c) => c.field);
      const labels = (columns || []).map((c) => c.label || c.field);
      const head = labels.map((label) => `<th>${{label}}</th>`).join("");
      const body = (rows || []).map((row) => {{
        const cells = cols.map((field) => {{
          const value = row[field];
          let display = value;
          if (field.endsWith("_pct")) display = fmtPct(value, 1);
          else if (typeof value === "number") display = Number.isInteger(value) ? fmtNumber(value, 0) : fmtNumber(value, 2);
          else if (field === "evidence_path" && value) display = buildEvidenceButton(value);
          else display = value ?? "—";
          const klass = field === "severity" || field === "priority" ? severityClass(value) : "";
          return `<td class="${{klass}}">${{display}}</td>`;
        }}).join("");
        return `<tr>${{cells}}</tr>`;
      }}).join("");
      return `<div class="table-wrap"><table><thead><tr>${{head}}</tr></thead><tbody>${{body}}</tbody></table></div>`;
    }}

    function horizontalBarChart(section, rows, labelField, valueField, color) {{
      const data = (rows || []).filter((row) => row && row[labelField] !== undefined && row[valueField] !== undefined);
      if (!data.length) return `<div class="small">No rows available.</div>`;
      const max = Math.max(...data.map((row) => Number(row[valueField]) || 0), 1);
      const leftPad = 180;
      const rowH = 36;
      const width = 960;
      const height = data.length * rowH + 24;
      const barMax = width - leftPad - 120;
      const bars = data.map((row, idx) => {{
        const y = 16 + idx * rowH;
        const label = String(row[labelField]);
        const value = Number(row[valueField]) || 0;
        const w = Math.max(2, (value / max) * barMax);
        const path = defaultEvidencePath(section, row);
        const attrs = path ? `class="chart-action evidence-chart" data-path="${{escapeHtml(path)}}" tabindex="0" role="button"` : "";
        const labelClass = path ? "chart-label-link evidence-chart" : "";
        const labelAttrs = path ? `data-path="${{escapeHtml(path)}}" tabindex="0" role="button"` : "";
        return `
          <text x="8" y="${{y + 15}}" class="${{labelClass}}" ${{labelAttrs}}>${{label}}</text>
          <g ${{attrs}}>
            <rect x="${{leftPad}}" y="${{y}}" width="${{barMax}}" height="18" fill="#1f2937" rx="4"></rect>
            <rect x="${{leftPad}}" y="${{y}}" width="${{w}}" height="18" fill="${{color}}" rx="4"></rect>
            <text x="${{leftPad + w + 8}}" y="${{y + 14}}" fill="#e5e7eb" font-size="12">${{fmtNumber(value, valueField.includes("score") ? 2 : 0)}}</text>
          </g>
        `;
      }}).join("");
      return `<svg viewBox="0 0 ${{width}} ${{height}}" aria-label="bar chart">${{bars}}</svg>`;
    }}

    function verticalBarChart(section, rows, labelField, valueField, color) {{
      const data = (rows || []).filter((row) => row && row[labelField] !== undefined && row[valueField] !== undefined).slice(0, 10);
      if (!data.length) return `<div class="small">No rows available.</div>`;
      const max = Math.max(...data.map((row) => Number(row[valueField]) || 0), 1);
      const width = 960;
      const height = 320;
      const left = 40;
      const baseY = 250;
      const usable = width - left - 20;
      const gap = 16;
      const barW = Math.max(28, (usable - gap * (data.length - 1)) / data.length);
      const bars = data.map((row, idx) => {{
        const x = left + idx * (barW + gap);
        const value = Number(row[valueField]) || 0;
        const h = (value / max) * 180;
        const y = baseY - h;
        const label = String(row[labelField]).slice(0, 14);
        const path = defaultEvidencePath(section, row);
        const attrs = path ? `class="chart-action evidence-chart" data-path="${{escapeHtml(path)}}" tabindex="0" role="button"` : "";
        const labelClass = path ? "chart-label-link evidence-chart" : "";
        const labelAttrs = path ? `data-path="${{escapeHtml(path)}}" tabindex="0" role="button"` : "";
        return `
          <g ${{attrs}}>
            <rect x="${{x}}" y="${{y}}" width="${{barW}}" height="${{h}}" fill="${{color}}" rx="4"></rect>
          </g>
          <text x="${{x + barW / 2}}" y="${{baseY + 18}}" text-anchor="middle" class="${{labelClass}}" ${{labelAttrs}} font-size="11">${{label}}</text>
          <text x="${{x + barW / 2}}" y="${{y - 8}}" text-anchor="middle" fill="#e5e7eb" font-size="11">${{fmtNumber(value, valueField.includes("pct") ? 1 : 0)}}</text>
        `;
      }}).join("");
      return `
        <svg viewBox="0 0 ${{width}} ${{height}}" aria-label="column chart">
          <line x1="${{left}}" y1="${{baseY}}" x2="${{width - 10}}" y2="${{baseY}}" stroke="#475569" />
          ${{bars}}
        </svg>
      `;
    }}

    function heatmapTable(rows) {{
      if (!(rows || []).length) return `<div class="small">No rows available.</div>`;
      const columns = [
        {{ field: "table_name", label: "Table" }},
        {{ field: "column_name", label: "Physical Column" }},
        {{ field: "column_alias", label: "Alias" }},
        {{ field: "null_pct", label: "Null %" }},
        {{ field: "completeness_score", label: "Completeness" }},
        {{ field: "evidence_path", label: "Evidence" }}
      ];
      const cols = columns.map((c) => c.field);
      const head = columns.map((c) => `<th>${{c.label}}</th>`).join("");
      const body = rows.map((row) => {{
        const cells = cols.map((field) => {{
          let value = row[field];
          let style = "";
          if (field === "null_pct") {{
            const pct = Number(value) || 0;
            const alpha = Math.min(0.9, 0.15 + pct / 25);
            style = `background: rgba(239, 68, 68, ${{alpha}});`;
            value = fmtPct(value, 1);
          }} else if (field === "completeness_score") {{
            const score = Number(value) || 0;
            const alpha = Math.min(0.9, 0.15 + score / 120);
            style = `background: rgba(16, 185, 129, ${{alpha}});`;
            value = fmtNumber(value, 1);
          }} else if (field === "evidence_path" && value) {{
            value = buildEvidenceButton(value);
          }}
          return `<td style="${{style}}">${{value ?? "—"}}</td>`;
        }}).join("");
        return `<tr>${{cells}}</tr>`;
      }}).join("");
      return `
        <div class="table-wrap"><table><thead><tr>${{head}}</tr></thead><tbody>${{body}}</tbody></table></div>
        <div class="legend">
          <span><i class="swatch" style="background: rgba(239, 68, 68, 0.65)"></i> higher null %</span>
          <span><i class="swatch" style="background: rgba(16, 185, 129, 0.65)"></i> higher completeness</span>
        </div>
      `;
    }}

    function trustColor(score) {{
      const n = Number(score) || 0;
      if (n >= 85) return "#10b981";
      if (n >= 70) return "#38bdf8";
      if (n >= 50) return "#f59e0b";
      return "#ef4444";
    }}

    function trustScorecard(section) {{
      const row = (section.rows || [])[0];
      if (!row) return `<div class="small">No trust rows available.</div>`;
      const tableEvidence = defaultEvidencePath(section, row);
      const components = [
        ["completeness_score", "Completeness"],
        ["validity_score", "Validity"],
        ["referential_integrity_score", "Referential Integrity"],
        ["freshness_score", "Freshness"],
        ["duplicate_risk_score", "Duplicate Risk"],
        ["trust_score", "Overall Trust"]
      ];
      const componentHtml = components.map(([field, label]) => {{
        const value = Number(row[field]) || 0;
        const color = trustColor(value);
        return `
          <div class="trust-component">
            <div class="trust-component-head">
              <span>${{label}}</span>
              <strong style="color:${{color}}">${{fmtNumber(value, 2)}}</strong>
            </div>
            <div class="meter"><span style="width:${{Math.max(0, Math.min(value, 100))}}%;background:${{color}}"></span></div>
          </div>
        `;
      }}).join("");
      return `
        <div class="trust-layout">
          <div class="trust-overview">
            <div class="small">Table</div>
            <h3 style="margin:4px 0 8px">${{row.table_name || "—"}}</h3>
            <div class="score" style="color:${{trustColor(row.trust_score)}}">${{fmtNumber(row.trust_score, 2)}}</div>
            <div class="small">Overall trust score across completeness, validity, referential integrity, freshness, and duplicate risk.</div>
            <div class="summary-row" style="margin-top:12px">
              <span class="summary-chip">Rows: ${{fmtNumber(row.row_count, 0)}}</span>
              <span class="summary-chip">Critical issues: ${{fmtNumber(section.summary?.critical_issue_count || 0, 0)}}</span>
              <span class="summary-chip">Warnings: ${{fmtNumber(section.summary?.warning_issue_count || 0, 0)}}</span>
              ${{
                tableEvidence
                  ? `<button class="btn evidence-btn" type="button" data-path="${{escapeHtml(tableEvidence)}}">Open Table Detail</button>`
                  : ""
              }}
            </div>
          </div>
          <div class="trust-components">${{componentHtml}}</div>
        </div>
      `;
    }}

    function componentMeters(components) {{
      const entries = Object.entries(components || {}).filter(([, value]) => value !== null && value !== undefined);
      if (!entries.length) return `<div class="small">No trust components available.</div>`;
      return `
        <div class="trust-components">
          ${{
            entries.map(([key, value]) => `
              <div class="trust-component">
                <div class="trust-component-head">
                  <span>${{escapeHtml(key.replaceAll("_", " "))}}</span>
                  <strong style="color:${{trustColor(value)}}">${{fmtNumber(value, 2)}}</strong>
                </div>
                <div class="meter"><span style="width:${{Math.max(0, Math.min(Number(value) || 0, 100))}}%;background:${{trustColor(value)}}"></span></div>
              </div>
            `).join("")
          }}
        </div>
      `;
    }}

    function sectionChart(section) {{
      const rows = section.rows || [];
      switch (section.chart_type) {{
        case "horizontal_bar":
          if (section.chart_key === "data_trust_scorecard") return trustScorecard(section);
          return horizontalBarChart(section, rows, section.y_field || "table_name", section.x_field || "trust_score", "#38bdf8");
        case "bar":
          if (section.chart_key === "duplicate_risk") return verticalBarChart(section, rows, "table_name", "duplicate_candidate_count", "#f59e0b");
          if (section.chart_key === "freshness_and_stability") return verticalBarChart(section, rows, "table_name", "freshness_lag_days", "#a78bfa");
          return verticalBarChart(section, rows, "table_name", "metric_value", "#22c55e");
        case "stacked_bar":
          if (section.chart_key === "validation_rule_failures") {{
            const labeledRows = rows.map((row) => ({{
              ...row,
              rule_label: `${{row.rule_type || "rule"}} · ${{row.column_alias || row.column_name || "column"}}`
            }}));
            return horizontalBarChart(section, labeledRows, "rule_label", "violation_count", "#ef4444");
          }}
          return verticalBarChart(section, rows, "table_name", "violation_count", "#ef4444");
        case "table_heatmap":
          return heatmapTable(rows);
        case "table":
        default:
          return tableHtml(section.display_columns || [], rows);
      }}
    }}

    function summaryCards() {{
      const sections = dashboard.chart_plan || [];
      const summaryView = dashboard.summary_view;
      if (summaryView && Array.isArray(summaryView.rows) && summaryView.rows.length) {{
        return `
          <div class="metric-grid">
            ${{
              summaryView.rows.map((row) => createMetric(
                row.label || row.metric_key || "Metric",
                row.metric_key && String(row.metric_key).includes("score")
                  ? fmtNumber(row.value, 2)
                  : (typeof row.value === "number" ? fmtNumber(row.value, 0) : (row.value ?? "—")),
                row.note || ""
              )).join("")
            }}
          </div>
        `;
      }}
      const executive = sections.find((item) => item.chart_key === "executive_summary");
      if (executive && Array.isArray(executive.rows) && executive.rows.length) {{
        return `
          <div class="metric-grid">
            ${{
              executive.rows.map((row) => createMetric(
                row.label || row.metric_key || "Metric",
                row.metric_key && String(row.metric_key).includes("score")
                  ? fmtNumber(row.value, 2)
                  : (typeof row.value === "number" ? fmtNumber(row.value, 0) : (row.value ?? "—")),
                row.note || ""
              )).join("")
            }}
          </div>
        `;
      }}
      const trust = sections.find((item) => item.chart_key === "data_trust_scorecard");
      const missing = sections.find((item) => item.chart_key === "missingness_heatmap");
      const rules = sections.find((item) => item.chart_key === "validation_rule_failures");
      const dupes = sections.find((item) => item.chart_key === "duplicate_risk");
      const actions = sections.find((item) => item.chart_key === "recommended_actions");
      const trustSummary = trust?.summary || {{}};
      const topMissing = (missing?.rows || []).reduce((best, row) => {{
        if (!best || Number(row.null_pct || 0) > Number(best.null_pct || 0)) return row;
        return best;
      }}, null);
      return `
        <div class="metric-grid">
          ${{createMetric("Quality Score", fmtNumber(dashboard.quality_score, 2), dashboard.quality_gate_passed ? "quality gate passed" : "quality gate failed")}}
          ${{createMetric("Critical Issues", fmtNumber(trustSummary.critical_issue_count || 0, 0), "from trust scorecard summary")}}
          ${{createMetric("Failed Rules", fmtNumber(rules?.summary?.failed_rule_count || 0, 0), "validation rules with violations")}}
          ${{createMetric("Top Missing Field", topMissing ? `${{topMissing.column_name}}` : "—", topMissing ? `${{fmtPct(topMissing.null_pct, 1)}} nulls` : "no missingness rows")}}
          ${{createMetric("Duplicate Candidates", fmtNumber((dupes?.rows || []).reduce((sum, row) => sum + (Number(row.duplicate_candidate_count) || 0), 0), 0), "across profiled tables")}}
          ${{createMetric("Recommended Actions", fmtNumber(actions?.summary?.action_count || 0, 0), `${{fmtNumber(actions?.summary?.critical_action_count || 0, 0)}} critical`)}}
          ${{createMetric("Run ID", dashboard.run_id || "—", dashboard.dashboard_id || "")}}
          ${{createMetric("Dashboard Type", dashboard.dashboard_type || "—", dashboard.status || "")}}
        </div>
      `;
    }}

    function objectTable(obj) {{
      const rows = Object.entries(obj || {{}})
        .map(([k, v]) => `<tr><th>${{escapeHtml(k)}}</th><td>${{typeof v === "object" ? `<pre>${{escapeHtml(JSON.stringify(v, null, 2))}}</pre>` : escapeHtml(v ?? "—")}}</td></tr>`)
        .join("");
      return `<div class="table-wrap"><table><tbody>${{rows}}</tbody></table></div>`;
    }}

    function renderDQTableDetail(data) {{
      const summary = data.summary || {{}};
      const columns = Array.isArray(data.columns) ? data.columns : [];
      const failedRules = Array.isArray(data.failed_rules) ? data.failed_rules : [];
      const duplicateCandidates = Array.isArray(data.duplicate_candidates) ? data.duplicate_candidates : [];
      const opportunities = Array.isArray(data.enrichment_opportunities) ? data.enrichment_opportunities : [];
      const explanations = data.trust_component_explanations || {{}};
      const topColumns = columns.slice(0, 12);
      const topFailedRules = failedRules.slice(0, 20);
      const topDuplicates = duplicateCandidates.slice(0, 20);
      const topOpportunities = opportunities.slice(0, 20);
      const summaryChips = [
        ["table", data.table_name],
        ["trust_score", data.trust_score],
        ["row_count", data.row_count],
        ["severity", data.severity],
        ["failed_rules", failedRules.length],
        ["duplicate_candidates", duplicateCandidates.length],
        ["enrichment_opportunities", opportunities.length]
      ]
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([key, value]) => `<span class="summary-chip">${{escapeHtml(key)}}: ${{typeof value === "number" ? fmtNumber(value, 2) : escapeHtml(String(value))}}</span>`)
        .join("");

      const columnCols = topColumns.length
        ? Object.keys(topColumns[0]).map((field) => ({{ field, label: field }}))
        : [];
      const failedRuleCols = topFailedRules.length
        ? Object.keys(topFailedRules[0]).map((field) => ({{ field, label: field }}))
        : [];
      const duplicateCols = topDuplicates.length
        ? Object.keys(topDuplicates[0]).map((field) => ({{ field, label: field }}))
        : [];
      const oppCols = topOpportunities.length
        ? Object.keys(topOpportunities[0]).map((field) => ({{ field, label: field }}))
        : [];

      return `
        <div class="detail-grid">
          <section class="detail-card span-12">
            <h3>Table Quality Overview</h3>
            <div class="summary-row">${{summaryChips}}</div>
            <div class="small">This endpoint combines persisted trust components, column profiling, failed rules, duplicate candidates, and enrichment opportunities for one table.</div>
          </section>
          <section class="detail-card span-4">
            <h3>Trust Components</h3>
            ${{componentMeters(data.components || {{}})}}
          </section>
          <section class="detail-card span-8">
            <h3>Summary</h3>
            ${{objectTable(summary)}}
          </section>
          <section class="detail-card span-12">
            <h3>Trust Component Explanations</h3>
            ${{
              Object.keys(explanations).length
                ? objectTable(explanations)
                : '<div class="small">No component explanations were returned.</div>'
            }}
          </section>
          <section class="detail-card span-12">
            <h3>Columns</h3>
            ${{
              topColumns.length
                ? tableHtml(columnCols, topColumns)
                : '<div class="small">No column artifacts were returned.</div>'
            }}
          </section>
          <section class="detail-card span-12">
            <h3>Failed Rules</h3>
            ${{
              topFailedRules.length
                ? tableHtml(failedRuleCols, topFailedRules)
                : '<div class="small">No failed rules were returned.</div>'
            }}
          </section>
          <section class="detail-card span-12">
            <h3>Duplicate Candidates</h3>
            ${{
              topDuplicates.length
                ? tableHtml(duplicateCols, topDuplicates)
                : '<div class="small">No duplicate candidates were returned.</div>'
            }}
          </section>
          <section class="detail-card span-12">
            <h3>Enrichment Opportunities</h3>
            ${{
              topOpportunities.length
                ? tableHtml(oppCols, topOpportunities)
                : '<div class="small">No enrichment opportunities were returned.</div>'
            }}
          </section>
        </div>
      `;
    }}

    function evidenceContent(data) {{
      if (Array.isArray(data)) {{
        if (!data.length) return `<div class="small">No rows returned.</div>`;
        if (typeof data[0] === "object" && data[0] !== null) {{
          const cols = Object.keys(data[0]).map((field) => ({{ field, label: field }}));
          return tableHtml(cols, data);
        }}
        return `<pre>${{escapeHtml(JSON.stringify(data, null, 2))}}</pre>`;
      }}
      if (data && typeof data === "object") {{
        if ("components" in data && "columns" in data && "failed_rules" in data) {{
          return renderDQTableDetail(data);
        }}
        for (const key of ["rows", "evidence_rows", "violations", "duplicate_rows", "approved_rows", "deferred_rows"]) {{
          if (Array.isArray(data[key])) {{
            const arr = data[key];
            if (!arr.length) continue;
            const cols = Object.keys(arr[0] || {{}}).map((field) => ({{ field, label: field }}));
            return `
              <div class="summary-row">
                ${{
                  Object.entries(data)
                    .filter(([k, v]) => !Array.isArray(v) && (typeof v !== "object" || v === null))
                    .slice(0, 8)
                    .map(([k, v]) => `<span class="summary-chip">${{escapeHtml(k)}}: ${{escapeHtml(typeof v === "string" ? v : JSON.stringify(v))}}</span>`)
                    .join("")
                }}
              </div>
              ${{tableHtml(cols, arr)}}
            `;
          }}
        }}
        return objectTable(data);
      }}
      return `<pre>${{escapeHtml(JSON.stringify(data, null, 2))}}</pre>`;
    }}

    async function openEvidence(path) {{
      const modal = document.getElementById("evidence-modal");
      const title = document.getElementById("modal-title");
      const subtitle = document.getElementById("modal-subtitle");
      const body = document.getElementById("modal-body");
      modal.classList.add("open");
      title.textContent = "Evidence";
      subtitle.textContent = path;
      body.innerHTML = `<div class="small">Loading evidence from localhost:8787...</div>`;
      try {{
        const response = await fetch(`${{API_BASE}}${{path}}`, {{
          headers: {{ "Accept": "application/json" }}
        }});
        const contentType = response.headers.get("content-type") || "";
        const payload = contentType.includes("application/json")
          ? await response.json()
          : await response.text();
        title.textContent = response.ok ? "Evidence Result" : `Evidence Error (${{response.status}})`;
        body.innerHTML = evidenceContent(payload);
      }} catch (error) {{
        body.innerHTML = `
          <div class="small">Failed to fetch evidence from localhost:8787.</div>
          <pre>${{escapeHtml(String(error && error.message ? error.message : error))}}</pre>
          <div class="small" style="margin-top:10px">If you open the HTML directly from disk, the browser may block local API calls unless CORS allows them.</div>
        `;
      }}
    }}

    function bindInteractions() {{
      document.querySelectorAll(".evidence-btn").forEach((button) => {{
        button.addEventListener("click", () => openEvidence(button.dataset.path));
      }});
      document.querySelectorAll(".evidence-chart").forEach((node) => {{
        const trigger = () => openEvidence(node.dataset.path);
        node.addEventListener("click", trigger);
        node.addEventListener("keydown", (event) => {{
          if (event.key === "Enter" || event.key === " ") {{
            event.preventDefault();
            trigger();
          }}
        }});
      }});
      const modal = document.getElementById("evidence-modal");
      document.getElementById("modal-close").addEventListener("click", () => modal.classList.remove("open"));
      modal.addEventListener("click", (event) => {{
        if (event.target === modal) modal.classList.remove("open");
      }});
    }}

    function sectionPanel(section) {{
      const summary = section.summary || {{}};
      const summaryChips = Object.entries(summary)
        .slice(0, 6)
        .map(([key, value]) => `<span class="summary-chip">${{escapeHtml(key)}}: ${{typeof value === "number" ? fmtNumber(value, 2) : escapeHtml(JSON.stringify(value))}}</span>`)
        .join("");
      return `
        <section class="panel span-12">
          <h2>${{section.title || section.chart_key || "Section"}}</h2>
          <p class="sub">${{section.chart_type || "section"}} | ${{section.data_source || "data source unknown"}}</p>
          ${{summaryChips ? `<div class="summary-row">${{summaryChips}}</div>` : ""}}
          <div class="chart-wrap">${{sectionChart(section)}}</div>
        </section>
      `;
    }}

    function render() {{
      const app = document.getElementById("app");
      const sections = dashboard.chart_plan || [];
      app.innerHTML = `
        <header class="hero">
          <h1>${{dashboard.title || "Data Quality Dashboard"}}</h1>
          <div class="small">${{dashboard.description || ""}}</div>
          <div class="meta">
            <span class="pill">tenant: ${{dashboard.tenant_id || "—"}}</span>
            <span class="pill">domain: ${{dashboard.domain_id || "—"}}</span>
            <span class="pill">run: ${{dashboard.run_id || "—"}}</span>
            <span class="pill">dashboard: ${{dashboard.dashboard_id || "—"}}</span>
            <span class="pill">created by: ${{dashboard.created_by || "—"}}</span>
            <span class="pill">updated: ${{dashboard.updated_at || dashboard.created_at || "—"}}</span>
          </div>
        </header>
        <main class="grid">
          <section class="panel span-12">
            <h2>Executive Summary</h2>
            <p class="sub">High-level view of trust, missingness, rule failures, duplicates, and remediation.</p>
            ${{summaryCards()}}
          </section>
          ${{sections.map(sectionPanel).join("")}}
        </main>
      `;
      bindInteractions();
    }}

    render();
  </script>
</body>
</html>
"""


def load_dashboard(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_html(dashboard: dict) -> str:
    title = str(dashboard.get("title") or dashboard.get("dashboard_id") or "Data Quality Dashboard")
    html = (
        HTML_TEMPLATE
        .replace("__TITLE__", title)
        .replace("__DASHBOARD_JSON__", json.dumps(dashboard, indent=2))
    )
    return html.replace("{{", "{").replace("}}", "}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a standalone HTML visualizer for a data quality dashboard JSON payload.")
    parser.add_argument("input_path", help="Path to the JSON or .md file containing the dashboard payload.")
    parser.add_argument("output_path", help="Path to write the generated HTML file.")
    args = parser.parse_args()

    input_path = Path(args.input_path)
    output_path = Path(args.output_path)

    dashboard = load_dashboard(input_path)
    html = render_html(dashboard)
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
