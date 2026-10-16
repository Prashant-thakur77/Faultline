# Demo video script (narrated, about 4:15)

The story comes first:
- **The problem.** Who has it, and why guessing is dangerous.
- **What we built.** Shown on the website: the hero and its 3D cube, the system map, how it decides, the product tour.
- **A live run of the hero incident.** In the incident room, through to a merged pull request.
- **More uses of the same graph.** Break it, the pre-deploy gate, the company brain.
- **The measured proof.** Then the live deployment.

The thesis is spoken at 0:30 and shown on screen from 0:42: no path, no claim.

How it is recorded:
- **Voice.** `frontend/scripts/narrate.py` writes the narration and fills every spoken number from `evals/results/latest.json`. It produces `tmp/narration/timing.json` (segment id, start, length, text), `narration.wav` and one WAV per segment. Third-party facts are attributed in the words.
- **Picture.** `frontend/scripts/record_demo_video.py` drives the real UI with Playwright.
  - **Timing.** Every beat keys to a narration segment and starts at that segment's start. Actions inside a beat are timed to the words they show: the voice says "zero rows" as the read-only re-run returns 0 rows.
  - **Overruns never desync the voice.** A beat that runs long pushes the next segment later, and the encoder places each segment's audio where its beat really started. Two segments never overlap, and the narration's pauses win the time back.
- **Pre-roll (trimmed from the video).** The recorder:
  - checks the API (and that it acts on the simulated or real GitHub the take expects);
  - re-arms the tenant with its confirm step;
  - runs the hero scenario once to read and check every value the take depends on;
  - confirms WebGL works for the cube;
  - shows a sync marker the encoder finds in the raw video, so the trim is exact.

  The take then runs the scenario again, live, from the launcher on the home page.
- **Numbers.**
  - **Stale narration.** The recorder re-fills the narration from the current `latest.json` and refuses a narration that no longer matches.
  - **What the voice states about the page is checked before recording:** three suspects, zero rows, the email deploy's max flow, two contradicted decisions, "blocked".
  - **The LLM card has no numbers of its own.** It shows only values the recorder reads from `latest.json` (and the model name from `evals/results/llm_arms.json`).
  - **The charts are byte-identical copies** of `docs/media/charts/` (drawn from `latest.json` by `scripts/gen_charts.py`).
  - **Claim tags.** Numbers below are tagged claims checked by `make claims`.
- **Captions.** The narration's own words, two or three chunks per segment, burned in at encode time and exported as `.srt` (`docs/video_captions.srt` for the real take).
- **Format.** 1536×864 viewport (the 125 % zoom of a 1920×1080 screen), upscaled to 1080p H.264 at 30 fps. Narration in AAC 192k, two-pass loudness normalisation to −16 LUFS. Length = the narration, plus any pushes, plus a 2 s tail on the end card.

**Before recording:**
1. `make up && make seed`, then start the API on :8400 and the production UI on :3000.
   - Next serves only the public files that existed when it started: rebuild and restart the UI after adding a file under `frontend/public/`. Edits to existing files are served as they are.
2. After `scripts/gen_charts.py`, run `cp docs/media/charts/*.svg frontend/public/media/charts/`.
3. The GitHub CLI must be signed in. The recorder uses it to check the merged pull request, the flag state at main of the demo infra repo, and the upstream issue's title and state.
4. A full Chrome is needed for WebGL (the hero cube renders in software through SwiftShader): `--chromium ~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`.
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

