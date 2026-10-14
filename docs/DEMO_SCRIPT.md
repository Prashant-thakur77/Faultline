# Demo video script (≤ 3:00)

How it is recorded:
- **Source.** Every shot comes from a real run in the UI (live), from the labelled replay at `/replay/s2-data-incident`, or from `evals/RESULTS.md` rendered verbatim (`frontend/public/media/results.html`). Nothing is mocked: the UI has no switch that breaks GitHub reads, so the UNKNOWN-verification beat (S9) is shown from its eval result, labelled as such.
- **Recorder.** `frontend/scripts/record_demo_video.py` (Playwright) presses "Reset demo data" (re-arm, with its confirm step), runs S1, opens the Cypher panels, runs the S6 preflight, approves the flag and asks the brain. Caption numbers (G5 flow, preflight verdict, write-back n/m, S9, arms) are read from the page at record time, never typed in.
- **Numbers.** Numbers below are tagged claims checked against `evals/results/latest.json` (`make claims`). Third-party statistics are attributed on screen.
- **Format.** 1536×864 viewport (the 125 % zoom of a 1920×1080 screen), upscaled to 1080p H.264; captions are burned in and also exported to `docs/video_captions.srt`. Length 3:00 exactly.

**Before recording:**
1. `make up && make seed`, then start the API on :8400 and the production UI (`npm run build && npx next start -p 3100`).
2. Wait a minute after any manual reset (it is rate-limited to 1/min); the recorder resets itself.
3. `.venv/bin/python frontend/scripts/record_demo_video.py --ui http://localhost:3100 [--gif]` (`--gif` regenerates `docs/media/hero.gif` from the gate beats).

