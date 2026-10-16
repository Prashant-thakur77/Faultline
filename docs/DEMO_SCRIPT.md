# Demo video script (narrated, 5:14)

The story comes first, and the sponsor's engine is the centre of it:
- **The problem.** Three changes, one broken checkout, and why guessing is dangerous.
- **The idea.** No path, no claim, made possible by FalkorDB.
- **How FalkorDB does it.** The 3D explainer (`/explainer`): one graph per tenant, sparse matrices, `algo.BFS`, `algo.SPpaths`, `algo.maxFlow`, the min-cut on a `GRAPH.COPY` branch, who fixes it, read-only by design, FalkorDB switched off.
- **The product, live.** The hero incident in the incident room, through to a real pull request merged and verified APPLIED, then preflight and the company brain.
- **The proof, honestly.** The trade of recall for safety, with intervals, and the cost of a decision.

How it is recorded:
- **Voice.** `frontend/scripts/narrate.py` (Kokoro-82M, Apache-2.0, built-in voice `af_heart`; no one's voice is cloned) writes the narration and fills every spoken number from `evals/results/latest.json`. "FalkorDB" gets a phoneme override; every take is transcribed with faster-whisper to check pronunciation.
- **Music.** `frontend/scripts/compose_music.py` composes the bed procedurally (ours, nothing to license), to the take's exact length; the encoder ducks it under the voice.
- **Picture.** `frontend/scripts/record_demo_video.py` drives the real UI with Playwright, rendering WebGL on the GPU (`--gpu`: ANGLE over EGL on the NVIDIA card; the take refuses to start on a software renderer). Each explainer scene is stretched over its narration line (`window.__explainer.playScene`).
  - **Timing.** Every beat keys to a narration segment and starts at that segment's start. Actions inside a beat are timed to the words they show: the voice says "zero rows" as the read-only re-run returns 0 rows.
  - **Overruns never desync the voice.** A beat that runs long pushes the next segment later, and the encoder places each segment's audio where its beat really started. Two segments never overlap, and the narration's pauses win the time back.
- **Pre-roll (trimmed from the video).** The recorder:
  - checks the API (and that it acts on the simulated or real GitHub the take expects);
  - re-arms the tenant with its confirm step;
  - runs the hero scenario once to read and check every value the take depends on;
  - confirms WebGL works (on the GPU with `--gpu`);
  - shows a sync marker the encoder finds in the raw video, so the trim is exact.

  The take then runs the scenario again, live, from the launcher on the home page.
- **Numbers.**
  - **Stale narration.** The recorder re-fills the narration from the current `latest.json` and refuses a narration that no longer matches.
  - **What the voice states about the page is checked before recording:** three suspects, zero rows, the email deploy's max flow, two contradicted decisions, "blocked".
  - **The charts are byte-identical copies** of `docs/media/charts/` (drawn from `latest.json` by `scripts/gen_charts.py`).
  - **Claim tags.** Numbers below are tagged claims checked by `make claims`.
- **Captions.** The narration's own words, two or three chunks per segment, burned in at encode time and exported as `.srt` (`docs/video_captions.srt` for the real take).
- **Format.** 1536×864 viewport (the 125 % zoom of a 1920×1080 screen), upscaled to 1080p H.264 at 30 fps. Narration in AAC 192k, two-pass loudness normalisation to −16 LUFS, with the music bed ducked under it. Length = the narration, plus any pushes, plus a 2 s tail on the end card.

**Before recording:**
1. `make up && make seed`, then start the API on :8400 and the production UI on :3000.
   - Next serves only the public files that existed when it started: rebuild and restart the UI after adding a file under `frontend/public/`. Edits to existing files are served as they are.
2. After `scripts/gen_charts.py`, run `cp docs/media/charts/*.svg frontend/public/media/charts/`.
3. The GitHub CLI must be signed in. The recorder uses it to check the merged pull request, the flag state at main of the demo infra repo, and the upstream issue's title and state.
4. A full Chrome is needed for WebGL: `--chromium ~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`, plus `--gpu` for smooth 3D.
5. **Dry run (simulated GitHub).** It writes only to `tmp/demo-video/`; drop `--no-encode` to get `tmp/demo-video/narrated_sim.mp4`.
   ```bash
   .venv/bin/python frontend/scripts/record_demo_video.py --ui http://localhost:3000 --api http://localhost:8400 \
       --narration tmp/narration --chromium ~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome --no-encode
   ```
   - **On screen.** A simulated take shows a "Dry run: simulated GitHub" badge from the approval on. Its github.com shot is the pull request an earlier real take merged, labelled as such.
   - **Safeguard.** A simulated take refuses to write `docs/media/demo.mp4`.
6. **Real take.**
   - Start the API with `FAULTLINE_GITHUB=real` and `FAULTLINE_APPROVER_KEY`.
   - Add `--real-github [--gif]` and `FAULTLINE_APPROVER_KEY_FILE=<file>`. The output is `docs/media/demo.mp4` and `docs/video_captions.srt`.
   - The recorder refuses to start unless the API acts on real GitHub and `paymentGate` is `on` at main of `faultline-demo-infra`.
   - It types the key into the password-type approver key field and never prints it.
   - After a real take the flag is off at main. Turn it back on in that repo before another real take.
7. `--reencode tmp/demo-video/meta.json` encodes an earlier take again, with no browser.

| Segment | Starts | Voice | On screen |
|---|---|---|---|
| `problem` | 0:00 | It's two in the morning. Checkout is failing, and every minute costs money. In the last ten minutes, three changes went live. Which one broke it? Roll back the wrong one, and you've made it worse, while the real cause keeps burning. | **Hook card** (`media/hook.html`), line by line: "2:04 a.m. · checkout is failing" → "Three changes went live. Which one broke it?" → "~70% of outages come from changes" with its source (*Site Reliability Engineering*, Google, chapter 1) → "Roll back the wrong one, and you make it worse." <!-- noclaim: third-party statistic, attributed on the card --> |
| `whyhard` | 0:14 | The answer isn't on any one dashboard. It lives in the connections: this deploy touches that service, which feeds this table, which checkout reads. Dashboards show symptoms. And today's AI agents answer with confidence, not proof. | The card's second state: "The answer lives in the connections" over a deploy → service → table → checkout chain that draws itself; "Dashboards show symptoms, not causes"; "AI agents answer with confidence, not proof." |
| `idea` | 0:29 | So we asked one question. What if an agent could never blame anything it couldn't prove as a path through those connections? That's Faultline. No path, no claim. And the engine that makes that rule possible is FalkorDB. | Third state: "What if an agent could never blame what it can't prove as a path?" → "Faultline. No path, no claim." → "Made possible by FalkorDB, the graph engine underneath." |
| `cube` | 0:43 | This cube is the graph of a real system. Open it, and there they are: services, deploys, tables, people, and the proof path between them. | The **website hero**; the pointer hovers the 3D cube (its seams widen), clicks, and it opens into the hero incident's graph; the pointer sweeps the blocks, which name themselves. |
| `x_tenant` | 0:52 | Here's how it works inside FalkorDB. Alerts, deploys, warehouse lineage, docs and people all stream into one graph per tenant. Every customer gets their own graph, and their own read-only user. | **`/explainer`, scene 1** (stage view, the FalkorDB call top left): sources stream into `tenant_acme`; `GRAPH.COPY golden_acme → tenant_acme`; per-tenant ACL user. |
| `x_matrices` | 1:05 | Underneath, FalkorDB stores each kind of relationship as a sparse matrix, and walks the graph with linear algebra. That's why a whole company graph, <!-- claim:scale.10k.nodes -->296261<!-- /claim --> nodes and <!-- claim:scale.10k.edges -->1097675<!-- /claim --> edges, fits in <!-- claim:scale.10k.memory_mb -->490<!-- /claim --> megabytes. | Scene 2: the graph folds into per-relationship sparse adjacency matrices (`db.meta.stats()`), the frontier advancing as a matrix row. |
| `x_blast` | 1:21 | Checkout raises an alert. A breadth-first search runs inside the database and spreads out from it, hop by hop. That frontier is the blast radius, found in a fraction of a millisecond. | Scene 3: `algo.BFS` spreads from checkout hop by hop: the blast radius. |
| `x_path` | 1:33 | Three deploys landed. For the recommendation deploy, the shortest-path procedure inside FalkorDB returns zero rows. There is no path to checkout, so it cannot be blamed. Full stop. | Scene 4: `algo.SPpaths` from `D-rec-12` returns 0 rows (dashed, "no path, no claim (G2)"); `D-pay-417 → payment → checkout` lights up. |
| `x_flow` | 1:46 | But a path is not enough. Max flow turns every edge into a pipe. The email deploy's pipe can carry only <!-- claim:s1.D-email-88.max_flow -->2%<!-- /claim --> of checkout's traffic, far too little to explain this outage. Rejected, with proof. | Scene 5: edges become pipes sized by capacity (`algo.maxFlow`); the email deploy's pipe is too narrow (G5); the payment pipe runs full. |
| `x_cut` | 1:59 | Max flow also gives the minimum cut: the smallest change that contains the damage. Faultline tries it first on a copy of the graph, made with graph copy in <!-- claim:scale.1k.copy_ms -->383<!-- /claim --> milliseconds. | Scene 6: the min-cut from max flow's edge flows, tried on a `GRAPH.COPY` branch beside the tenant graph. |
| `x_who` | 2:11 | Who should fix it? Centrality over who knows what ranks the people closest to this code, and a spanning forest draws the escalation chain. | Scene 7: `algo.HarmonicCentrality` ranks the people near the payment code; `algo.MSF` draws the escalation chain. |
| `x_readonly` | 2:20 | And the model can only point. Every read is a read-only query, with a timeout and a limit. Only after a human approves does one atomic write record the decision, and a separate read-only connection checks it. | Scene 8: the model as a probe that can only point; `GRAPH.RO_QUERY` with TIMEOUT and LIMIT; one atomic write-back, re-read on a separate read-only connection. |
| `x_unplug` | 2:34 | Faultline uses all <!-- claim:repo.algorithms -->10<!-- /claim --> graph algorithms this FalkorDB release ships, and each one changes a decision. When a look-alike has a fault of its own, only max flow can tell it from the cause: with it, <!-- claim:decisive.full.g5_only.right_cause -->20<!-- /claim --> right out of <!-- claim:decisive.full.g5_only.cases -->20<!-- /claim -->. Without it, <!-- claim:decisive.no_maxflow.g5_only.right_cause -->0<!-- /claim -->. Switch FalkorDB off, and Faultline refuses to confirm anything. FalkorDB isn't a feature here. It's the brain. | Scene 9: FalkorDB switched off ("it refuses to confirm anything"), the ladder of right causes, and the end card listing every `algo.*` procedure the pinned engine ships. |
| `run` | 2:56 | Now let's watch it live. Checkout errors spike. The incident opens, and a crew of agents gets to work: recall, scope, suspects, investigation. Every step lands in the graph. | The home page's launcher; **Run S1** opens the incident room live; the timeline fills (recall, scope, suspects, investigation). |
| `g2` | 3:08 | The gate rejects the recommendation deploy. Here's the exact Cypher it ran, and its zero rows. | The gate's rejected `D-rec-12` opens its Cypher panel (`Q-GATE-1`, `gate_path.cypher`); **Re-run (read-only)** returns 0 rows. |
| `g5` | 3:14 | The email deploy has a path, but a narrow one. Max flow rejects it. | The `D-email-88` rejection: max flow below what is needed; its Cypher panel. |
| `proof` | 3:19 | The payment deploy passes every check. Here's the proof path, edge by edge, and every piece of evidence, traced to the agent and the query that produced it. | The root cause; the proof path replays edge by edge on the graph; **Why do you believe this?** opens the provenance: evidence, calls and agents. |
| `contain` | 3:29 | The smallest containment, tested on a copy. And the people who should fix it, because they wrote this code and fixed it last time. | Containment (the min-cut, tried on a copy) and **Who fixes it**, the top responder highlighted. |
| `act` | 3:37 | A human approves the exact change, bound to its plan hash. Faultline opens a real pull request on GitHub, merges it, and verifies it through a second channel. Applied. Then it writes the decision back into FalkorDB, so the next incident starts warm. | **Two-step approval**: choose the option, see the exact action and its plan hash, enter the approver key (masked), approve. The plan card stays in view through execute and verify: **APPLIED**, write-back verified, RESOLVED. Then the merged pull request on github.com. |
| `preflight` | 4:05 | The same graph guards the next deploy. This pull request drops payment retries, and it contradicts two decisions the team already made. Blocked, before it ships. | **Preflight** on the S6 pull request: the contradicted decisions flash, then the **BLOCK** verdict. |
| `brain` | 4:15 | And it's the team's memory. Who decided the payment timeout, and are they still here? Every name in the answer comes from a query. | **Company brain**: the question is typed and answered with node-id citations (citation guard ✓) and its answer graph. |
| `numbers` | 4:23 | Now, the numbers, honestly. We generated <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> worlds built to fool it. Faultline made <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> confident wrong blames. It named the right cause in <!-- claim:deep.fresh.all.right_cause -->51<!-- /claim --> of the <!-- claim:deep.fresh.all.cause_cases -->100<!-- /claim --> worlds with a real cause, and on the rest it said: not sure. On call, a wrong rollback costs far more than an honest not sure. | `media/proof.html#deep`: right causes, confident wrong blames and abstentions on the deep bench, with 95 % intervals, against the telemetry heuristics. |
| `cost` | 4:42 | And refusing is cheap. Proving there is no path takes FalkorDB <!-- claim:perf.acme.shortest_causal_path.falkordb_engine_p50 -->0.053<!-- /claim --> milliseconds, and zero tokens. A language model just reading the same incident spends <!-- claim:arm.A0.tokens_median -->2,331<!-- /claim --> tokens to make a guess. | `media/proof.html#cost`: the cost of a decision, a no-path proof in FalkorDB against an LLM's tokens. |
| `close` | 4:58 | And it's live right now: <!-- claim:live.hero.applied -->5<!-- /claim --> out of <!-- claim:live.hero.n -->5<!-- /claim --> real runs, verified. Any agent can use the same read-only tools over M.C.P. Faultline, built on FalkorDB. No path, no claim. Clone it, run make judge check, and verify it yourself. | `media/proof.html#live` with the live URL; the open card (MCP, `make judge-check`, the upstream issue); the end card. |

**Notes:**
- **The take refuses rather than show something the page or the results do not back.** It stops when:
  - the G2 re-run returns rows;
  - the action ends anything but APPLIED and RESOLVED;
  - the brain answer fails its citation guard;
  - the narration is stale;
  - the page disagrees with what the voice says.
- **The home intro (the node-count odometer) is skipped.** In headless Chromium its digits stay at "0000", which would read as an empty graph.
- **The UNKNOWN-verification result (S9) is not in this cut.** It is an eval result, not a UI state; see `evals/RESULTS.md`.
- **What the video does not claim.**
  - Warm memory did not reduce tool calls for the deterministic investigator (<!-- claim:memory.cold_tool_calls -->17<!-- /claim --> → <!-- claim:memory.warm_tool_calls -->17<!-- /claim -->), so the voice says the next incident "starts warm", never "takes fewer steps".
  - The video makes no LLM-versus-graph claim: the recorded LLM test had two flaws (see PROOF.md), so the voice compares only the cost of a decision.
  - It never says "every scenario right": the deep bench's right-cause rate is spoken with its abstentions.
