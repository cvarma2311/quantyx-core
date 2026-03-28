#!/usr/bin/env bash
# =============================================================================
# migrate_unified_dashboards.sh
#
# Phase 44 — Unified Dashboard and Chart Schema migration.
#
# What this script does (in order, safe to re-run):
#   Step 1 : Create new tables quantyx_dashboards + quantyx_dashboard_charts
#   Step 2 : Add chart_source / title / created_by columns to quantyx_chart_requests
#   Step 3 : Migrate system dashboards from quantyx_dashboard_specs
#   Step 4 : Backfill run_id on system dashboards from quantyx_agent_run_events
#   Step 5 : Migrate user dashboards from quantyx_user_dashboards
#   Step 6 : Migrate user chart links from quantyx_user_dashboard_charts
#   Step 7 : Backfill chart_source on existing quantyx_chart_requests rows
#   Step 8 : Expand spec.charts JSON into quantyx_dashboard_charts (Python helper)
#
# Usage:
#   bash scripts/migrate_unified_dashboards.sh
#
# Prerequisites:
#   - .env file with DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD
#   - Python 3.10+ with psycopg2 installed (for Step 8)
#
# All steps use ON CONFLICT / IF NOT EXISTS so the script is idempotent.
# =============================================================================

set -euo pipefail

cd "$(dirname "$0")/.."
set -a
source .env
set +a

export PGHOST="${DB_HOST}"
export PGPORT="${DB_PORT}"
export PGDATABASE="${DB_NAME}"
export PGUSER="${DB_USER}"
export PGPASSWORD="${DB_PASSWORD}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# -----------------------------------------------------------------------------
# Step 1 — Create unified tables (idempotent)
# -----------------------------------------------------------------------------
log "Step 1: Creating quantyx_dashboards and quantyx_dashboard_charts tables..."
psql -v ON_ERROR_STOP=1 <<'SQL'

