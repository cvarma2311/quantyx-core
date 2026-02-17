# Phase X: Canvas Graph Persistence (Multi‑Canvas, Rooted Tenant View)

Goal: Store full canvas graphs (nodes + edges) per tenant, allow multiple canvases, and maintain explicit relationships between canvases and semantic objects (dimensions, facts, metrics). Provide a single endpoint to save/update a canvas with nodes + edges. Support a tenant‑level rooted view (single point → branches).

---

## 1) Dependency on Phase V

This phase **depends on Phase V** (Semantic Canvas Modeling):
- Phase V defines the semantic objects (dimension/fact/metric payloads).
- Phase X persists the **canvas graph** that connects those objects.

So: **Phase V is a prerequisite**, Phase X builds on it.

---

## 2) Data Model

### 2.1 Canvas Table
`quantyx_canvases`

Fields:
- `canvas_id` (PK)
- `tenant_id`, `domain_id`
- `name`, `description`
- `graph_json` (nodes + edges snapshot)
- `root_node_id` (optional; if not set, a virtual root is used)
- `status` (`draft`, `reviewed`, `certified`)
- `created_at`, `updated_at`

### 2.2 Node Link Table
`quantyx_canvas_nodes`

Many‑to‑many between canvases and semantic objects.

Fields:
- `canvas_id`
- `node_type` (`dimension` | `fact` | `metric`)
- `node_id` (dimension_id / fact_id / metric_id)
- `PRIMARY KEY (canvas_id, node_type, node_id)`

### 2.3 Edge Table
`quantyx_canvas_edges`

Fields:
- `canvas_id`
- `from_type`, `from_id`
- `to_type`, `to_id`
- `edge_type` (`dimension_to_fact`, `fact_to_metric`, `root_to_dimension`)
- `source` (`manual`, `llm`, `heuristic`)
- `confidence` (optional numeric)
- `PRIMARY KEY (canvas_id, from_type, from_id, to_type, to_id)`

---

## 3) API Design

### 3.1 POST /canvas/save
Single endpoint that accepts **nodes + edges**, persists objects, and stores the graph.

Request:
```json
{
  "tenant_id": "tenant_a",
  "domain_id": "petroleum_refinery",
  "name": "Default Semantic Canvas",
  "description": "Main tenant canvas",
  "nodes": [
    { "type": "dimension", "payload": { "name": "dim_plant", "keys": ["plant_id"] } },
    { "type": "fact", "payload": { "table_name": "fact_dispatch_daily", "grain": "day" } },
    { "type": "metric", "payload": { "metric_name": "dispatch_volume_tmt", "type": "sum" } }
  ],
  "edges": [
    { "from": "dim_plant", "to": "fact_dispatch_daily", "edge_type": "dimension_to_fact" },
    { "from": "fact_dispatch_daily", "to": "dispatch_volume_tmt", "edge_type": "fact_to_metric" }
  ]
}
```

Behavior:
- Upserts each node payload into registries.
- Resolves IDs and stores links in `quantyx_canvas_nodes`.
- Stores edges in `quantyx_canvas_edges`.
- Writes `graph_json` snapshot into `quantyx_canvases`.

Response:
```json
{ "canvas_id": "canvas_123", "status": "saved" }
```

### 3.2 PUT /canvas/{canvas_id}
Replace graph snapshot + edges for an existing canvas.

### 3.3 GET /canvas?tenant_id=...
List canvases for a tenant.

### 3.4 GET /canvas/{canvas_id}
Fetch the full graph snapshot (nodes + edges).

### 3.5 GET /canvas/tree?tenant_id=...
Return a **tenant‑rooted** view:
- A virtual root node
- Root → all dimensions
- Dimensions → facts
- Facts → metrics

---

## 4) Rooted Tenant View

The tenant‑level view presents a single “root”:

```
tenant_root
  ├── dim_plant
  │     └── fact_dispatch_daily
  │             └── dispatch_volume_tmt
  ├── dim_product
  │     └── fact_dispatch_daily
  │             └── dispatch_volume_tmt
```

This makes lineage easy to scan and aligns with your “single point root” requirement.

---

## 5) Persistence Flow

1. Canvas save request arrives.
2. Persist / upsert facts, dimensions, metrics.
3. Store relationships in:
   - `quantyx_canvas_nodes`
   - `quantyx_canvas_edges`
4. Store the **full graph snapshot** in `quantyx_canvases.graph_json`.

---

## 6) Changes Checklist

1. Add DB tables:
   - `quantyx_canvases`
   - `quantyx_canvas_nodes`
   - `quantyx_canvas_edges`
2. Add `POST /canvas/save`
3. Add `PUT /canvas/{canvas_id}`
4. Add canvas list + get endpoints
5. Add rooted tree endpoint
6. Update Swagger + V2_API docs

---

## 7) Open Questions

1. Should `graph_json` be source of truth or snapshot?
2. Should `POST /canvas/save` be idempotent?
3. Do we allow multiple roots, or force single root?
