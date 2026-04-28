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
    :root {
      --bg: #08111f;
      --panel: #0f172a;
      --panel-2: #111827;
      --line: #233044;
      --text: #e5eef8;
      --muted: #93a4b8;
      --good: #10b981;
      --warn: #f59e0b;
      --bad: #ef4444;
      --info: #38bdf8;
      --neutral: #64748b;
      --baseline: #a78bfa;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #020617 0%, #08111f 100%);
      color: var(--text);
    }
    .page { max-width: 1480px; margin: 0 auto; padding: 24px; }
    .hero, .panel {
      border: 1px solid var(--line);
      background: rgba(15, 23, 42, 0.92);
      border-radius: 8px;
    }
    .hero { padding: 24px; margin-bottom: 18px; }
    .hero h1 { margin: 0 0 10px; font-size: 28px; line-height: 1.1; }
    .hero .meta, .chips { display: flex; flex-wrap: wrap; gap: 10px; }
    .pill, .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(17, 24, 39, 0.88);
      color: var(--muted);
      font-size: 12px;
    }
    .chip.good { color: #d1fae5; border-color: rgba(16,185,129,0.45); background: rgba(16,185,129,0.12); }
    .chip.bad { color: #fee2e2; border-color: rgba(239,68,68,0.45); background: rgba(239,68,68,0.12); }
    .chip.warn { color: #fef3c7; border-color: rgba(245,158,11,0.45); background: rgba(245,158,11,0.12); }
    .chip.info { color: #dbeafe; border-color: rgba(56,189,248,0.45); background: rgba(56,189,248,0.12); }
    .grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 16px; }
    .span-12 { grid-column: span 12; }
    .span-8 { grid-column: span 8; }
    .span-6 { grid-column: span 6; }
    .span-4 { grid-column: span 4; }
    .span-3 { grid-column: span 3; }
    @media (max-width: 1100px) {
      .span-8, .span-6, .span-4, .span-3 { grid-column: span 12; }
    }
    .panel { padding: 16px; overflow: hidden; }
    .panel h2, .panel h3 { margin: 0 0 10px; font-size: 16px; }
    .sub { margin: 0 0 14px; color: var(--muted); font-size: 13px; }
    .metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    @media (max-width: 1100px) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 680px) { .metric-grid { grid-template-columns: 1fr; } }
    .metric {
      border: 1px solid var(--line);
      background: rgba(17, 24, 39, 0.86);
      border-radius: 8px;
      padding: 14px;
    }
    .metric .label { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .metric .value { font-size: 28px; font-weight: 800; line-height: 1; }
    .metric .note { margin-top: 6px; color: var(--muted); font-size: 12px; }
    .table-wrap { overflow: auto; border: 1px solid var(--line); border-radius: 8px; }
    table { width: 100%; border-collapse: collapse; min-width: 880px; }
    th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--line); font-size: 13px; vertical-align: top; }
    th { position: sticky; top: 0; z-index: 1; background: #111827; color: #cbd5e1; }
    .small { color: var(--muted); font-size: 12px; }
    .btn {
      appearance: none;
      border: 1px solid #0ea5e9;
      background: rgba(14, 165, 233, 0.12);
      color: #bae6fd;
      padding: 6px 10px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      white-space: nowrap;
    }
    .btn:hover { background: rgba(14,165,233,0.22); }
    .clickable { cursor: pointer; }
    .status-improved { color: var(--good); font-weight: 700; }
    .status-worsened { color: var(--bad); font-weight: 700; }
    .status-unchanged { color: var(--muted); font-weight: 700; }
    .status-baseline { color: var(--baseline); font-weight: 700; }
    .status-changed { color: var(--warn); font-weight: 700; }
    .direction-higher_better { color: #d1fae5; }
    .direction-lower_better { color: #fef3c7; }
    .direction-status_transition, .direction-neutral { color: var(--muted); }
    .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
    .tab {
      appearance: none; border: 1px solid var(--line); background: rgba(17,24,39,0.88);
      color: var(--muted); padding: 6px 10px; border-radius: 999px; cursor: pointer; font-size: 12px;
    }
    .tab.active { color: var(--text); border-color: #38bdf8; background: rgba(56,189,248,0.12); }
    .chart-wrap { min-height: 280px; }
    svg { width: 100%; height: auto; display: block; }
    .modal {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      background: rgba(2, 6, 23, 0.78);
      padding: 24px;
      z-index: 50;
    }
    .modal.open { display: flex; }
    .modal-card {
      width: min(1180px, 100%);
      max-height: 88vh;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #0f172a;
      box-shadow: 0 16px 60px rgba(0, 0, 0, 0.45);
    }
    .modal-head {
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
    }
    .modal-body { padding: 16px; }
    pre {
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
    }
  </style>
</head>
<body>
  <div class="page" id="app"></div>
  <div class="modal" id="detail-modal">
    <div class="modal-card">
      <div class="modal-head">
        <div>
          <div id="modal-title">Trend Detail</div>
          <div class="small" id="modal-subtitle"></div>
        </div>
        <button class="btn" id="modal-close" type="button">Close</button>
      </div>
      <div class="modal-body" id="modal-body"></div>
    </div>
  </div>
  <script>
    const trendPayload = __TRENDS_JSON__;

    function fmtNumber(value, digits = 0) {
      if (value === null || value === undefined || value === "") return "—";
      const n = Number(value);
      if (Number.isNaN(n)) return String(value);
      return new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
    }

    function fmtPct(value, digits = 1) {
      if (value === null || value === undefined || value === "") return "—";
      const n = Number(value);
      if (Number.isNaN(n)) return String(value);
      return `${fmtNumber(n, digits)}%`;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function statusClass(value) {
      const key = String(value || "").toLowerCase();
      return key ? `status-${key}` : "";
    }

    function buildMetric(label, value, note, extraClass = "") {
      return `
        <div class="metric">
          <div class="label">${label}</div>
          <div class="value ${extraClass}">${value}</div>
          <div class="note">${note || ""}</div>
        </div>
      `;
    }

    function inferredEvidencePath(row) {
      if (row.evidence_path) return row.evidence_path;
      const tenant = encodeURIComponent(trendPayload.tenant_id || "");
      const domain = encodeURIComponent(trendPayload.domain_id || "");
      const runId = encodeURIComponent(trendPayload.run_id || "");
      const objectType = encodeURIComponent(row.object_type || "");
      const objectKey = encodeURIComponent(row.object_key || "");
      const metricName = encodeURIComponent(row.metric_name || "");
      if (row.object_type === "table" && row.object_key) {
        return `/data-quality/trends/tables/${objectKey}?tenant_id=${tenant}&domain_id=${domain}&run_id=${runId}`;
      }
      if (row.object_type === "rule" && row.object_key) {
        return `/data-quality/trends/rules/${objectKey}?tenant_id=${tenant}&domain_id=${domain}&run_id=${runId}`;
      }
      return `/data-quality/trends?tenant_id=${tenant}&domain_id=${domain}&run_id=${runId}&object_type=${objectType}&object_key=${objectKey}&metric_name=${metricName}`;
    }

    function apiHref(path) {
      const raw = String(path || "").trim();
      if (!raw) return "#";
      if (raw.startsWith("http://") || raw.startsWith("https://")) return raw;
      return `http://localhost:8787${raw}`;
    }

    function trendRows() {
      return Array.isArray(trendPayload.trends) ? trendPayload.trends : [];
    }

    function trendCards() {
      return Array.isArray(trendPayload.cards) ? trendPayload.cards : [];
    }

    function trendChartPlan() {
      return Array.isArray(trendPayload.chart_plan) ? trendPayload.chart_plan : [];
    }

    function chartByKey(key) {
      return trendChartPlan().find((item) => item && item.chart_key === key) || null;
    }

    function groupedRows(mode) {
      const groups = trendPayload.groups || {};
      if (mode === "run") return (groups.run_final_dataset || {}).rows || null;
      if (mode === "table") return (groups.tables || {}).rows || null;
      if (mode === "rule") return (groups.rules || {}).rows || null;
      if (mode === "stage") return (groups.stages || {}).rows || null;
      if (mode === "improved") return (groups.improved || {}).rows || null;
      if (mode === "worsened") return (groups.worsened || {}).rows || null;
      if (mode === "baseline") return (groups.baseline || {}).rows || null;
      if (mode === "changed") return (groups.changed || {}).rows || null;
      if (mode === "unchanged") return (groups.unchanged || {}).rows || null;
      return null;
    }

    function summarizeByStatus(rows) {
      const counts = { improved: 0, worsened: 0, unchanged: 0, baseline: 0, changed: 0 };
      rows.forEach((row) => {
        const key = String(row.trend_status || "").toLowerCase();
        if (counts[key] !== undefined) counts[key] += 1;
      });
      return counts;
    }

    function summarizeByType(rows) {
      const counts = {};
      rows.forEach((row) => {
        const key = String(row.object_type || "unknown");
        counts[key] = (counts[key] || 0) + 1;
      });
      return Object.entries(counts).sort((a, b) => b[1] - a[1]);
    }

    function topDeltaRows(rows, filterStatus, limit = 10) {
      return rows
        .filter((row) => String(row.trend_status || "") === filterStatus && row.delta_value !== null && row.delta_value !== undefined && row.delta_value !== "")
        .sort((a, b) => Math.abs(Number(b.delta_value) || 0) - Math.abs(Number(a.delta_value) || 0))
        .slice(0, limit);
    }

    function statusColor(status) {
      if (status === "improved") return "#10b981";
      if (status === "worsened") return "#ef4444";
      if (status === "baseline") return "#a78bfa";
      if (status === "changed") return "#f59e0b";
      return "#64748b";
    }

    function horizontalBarChart(rows, valueGetter, labelGetter, colorGetter) {
      if (!rows.length) return `<div class="small">No rows available.</div>`;
      const width = 960;
      const left = 260;
      const rowH = 34;
      const height = rows.length * rowH + 24;
      const max = Math.max(...rows.map((row) => Math.abs(Number(valueGetter(row)) || 0)), 1);
      const barMax = width - left - 130;
      const bars = rows.map((row, idx) => {
        const y = 12 + idx * rowH;
        const value = Number(valueGetter(row)) || 0;
        const w = Math.max(2, (Math.abs(value) / max) * barMax);
        const label = escapeHtml(labelGetter(row));
        const color = colorGetter(row);
        const path = inferredEvidencePath(row);
        const href = apiHref(path);
        return `
          <text x="8" y="${y + 14}" fill="#cbd5e1" font-size="12">${label}</text>
          <g class="trend-bar clickable" data-href="${escapeHtml(href)}" tabindex="0" role="button">
            <rect x="${left}" y="${y}" width="${barMax}" height="18" fill="#1f2937" rx="4"></rect>
            <rect x="${left}" y="${y}" width="${w}" height="18" fill="${color}" rx="4"></rect>
            <text x="${left + w + 8}" y="${y + 14}" fill="#e5eef8" font-size="12">${fmtNumber(value, 2)}</text>
          </g>
        `;
      }).join("");
      return `<svg viewBox="0 0 ${width} ${height}" aria-label="delta chart">${bars}</svg>`;
    }

    function statusDistributionChart(counts) {
      const rows = Object.entries(counts).filter(([, count]) => count > 0);
      if (!rows.length) return `<div class="small">No rows available.</div>`;
      const width = 960;
      const height = 260;
      const baseY = 200;
      const left = 50;
      const gap = 28;
      const barW = 110;
      const max = Math.max(...rows.map(([, count]) => count), 1);
      const bars = rows.map(([status, count], idx) => {
        const x = left + idx * (barW + gap);
        const h = (count / max) * 130;
        const y = baseY - h;
        return `
          <rect x="${x}" y="${y}" width="${barW}" height="${h}" fill="${statusColor(status)}" rx="6"></rect>
          <text x="${x + barW / 2}" y="${y - 8}" text-anchor="middle" fill="#e5eef8" font-size="12">${fmtNumber(count, 0)}</text>
          <text x="${x + barW / 2}" y="${baseY + 18}" text-anchor="middle" fill="#cbd5e1" font-size="12">${status}</text>
        `;
      }).join("");
      return `<svg viewBox="0 0 ${width} ${height}" aria-label="status distribution"><line x1="${left}" y1="${baseY}" x2="${width - 20}" y2="${baseY}" stroke="#334155"></line>${bars}</svg>`;
    }

    function typeDistributionTable(rows) {
      const body = rows.map(([type, count]) => `<tr><td>${escapeHtml(type)}</td><td>${fmtNumber(count, 0)}</td></tr>`).join("");
      return `<div class="table-wrap"><table><thead><tr><th>Object Type</th><th>Trend Rows</th></tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function chartTable(chart) {
      const columns = Array.isArray(chart?.columns) ? chart.columns : [];
      const rows = Array.isArray(chart?.rows) ? chart.rows : [];
      if (!columns.length) return `<div class="small">No rows available.</div>`;
      const body = rows.map((row) => `
        <tr>
          ${columns.map((col) => {
            const value = row[col.field];
            if (col.field === "evidence_path" && value) {
              return `<td><button type="button" class="btn trend-drillthrough" data-href="${escapeHtml(apiHref(value))}">Drill Through</button></td>`;
            }
            return `<td>${escapeHtml(value ?? "—")}</td>`;
          }).join("")}
        </tr>
      `).join("");
      return `<div class="table-wrap"><table><thead><tr>${columns.map((col) => `<th>${escapeHtml(col.label || col.field || "")}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function trendTable(rows) {
      const body = rows.map((row) => {
        const previous = row.previous_value_text ?? (row.previous_value_num !== null && row.previous_value_num !== undefined ? fmtNumber(row.previous_value_num, 2) : "—");
        const current = row.current_value_text ?? (row.current_value_num !== null && row.current_value_num !== undefined ? fmtNumber(row.current_value_num, 2) : "—");
        const delta = row.delta_value !== null && row.delta_value !== undefined && row.delta_value !== "" ? fmtNumber(row.delta_value, 2) : "—";
        const deltaPct = row.delta_pct !== null && row.delta_pct !== undefined && row.delta_pct !== "" ? fmtPct(row.delta_pct, 2) : "—";
        const path = apiHref(inferredEvidencePath(row));
        return `
          <tr>
            <td>${escapeHtml(row.object_type || "—")}</td>
            <td>${escapeHtml(row.object_name || row.object_key || "—")}</td>
            <td>${escapeHtml(row.metric_name || "—")}</td>
            <td>${escapeHtml(previous)}</td>
            <td>${escapeHtml(current)}</td>
            <td>${escapeHtml(delta)}</td>
            <td>${escapeHtml(deltaPct)}</td>
            <td class="${statusClass(row.trend_status)}">${escapeHtml(row.trend_status || "—")}</td>
            <td class="direction-${escapeHtml(row.directionality || "")}">${escapeHtml(row.directionality || "—")}</td>
            <td><button type="button" class="btn trend-drillthrough" data-href="${escapeHtml(path)}">Drill Through</button></td>
          </tr>
        `;
      }).join("");
      return `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Object</th>
                <th>Metric</th>
                <th>Previous</th>
                <th>Current</th>
                <th>Delta</th>
                <th>Delta %</th>
                <th>Status</th>
                <th>Direction</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      `;
    }

    function filterRows(rows, mode) {
      if (mode === "all") return rows;
      if (mode === "rule") return rows.filter((row) => row.object_type === "rule");
      if (mode === "table") return rows.filter((row) => row.object_type === "table");
      if (mode === "stage") return rows.filter((row) => row.object_type === "stage");
      if (mode === "run") return rows.filter((row) => row.object_type === "run" || row.object_type === "final_dataset");
      if (mode === "improved") return rows.filter((row) => row.trend_status === "improved");
      if (mode === "worsened") return rows.filter((row) => row.trend_status === "worsened");
      if (mode === "baseline") return rows.filter((row) => row.trend_status === "baseline");
      if (mode === "changed") return rows.filter((row) => row.trend_status === "changed");
      if (mode === "unchanged") return rows.filter((row) => row.trend_status === "unchanged");
      return rows;
    }

    function detailTable(rows) {
      const body = rows.map((row) => {
        const previous = row.previous_value_text ?? (row.previous_value_num !== null && row.previous_value_num !== undefined ? fmtNumber(row.previous_value_num, 2) : "—");
        const current = row.current_value_text ?? (row.current_value_num !== null && row.current_value_num !== undefined ? fmtNumber(row.current_value_num, 2) : "—");
        const delta = row.delta_value !== null && row.delta_value !== undefined && row.delta_value !== "" ? fmtNumber(row.delta_value, 2) : "—";
        const deltaPct = row.delta_pct !== null && row.delta_pct !== undefined && row.delta_pct !== "" ? fmtPct(row.delta_pct, 2) : "—";
        return `
          <tr>
            <td>${escapeHtml(row.object_type || "—")}</td>
            <td>${escapeHtml(row.object_name || row.object_key || "—")}</td>
            <td>${escapeHtml(row.metric_name || "—")}</td>
            <td>${escapeHtml(previous)}</td>
            <td>${escapeHtml(current)}</td>
            <td>${escapeHtml(delta)}</td>
            <td>${escapeHtml(deltaPct)}</td>
            <td class="${statusClass(row.trend_status)}">${escapeHtml(row.trend_status || "—")}</td>
          </tr>
        `;
      }).join("");
      return `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Object</th>
                <th>Metric</th>
                <th>Previous</th>
                <th>Current</th>
                <th>Delta</th>
                <th>Delta %</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      `;
    }

    function openModal(title, subtitle, html) {
      document.getElementById("modal-title").textContent = title;
      document.getElementById("modal-subtitle").textContent = subtitle || "";
      document.getElementById("modal-body").innerHTML = html;
      document.getElementById("detail-modal").classList.add("open");
    }

    function closeModal() {
      document.getElementById("detail-modal").classList.remove("open");
    }

    function renderTrendDetailPayload(payload, href) {
      if (!payload || typeof payload !== "object") {
        return `<pre>${escapeHtml(String(payload))}</pre>`;
      }
      function detailMetrics(rows) {
        const statusRow = rows.find((row) => row.metric_name === "result_status" || row.metric_name === "readiness_status");
        const scoreRow = rows.find((row) => String(row.metric_name || "").includes("trust_score"));
        const countRow = rows.find((row) => String(row.metric_name || "").includes("violation_count") || String(row.metric_name || "").includes("row_count"));
        const cards = [];
        if (statusRow) {
          cards.push(buildMetric("Status", escapeHtml(statusRow.current_value_text || "—"), `Trend: ${escapeHtml(statusRow.trend_status || "—")}`, statusClass(statusRow.trend_status)));
        }
        if (scoreRow) {
          cards.push(buildMetric("Primary Score", fmtNumber(scoreRow.current_value_num, 2), `Previous: ${fmtNumber(scoreRow.previous_value_num, 2)}`));
        }
        if (countRow) {
          cards.push(buildMetric("Primary Count", fmtNumber(countRow.current_value_num, 0), `Delta: ${fmtNumber(countRow.delta_value, 2)}`));
        }
        if (!cards.length) return "";
        return `<div class="metric-grid" style="margin-bottom:12px">${cards.join("")}</div>`;
      }

      function groupedRows(rows) {
        const groups = {};
        rows.forEach((row) => {
          const key = String(row.metric_name || "metric");
          (groups[key] ||= []).push(row);
        });
        return Object.entries(groups);
      }

      function tableObjectView(payload) {
        const rows = payload.trends || [];
        const latest = rows[0] || {};
        const metricRows = rows.map((row) => `
          <tr>
            <td>${escapeHtml(row.metric_name || "—")}</td>
            <td>${escapeHtml(row.previous_value_text ?? (row.previous_value_num != null ? fmtNumber(row.previous_value_num, 2) : "—"))}</td>
            <td>${escapeHtml(row.current_value_text ?? (row.current_value_num != null ? fmtNumber(row.current_value_num, 2) : "—"))}</td>
            <td>${escapeHtml(row.delta_value != null ? fmtNumber(row.delta_value, 2) : "—")}</td>
            <td class="${statusClass(row.trend_status)}">${escapeHtml(row.trend_status || "—")}</td>
          </tr>
        `).join("");
        return `
          ${detailMetrics(rows)}
          <div class="chips" style="margin-bottom:12px">
            <span class="chip info">Table: ${escapeHtml(payload.table_name || latest.object_name || latest.object_key || "—")}</span>
            <span class="chip">Metrics: ${fmtNumber(rows.length, 0)}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Metric</th><th>Previous</th><th>Current</th><th>Delta</th><th>Status</th></tr></thead>
              <tbody>${metricRows}</tbody>
            </table>
          </div>
          <div style="margin-top:12px"><a class="btn" href="${escapeHtml(href)}" target="_blank">Open Raw API Response</a></div>
        `;
      }

      function ruleObjectView(payload) {
        const rows = payload.trends || [];
        const latest = rows[0] || {};
        const grouped = groupedRows(rows).map(([metricName, metricRows]) => {
          const row = metricRows[0];
          return `
            <tr>
              <td>${escapeHtml(metricName)}</td>
              <td>${escapeHtml(row.previous_value_text ?? (row.previous_value_num != null ? fmtNumber(row.previous_value_num, 2) : "—"))}</td>
              <td>${escapeHtml(row.current_value_text ?? (row.current_value_num != null ? fmtNumber(row.current_value_num, 2) : "—"))}</td>
              <td>${escapeHtml(row.delta_value != null ? fmtNumber(row.delta_value, 2) : "—")}</td>
              <td class="${statusClass(row.trend_status)}">${escapeHtml(row.trend_status || "—")}</td>
            </tr>
          `;
        }).join("");
        return `
          ${detailMetrics(rows)}
          <div class="chips" style="margin-bottom:12px">
            <span class="chip info">Rule: ${escapeHtml(latest.object_name || payload.rule_logical_key || "—")}</span>
            <span class="chip">Logical Key: ${escapeHtml(payload.rule_logical_key || latest.object_key || "—")}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Metric</th><th>Previous</th><th>Current</th><th>Delta</th><th>Status</th></tr></thead>
              <tbody>${grouped}</tbody>
            </table>
          </div>
          <div style="margin-top:12px"><a class="btn" href="${escapeHtml(href)}" target="_blank">Open Raw API Response</a></div>
        `;
      }

      function runObjectView(payload) {
        const rows = payload.trends || [];
        const summary = payload.summary || {};
        const body = rows.map((row) => `
          <tr>
            <td>${escapeHtml(row.object_name || row.object_key || "—")}</td>
            <td>${escapeHtml(row.metric_name || "—")}</td>
            <td>${escapeHtml(row.previous_value_text ?? (row.previous_value_num != null ? fmtNumber(row.previous_value_num, 2) : "—"))}</td>
            <td>${escapeHtml(row.current_value_text ?? (row.current_value_num != null ? fmtNumber(row.current_value_num, 2) : "—"))}</td>
            <td>${escapeHtml(row.delta_value != null ? fmtNumber(row.delta_value, 2) : "—")}</td>
            <td class="${statusClass(row.trend_status)}">${escapeHtml(row.trend_status || "—")}</td>
          </tr>
        `).join("");
        return `
          <div class="metric-grid" style="margin-bottom:12px">
            ${buildMetric("Trend Rows", fmtNumber(summary.trend_row_count || rows.length, 0), "Rows in this filtered response")}
            ${buildMetric("Improved", fmtNumber(summary.improved_metric_count || 0, 0), "Improved metrics", "status-improved")}
            ${buildMetric("Worsened", fmtNumber(summary.worsened_metric_count || 0, 0), "Regressions", "status-worsened")}
            ${buildMetric("Baseline", fmtNumber(summary.baseline_metric_count || 0, 0), "Baseline-only metrics", "status-baseline")}
          </div>
          <div class="chips" style="margin-bottom:12px">
            <span class="chip info">Run: ${escapeHtml(payload.run_id || "—")}</span>
            <span class="chip">Baseline: ${escapeHtml(payload.baseline_run_id || "None")}</span>
            <span class="chip">Scope: ${escapeHtml(payload.trend_scope_key || "—")}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Object</th><th>Metric</th><th>Previous</th><th>Current</th><th>Delta</th><th>Status</th></tr></thead>
              <tbody>${body}</tbody>
            </table>
          </div>
          <div style="margin-top:12px"><a class="btn" href="${escapeHtml(href)}" target="_blank">Open Raw API Response</a></div>
        `;
      }

      if (Array.isArray(payload.trends)) {
        if (payload.rule_logical_key) return ruleObjectView(payload);
        if (payload.table_name) return tableObjectView(payload);
        return runObjectView(payload);
      }
      return `
        <pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
        <div style="margin-top:12px"><a class="btn" href="${escapeHtml(href)}" target="_blank">Open Raw API Response</a></div>
      `;
    }

    async function openTrendDetail(href) {
      if (!href || href === "#") return;
      try {
        const response = await fetch(href, { headers: { "accept": "application/json" } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        const title = payload.rule_logical_key
          ? "Rule Trend Detail"
          : payload.table_name
          ? "Table Trend Detail"
          : "Trend Detail";
        const subtitle = href.replace("http://localhost:8787", "");
        openModal(title, subtitle, renderTrendDetailPayload(payload, href));
      } catch (error) {
        window.open(href, "_blank", "noopener,noreferrer");
      }
    }

    function render(mode = "all") {
      const rows = trendRows();
      const grouped = groupedRows(mode);
      const filtered = Array.isArray(grouped) ? grouped : filterRows(rows, mode);
      const summary = trendPayload.summary || {};
      const cards = trendCards();
      const statusChart = chartByKey("trend_status_distribution");
      const objectTypeChart = chartByKey("object_type_distribution");
      const topImprovedChart = chartByKey("top_improved_deltas");
      const topWorsenedChart = chartByKey("top_worsened_deltas");
      const readinessChart = chartByKey("publish_readiness");
      const businessTermChart = chartByKey("business_term_trends");
      const statusCounts = statusChart
        ? Object.fromEntries((statusChart.rows || []).map((row) => [row.category, row.value]))
        : summarizeByStatus(rows);
      const typeCounts = objectTypeChart
        ? (objectTypeChart.rows || []).map((row) => [row.category, row.value])
        : summarizeByType(rows);
      const topImproved = topImprovedChart ? (topImprovedChart.rows || []) : topDeltaRows(rows, "improved", 8);
      const topWorsened = topWorsenedChart ? (topWorsenedChart.rows || []) : topDeltaRows(rows, "worsened", 8);
      const app = document.getElementById("app");
      const metricCards = cards.length
        ? cards.slice(0, 6).map((card) => {
            const value = card.value === null || card.value === undefined || card.value === "" ? "—" : escapeHtml(String(card.value));
            const noteBits = [];
            if (card.note !== null && card.note !== undefined && card.note !== "") noteBits.push(escapeHtml(String(card.note)));
            if (card.delta_value !== null && card.delta_value !== undefined && card.delta_value !== "") noteBits.push(`Δ ${escapeHtml(fmtNumber(card.delta_value, 2))}`);
            if (card.delta_pct !== null && card.delta_pct !== undefined && card.delta_pct !== "") noteBits.push(escapeHtml(fmtPct(card.delta_pct, 2)));
            return buildMetric(card.title || card.card_key || "Metric", value, noteBits.join(" · "), statusClass(card.trend_status));
          }).join("")
        : `
            ${buildMetric("Trend Rows", fmtNumber(summary.trend_row_count || 0, 0), "Persisted comparison rows in this run")}
            ${buildMetric("Improved", fmtNumber(summary.improved_metric_count || 0, 0), "Metrics better than baseline", "status-improved")}
            ${buildMetric("Worsened", fmtNumber(summary.worsened_metric_count || 0, 0), "Metrics worse than baseline", "status-worsened")}
            ${buildMetric("Baseline Only", fmtNumber(summary.baseline_metric_count || 0, 0), "New metrics or first-seen metrics", "status-baseline")}
          `;
      const readinessCards = Array.isArray(readinessChart?.rows) && readinessChart.rows.length
        ? readinessChart.rows.map((row) => buildMetric(row.label || row.metric_key || "Metric", escapeHtml(row.value ?? "—"), escapeHtml(row.note ?? ""), statusClass(row.trend_status))).join("")
        : buildMetric("Publish Readiness", "—", "No readiness section available");
      const businessTermTable = businessTermChart ? chartTable(businessTermChart) : `<div class="small">No business-term trend rows available.</div>`;

      app.innerHTML = `
        <section class="hero">
          <h1>Data Quality Trend View</h1>
          <p class="sub">Run-over-run trend summary for a selected monitor scope. Use this shape for the UI trend page, drill-through bars, and filtered object views.</p>
          <div class="meta">
            <span class="pill">Tenant: ${escapeHtml(trendPayload.tenant_id || "—")}</span>
            <span class="pill">Domain: ${escapeHtml(trendPayload.domain_id || "—")}</span>
            <span class="pill">Run: ${escapeHtml(trendPayload.run_id || "—")}</span>
            <span class="pill">Baseline: ${escapeHtml(trendPayload.baseline_run_id || "None")}</span>
          </div>
          <div class="chips" style="margin-top:10px">
            <span class="chip info">Scope: ${escapeHtml(trendPayload.trend_scope_key || "—")}</span>
            <span class="chip good">Improved: ${fmtNumber(summary.improved_metric_count || 0, 0)}</span>
            <span class="chip bad">Worsened: ${fmtNumber(summary.worsened_metric_count || 0, 0)}</span>
            <span class="chip warn">Baseline: ${fmtNumber(summary.baseline_metric_count || 0, 0)}</span>
          </div>
        </section>

        <section class="grid">
          <div class="panel span-12">
            <div class="metric-grid">
              ${metricCards}
            </div>
          </div>

          <div class="panel span-6">
            <h2>Status Distribution</h2>
            <p class="sub">This is the first chart the UI should show. It tells the user whether the run mostly improved, regressed, or just surfaced new baseline-only metrics.</p>
            <div class="chart-wrap">${statusDistributionChart(statusCounts)}</div>
          </div>

          <div class="panel span-6">
            <h2>Object Type Mix</h2>
            <p class="sub">Use this as a quick navigator into rule, table, stage, and run-level trend slices.</p>
            ${typeDistributionTable(typeCounts)}
          </div>

          <div class="panel span-6">
            <h2>Top Improved Deltas</h2>
            <p class="sub">These bars are drill-through capable. Each bar opens the appropriate trend detail route.</p>
            <div class="chart-wrap">
              ${horizontalBarChart(topImproved, (row) => row.delta_value ?? row.value, (row) => `${row.object_name || row.label} · ${row.metric_name || ""}`.replace(/ · $/, ""), () => "#10b981")}
            </div>
          </div>

          <div class="panel span-6">
            <h2>Top Worsened Deltas</h2>
            <p class="sub">Use the same interaction model as improved deltas. If empty, the run has no regressions.</p>
            <div class="chart-wrap">
              ${horizontalBarChart(topWorsened, (row) => row.delta_value ?? row.value, (row) => `${row.object_name || row.label} · ${row.metric_name || ""}`.replace(/ · $/, ""), () => "#ef4444")}
            </div>
          </div>

          <div class="panel span-12">
            <h2>${escapeHtml((readinessChart && readinessChart.title) || "Publish Readiness")}</h2>
            <p class="sub">${escapeHtml((readinessChart && readinessChart.subtitle) || "Certification and readiness summary from the backend trend payload.")}</p>
            <div class="metric-grid">${readinessCards}</div>
          </div>

          <div class="panel span-12">
            <h2>${escapeHtml((businessTermChart && businessTermChart.title) || "Business Term Trends")}</h2>
            <p class="sub">${escapeHtml((businessTermChart && businessTermChart.subtitle) || "Glossary-grouped trend coverage from the backend payload.")}</p>
            ${businessTermTable}
          </div>

          <div class="panel span-12">
            <h2>Filtered Trend Rows</h2>
            <p class="sub">This should map cleanly to tabs or chips in the UI.</p>
            <div class="tabs">
              <button class="tab ${mode === "all" ? "active" : ""}" data-mode="all">All</button>
              <button class="tab ${mode === "run" ? "active" : ""}" data-mode="run">Run + Final Dataset</button>
              <button class="tab ${mode === "table" ? "active" : ""}" data-mode="table">Tables</button>
              <button class="tab ${mode === "rule" ? "active" : ""}" data-mode="rule">Rules</button>
              <button class="tab ${mode === "stage" ? "active" : ""}" data-mode="stage">Stages</button>
              <button class="tab ${mode === "improved" ? "active" : ""}" data-mode="improved">Improved</button>
              <button class="tab ${mode === "worsened" ? "active" : ""}" data-mode="worsened">Worsened</button>
              <button class="tab ${mode === "baseline" ? "active" : ""}" data-mode="baseline">Baseline</button>
              <button class="tab ${mode === "changed" ? "active" : ""}" data-mode="changed">Changed</button>
              <button class="tab ${mode === "unchanged" ? "active" : ""}" data-mode="unchanged">Unchanged</button>
            </div>
            ${trendTable(filtered)}
          </div>
        </section>
      `;

      document.querySelectorAll(".tab").forEach((button) => {
        button.addEventListener("click", () => render(button.dataset.mode || "all"));
      });

      document.querySelectorAll(".trend-drillthrough").forEach((button) => {
        button.addEventListener("click", () => {
          const href = button.dataset.href;
          if (href) openTrendDetail(href);
        });
      });

      document.querySelectorAll(".trend-bar").forEach((node) => {
        const open = () => {
          const href = node.dataset.href;
          if (href) openTrendDetail(href);
        };
        node.addEventListener("click", open);
        node.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open();
          }
        });
      });
    }

    document.getElementById("modal-close").addEventListener("click", closeModal);
    document.getElementById("detail-modal").addEventListener("click", (event) => {
      if (event.target.id === "detail-modal") closeModal();
    });

    render();
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a data-quality trends payload to a standalone HTML page.")
    parser.add_argument("input_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input_path.read_text(encoding="utf-8"))
    title = f"Trend Visualizer - {payload.get('run_id') or 'data-quality'}"
    html = HTML_TEMPLATE.replace("__TITLE__", title).replace(
        "__TRENDS_JSON__", json.dumps(payload, ensure_ascii=False)
    )
    args.output_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
