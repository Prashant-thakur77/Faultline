# Incident inc-s1-b0472ed3: 

**Cause (gate-accepted):** `D-pay-417` · confident: **True**

**Mechanism (G2 path):** `D-pay-417` → `payment` → `checkout`

## Proven (each claim backed by a passed gate check)

- G1 grounded: cause seen in a graph result this run; all cited evidence produced by this run
- G2 path: D-pay-417 → payment → checkout
- G3 time: change 3.0 min before onset (window 30 min)
- G4 quantitative: ev_9dc2e8c800 on checkout; ev_d3ce0adb65 on payment [ev_9dc2e8c800, ev_d3ce0adb65]
- G4 origin: ev_d3ce0adb65 on payment [ev_d3ce0adb65]
- G4 upstream: no anomalous component upstream can carry the changed component's excess [ev_0d9b87053a]
- G5 sufficiency: checkout: max flow 1.0000 ≥ needed 0.2433 [ev_d3ce0adb65, ev_edbfd9c531]
- G6 competitors: every competitor eliminated with evidence
- G7 agreement: independent channels on the chain: ['falkordb', 'simulator']
- G7 correlation: change and code specialists both name D-pay-417 (CHANGED → payment)

## Inferred / not established

- (none)

## Contradictions (active decisions the cause violates; G8 attaches, never blocks)

- violates ADR-012: payment.client.timeout_ms <= 2000 (actual 5000); violates ADR-013: payment.client.retries >= 2 (actual 0)

## Why alerts missed it (alert coverage along the causal chain)

first alert at hop 2 of 3 (payment); hops before it were silent: D-pay-417

| hop | node | alerted | first alert after onset (s) |
|---|---|---|---|
| 1 | `D-pay-417` | no | — |
| 2 | `payment` | yes | -60 |
| 3 | `checkout` | yes | -60 |

## Ownership when the change shipped

payment was owned by team-payments when D-pay-417 shipped and still is.

## Residue check (advisory; does not change the verdict)

the confirmed cause explains 3 of 4 anomalous components; another fault may be active: recommendation.

## Learned remediation ordering (reorders options only)

- history: rollback worked 6/6 times on past incidents sharing a symptom with this one (smoothed success 0.88)
- history: flag paymentGate → off worked 4/5 times on past incidents sharing a symptom with this one (smoothed success 0.71)

## Futures (each option predicted on its own GRAPH.COPY branch before approval, Q-FUTURE-1)

| option | predicted | why | verified | came true |
|---|---|---|---|---|
| roll back D-pay-417 | contains | contains if the confirmed cause is the cause (removing the origin's fault; assumed, not measured) [ev_cfe3b16bdb] | — | — |
| flag paymentGate → off | contains | contains: every symptom predicted back in band; leaves kpi.exec_revenue exposed [ev_cfe3b16bdb] | — | — |
| open an issue for D-pay-417 | does not contain | does not contain: checkout residual 0.4029 over its band, frontend residual 0.4029 over its band; leaves frontend-proxy, kpi.exec_revenue exposed [ev_cfe3b16bdb] | — | — |

## Obligations at risk (obligation clock; decides urgency, never the cause)

**URGENT: page now.** slo-checkout (checkout) runs out of error budget in ~605 min at 30.7x burn (43% of budget left); under the 1440-min paging line; 5 customers reached, 28,600 MRR at risk. [ev_881a6ca427]

| SLO | service | objective | error rate now | burn | budget left | time to breach |
|---|---|---|---|---|---|---|
| `slo-payment` | `payment` | 99.0% | 30.91% | 30.9x | 75% | ~17.4 h |
| `slo-checkout` | `checkout` | 99.0% | 30.69% | 30.7x | 43% | ~10.1 h |
| `slo-frontend` | `frontend` | 99.0% | 1.75% | 1.8x | 52% | ~8.8 days |
| `slo-frontend-proxy` | `frontend-proxy` | 99.0% | 1.46% | 1.5x | 63% | ~13.0 days |

Customers reached through the failure: 5 (each counted once), 28,600 MRR at risk.

| customer | MRR | reached through | nearest failure path |
|---|---|---|---|
| `cust-orion-optics` Orion Optics Ltd (synthetic) | 12,000 | `checkout` (checkout API (PlaceOrder)), `frontend` (storefront web) | `payment` → `checkout` |
| `cust-lyra-labs` Lyra Labs (synthetic) | 9,000 | `checkout` (checkout API (PlaceOrder)) | `payment` → `checkout` |
| `cust-vega-schools` Vega Schools Network (synthetic) | 4,000 | `frontend` (storefront web) | `payment` → `checkout` → `frontend` |
| `cust-pavo-partners` Pavo Partners (synthetic revenue-share partner) | 3,000 | `kpi.exec_revenue` (monthly revenue-share statement) | `payment` → `raw.raw_orders` → `staging.stg_orders` → `marts.fct_revenue` → `marts.exec_revenue_metric` → `kpi.exec_revenue` |
| `cust-cygnus-club` Cygnus Stargazers Club (synthetic) | 600 | `frontend-proxy` (public web) | `payment` → `checkout` → `frontend` → `frontend-proxy` |

## Rejected by the gate (first-class, with the failing checks)

- `D-email-88` (sweep, gr-inc-s1-b0472ed3-d2668e95): G5 sufficiency: G5: max flow 0.0200 < needed 0.2433 (observed 0.3041 × 0.8); another suspect alone can carry 1.0000
- `D-rec-12` (sweep, gr-inc-s1-b0472ed3-0db43d36): G2 path: G2: no path to any primary symptom (no path, no claim)

## Evidence

| id | kind | source | about | summary |
|---|---|---|---|---|
| ev_03b4535c58 | flow | falkordb | checkout, email | bound 0.0200 (max flow 0.0200, up to 1 path(s)) vs needed 0.2433 (insufficient) |
| ev_0d9b87053a | upstream | falkordb | payment | bound: no anomalous component upstream accounts for payment |
| ev_1a986a73de | path | falkordb | checkout, D-email-88 | D-email-88 → email → checkout |
| ev_5b8e92d948 | path | falkordb | checkout, D-rec-12 | no path D-rec-12 → checkout (≤ 8 hops) |
| ev_9dc2e8c800 | error_rate | simulator | checkout | checkout error rate 30.69% vs baseline 0.69% (×44.5, band 1.5745) |
| ev_d3ce0adb65 | error_rate | simulator | payment | payment error rate 30.91% vs baseline 0.71% (×43.6, band 1.4575) |
| ev_d9c05ffae8 | path | falkordb | checkout, D-pay-417 | D-pay-417 → payment → checkout |
| ev_edbfd9c531 | flow | falkordb | checkout, payment | bound 1.0000 (max flow 1.0000, up to 1 path(s)) vs needed 0.2433 (sufficient) |