| Segment | Voice (planned) | On screen |
|---|---|---|
| `problem` | 0:00–0:16 | **Hook card** (`media/hook.html`), line by line with the voice: "2:04 a.m. · checkout is failing" → "Three changes went live. Which one broke it?" → "~70% of outages come from changes", with its source (*Site Reliability Engineering*, Google, chapter 1) → "Roll back the wrong one, and you make it worse." <!-- noclaim: third-party statistic, attributed on the card and in the voice --> |
| `usecase` | 0:17–0:29 | The card's second state: "The on-call question, night after night" → "Dashboards show symptoms, not causes" → "AI agents answer with confidence, not proof." |
| `built` | 0:30–0:45 | The **website hero**: "No path, no claim." rises in; the 3D cube loads beside it; the pointer moves to the cube, whose seams widen. |
| `cube` | 0:45–0:52 | **Click the cube.** It splits into the hero incident's graph and the gate's decision plays on it (G2 no path, G5 flow, the proof path); the pointer sweeps across the blocks, which name themselves. |
| `map` | 0:53–1:10 | **"Where it sits"** (the system map). Each part lights as the voice names it, and the caption under the map changes: Alerts → Deploys → Warehouse → Docs & decisions → FalkorDB context graph → Faultline crew → One approved action → Who fixes it. |
| `decides` | 1:11–1:20 | **"How it decides"** (the proof story). The "one incident" bar is clicked step by step with the voice: Alert → Path → Flow → Proof → Cut → Act; the pinned figure changes scene with each. |
| `tour` | 1:21–1:31 | **Product tour** tabs, one per phrase: Incident room → Crew → Why → Preflight → Brain. |
| `run` | 1:32–1:42 | The home page's **Run a scenario**: S1 is run live; the incident room opens and the stage timeline fills (recall, localize, …) until "paused: awaiting approval". |
| `g2` | 1:42–1:51 | Evidence gate → `D-rec-12` rejected by G2 → its Cypher panel → **Re-run (read-only)** → "0 rows. For a G2 path query this means no path, so no claim." |
| `g5` | 1:52–2:03 | `D-email-88`: the G5 row and its flow bar; max flow <!-- claim:s1.D-email-88.max_flow -->0.0200<!-- /claim --> of the <!-- claim:s1.D-email-88.needed -->0.2433<!-- /claim --> needed (the voice: "only <!-- claim:s1.D-email-88.max_flow -->2%<!-- /claim --> of checkout's traffic"), then its Cypher panel. |
| `crew` | 2:03–2:11 | The **Crew** board: lanes flashed as the voice says who claimed, what ran, whom it handed to. |
| `proof` | 2:11–2:23 | `D-pay-417`'s gate run; **Path** mode replayed (<!-- claim:s1.chain -->D-pay-417 → payment → checkout<!-- /claim -->); then **Why do you believe this?** (the provenance graph). |
| `contain` | 2:23–2:35 | **Containment**: the min-cut table (a what-if on a GRAPH.COPY branch); then **Who fixes it**, the top person flashed. |
| `act` | 2:35–2:50 | **Choose** "flag paymentGate → off" → the exact action and its plan hash → (real take: the approver key, masked) → **Approve this exact action** → **APPLIED** → write-back verified <!-- claim:s1.writeback -->7/7<!-- /claim --> → RESOLVED. Then 4 s with no voice on the merged pull request at github.com, its URL shown. |
| `breakit` | 2:50–2:56 (+push) | **Break it** (`/playground`): "Remove the call payment → checkout" → **Break it** → "What moved", the changed decision highlighted. |
| `preflight` | 2:57–3:07 (+push) | `/preflight` → **S6** → verdict **<!-- claim:s6.verdict -->block<!-- /claim -->**; the two contradicted decisions flashed; the verdict again on "Blocked". |
| `brain` | 3:07–3:16 (+push) | `/brain`: "Who decided the payment timeout, and are they still here?" typed → the answer with **citation guard ✓** → **Answer as a graph**. |
| `numbers` | 3:17–3:35 (+push) | The **outcome** chart, then the **false-blame** chart on "zero confident wrong blames". |
| `llm` | 3:36–3:46 (+push) | The **LLM card** (`media/proof.html#llm`): the same model three ways; values from `latest.json`, listed below. |
| `falkordb` | 3:47–3:57 (+push) | The **ladder** chart; on "Switch FalkorDB off", the outcome chart again (its "FalkorDB switched off" row). |
| `close` | 3:58–4:11 (+push) | The **live deployment** (`https://13-203-185-119.sslip.io`, URL shown) → `media/open.html` (the hosted MCP one-liner from [MCP.md](MCP.md), FalkorDB#3349 with its title and state read from GitHub) → the **end card** (`media/end.html`), held 2 s after the last word. |

The "+push" segments start later than planned in a take. In the last simulated dry run they started about 3–5 s late because of the silent github.com shot, and the pauses had won back 2 s of that by `close`. Each segment's audio moves with its beat. <!-- noclaim: timing of one dry run, not a measured result -->

**What the voice says, with its sources:**
- **`g5`.** "only <!-- claim:s1.D-email-88.max_flow -->2%<!-- /claim --> of checkout's traffic". The recorder also checks it against the page's own max flow.
- **`numbers`.** "every scenario right" (<!-- claim:arm.A3.outcome_correct_rate -->100%<!-- /claim -->), and the comparisons:
  - telemetry alone <!-- claim:arm.T.outcome_correct_rate -->62.5%<!-- /claim -->;
  - vector search <!-- claim:arm.V.outcome_correct_rate -->25%<!-- /claim -->;
  - the latest deploy <!-- claim:arm.N.outcome_correct_rate -->0%<!-- /claim -->.

  "Across <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> adversarial worlds, <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> confident wrong blames."
- **`llm`.** "a strong language model on its own? <!-- claim:arm.A0.outcome_correct_rate -->75%<!-- /claim -->". Then, inside Faultline's gate, <!-- claim:arm.A3L.trials -->4<!-- /claim --> out of <!-- claim:arm.A3L.trials -->4<!-- /claim -->.
- **`falkordb`.** Correct answers fall from <!-- claim:ladder.full.correct -->100<!-- /claim --> to <!-- claim:ladder.neither.correct -->56<!-- /claim -->; with FalkorDB switched off it confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> causes.
- **`close`.** <!-- claim:live.hero.applied -->5<!-- /claim --> out of <!-- claim:live.hero.n -->5<!-- /claim --> real runs on the live deployment, verified.

**The LLM card** (model `claude-opus-5-5`, from `evals/results/llm_arms.json`):

| Approach | Scenarios | Right verdict | Right when nothing is to blame |
|---|---|---|---|
| The model alone: the alert, raw telemetry and the change list (A0) | <!-- claim:arm.A0.trials -->8<!-- /claim --> | <!-- claim:arm.A0.outcome_correct_rate -->75%<!-- /claim --> | <!-- claim:arm.A0.abstention_correct_rate -->33.3%<!-- /claim --> |
| The model + vector RAG over runbooks, postmortems and ADRs (A1) | <!-- claim:arm.A1.trials -->8<!-- /claim --> | <!-- claim:arm.A1.outcome_correct_rate -->75%<!-- /claim --> | <!-- claim:arm.A1.abstention_correct_rate -->33.3%<!-- /claim --> |
| Faultline, same model: it proposes, the graph gate decides (A3L) | <!-- claim:arm.A3L.trials -->4<!-- /claim --> | <!-- claim:arm.A3L.outcome_correct_rate -->100%<!-- /claim --> | <!-- claim:arm.A3L.abstention_correct_rate -->100%<!-- /claim --> |

The card says what PROOF.md says: one trial per scenario, with A3L on four scenarios. It is a direction, not a benchmark.

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
  - The LLM comparison is small (above); the voice states its result and the card shows its size.
