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
    # cut v4 short (under 4:30): every cue word the recorder times a beat to is kept; numbers come from latest.json
    ("problem", 0.8,
     "It's two in the morning, and checkout is failing. In ten minutes, three changes went live. Which one broke it? "
     "Roll back the wrong one, and it gets worse."),
    ("whyhard", 0.4,
     "The answer lives in the connections. Dashboards show symptoms, and today's AI agents answer with confidence, "
     "not proof."),
    ("idea", 0.4,
     "What if an agent could only blame what it can prove as a path? That's Faultline. No path, no claim. And the "
     "engine that makes it possible is FalkorDB."),
    ("cube", 0.3,
     "This cube is a real system's graph. Open it: services, deploys, people, and the proof path between them."),
    # --- 2. how FalkorDB does it (the 3D explainer, one scene per line)
    ("x_tenant", 0.4,
     "Inside FalkorDB, alerts, deploys, lineage, docs and people stream into one graph per customer, each with its "
     "own read-only user."),
    ("x_matrices", 0.3,
     "Every relationship is a sparse matrix, walked with linear algebra: {scale.10k.nodes:approx} nodes and "
     "{scale.10k.edges:approx} edges fit in {scale.10k.memory_mb} megabytes."),
    ("x_blast", 0.3,
     "Checkout alerts. A breadth-first search spreads out inside the database: the blast radius, in a fraction of a "
     "millisecond."),
    ("x_path", 0.3,
     "Three deploys landed. For the recommendation deploy, the shortest-path procedure returns zero rows. No path, so "
     "it cannot be blamed."),
    ("x_flow", 0.3,
     "But a path is not enough. Max flow shows the email deploy can carry only {s1.D-email-88.max_flow:pct} of "
     "checkout's traffic. Rejected, with proof."),
    ("x_cut", 0.3,
     "The minimum cut is the smallest containment, tried first on a graph copy made in {scale.1k.copy_ms:int} "
     "milliseconds."),
    ("x_who", 0.3,
     "Centrality ranks who should fix it, and a spanning forest draws the escalation chain."),
    ("x_readonly", 0.3,
     "The model can only point: every read is read-only, and one atomic write records a human's approval."),
    ("x_unplug", 0.4,
     "All {repo.algorithms} graph algorithms change a decision. Without max flow, the right cause drops from "
     "{decisive.full.g5_only.right_cause} of {decisive.full.g5_only.cases} to {decisive.no_maxflow.g5_only.right_cause}. "
     "Switch FalkorDB off, and Faultline confirms nothing. FalkorDB is the brain."),
    # --- 3. the product, live
    ("run", 0.5,
     "Now, live. The incident opens, and a crew of agents gets to work: recall, scope, suspects. Every step lands in "
     "the graph."),
    ("g2", 0.3,
     "The gate rejects the recommendation deploy: the exact Cypher, and its zero rows."),
    ("g5", 0.3,
     "The email deploy's path is too narrow: max flow rejects it."),
    ("proof", 0.3,
     "The payment deploy passes. Here's the proof path, and every piece of evidence behind it."),
    ("contain", 0.3,
     "The smallest containment, tested on a copy, and who should fix it."),
    ("act", 0.4,
     "A human approves the exact change, bound to its plan hash. Faultline opens a real pull request, merges it, and "
     "verifies it. Applied. Then it writes the decision back into FalkorDB."),
    # --- 3b. on call, then the same graph's other jobs. The recorder checks each claim against the page and the
    # graph: "on call for the owning team", the ack stopping the escalation, "one use" / "seven days", "zero people
    # woken", "moved up from number two". Beats time their actions to cue words with a fallback.
    ("oc_page", 0.4,
     "Faultline also runs the pager. It pages whoever the graph says is on call for the owning team. On their phone: "
     "the verdict, the proof path, and who fixes it."),
    ("oc_ack", 0.3,
     "One tap acknowledges it, and the escalation stops."),
    ("oc_contract", 0.4,
     "After a verified fix, the on-call can grant a standing approval: one use, seven days. When the same fault comes "
     "back, the gate still proves the cause, and a second real pull request merges and verifies. Handled while you "
     "slept. Zero people woken."),
    ("brain", 0.4,
     "It's the team's memory, too. Who decided the payment timeout? Every name in the answer comes from a query."),
    ("learn", 0.4,
     "And it learns from the people using it: the fixes your team prefers, the guidelines they set, who actually "
     "answers. The next plan puts your team's choice first: moved up from number two."),
    ("engine", 0.4,
     "And FalkorDB shows its own work: the memory each graph takes, every query's timing, and the live tail."),
    # --- 4. the proof, honestly
    ("numbers", 0.5,
     "The numbers, honestly. On {deep.fresh.all.cases} worlds built to fool it: {deep.fresh.all.wrong_confident} "
     "confident wrong blames, the right cause in {deep.fresh.all.right_cause} of {deep.fresh.all.cause_cases}, and not "
     "sure on the rest. A strong language model blamed an innocent change {llm_deep.deep.all.wrong_confident} times. "
     "On a real system, the OpenTelemetry Demo: the right cause in {otel.faultline.right_cause.k} of "
     "{otel.faultline.right_cause.n} faults, {otel.faultline.wrong.k} wrong blames in {otel.faultline.wrong.n} windows. "
     "A telemetry threshold was wrong {otel.Tplus.wrong.k} times."),
    ("cost", 0.3,
     "Refusing is cheap: no path in {perf.acme.shortest_causal_path.falkordb_engine_p50} milliseconds, and zero tokens. "
     "And it scales: {tenants.n} customer graphs on one engine, {tenants.acl.leaks} leaks."),
    ("close", 0.4,
     "It's live now: {live.hero.applied} of {live.hero.n} real runs, verified. Any agent can use the same tools over "
     "M.C.P. Faultline, built on FalkorDB. No path, no claim."),
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
    ap.add_argument("--speed", type=float, default=1.25)          # kokoro speaking rate: brisk, for a cut under 4:30
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
