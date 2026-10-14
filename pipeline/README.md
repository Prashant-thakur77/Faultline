# Faultline demo data fixture

This directory contains a **deterministic synthetic scenario** — a compact retail
data pipeline built for the Faultline demo. None of the data is real. Every run is
byte-identical: "today" is pinned to `ANCHOR_DAY = 2026-08-09` and everything is
driven by a single RNG seed (42). No wall clock is consulted anywhere.

## What it models

90 days of orders (~400/day) for a small retailer, with customers and daily FX
rates, flowing through staging into a daily revenue mart and a single-row
executive KPI. On **2026-08-07T00:00Z** the business migrates payment
processing to `cloudpay_v2` — this migration is real and happens in *both*
modes.

## The seeded incident

In `--mode incident`, rows processed by `cloudpay_v2` report `amount` as
**integer cents** instead of decimal dollars (49.99 becomes 4999). The schema
stays valid and nothing crashes — the daily revenue metric silently inflates
~100x from the cutover onward. In `--mode healthy` the same rows carry decimal
dollars. That encoding step is the *only* difference between modes; all
pre-cutover rows are byte-identical across modes.

A deliberate **distractor** exists in both modes: the FX rates feed stops
updating after 2026-08-05 (stale feed). It is suspicious but cannot explain
the jump — non-USD is ~7% of revenue and staleness moves rates by well under 2%.

Nothing in the pipeline, tests, or metadata hardcodes the answer; the incident
is discoverable only from the data (e.g. per-processor amount profiles).

## Lineage

    raw_orders.csv    --> raw.raw_orders    --> staging.stg_orders ----+
                                                                       +--> marts.fct_revenue --> marts.exec_revenue_metric
    raw_fx_rates.csv  --> raw.raw_fx_rates  --> staging.stg_fx_rates --+
    raw_customers.csv --> raw.raw_customers --> staging.stg_customers      (dimension; not on the revenue path)

## Layout

- `generate_sources.py` — writes `data/sources/*.csv` (gitignored, regenerated)
  and `data/warehouse/.fixture_mode` (mode marker for eval tooling only).
- `run.py` — loads CSVs into DuckDB (`data/warehouse/faultline.duckdb`, schemas
  `raw` / `staging` / `marts`), runs `transforms/*.sql` in order, writes
  `data/warehouse/metric_snapshot.json`.
- `transforms/` — SQL, executed in order: `stg_orders`, `stg_customers`,
  `stg_fx_rates` (forward-fills stale rates), `fct_revenue`, `exec_revenue_metric`.
- `baselines/` — **committed** healthy-run observability record
  (`daily_revenue_baseline.json`, `profile_baseline.json`); regenerate with
  `make baselines` (runs in a temp dir, never clobbers `data/`).
- `invariants/test_invariants.py` — 32 pytest invariants against the warehouse.

## How to run / reset

```bash
make setup         # uv sync
make demo-reset    # seed the INCIDENT fixture + rebuild the warehouse
make demo-healthy  # seed the healthy fixture + rebuild the warehouse
make build         # rebuild the warehouse from existing CSVs
make test          # run the invariants
```

Expected: healthy mode passes all 32 invariants. Incident mode fails exactly 7
(AOV and continuity for Aug 7-9, plus the max-USD-amount bound) while
historical immutability still passes.
