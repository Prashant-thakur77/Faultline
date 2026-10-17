# Demo video script (narrated, 4:27)

The story comes first, and the sponsor's engine is the centre of it:
- **The problem.** Three changes, one broken checkout, and why guessing is dangerous.
- **The idea.** No path, no claim, made possible by FalkorDB.
- **How FalkorDB does it.** The 3D explainer (`/explainer`): one graph per tenant, sparse matrices, `algo.BFS`, `algo.SPpaths`, `algo.maxFlow`, the min-cut on a `GRAPH.COPY` branch, who fixes it, read-only by design, FalkorDB switched off.
- **The product, live.** The hero incident in the incident room, through to a real pull request merged and verified APPLIED.
- **On call.** The page on a phone, one tap to acknowledge, a standing approval, and the same fault fixed again by a second real pull request with nobody woken; then the company brain, what Faultline learned from the on-call, and `/engine`, FalkorDB observing itself.
- **The proof, honestly.** The trade of recall for safety, with intervals; the real OpenTelemetry Demo; the cost of a decision; how it scales on one engine.

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
   - Add `--real-github --real-repeat [--gif]` and `FAULTLINE_APPROVER_KEY_FILE=<file>`. The output is `docs/media/demo.mp4` and `docs/video_captions.srt`.
   - `--real-repeat`: after the take's fix the flag is off at main, so the recorder turns it back on (one commit) before the repeat incident; its standing approval then merges a second real pull request.
   - The recorder refuses to start unless the API acts on real GitHub and `paymentGate` is `on` at main of `faultline-demo-infra`.
   - It types the key into the password-type approver key field and never prints it.
   - After a real take the flag is off at main (two pull requests merged). Turn it back on in that repo before another real take.
   - The Telegram still (`oc_telegram`) joins the cut once `frontend/public/media/telegram.png` exists: add the segment back to `narrate.SEGMENTS` and to `ONCALL` in the recorder.
7. `--reencode tmp/demo-video/meta.json` encodes an earlier take again, with no browser.

