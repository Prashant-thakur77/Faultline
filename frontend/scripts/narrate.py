"""Narration for the demo video: story first (the problem → the idea → how FalkorDB makes it possible, over the 3D
explainer → the product, live → on call: the page, the ack, a standing approval, what it learned → inside FalkorDB →
the proof, with its limits), synthesized with Kokoro (built-in voices, Apache-2.0) or
Chatterbox. Every number spoken is filled from
evals/results/latest.json at generation time (never typed here); third-party facts are attributed in the words.

Runs in an environment that has `kokoro` (or `chatterbox-tts`) and torch, not the project venv:
    python frontend/scripts/narrate.py --engine kokoro --voice af_heart --out tmp/narration
Writes one WAV per segment, narration.wav (all segments with their gaps) and timing.json, which the recorder reads to
time its beats to the voice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (id, gap before in seconds, text). {key} is filled from latest.json; {key:pct} speaks a rate as a percentage.
SEGMENTS: list[tuple[str, float, str]] = [
    # --- 1. the problem
    ("problem", 0.8,
     "It's two in the morning. Checkout is failing, and every minute costs money. In the last ten minutes, three "
     "changes went live. Which one broke it? Roll back the wrong one, and you've made it worse, while the real cause "
     "keeps burning."),
    ("whyhard", 0.6,
     "The answer isn't on any one dashboard. It lives in the connections: this deploy touches that service, which "
     "feeds this table, which checkout reads. Dashboards show symptoms. And today's AI agents answer with "
     "confidence, not proof."),
    ("idea", 0.7,
     "So we asked one question. What if an agent could never blame anything it couldn't prove as a path through those "
     "connections? That's Faultline. No path, no claim. And the engine that makes that rule possible is FalkorDB."),
    ("cube", 0.5,
     "This cube is the graph of a real system. Open it, and there they are: services, deploys, tables, people, and "
     "the proof path between them."),
    # --- 2. how FalkorDB does it (the 3D explainer, one segment per scene)
    ("x_tenant", 0.7,
     "Here's how it works inside FalkorDB. Alerts, deploys, warehouse lineage, docs and people all stream into one "
     "graph per tenant. Every customer gets their own graph, and their own read-only user."),
    ("x_matrices", 0.5,
     "Underneath, FalkorDB stores each kind of relationship as a sparse matrix, and walks the graph with linear "
     "algebra. That's why a whole company graph, {scale.10k.nodes:approx} nodes and {scale.10k.edges:approx} edges, "
     "fits in {scale.10k.memory_mb} megabytes."),
    ("x_blast", 0.5,
     "Checkout raises an alert. A breadth-first search runs inside the database and spreads out from it, hop by hop. That "
     "frontier is the blast radius, found in a fraction of a millisecond."),
    ("x_path", 0.5,
     "Three deploys landed. For the recommendation deploy, the shortest-path procedure inside FalkorDB returns zero rows. "
     "There is no path to checkout, so it cannot be blamed. Full stop."),
    ("x_flow", 0.5,
     "But a path is not enough. Max flow turns every edge into a pipe. The email deploy's pipe can carry only "
     "{s1.D-email-88.max_flow:pct} of checkout's traffic, far too little to explain this outage. Rejected, with proof."),
    ("x_cut", 0.5,
     "Max flow also gives the minimum cut: the smallest change that contains the damage. Faultline tries it first on "
     "a copy of the graph, made with graph copy in {scale.1k.copy_ms:int} milliseconds."),
    ("x_who", 0.5,
     "Who should fix it? Centrality over who knows what ranks the people closest to this code, and a spanning forest "
     "draws the escalation chain."),
    ("x_readonly", 0.5,
     "And the model can only point. Every read is a read-only query, with a timeout and a limit. Only after a human "
     "approves does one atomic write record the decision, and a separate read-only connection checks it."),
    ("x_unplug", 0.6,
     "Faultline uses all {repo.algorithms} graph algorithms this FalkorDB release ships, and each one changes a "
     "decision. When a look-alike has a fault of its own, only max flow can tell it from the cause: with it, "
     "{decisive.full.g5_only.right_cause} right out of {decisive.full.g5_only.cases}. Without it, "
     "{decisive.no_maxflow.g5_only.right_cause}. Switch FalkorDB off, and Faultline refuses to confirm anything. "
     "FalkorDB isn't a feature here. It's the brain."),
    # --- 3. the product, live
    ("run", 0.8,
     "Now let's watch it live. Checkout errors spike. The incident opens, and a crew of agents gets to work: recall, "
     "scope, suspects, investigation. Every step lands in the graph."),
    ("g2", 0.5,
     "The gate rejects the recommendation deploy. Here's the exact Cypher it ran, and its zero rows."),
    ("g5", 0.5,
     "The email deploy has a path, but a narrow one. Max flow rejects it."),
    ("proof", 0.5,
     "The payment deploy passes every check. Here's the proof path, edge by edge, and every piece of evidence, traced "
     "to the agent and the query that produced it."),
    ("contain", 0.5,
     "The smallest containment, tested on a copy. And the people who should fix it, because they wrote this code and "
     "fixed it last time."),
    ("act", 0.6,
     "A human approves the exact change, bound to its plan hash. Faultline opens a real pull request on GitHub, "
     "merges it, and verifies it through a second channel. Applied. Then it writes the decision back into FalkorDB, so "
     "the next incident starts warm."),
    # --- 3b. on call, then the same graph's other jobs (v4). The recorder checks each claim against the page and the
    # graph: "on call for the owning team" (the paged person is the on-call the incident's who_fixes evidence names),
    # the ack stopping the escalation, "one use" / "seven days" (the contract's scope), "zero people woken" (the repeat
    # incident's pages), "contradicts two decisions" (preflight), "moved up from number two" (the plan). Beats time
    # their actions to cue words with a fallback; a number or claim the page does not back stops the take.
    ("oc_page", 0.8,
     "Faultline also runs the pager. The moment the gate confirms a cause, it pages whoever the graph says is on call "
     "for the owning team. On their phone: the verdict, the proof path, and who should fix it."),
    ("oc_ack", 0.5,
     "One tap acknowledges it. The escalation stops, and the graph records who answered."),
    ("oc_telegram", 0.5,
     "The same page reaches Telegram, on the on-call's own phone."),
    ("oc_contract", 0.6,
     "After a verified fix, the on-call can grant a standing approval for exactly this repeat: one use, seven days. "
     "When the same fault comes back, the gate still has to prove the cause. Then the same fix runs, a second real "
     "pull request merges, and it verifies. Handled while you slept. Zero people woken."),
    ("preflight", 0.6,
     "The same graph guards the next deploy. This pull request drops payment retries, and it contradicts two "
     "decisions the team already made. Blocked, before it ships."),
    ("brain", 0.5,
     "And it's the team's memory. Who decided the payment timeout, and are they still here? Every name in the answer "
     "comes from a query."),
    ("learn", 0.6,
     "It learns from the people using it, too: the fixes your team prefers, and why, the guidelines they set, and who "
     "actually answers the page. The next plan puts your team's choice first: moved up from number two."),
    ("engine", 0.6,
     "And FalkorDB shows its own work. From inside the engine: the memory each graph takes, every query's timing from "
     "the engine's own telemetry, and the live tail as queries run."),
    # --- 4. the proof, honestly
    ("numbers", 0.8,
     "Now, the numbers, honestly. We generated {deep.fresh.all.cases} worlds built to fool it. Faultline made "
     "{deep.fresh.all.wrong_confident} confident wrong blames. It named the right cause in "
     "{deep.fresh.all.right_cause} of the {deep.fresh.all.cause_cases} worlds with a real cause, and on the rest it said: "
     "not sure. A strong language model, given the same telemetry on the same worlds, found more causes, and blamed an "
     "innocent change {llm_deep.deep.all.wrong_confident} times. Then we broke a real system: the OpenTelemetry Demo, "
     "with its own fault flags and its real telemetry. Faultline named the right cause in "
     "{otel.faultline.right_cause.k} of {otel.faultline.right_cause.n} faults, with {otel.faultline.wrong.k} wrong blames "
     "in {otel.faultline.wrong.n} windows. A threshold on the same telemetry was wrong {otel.Tplus.wrong.k} times. On "
     "call, a wrong rollback costs far more than an honest not sure."),
    ("cost", 0.5,
     "And refusing is cheap. Proving there is no path takes FalkorDB "
     "{perf.acme.shortest_causal_path.falkordb_engine_p50} milliseconds, and zero tokens. A language model just "
     "reading the same incident spends {arm.A0.tokens_median:approx} tokens to make a guess. And it scales: "
     "{tenants.n} customer graphs on one FalkorDB engine, with {tenants.acl.leaks} leaks between them, and at "
     "{scale.10k.services:approx} services the proof path still takes about "
     "{scale.10k.tail.Q-GATE-1.engine_ms_p99:int} milliseconds."),
    ("close", 0.7,
     "And it's live right now: {live.hero.applied} out of {live.hero.n} real runs, verified. Any agent can use the "
     "same read-only tools over M.C.P. Faultline, built on FalkorDB. No path, no claim. Clone it, run make judge "
     "check, and verify it yourself."),
]


# How the voice should say words it mispronounces (checked by transcribing the takes); captions keep the real spelling.
SAY = {"FalkorDB's": "Falcor D B's", "FalkorDB": "Falcor D B", "Faultline's": "Fault line's", "Faultline": "Fault line",
       "M.C.P.": "M C P", "make judge check": "make, judge, check", "S.R.E.": "S R E"}


# Kokoro reads "FalkorDB" as "Faulker"; an inline phoneme override fixes it (checked with faster-whisper).
SAY_KOKORO = {"FalkorDB": "[FalkorDB](/fˈælkɔɹ dˌi bˈi/)", "M.C.P.": "M C P"}   # no possessive: the override breaks


def for_voice(text: str, say: dict[str, str] = SAY) -> str:
    for word, sound in say.items():
        text = text.replace(word, sound)
    return text


def spoken(v, fmt: str) -> str:
    if fmt == "int":
        return str(round(float(v)))
    if fmt == "approx":   # a count read the way a person says it: "296 thousand", "1.1 million"
        x = float(v)
        if x >= 1e6:
            return f"{x / 1e6:.1f}".rstrip("0").rstrip(".") + " million"
        if x >= 1e4:
            return f"{round(x / 1e3)} thousand"
        return f"{x:,.0f}"
    if fmt == "pct":
        x = float(v) * 100
        return (f"{x:.1f}".rstrip("0").rstrip(".") if x % 1 else f"{x:.0f}") + " percent"
    return str(v)


def fill(text: str, latest: dict) -> str:
    import re

    def sub(m: re.Match) -> str:
        key, fmt = m.group(1), m.group(2) or ""
        if key not in latest:
            raise KeyError(f"narration needs {key!r}, which latest.json does not have")
        return spoken(latest[key], fmt)

    return re.sub(r"\{([\w.\-]+)(?::(\w+))?\}", sub, text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["kokoro", "chatterbox"], default="kokoro")
    ap.add_argument("--voice", default="af_heart",
                    help="kokoro: a built-in voice id (af_heart, af_bella, af_sarah); chatterbox: a reference WAV to clone")
    ap.add_argument("--speed", type=float, default=1.08)          # kokoro speaking rate: a touch brisk, energetic
    ap.add_argument("--out", default=str(ROOT / "tmp" / "narration"))
    ap.add_argument("--exaggeration", type=float, default=0.6)    # energy: above the 0.5 default, below theatrical
    ap.add_argument("--cfg", type=float, default=0.3)             # low pacing weight: deliberate pace for a fast reference voice
    ap.add_argument("--tempo", type=float, default=0.86)   # <1 slows the take without changing pitch
    ap.add_argument("--only", nargs="*", help="re-synthesize only these segment ids")
    ap.add_argument("--latest", default=str(ROOT / "evals" / "results" / "latest.json"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    latest = json.loads(Path(a.latest).read_text())
    texts = [(sid, gap, fill(t, latest)) for sid, gap, t in SEGMENTS]

    import subprocess

    import numpy as np
    import soundfile as sf
    import torch

    if a.engine == "kokoro":   # Apache-2.0 model with built-in voices: no one's voice is cloned
        from kokoro import KPipeline

        pipe, sr = KPipeline(lang_code="a"), 24000

        def synth(text: str) -> np.ndarray:
            return np.concatenate([r.audio.numpy() for r in pipe(text, voice=a.voice, speed=a.speed) if r.audio is not None])
    else:
        from chatterbox.tts import ChatterboxTTS

        model = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
        sr = model.sr

        def synth(text: str) -> np.ndarray:
            return model.generate(for_voice(text), audio_prompt_path=a.voice, exaggeration=a.exaggeration,
                                  cfg_weight=a.cfg).squeeze(0).cpu().numpy()

    for sid, _, text in texts:
        if a.only and sid not in a.only and (out / f"{sid}.wav").exists():
            continue
        torch.manual_seed(7)   # the same take every run
        sf.write(out / f"{sid}.raw.wav", synth(for_voice(text, SAY_KOKORO) if a.engine == "kokoro" else text), sr)
        tempo = a.tempo if a.engine == "chatterbox" else 1.0   # the cloned reference voice is fast; kokoro sets speed
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / f"{sid}.raw.wav"), "-filter:a", f"atempo={tempo}",
                        str(out / f"{sid}.wav")], check=True)
        print(f"{sid}: {len(text.split())} words", flush=True)

    # one track: each segment after its gap; timing.json gives every segment's start and length
    timing, track, t = [], [], 0.0
    for sid, gap, text in texts:
        seg, seg_sr = sf.read(out / f"{sid}.wav")
        assert seg_sr == sr
        track.append(np.zeros(int(gap * sr)))
        t += gap
        timing.append({"id": sid, "start": round(t, 3), "length": round(len(seg) / sr, 3), "text": text})
        track.append(seg)
        t += len(seg) / sr
    sf.write(out / "narration.wav", np.concatenate(track), sr)
    (out / "timing.json").write_text(json.dumps({"total": round(t, 3), "segments": timing}, indent=2) + "\n")
    print(f"narration: {t:.1f} s in {len(timing)} segments → {out / 'narration.wav'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