-- ── quantyx_dashboards ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.quantyx_dashboards (
  dashboard_id          TEXT PRIMARY KEY,
  tenant_id             TEXT NOT NULL,
  domain_id             TEXT NOT NULL,
  name                  TEXT NOT NULL,
  description           TEXT NULL,
  dashboard_type        TEXT NOT NULL DEFAULT 'system',   -- 'system' | 'user'
  status                TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'archived'

  -- Agentic / system fields
  run_id                TEXT NULL,
  latest_refresh_id     TEXT NULL,
  quality_score         FLOAT NULL,
  quality_gate_passed   BOOLEAN NULL,
  chart_plan            JSONB NULL,

  -- User fields
  created_by            TEXT NULL,

  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboards_tenant
  ON public.quantyx_dashboards (tenant_id, domain_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dashboards_type
  ON public.quantyx_dashboards (tenant_id, dashboard_type, status);

-- ── quantyx_dashboard_charts ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.quantyx_dashboard_charts (
  entry_id              TEXT PRIMARY KEY,
  dashboard_id          TEXT NOT NULL
    REFERENCES public.quantyx_dashboards(dashboard_id) ON DELETE CASCADE,
  chart_id              TEXT NOT NULL,
  position              INTEGER NOT NULL DEFAULT 0,
  title_override        TEXT NULL,
  added_by              TEXT NULL,
  added_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (dashboard_id, chart_id)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_charts_dashboard
  ON public.quantyx_dashboard_charts (dashboard_id, position ASC);

CREATE INDEX IF NOT EXISTS idx_dashboard_charts_chart
  ON public.quantyx_dashboard_charts (chart_id);

SQL
log "Step 1: Done."

# -----------------------------------------------------------------------------
# Step 2 — Add discriminator columns to quantyx_chart_requests (idempotent)
# -----------------------------------------------------------------------------
log "Step 2: Adding chart_source / title / created_by to quantyx_chart_requests..."
psql -v ON_ERROR_STOP=1 <<'SQL'

ALTER TABLE public.quantyx_chart_requests
  ADD COLUMN IF NOT EXISTS chart_source  TEXT NULL,
  ADD COLUMN IF NOT EXISTS title         TEXT NULL,
  ADD COLUMN IF NOT EXISTS created_by    TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_chart_requests_source
  ON public.quantyx_chart_requests (tenant_id, domain_id, chart_source, status, updated_at DESC);

SQL
log "Step 2: Done."

# -----------------------------------------------------------------------------
# Step 3 — Migrate system dashboards from quantyx_dashboard_specs
# -----------------------------------------------------------------------------
log "Step 3: Migrating system dashboards from quantyx_dashboard_specs..."
psql -v ON_ERROR_STOP=1 <<'SQL'

INSERT INTO public.quantyx_dashboards (
  dashboard_id,
  tenant_id,
  domain_id,
  name,
  description,
  dashboard_type,
  status,
  run_id,
  latest_refresh_id,
  quality_score,
  quality_gate_passed,
  chart_plan,
  created_at,
  updated_at
)
SELECT
  dashboard_id,
  tenant_id,
  domain_id,
  title                                                         AS name,
  NULL                                                          AS description,
  'system'                                                      AS dashboard_type,
  'active'                                                      AS status,
  NULL                                                          AS run_id,
  NULL                                                          AS latest_refresh_id,
  CASE
    WHEN jsonb_typeof(spec->'quality'->'quality_score') IN ('number','string')
    THEN (spec->'quality'->>'quality_score')::float
    ELSE NULL
  END                                                           AS quality_score,
  CASE
    WHEN spec->'quality'->>'gate_passed' IS NOT NULL
    THEN (spec->'quality'->>'gate_passed')::boolean
    ELSE NULL
  END                                                           AS quality_gate_passed,
  CASE
    WHEN jsonb_typeof(spec->'chart_plan') = 'array'
    THEN spec->'chart_plan'
    ELSE NULL
  END                                                           AS chart_plan,
  created_at,
  updated_at
FROM public.quantyx_dashboard_specs
ON CONFLICT (dashboard_id) DO NOTHING;

SQL
log "Step 3: Done."

# -----------------------------------------------------------------------------
# Step 4 — Backfill run_id on system dashboards from quantyx_agent_run_events
# -----------------------------------------------------------------------------
log "Step 4: Backfilling run_id on system dashboards..."
psql -v ON_ERROR_STOP=1 <<'SQL'

UPDATE public.quantyx_dashboards d
SET run_id = sub.run_id
FROM (
  SELECT DISTINCT ON (artifacts->>'dashboard_id')
    artifacts->>'dashboard_id' AS dashboard_id,
    run_id
  FROM public.quantyx_agent_run_events
  WHERE agent_name = 'DashboardAgent'
    AND status     = 'completed'
    AND artifacts->>'dashboard_id' IS NOT NULL
  ORDER BY artifacts->>'dashboard_id', created_at DESC
) sub
WHERE d.dashboard_id = sub.dashboard_id
  AND d.dashboard_type = 'system'
  AND d.run_id IS NULL;

SQL
log "Step 4: Done."

# -----------------------------------------------------------------------------
# Step 5 — Migrate user dashboards from quantyx_user_dashboards
# -----------------------------------------------------------------------------
log "Step 5: Migrating user dashboards from quantyx_user_dashboards..."
psql -v ON_ERROR_STOP=1 <<'SQL'

INSERT INTO public.quantyx_dashboards (
  dashboard_id,
  tenant_id,
  domain_id,
  name,
  description,
  dashboard_type,
  status,
  created_by,
  created_at,
  updated_at
)
SELECT
  dashboard_id,
  tenant_id,
  domain_id,
  name,
  description,
  'user'       AS dashboard_type,
  status,
  created_by,
  created_at,
  updated_at
FROM public.quantyx_user_dashboards
ON CONFLICT (dashboard_id) DO NOTHING;

SQL
log "Step 5: Done."

# -----------------------------------------------------------------------------
# Step 6 — Migrate user chart links from quantyx_user_dashboard_charts
# -----------------------------------------------------------------------------
log "Step 6: Migrating chart links from quantyx_user_dashboard_charts..."
psql -v ON_ERROR_STOP=1 <<'SQL'

INSERT INTO public.quantyx_dashboard_charts (
  entry_id,
  dashboard_id,
  chart_id,
  position,
  title_override,
  added_by,
  added_at
)
SELECT
  entry_id,
  dashboard_id,
  chart_id,
  position,
  NULL       AS title_override,
  added_by,
  added_at
FROM public.quantyx_user_dashboard_charts
ON CONFLICT (dashboard_id, chart_id) DO NOTHING;

SQL
log "Step 6: Done."

# -----------------------------------------------------------------------------
# Step 7 — Backfill chart_source on existing quantyx_chart_requests rows
# -----------------------------------------------------------------------------
log "Step 7: Backfilling chart_source on quantyx_chart_requests..."
psql -v ON_ERROR_STOP=1 <<'SQL'

-- Charts tied to an agentic run → 'agentic_run'
UPDATE public.quantyx_chart_requests
SET chart_source = 'agentic_run'
WHERE run_id IS NOT NULL
  AND chart_source IS NULL;

-- Charts from workspace / conversation (have a question, no run_id) → 'workspace'
UPDATE public.quantyx_chart_requests
SET chart_source = 'workspace'
WHERE run_id IS NULL
  AND question IS NOT NULL
  AND chart_source IS NULL;

-- Any remaining (no question, no run_id) → 'unknown'
UPDATE public.quantyx_chart_requests
SET chart_source = 'unknown'
WHERE chart_source IS NULL;

SQL
log "Step 7: Done."

# -----------------------------------------------------------------------------
# Step 8 — Expand spec.charts JSON into quantyx_dashboard_charts rows
#           (Python helper — handles positional index cleanly)
# -----------------------------------------------------------------------------
log "Step 8: Expanding spec.charts into quantyx_dashboard_charts rows (Python)..."
python3 - <<'PYEOF'
import os
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(
    host=os.environ["DB_HOST"],
    port=os.environ["DB_PORT"],
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
)

inserted = 0
skipped  = 0

try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Fetch all system dashboards that have a spec with a charts array
        cur.execute("""
            SELECT dashboard_id, spec
              FROM public.quantyx_dashboard_specs
             WHERE jsonb_typeof(spec->'charts') = 'array'
        """)
        rows = cur.fetchall()

    for row in rows:
        dashboard_id = row["dashboard_id"]
        charts = row["spec"]["charts"] if row["spec"] else []

        for position, chart in enumerate(charts):
            if not isinstance(chart, dict):
                continue
            chart_id = chart.get("chart_id")
            if not chart_id:
                continue
            title_override = chart.get("title") or chart.get("chart_title") or None
            entry_id = f"dc_{uuid.uuid4().hex[:10]}"

            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO public.quantyx_dashboard_charts
                          (entry_id, dashboard_id, chart_id, position, title_override, added_at)
                        VALUES (%s, %s, %s, %s, %s, now())
                        ON CONFLICT (dashboard_id, chart_id) DO NOTHING
                    """, [entry_id, dashboard_id, chart_id, position, title_override])
                    if cur.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1
                conn.commit()
            except psycopg2.errors.ForeignKeyViolation:
                # chart_id not in quantyx_chart_requests — skip orphan
                conn.rollback()
                skipped += 1

    print(f"  Inserted: {inserted} chart-dashboard links")
    print(f"  Skipped:  {skipped} (already existed or orphan chart_id)")
finally:
    conn.close()
PYEOF
log "Step 8: Done."

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
log "============================================================"
log "Migration complete. Verification queries:"
log ""
psql -v ON_ERROR_STOP=1 <<'SQL'

SELECT
  dashboard_type,
  COUNT(*) AS dashboard_count
FROM public.quantyx_dashboards
GROUP BY dashboard_type
ORDER BY dashboard_type;

SELECT COUNT(*) AS dashboard_chart_links
FROM public.quantyx_dashboard_charts;

SELECT
  chart_source,
  COUNT(*) AS chart_count
FROM public.quantyx_chart_requests
GROUP BY chart_source
ORDER BY chart_source;

SQL

log "============================================================"
log "Next steps (manual, after smoke-testing the new tables):"
log "  1. Deploy updated store layer (dashboards_store.py)"
log "  2. Deploy updated API (main.py)"
log "  3. Validate GET /dashboards returns both system and user dashboards"
log "  4. Once validated, retire old tables:"
log "       DROP TABLE public.quantyx_user_dashboard_charts;"
log "       DROP TABLE public.quantyx_user_dashboards;"
log "       DROP TABLE public.quantyx_dashboard_specs;"
log "============================================================"