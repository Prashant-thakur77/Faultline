# Scenario numbers and the meaning of `cap` (design note, pre-event; revised after the adversarial review)

## 1. What `cap` means, and what G5 can and cannot claim

**Two definitions were rejected.**
- *rps share* rejects true causes under synchronous fan-out: payment carries ~11% of checkout's calls, yet 100% of orders need it.
- *dependency share (criticality × share of the target's requests that call the source)* is not a sound bound. It fails under:
  - **fan-in**: the share is unconditioned across callers, e.g. cap(X→product-catalog) = 120/1020 while checkout depends on X 100%;
  - **call multiplicity**: 3 calls per order gives 1−0.7³ ≠ 0.3;
  - **value share in lineage**, which does not bound a magnitude change. A 7%-of-value input can still move the KPI 93×.

**Adopted (decision of record):**
- **Service edges:** `cap = criticality` ∈ {1.0 synchronous, error-propagating; 0.02 best-effort or async}. It is a property of the call type, taken from the topology file and justified per edge. It is never a traffic share.
- **Lineage edges:** `cap = row share`, the fraction of the downstream table's rows that are derived from rows of the input. The FX feed only touches non-USD rows. This is computed by SQL at export time and committed in the JSON with the SQL that produced it.
- **Observed impact share, service:** `(err_now − err_base) / (1 − err_base)` at the symptom. The baseline error rate is removed.
- **Observed impact share, data:** the **anomalous-row share** of the symptom's input on the incident day: the share of rows whose value lies outside the baseline robust range (pre-onset [p0.1, p99.9] of the same column). It comes from a deterministic data tool `anomalous_row_share(table, column, day)` and is recorded as Evidence. It never comes from the model.

**What the gate claims (README "Honest limits", verbatim intent):** "G5 is an upper bound under a single-cause assumption with criticality caps. A best-effort dependency can explain at most its criticality share of failures. A lineage input can corrupt at most its row share of rows."
- The multi-cause case is handled by the joint test below, not by the bound.
- Repeated best-effort calls raise the true share to 1−(1−ε)^k. That is a documented limit; ε = 0.02 with k ≤ 3 gives ≤ 0.06, still far below S1's 0.326.

**Proof sketch (services; this is what the claim rests on).**
1. Read `cap(u→v)` as the per-call conditional probability that a failure at u turns a calling v-request into a failure (criticality), with multiplicity k = 1.
2. Along a path, the probability that a symptom request fails through that path is the product of caps, which is ≤ the minimum cap.
3. Every failure chain from s to t crosses some edge of any s–t cut C. By the union bound, P(t-request fails because of s) ≤ Σ_{e∈C} cap(e). The minimum over cuts is the min-cut, which equals `maxFlow` (s→t).
4. With k calls per request over a best-effort edge, the share is 1−(1−ε)^k ≤ kε, so the bound is scaled by `k_max` (≤ 3 in our topologies; documented).

The **joint test below is a decision rule, not a bound.**

**Lineage caps are end-to-end, on the same row population as the observation.**
- Population: the *contributing rows* of the symptom (for the revenue KPI, the completed order rows of the KPI day that feed `fct_revenue`).
- An input's cap is the share of that population derived from (or joined with) the input. It is computed by one SQL relative to the symptom's population and stored on the edge **into** the table where the join happens.
- Every upstream lineage edge has cap 1.0. That makes min-along-path equal to the end-to-end share and avoids the filter/select amplification hole (A→B 0.01 followed by a B→C filter that keeps only A rows).
- The static cap = max(baseline share, incident-day share). For FX: max(0.0692, 0.0459) = 0.0692.
- The observed anomalous-row share is measured on **the same population** (the KPI day's contributing order rows: 327/327 = 1.0).

**maxFlow source and sink.**
- The source is the changed node (the target of `CHANGED`/`GATES`). `CHANGED`/`GATES` also carry `cap: 1.0`, so a run that starts from the Deploy node gives the same result.
- The sink is the symptom node.

**Joint G5 with a fixpoint (multi-cause safe, order-independent).**
- Let `S` = suspects that still pass G2–G4. Repeat until `S` stops changing:
  - eliminate s ∈ S if `maxFlow({s}) < observed × slack` **and** `maxFlow(S∖{s}) ≥ observed × slack` (one multi-source `algo.maxFlow` with `sourceNodes:[...]`);
  - the comparison set is always re-computed from the current `S`.
- If no single suspect is sufficient but `S` jointly is, the incident is **multi-cause**: `confident=false`, and those suspects are `unresolved`.
- If even `S` is insufficient, abstain (unknown cause; S12).

**Several alerts.**
- Alerts that lie downstream of the primary symptom (reachable from it over `PROPAGATES_TO`) are consequences and are not G5-tested separately.
- Each **independent** alert gets its own G5 verdict.
- A suspect is eliminated only for the alerts where it fails, and stays a candidate for any alert where it passes.
- The primary symptom is the most specific alerting node (no upstream alert on a path to it). This closes the "frontend symptom lets email pass" hole without killing true causes of separate alerts.

**Tests.**
- `tests/gate/test_g5.py`: single cause + distractor; two half-causes → multi-cause; no sufficient suspect → abstain; boundary at exactly `observed × slack` → pass; fixpoint order-independence (permute suspect order → same verdicts); multi-alert independence.
- `tests/gate/test_g5_bound_property.py`: random **DAGs with fan-in, reconvergent paths and multiplicity k ≤ 3**, a single injected cause, simulated requests. Assert `maxFlow · k_max ≥ empirical failure share` in every trial.

## 2. S2: existing data incident (measured on the existing fixture, incident mode, 2026-10-13)

| Quantity | Value | Source |
|---|---|---|
| KPI day | 2026-08-09 | `marts.exec_revenue_metric` |
| KPI revenue / trailing-28d median | 2,737,323.5 / 29,349.39 (93.27×) | same |
| Completed orders on the KPI day | 327 | `staging.stg_orders` |
| KPI-day contributing order rows (completed, feeding `fct_revenue`) above the pre-cutover maximum amount (1,114.51) | 327 / 327 = **1.000** | anomalous-row share, same population as the FX cap |
| Non-USD row share (pre-cutover completed / KPI day) | **0.0692** / 0.0459 | `stg_orders.currency <> 'USD'` |
| cloudpay_v2 share of post-cutover completed orders | 100% (1,010 rows) | `stg_orders` |

**Lineage caps (row share).**
- `raw_orders → stg_orders` 1.0
- `stg_orders → fct_revenue` 1.0
- `raw_fx_rates → stg_fx_rates` 1.0
- `stg_fx_rates → fct_revenue` **0.0692** = max(baseline 0.0692, incident-day 0.0459) share of contributing order rows that join a non-unit FX rate (end-to-end, relative to the KPI's contributing rows)
- `fct_revenue → exec_revenue_metric` 1.0
- Cross-domain: `payment -EMITS-> raw_orders` 1.0

**Gate outcomes on S2.**
- **G5, FX distractor:** 0.0692 < 1.000 × 0.8, and the remaining suspects jointly reach 1.0. **Eliminated.** Narration: "the FX feed can touch at most 6.9% of the rows; 100% of today's rows are anomalous."
- **G5, cutover:** 1.0 ≥ 0.8, so it passes.
- **G2 path:** `D-cutover-1 -CHANGED-> payment -PROPAGATES_TO-> raw_orders → stg_orders → fct_revenue → exec_revenue_metric` is 5 edges. The KPI node adds 1, giving 6. `gate.max_len` is 8, so a Dashboard symptom (7) still fits with margin. Justification: the longest seeded propagation chain is 7.

**S4 data control (healthy mode):** the same cutover exists and a path exists, but anomalous-row share = 0 and every metric on the path is in band. Q-NEG-1 gives NO_INCIDENT, three-valued (ready, completed, ids known).

## 3. S1: hero (acme, OTel Demo topology; generated by the simulator in M4)

**Traffic matrix** (rps; entry frontend-proxy = 1000; used for blast-radius impact scoring and `cut_cost`, never for `cap`):
- frontend-proxy → frontend 900, image-provider 80, chatbot 10, flagd-ui 10
- frontend → product-catalog 600, currency 400, recommendation 300, ad 250, cart 200, shipping 50, checkout 40
- checkout → payment, cart, currency, shipping, email, queue 40 each; product-catalog 120
- recommendation → product-catalog 300 · shipping → quote 90 · cart → cache 240 · product-catalog → astronomy-db 1020 · queue → accounting 40, fraud-detection 40

**Caps (criticality):** every synchronous call 1.0. `checkout → email` 0.02 (best-effort confirmation; verify against the demo's checkout source in M1). `checkout → queue` 0.02 (async).

**Injected effect.** `D-pay-417` makes payment `charge` fail 41%. The alert fires on checkout error rate. The baseline error at checkout is 0.5%, so observed = (0.41 − 0.005)/(1 − 0.005) ≈ **0.407**. Slack 0.8 gives the threshold ≈ 0.326.

| Change (same 5-minute window) | Target | G2 path to checkout | G5 single / joint | Verdict |
|---|---|---|---|---|
| `D-pay-417` (14:02) | payment | yes, 2 hops | 1.0 ≥ 0.326 | **confirmed** (G3 time, G4 metric on the path, G7 agreement) |
| `D-email-88` (14:02) | email | yes, 2 hops | 0.02 < 0.326, and the others (payment) reach 1.0 | **eliminated by G5**: "a path is not enough" |
| `D-rec-12` (14:01; recommendation cache noise) | recommendation | **none** (recommendation feeds frontend, never checkout) | — | **eliminated by G2**: "no path, no claim" |

All three are evaluated by the deterministic **competitor sweep** at GATE (§6.4 extension), which writes one GateRun row per competitor. The on-camera rejection therefore never depends on the model choosing to test the distractor.

**Containment: a non-trivial, cross-domain min-cut.** The protected set is {frontend-proxy (storefront entry), `exec_revenue_metric` (the executive KPI)}. The failing component is payment. Failure reaches the storefront via payment → checkout → frontend → frontend-proxy, and reaches the KPI via payment -EMITS-> raw_orders → … → KPI. `algo.maxFlow` with `targetNodes:[frontend-proxy, exec_revenue_metric]` and `cut_cost` capacities gives a **2-edge cut**:
- **Service cut:** flag on checkout's payment endpoint (degrade checkout only).
- **Data cut:** hold or quarantine payment-emitted rows from cloudpay at `stg_orders`, so the KPI never ingests failed charges.

`cut_cost = traffic share × tier weight` (weights.yaml), derived, not hand-set. The what-if on a GRAPH.COPY branch (BFS + WCC) shows browse, cart and recommendation still connected to the entry.

## 4. Numbers that will be claimed

None of the above are claims. They are design inputs. README and video numbers come only from `evals/results/latest.json` via `make claims`.