| Segment | Starts | Voice | On screen |
|---|---|---|---|
| `problem` | 0:00 | It's two in the morning, and checkout is failing. In ten minutes, three changes went live. Which one broke it? Roll back the wrong one, and it gets worse. | **Hook card** (`media/hook.html`), line by line: "2:04 a.m. · checkout is failing" → "Three changes went live. Which one broke it?" → "~70% of outages come from changes" with its source (*Site Reliability Engineering*, Google, chapter 1) → "Roll back the wrong one, and you make it worse." <!-- noclaim: third-party statistic, attributed on the card --> |
| `whyhard` | 0:09 | The answer lives in the connections. Dashboards show symptoms, and today's AI agents answer with confidence, not proof. | The card's second state: "The answer lives in the connections" over a deploy → service → table → checkout chain that draws itself; "Dashboards show symptoms, not causes"; "AI agents answer with confidence, not proof." |
| `idea` | 0:16 | What if an agent could only blame what it can prove as a path? That's Faultline. No path, no claim. And the engine that makes it possible is FalkorDB. | Third state: "What if an agent could never blame what it can't prove as a path?" → "Faultline. No path, no claim." → "Made possible by FalkorDB, the graph engine underneath." |
| `cube` | 0:24 | This cube is a real system's graph. Open it: services, deploys, people, and the proof path between them. | The **website hero**; the pointer hovers the 3D cube (its seams widen), clicks, and it opens into the hero incident's graph; the pointer sweeps the blocks, which name themselves. |
| `x_tenant` | 0:31 | Inside FalkorDB, alerts, deploys, lineage, docs and people stream into one graph per customer, each with its own read-only user. | **`/explainer`, scene 1** (stage view, the FalkorDB call top left): sources stream into `tenant_acme`; `GRAPH.COPY golden_acme → tenant_acme`; per-tenant ACL user. |
| `x_matrices` | 0:39 | Every relationship is a sparse matrix, walked with linear algebra: <!-- claim:scale.10k.nodes -->296261<!-- /claim --> nodes and <!-- claim:scale.10k.edges -->1097675<!-- /claim --> edges fit in <!-- claim:scale.10k.memory_mb -->490<!-- /claim --> megabytes. | Scene 2: the graph folds into per-relationship sparse adjacency matrices (`db.meta.stats()`), the frontier advancing as a matrix row. |
| `x_blast` | 0:49 | Checkout alerts. A breadth-first search spreads out inside the database: the blast radius, in a fraction of a millisecond. | Scene 3: `algo.BFS` spreads from checkout hop by hop: the blast radius. |
| `x_path` | 0:56 | Three deploys landed. For the recommendation deploy, the shortest-path procedure returns zero rows. No path, so it cannot be blamed. | Scene 4: `algo.SPpaths` from `D-rec-12` returns 0 rows (dashed, "no path, no claim (G2)"); `D-pay-417 → payment → checkout` lights up. |
| `x_flow` | 1:04 | But a path is not enough. Max flow shows the email deploy can carry only <!-- claim:s1.D-email-88.max_flow -->2%<!-- /claim --> of checkout's traffic. Rejected, with proof. | Scene 5: edges become pipes sized by capacity (`algo.maxFlow`); the email deploy's pipe is too narrow (G5); the payment pipe runs full. |
| `x_cut` | 1:12 | The minimum cut is the smallest containment, tried first on a graph copy made in <!-- claim:scale.1k.copy_ms -->383<!-- /claim --> milliseconds. | Scene 6: the min-cut from max flow's edge flows, tried on a `GRAPH.COPY` branch beside the tenant graph. |
| `x_who` | 1:19 | Centrality ranks who should fix it, and a spanning forest draws the escalation chain. | Scene 7: `algo.HarmonicCentrality` ranks the people near the payment code; `algo.MSF` draws the escalation chain. |
| `x_readonly` | 1:23 | The model can only point: every read is read-only, and one atomic write records a human's approval. | Scene 8: the model as a probe that can only point; `GRAPH.RO_QUERY` with TIMEOUT and LIMIT; one atomic write-back, re-read on a separate read-only connection. |
| `x_unplug` | 1:30 | All <!-- claim:repo.algorithms -->10<!-- /claim --> graph algorithms change a decision. Without max flow, the right cause drops from <!-- claim:decisive.full.g5_only.right_cause -->20<!-- /claim --> of <!-- claim:decisive.full.g5_only.cases -->20<!-- /claim --> to <!-- claim:decisive.no_maxflow.g5_only.right_cause -->0<!-- /claim -->. Switch FalkorDB off, and Faultline confirms nothing. FalkorDB is the brain. | Scene 9: FalkorDB switched off ("it refuses to confirm anything"), the ladder of right causes, and the end card listing every `algo.*` procedure the pinned engine ships. |
| `run` | 1:41 | Now, live. The incident opens, and a crew of agents gets to work: recall, scope, suspects. Every step lands in the graph. | The home page's launcher; **Run S1** opens the incident room live; the timeline fills (recall, scope, suspects, investigation). |
| `g2` | 1:49 | The gate rejects the recommendation deploy: the exact Cypher, and its zero rows. | The gate's rejected `D-rec-12` opens its Cypher panel (`Q-GATE-1`, `gate_path.cypher`); **Re-run (read-only)** returns 0 rows. |
| `g5` | 1:54 | The email deploy's path is too narrow: max flow rejects it. | The `D-email-88` rejection: max flow below what is needed; its Cypher panel. |
| `proof` | 1:58 | The payment deploy passes. Here's the proof path, and every piece of evidence behind it. | The root cause; the proof path replays edge by edge on the graph; **Why do you believe this?** opens the provenance: evidence, calls and agents. |
| `contain` | 2:04 | The smallest containment, tested on a copy, and who should fix it. | Containment (the min-cut, tried on a copy) and **Who fixes it**, the top responder highlighted. |
| `act` | 2:08 | A human approves the exact change, bound to its plan hash. Faultline opens a real pull request, merges it, and verifies it. Applied. Then it writes the decision back into FalkorDB. | **Two-step approval**: choose the option, see the exact action and its plan hash, enter the approver key (masked), approve. The plan card stays in view through execute and verify: **APPLIED**, write-back verified, RESOLVED. Then the merged pull request on github.com. |
| `oc_page` | 2:38 | Faultline also runs the pager. It pages whoever the graph says is on call for the owning team. On their phone: the verdict, the proof path, and who fixes it. | **`/oncall`**: the pager inbox with incident B's page highlighted (B is a second run of the hero scenario, opened through the API right after the take's own fix); then the page's own link at a phone's size (`media/phone.html`, 390×844): the verdict, the proof path and who fixes it, all read from the graph. |
| `oc_ack` | 2:48 | One tap acknowledges it, and the escalation stops. | A tap on **Acknowledge** in the phone frame (the page link's signed token): "Acked: the escalation stopped." The recorder checks the graph shows the ack by the person paged and no page of B still waiting. |
| `oc_contract` | 2:52 | After a verified fix, the on-call can grant a standing approval: one use, seven days. When the same fault comes back, the gate still proves the cause, and a second real pull request merges and verifies. Handled while you slept. Zero people woken. | In the incident room the on-call grants a **standing approval** in two steps (one use, seven days). The same fault runs again as incident C; `/oncall` shows the contract used, the stat tile "Handled while you slept" going up by one, and silent "FYI · contract notice" items; in a real take C's fix merges a second real pull request. |
| `brain` | 3:22 | It's the team's memory, too. Who decided the payment timeout? Every name in the answer comes from a query. | **Company brain**: the question is typed and answered with node-id citations (citation guard ✓) and its answer graph. |
| `learn` | 3:27 | And it learns from the people using it: the fixes your team prefers, the guidelines they set, who actually answers. The next plan puts your team's choice first: moved up from number two. | **`/memory#learned`**: preferences with their why lines, proposed guidelines from rejections and who actually answers; then incident B's plan with the flag flip "moved up from #2". |
| `engine` | 3:37 | And FalkorDB shows its own work: the memory each graph takes, every query's timing, and the live tail. | **`/engine`**: FalkorDB observing itself: memory per graph (`GRAPH.MEMORY USAGE`), every query template's timing from the engine's own telemetry stream, and the live tail. |
| `numbers` | 3:44 | The numbers, honestly. On <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> worlds built to fool it: <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> confident wrong blames, the right cause in <!-- claim:deep.fresh.all.right_cause -->51<!-- /claim --> of <!-- claim:deep.fresh.all.cause_cases -->100<!-- /claim -->, and not sure on the rest. A strong language model blamed an innocent change <!-- claim:llm_deep.deep.all.wrong_confident -->37<!-- /claim --> times. On a real system, the OpenTelemetry Demo: the right cause in <!-- claim:otel.faultline.right_cause.k -->11<!-- /claim --> of <!-- claim:otel.faultline.right_cause.n -->20<!-- /claim --> faults, <!-- claim:otel.faultline.wrong.k -->0<!-- /claim --> wrong blames in <!-- claim:otel.faultline.wrong.n -->40<!-- /claim --> windows. A telemetry threshold was wrong <!-- claim:otel.Tplus.wrong.k -->8<!-- /claim --> times. | `media/proof.html#deep`: right causes, confident wrong blames and abstentions on the deep bench, with 95 % intervals, against the telemetry heuristics. |
| `cost` | 4:05 | Refusing is cheap: no path in <!-- claim:perf.acme.shortest_causal_path.falkordb_engine_p50 -->0.053<!-- /claim --> milliseconds, and zero tokens. And it scales: <!-- claim:tenants.n -->250<!-- /claim --> customer graphs on one engine, <!-- claim:tenants.acl.leaks -->0<!-- /claim --> leaks. | `media/proof.html#cost`: the cost of a decision, a no-path proof in FalkorDB against an LLM's tokens. |
| `close` | 4:15 | It's live now: <!-- claim:live.hero.applied -->5<!-- /claim --> of <!-- claim:live.hero.n -->5<!-- /claim --> real runs, verified. Any agent can use the same tools over M.C.P. Faultline, built on FalkorDB. No path, no claim. | `media/proof.html#live` with the live URL; the open card (MCP, `make judge-check`, the upstream issue); the end card. |

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
  - Its one LLM line ("a strong language model blamed an innocent change <!-- claim:llm_deep.deep.all.wrong_confident -->37<!-- /claim --> times") is the deep-bench result with the fixed prompt (v2); the voice never says the graph is more accurate, because the model names more right causes (<!-- claim:llm_deep.deep.all.right_cause -->66<!-- /claim --> of <!-- claim:llm_deep.deep.all.cause_cases -->100<!-- /claim -->, against Faultline's <!-- claim:deep.fresh.all.right_cause -->51<!-- /claim -->).
  - It never says "every scenario right": the deep bench's right-cause rate is spoken with its abstentions.
