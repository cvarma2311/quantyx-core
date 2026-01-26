# Phase J: Anomaly Detection + Time-Series Narratives

Goal: detect anomalies, visualize them on time-series charts, and explain root causes.

## Scope
- Detect anomalies for key metrics (time-series).
- Persist anomaly insights to `quantyx_insight_events`.
- Provide drill-down details and driver attribution.
- Expose APIs to fetch chart-ready series and anomaly overlays.

---

## Phase J.1: Data + Baselines

1) **Baseline series generation**
   - Use trailing history for each metric (e.g., last 12–24 periods).
   - Baseline methods (configurable):
     - Rolling mean + std (z-score)
     - Median + MAD (robust)
     - Seasonal baseline (same month/quarter last year)

2) **Time grain alignment**
   - Align to metric grain (day/month/quarter).
   - Normalize fiscal/calendar alignment based on domain.

3) **Storage**
   - Store per-period baseline + actual in `quantyx_insight_events` (drivers field).
   - Optional: create a dedicated table later for time-series caches.

Deliverable:
- A baseline computation service and a reproducible query for each metric.

---

## Phase J.2: Anomaly Detection Engine

1) **Anomaly rules**
   - z-score threshold (default 2.5)
   - MAD threshold (default 3.0)
   - minimum history length (default 6 periods)

2) **Severity + confidence**
   - Severity mapping by deviation size.
   - Confidence increases with history length and deviation magnitude.

3) **Persistence**
   - Save anomaly as `insight_type = "anomaly"` in `quantyx_insight_events`.
   - Include `entity_scope`, `metric_refs`, and detected period.

Deliverable:
- `/insights/generate?type=anomaly` API to generate and persist anomalies.

---

## Phase J.3: Time-Series API (Chart + Overlay)

1) **Time-series endpoint**
   - `GET /timeseries?metric=...&dimensions=...&filters=...&grain=...`
   - Returns ordered points: {period, actual, baseline, is_anomaly}

2) **Anomaly overlay**
   - Mark anomalous points for UI highlighting.
   - Provide delta/percent deviation per point.

Deliverable:
- Chart-ready payload for line graph + anomaly overlay.

---

## Phase J.4: Root-Cause + Correlation Drilldown

1) **Driver attribution**
   - For an anomaly period, compute top contributors by dimension.
   - Example: sales_area_name, product_name, region_name.

2) **Correlated facts**
   - Compare related metrics in the same window (targets, run-rate, inventory).
   - Provide side-by-side deltas.

3) **Drilldown API**
   - `GET /insights/{id}/details`
   - Returns drivers, peer comparisons, and contributing rows.

Deliverable:
- A detailed explanation payload for the clicked anomaly point.

---

## Phase J.5: UI/Visualization Hooks

1) **Line chart support**
   - Plot actual vs baseline.
   - Highlight anomaly points (color + tooltip).

2) **Click-through**
   - Clicking an anomaly point calls `/insights/{id}/details`.
   - Show drivers, correlated metrics, and suggested actions.

Deliverable:
- UI-ready payloads for chart + details.

---

## Acceptance Criteria
- Anomalies are detected and persisted.
- Time-series endpoint renders line graph with anomaly markers.
- Clicking an anomaly returns a clear explanation and drivers.

---

## Open Questions
- Default thresholds and history length per domain?
- Which metrics are in the anomaly watchlist by default?
- Should anomalies be per entity (e.g., per sales area) or global only?
