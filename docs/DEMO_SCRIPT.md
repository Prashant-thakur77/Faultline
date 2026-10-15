# Demo video script (3:00)

The thesis comes first: by 0:20 the video has shown a suspect deploy cleared because FalkorDB returns no causal path from it to the failing service. No path, no claim.

How it is recorded:
- **Source.** Every product shot comes from a real run in the UI. The cards (hook, proof charts, "try it", end) are static pages under `frontend/public/media/`. The charts are byte-identical copies of `docs/media/charts/`, drawn from `evals/results/latest.json` by `scripts/gen_charts.py`; the recorder refuses to run when a copy differs.
- **Recorder.** `frontend/scripts/record_demo_video.py` (Playwright). Before the kept footage starts (pre-roll, trimmed), it:
  - checks the API;
  - presses "Reset demo data (all visitors)" with its confirm step;
  - runs S1 from the launcher;
  - reads every value the captions will state.

  A missing element therefore fails the take before anything is recorded. The hook card is then laid over the finished incident room, so the room appears without a reload when the card lifts.
- **Numbers.** Every number in a caption is read from the page at record time or from `evals/results/latest.json`; none is typed into the recorder. Numbers below are tagged claims checked against `latest.json` (`make claims`). The one third-party statistic is attributed on screen.
- **Format.** 1536×864 viewport (the 125 % zoom of a 1920×1080 screen), upscaled to 1080p H.264, no voice. Captions are burned in and exported to `docs/video_captions.srt`. The cards' text goes into the .srt only, so screen-reader and caption users get it too. Length 3:00 exactly.

**Before recording:**
1. `make up && make seed`, start the API on :8400, then build and start the production UI (`npm run build && npx next start -p 3100`). Rebuild after any change under `frontend/public/`: the server only serves public files that were there at build time.
2. After `scripts/gen_charts.py`, copy the charts: `cp docs/media/charts/*.svg frontend/public/media/charts/`.
3. The GitHub CLI must be signed in. The recorder uses it to check:
   - the pull request it shows is merged;
   - the flag state at main of the demo infra repo;
   - the upstream issue's title and state.
4. Dry run on the simulated GitHub (writes only `tmp/demo-video/`):
   ```bash
   .venv/bin/python frontend/scripts/record_demo_video.py --ui http://localhost:3100 --api http://localhost:8400 --no-encode
   ```
5. Real take:
   - Start the API with `FAULTLINE_GITHUB=real` and `FAULTLINE_APPROVER_KEY`.
   - Run with the key file in the environment: `FAULTLINE_APPROVER_KEY_FILE=<file> .venv/bin/python frontend/scripts/record_demo_video.py --real-github [--gif]`.
   - The recorder refuses to start unless `paymentGate` is `on` at main of `faultline-demo-infra`; otherwise the action would be a no-op.
   - It types the key into the approver key field, which is a password field (masked with CSS if it ever were not). It never prints the key.
   - After a real take the flag is off at main. Turn it back on in that repo before another real take.

