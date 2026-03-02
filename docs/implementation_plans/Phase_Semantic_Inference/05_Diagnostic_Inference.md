# Phase 5: Diagnostic / "Why" Inference

## Objective
Explain *why* a metric changed using deltas + driver correlations.

## Inputs
- Resolved metric
- Baseline windows (A vs B)
- Candidate drivers (dimensions + related metrics)

## Outputs
- Ranked drivers
- Explanation text
- Inference summary persisted

## Step-by-Step
1) **Intent detection**
   - "why", "down", "drop" → diagnostic
2) **Metric resolution**
   - Deterministic graph resolution
3) **Baseline selection**
   - Default: last 7 days vs previous 7 days
4) **Driver selection**
   - Pull top dimensions from semantic graph
   - Include operational metrics like downtime/rejects
5) **Delta computation**
   - For each driver, compute delta + % change
6) **Correlation**
   - Correlate driver changes with metric drop
7) **Explanation**
   - Combine top drivers into natural language
8) **Persist**
   - Save inference summary for future reuse

## Diagnostic SQL Templates
- Metric delta by driver
- Correlation between production and downtime

## Success Metrics
- Explanation coverage for top drivers
- User-confirmed explanations > 70%

