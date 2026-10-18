# Incident inc-s2-2defc7b1: CONFIRMED

**Cause (gate-accepted):** `D-cutover-1` · confident: **True**

**Mechanism (G2 path):** `D-cutover-1` → `payment` → `raw.raw_orders` → `staging.stg_orders` → `marts.fct_revenue` → `marts.exec_revenue_metric` → `kpi.exec_revenue`

## Proven (each claim backed by a passed gate check)

- G1 grounded: cause seen in a graph result this run; all cited evidence produced by this run
- G2 path: D-cutover-1 → payment → raw.raw_orders → staging.stg_orders → marts.fct_revenue → marts.exec_revenue_metric → kpi.exec_revenue
- G3 time: change 40.0 min before onset (window 60 min)
- G4 quantitative: ev_201daec0f6 on marts.fct_revenue; ev_41900686e1 on staging.stg_orders; ev_7cf2442039 on kpi.exec_revenue; ev_7cf2442039 on marts.exec_revenue_metric [ev_201daec0f6, ev_41900686e1, ev_7cf2442039, ev_7cf2442039]
- G4 origin: ev_201daec0f6 on marts.fct_revenue; ev_41900686e1 on staging.stg_orders; ev_7cf2442039 on marts.exec_revenue_metric [ev_201daec0f6, ev_41900686e1, ev_7cf2442039]
- G4 upstream: no anomalous component upstream can carry the changed component's excess [ev_a558c98853]
- G5 sufficiency: kpi.exec_revenue: max flow 1.0000 ≥ needed 0.8000 [ev_41900686e1, ev_f7f81dcffd]
- G6 competitors: every competitor eliminated with evidence
- G7 agreement: independent channels on the chain: falkordb, warehouse
- G7 correlation: change and data specialists both name D-cutover-1 (CHANGED → payment)

## Inferred / not established

- (none)

## Why alerts missed it (alert coverage along the causal chain)

first alert at hop 7 of 7 (kpi.exec_revenue); hops before it were silent: D-cutover-1, payment, raw.raw_orders, staging.stg_orders, marts.fct_revenue, marts.exec_revenue_metric

| hop | node | alerted | first alert after onset (s) |
|---|---|---|---|
| 1 | `D-cutover-1` | no | — |
| 2 | `payment` | no | — |
| 3 | `raw.raw_orders` | no | — |
| 4 | `staging.stg_orders` | no | — |
| 5 | `marts.fct_revenue` | no | — |
| 6 | `marts.exec_revenue_metric` | no | — |
| 7 | `kpi.exec_revenue` | yes | 0 |

## Ownership when the change shipped

payment was owned by team-payments when D-cutover-1 shipped and still is.

## Residue check (advisory; does not change the verdict)

the confirmed cause explains 4 of 4 anomalous components.

## Learned remediation ordering (reorders options only)

- history: data repair worked 6/6 times on past incidents sharing a symptom with this one (smoothed success 0.88)

## Futures (each option predicted on its own GRAPH.COPY branch before approval, Q-FUTURE-1)

| option | predicted | why | verified | came true |
|---|---|---|---|---|
| open an issue for D-cutover-1 | unknown | unknown: kpi.exec_revenue (no baseline windows) [ev_984714dc7c] | — | — |
| flag paymentGate → off | unknown | unknown: kpi.exec_revenue (no baseline windows) [ev_984714dc7c] | — | — |

## Obligations at risk (obligation clock; decides urgency, never the cause)

Urgency unknown: unmeasured: none of the 4 SLOs in the blast radius has current telemetry, so the time to breach is unknown; 5 customers reached, 28,600 MRR at risk. [ev_03e17dace3]

| SLO | service | objective | error rate now | burn | budget left | time to breach |
|---|---|---|---|---|---|---|
| `slo-checkout` | `checkout` | 99.0% | — | — | 43% | no breach projected |
| `slo-frontend` | `frontend` | 99.0% | — | — | 52% | no breach projected |
| `slo-frontend-proxy` | `frontend-proxy` | 99.0% | — | — | 64% | no breach projected |
| `slo-payment` | `payment` | 99.0% | — | — | 75% | no breach projected |

Customers reached through the failure: 5 (each counted once), 28,600 MRR at risk.

| customer | MRR | reached through | nearest failure path |
|---|---|---|---|
| `cust-orion-optics` Orion Optics Ltd (synthetic) | 12,000 | `checkout` (checkout API (PlaceOrder)), `frontend` (storefront web) | `payment` → `checkout` |
| `cust-lyra-labs` Lyra Labs (synthetic) | 9,000 | `checkout` (checkout API (PlaceOrder)) | `payment` → `checkout` |
| `cust-vega-schools` Vega Schools Network (synthetic) | 4,000 | `frontend` (storefront web) | `payment` → `checkout` → `frontend` |
| `cust-pavo-partners` Pavo Partners (synthetic revenue-share partner) | 3,000 | `kpi.exec_revenue` (monthly revenue-share statement) | `payment` → `raw.raw_orders` → `staging.stg_orders` → `marts.fct_revenue` → `marts.exec_revenue_metric` → `kpi.exec_revenue` |
| `cust-cygnus-club` Cygnus Stargazers Club (synthetic) | 600 | `frontend-proxy` (public web) | `payment` → `checkout` → `frontend` → `frontend-proxy` |

## Rejected by the gate (first-class, with the failing checks)

- `D-fx-pause-7` (sweep, gr-inc-s2-2defc7b1-1d527e29): G5 sufficiency: G5: max flow 0.0692 < needed 0.8000 (observed 1.0000 × 0.8); another suspect alone can carry 1.0000

## Evidence

| id | kind | source | about | summary |
|---|---|---|---|---|
| ev_201daec0f6 | baseline_comparison | warehouse | marts.fct_revenue | worst day ratio ×100.0 (band 1.377); anomalous days: ['2026-08-09', '2026-08-08', '2026-08-07'] |
| ev_299133ee43 | path | falkordb | kpi.exec_revenue, D-cutover-1 | D-cutover-1 → payment → raw.raw_orders → staging.stg_orders → marts.fct_revenue → marts.exec_revenue_metric → kpi.exec_r |
| ev_41900686e1 | row_share | warehouse | staging.stg_orders.amount, staging.stg_orders | 327/327 rows of staging.stg_orders.amount on 2026-08-09 outside baseline range [5.0, 1114.51] → share 1.0 |
| ev_7cf2442039 | metric | warehouse | kpi.exec_revenue, marts.exec_revenue_metric | KPI 2026-08-09: 2,737,324 vs expected 29,349 (×93.27, band 1.377) |
| ev_99167a4ab6 | flow | falkordb | kpi.exec_revenue, raw.raw_fx_rates | bound 0.0692 (max flow 0.0692, up to 1 path(s)) vs needed 0.8000 (insufficient) |
| ev_a558c98853 | upstream | falkordb | payment | bound: no anomalous component upstream accounts for payment |
| ev_eae6fb8db2 | path | falkordb | kpi.exec_revenue, D-fx-pause-7 | D-fx-pause-7 → raw.raw_fx_rates → staging.stg_fx_rates → marts.fct_revenue → marts.exec_revenue_metric → kpi.exec_revenu |
| ev_f7f81dcffd | flow | falkordb | kpi.exec_revenue, payment | bound 1.0000 (max flow 1.0000, up to 1 path(s)) vs needed 0.8000 (sufficient) |