| Time | On screen | Caption |
|---|---|---|
| 0:00–0:08 | **Hook card** (`media/hook.html`, the site's near-black and Mona Sans): "Roughly 70% of outages come from changes" with its source (*Site Reliability Engineering*, Google, chapter 1), then "Two deploys land in the same minute. Which one broke checkout?" | (card text; .srt only) <!-- noclaim: third-party statistic, attributed on the card --> |
| 0:08–0:20 | The S1 incident room. Evidence gate → `D-rec-12` rejected by **<!-- claim:s1.D-rec-12.rejected_by -->G2<!-- /claim -->** → its Cypher panel → **Re-run (read-only)** → 0 rows | "Checkout is failing and several deploys are in the window. Could D-rec-12 be the cause? Ask FalkorDB for a causal path to checkout (Q-GATE-1), read-only." then "No path, no claim: FalkorDB returns no causal path from D-rec-12 to checkout (0 rows), so it cannot be blamed." |
| 0:20–0:32 | How the run got here: the stage timeline (left) and the **Crew** board, named agents claiming steps | "How it got here: a crew of least-privilege agents (*n* steps · *m* specialists, read from the board). Every step is a record in the graph: who claimed it, what it ran, who it handed to." |
| 0:32–0:44 | `D-email-88`: **G5** check with its flow bar, then its Cypher panel. Max flow <!-- claim:s1.D-email-88.max_flow -->0.0200<!-- /claim --> vs needed <!-- claim:s1.D-email-88.needed -->0.2433<!-- /claim --> | "D-email-88 shipped in the same minute and has a path. But algo.maxFlow says it can carry only *flow* of the *needed* needed. Rejected." (both numbers read from the G5 row) |
| 0:44–0:56 | **Path** mode, replayed: <!-- claim:s1.chain -->D-pay-417 → payment → checkout<!-- /claim --> lit edge by edge; then **Why do you believe this?** (provenance graph) | "The proof path, lit edge by edge: *chain*." then "Why do you believe this? Provenance from the verdict back to the tool calls and agents that produced each piece of evidence (*counts*), every arrow a stored edge." |
| 0:56–1:06 | Containment: the min-cut table and the what-if verdict; then **Who fixes it**, top person flashed | "Smallest containment: cut *edge* (algo.maxFlow min-cut). A what-if on a GRAPH.COPY branch checks it first: *contains*." then "Who fixes it: *name (id)* first, ranked by algo.HarmonicCentrality over who wrote this code and fixed past outages here." |
| 1:06–1:24 | Two-step approval, then the pull request on github.com:<ul><li>**Choose** "flag paymentGate → off", which shows the exact diff and the plan hash.</li><li>Real take: type the approver key (password field).</li><li>**Approve this exact action** → VERIFY → **APPLIED** → write-back verified <!-- claim:s1.writeback -->7/7<!-- /claim --> → **RESOLVED**.</li><li>Open the pull request the UI links on github.com, with its URL overlaid.</li></ul> | <ul><li>"Choosing isn't approving: the server first renders the exact diff, the PR body and the plan hash."</li><li>"Approve this exact action, bound to plan hash *hash*: if the plan changes, the server refuses it."</li><li>"*APPLIED*: GitHub main re-read and telemetry back in band. Write-back verified *n/m*: RESOLVED, and the incident becomes memory."</li><li>Real take: "A real pull request (#*n*), merged after two-step approval and verified through a second channel: APPLIED."</li><li>Simulated take: "This take used the simulated GitHub (labelled). The same path against real GitHub opened and merged this pull request (#1), verified APPLIED."</li></ul> <!-- noclaim: narration repeats the values tagged in this row --> |
| 1:24–1:36 | **Break it** (`/playground`): "Remove the call payment → checkout" → **Break it** → "What moved", the changed decision highlighted | "Break it: take one edge out of a GRAPH.COPY of the graph and run the product again." then "Take a graph edge away and the decision changes (*decision*: *before* → *after*). The graph is load-bearing." |
| 1:36–1:48 | `/preflight` → **S6** → verdict **<!-- claim:s6.verdict -->block<!-- /claim -->**, the ADRs it contradicts; then the **reversal guard** card ("catalog: off-peak migrations again" when S6 reinstates no reversed decision) | "Preflight verdict: block. It contradicts *ADR ids*. The same graph that explained the outage gates the next change." then "Reversal guard: a PR that puts back what *ADR* decided, which the team replaced with *ADR*, is named with the evidence (advisory; the verdict is unchanged)." |
| 1:48–2:00 | `/brain`: the question "Who decided the payment timeout, and are they still here?" is typed → answer with **citation guard ✓** → **Answer as a graph** | "The company brain: who owns, knows and decided what." then "It answers citing only nodes its own queries returned (citation guard), and draws the answer as a graph." |
| 2:00–2:36 | Proof charts, full screen, one after another (`media/proof.html`); this beat absorbs any slack so the end card lands on time | One caption per chart, numbers read from `latest.json` at record time (listed below) |
| 2:36–2:50 | The live deployment (`https://13-203-185-119.sslip.io`, URL overlaid) with its status panel; then `media/open.html`: the hosted MCP one-liner from [MCP.md](MCP.md) and FalkorDB#3349 with its title and state read from GitHub | "Live now at *host*: *engine*, *size*, read through a read-only ACL user." (from the live status panel) then "Any agent can query the same graph over hosted MCP (read-only, public demo key). Engine issues found along the way are filed upstream: FalkorDB#3349." |
| 2:50–3:00 | End card (`media/end.html`): "No path, no claim." · github.com/Prashant-thakur77/Faultline · `make judge-check` | (card text; .srt only) |

**Chart captions (2:00–2:36):**
- **Outcome.** "Right verdict on the scenario suite (<!-- claim:arm.A3.trials -->24<!-- /claim --> trials): Faultline <!-- claim:arm.A3.outcome_correct_rate -->100%<!-- /claim -->; telemetry only <!-- claim:arm.T.outcome_correct_rate -->62.5%<!-- /claim -->, vector similarity <!-- claim:arm.V.outcome_correct_rate -->25%<!-- /claim -->, naive recency <!-- claim:arm.N.outcome_correct_rate -->0%<!-- /claim -->. FalkorDB switched off confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> causes."
- **False blame.** "Confidently blaming the wrong change: Faultline <!-- claim:arm.A3.false_blame_rate -->0%<!-- /claim -->; telemetry only <!-- claim:arm.T.false_blame_rate -->20%<!-- /claim -->, vector similarity <!-- claim:arm.V.false_blame_rate -->60%<!-- /claim -->, naive recency <!-- claim:arm.N.false_blame_rate -->100%<!-- /claim -->."
- **Ladder.** "Take FalkorDB's algorithms away: correct verdicts on <!-- claim:ladder.full.cases -->100<!-- /claim --> held-out worlds fall from <!-- claim:ladder.full.correct -->100<!-- /claim --> to <!-- claim:ladder.no_maxflow.correct -->80<!-- /claim --> without algo.maxFlow, <!-- claim:ladder.no_sppaths.correct -->76<!-- /claim --> without algo.SPpaths, <!-- claim:ladder.neither.correct -->56<!-- /claim --> without both; confident wrong blames stay at <!-- claim:ladder.full.wrong_confident -->0<!-- /claim -->."
- **Context.** "Context for any agent, unrelated deploys crowding the window: the true cause ranks far higher in the graph's context pack (MRR <!-- claim:ctx.busy30.b1000.GA.mrr -->0.66<!-- /claim -->) than in vector RAG (<!-- claim:ctx.busy30.b1000.V.mrr -->0.42<!-- /claim -->) or by recency (<!-- claim:ctx.busy30.b1000.R.mrr -->0.08<!-- /claim -->)."
- **Live** (shown when `docs/media/charts/live.svg` exists). "The live deployment, measured over HTTPS: right cause <!-- claim:live.hero.cause_correct -->5<!-- /claim -->/<!-- claim:live.hero.n -->5<!-- /claim -->, verified APPLIED <!-- claim:live.hero.applied -->5<!-- /claim -->/<!-- claim:live.hero.n -->5<!-- /claim -->; alert to RESOLVED p50 <!-- claim:live.hero.total_ms_p50 -->2,719<!-- /claim --> ms."

**Notes:**
- **The approval beat depends on the mode.**
  - A real take (`--real-github`) opens and merges a pull request on `faultline-demo-infra` and shows that pull request.
  - A simulated take says so in its caption. It then shows [PR #1](https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1), which the same path opened against real GitHub, after `gh` confirms it is merged.
- **The take refuses rather than captions something the page does not show.** It stops when:
  - the G2 re-run returns rows;
  - the action ends anything but APPLIED and RESOLVED;
  - the brain answer fails its citation guard.

  A take that runs past 3:00 is encoded whole, never cut, and reported as a failure.
- **What the video does not claim.**
  - The LLM arms have not run (no approved budget), so the video makes no LLM-vs-graph claim.
  - Warm memory did not reduce tool calls for the deterministic investigator (<!-- claim:memory.cold_tool_calls -->17<!-- /claim --> → <!-- claim:memory.warm_tool_calls -->17<!-- /claim -->), so it is never shown as "fewer steps".
- **The UNKNOWN-verification result (S9) is not in this cut.** It is an eval result, not a UI state: the UI has no switch that breaks GitHub reads. See `evals/RESULTS.md`.
- **Where `D-pay-417` lives.** It exists only in the run's own graph (`eval_acme_…`), not in `tenant_acme`. The FalkorDB Browser screenshots in `docs/media/` therefore show the payment → frontend-proxy failure path on `tenant_acme` instead.