| Time | On screen | Caption |
|---|---|---|
| 0:00–0:06 | Title card | "Faultline: an on-call agent whose brain is a FalkorDB graph. The model suggests; a read-only query decides." |
| 0:06–0:11 | **Reset demo data** (re-arm) in the top bar: `tenant_acme` restored from `golden_acme` | "Reset: restore the tenant graph from its golden copy." |
| 0:11–0:20 | Run **S1** from the launcher; the stage rail moves INTAKE → RECALL → … → paused, awaiting approval | "Run S1, “Checkout errors are spiking”, with the keyless baseline investigator …" |
| 0:20–0:28 | Memory card: payment incidents recalled through the vector index and a shared symptom node; fix history | "First it remembers: past payment incidents found in FalkorDB's vector index and confirmed through a shared symptom node, never similarity alone." |
| 0:28–0:36 | Graph view in **Ripple** mode: payment red, the blast radius yellow hop by hop | "algo.BFS shows what breaks: payment red, the blast radius yellow, hop by hop." |
| 0:36–0:48 | Gate: `D-rec-12` rejected by **G2**; Cypher panel → Q-GATE-1 → **Re-run (read-only)** → 0 rows | "Three changes in the window. The recommendation deploy has no causal path to checkout: Q-GATE-1 returns 0 rows. No path, no claim." |
| 0:48–0:58 | `D-email-88`: **G5** flow bar, max flow <!-- claim:s1.D-email-88.max_flow -->0.02<!-- /claim --> vs needed <!-- claim:s1.D-email-88.needed -->0.2433<!-- /claim --> | "The email deploy shipped in the same minute and has a path. But algo.maxFlow says it carries at most 0.0200; 0.2433 is needed. Rejected, with proof." | <!-- noclaim: narration repeats the values tagged in this row -->
| 0:58–1:11 | **Path** mode: D-pay-417 → payment → checkout lit edge by edge; G2 Cypher panel → **PROFILE** with engine ms | "algo.SPpaths: D-pay-417 → payment → checkout, lit edge by edge. Every claim carries its Cypher, with PROFILE engine time." |
| 1:11–1:22 | **S2** recorded replay at 8×: cutover traced into the revenue lineage; the FX feed rejected by flow (<!-- claim:s2.D-fx-pause-7.max_flow -->0.0692<!-- /claim --> < <!-- claim:s2.D-fx-pause-7.needed -->0.8<!-- /claim -->) | "Same graph, data incident (recorded replay): … the stale FX feed is ruled out by flow (0.0692 < 0.8000)." | <!-- noclaim: narration repeats the values tagged in this row -->
| 1:22–1:36 | **`/preflight` → S6** (starts at 1:22, rubric C2): verdict **<!-- claim:s6.verdict -->block<!-- /claim -->**, path to checkout, ADR-012/013 contradicted, required reviewers, PR comment preview | "Better still: the same graph scores the risky pull request before it ships …" then "Preflight verdict: block. The same graph that explained the outage gates the next change before it merges." |
| 1:36–1:45 | Back to the incident. Containment: min-cut, what-if on a GRAPH.COPY branch: "contains" | "Back to the incident. algo.maxFlow finds the smallest cut; a what-if on a GRAPH.COPY branch checks that it contains the failure first." |
| 1:45–1:53 | Who fixes it: ranked people with reasons, bus factor, escalation tree | "Who fixes it: the people who wrote this code and fixed the last outages here, ranked by harmonic centrality; bus factor and escalation tree." |
| 1:53–2:03 | Choose the flag → exact diff, commit message, reviewers, plan hash | "Choosing isn't approving: the server renders the exact diff, the PR body with reviewers, and the plan hash first." |
| 2:03–2:18 | Approve → EXECUTE → VERIFY → **APPLIED** (GitHub main re-read, telemetry back in band, no collateral) → write-back **verified <!-- claim:s1.writeback -->7/7<!-- /claim -->** → RESOLVED | "Approve this exact change …" then "APPLIED: GitHub main re-read and telemetry back in band, no collateral. Write-back verified 7/7; the incident becomes memory." | <!-- noclaim: narration repeats the values tagged in this row -->
| 2:18–2:29 | `evals/RESULTS.md` (rendered verbatim), the **S9 unknown verification** line highlighted: verdict <!-- claim:s9.verdict -->UNKNOWN<!-- /claim -->, success written = <!-- claim:s9.success_written -->False<!-- /claim -->; reconciler → <!-- claim:s9.reconciled -->[['at_main', 'APPLIED', '7/7']]<!-- /claim --> | "And when verification can't read GitHub (S9, an eval run; the GitHub read times out): verdict UNKNOWN, success written = False. Never a silent success: a later reconciler pass re-reads main → APPLIED 7/7. (evals/RESULTS.md)" | <!-- noclaim: narration repeats the values tagged in this row -->
| 2:29–2:40 | `/brain`: "What breaks if productcatalog goes down?" → cited chips, citation guard ✓ | "And it's the team's memory: every node an answer cites was read by that question's own queries, or the answer is withheld." |
| 2:40–2:54 | `evals/RESULTS.md` arms table; **A3-noG5** and **A4** rows outlined. A4 = <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> confirmed causes; A3-noG5 top-1 <!-- claim:arm.A3-noG5.top1 -->0.8<!-- /claim -->; naive recency top-1 <!-- claim:arm.N.top1 -->0.1<!-- /claim -->; graph (A3) top-1 <!-- claim:arm.A3.top1 -->1.0<!-- /claim --> | "Switch FalkorDB off (A4): no cause is confirmed. Switch off only the max-flow check (A3-noG5): top-1 falls. Naive recency and vector similarity guess wrong. The graph gets every one. (evals/RESULTS.md)" |
| 2:54–3:00 | End card (title card) | "Faultline: no path, no claim. Verify it yourself: make judge-check." |

**Notes:**
- The LLM arms have not run (no approved budget). The video does **not** claim LLM-vs-graph numbers until `latest.json` has them.
- Warm memory did not reduce tool calls for the deterministic investigator (<!-- claim:memory.cold_tool_calls -->17<!-- /claim --> → <!-- claim:memory.warm_tool_calls -->17<!-- /claim -->). Show the warm effect as ordering and runbook, never as "fewer steps".
- The S9 beat is an eval result, not a UI state: the eval makes the verifier's GitHub read time out (`evals/harness.py`, `_bad_fix_and_unknown`). There is no UI or API switch to stage it live, and the video does not fake one.
- `D-pay-417` exists only in the run's own graph (`eval_acme_…`), not in `tenant_acme`; the FalkorDB Browser screenshots in `docs/media/` therefore show the payment → frontend-proxy failure path on `tenant_acme` instead.
