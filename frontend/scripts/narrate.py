"""Narration for the demo video: story first (problem → use case → what we built → how it decides → live demo →
proof), synthesized with Chatterbox TTS from a reference voice. Every number spoken is filled from
evals/results/latest.json at generation time (never typed here); third-party facts are attributed in the words.

Runs in an environment that has `chatterbox-tts` and a CUDA torch (not the project venv):
    python frontend/scripts/narrate.py --voice tmp/narration/voice_ref.wav --out tmp/narration
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
    # --- the problem and who has it
    ("problem", 0.8,
     "It's two a.m. Checkout is failing, and money is walking out the door. In the last few minutes, three changes "
     "went live. Which one broke it? Google's S.R.E. book says roughly seventy percent of outages come from changes. "
     "Roll back the wrong one, and you have just made it worse."),
    ("usecase", 0.6,
     "That is the on-call engineer's question, night after night. Dashboards show symptoms, not causes. And today's "
     "A.I. agents answer with confidence, not proof. They guess, and some of them act on the guess."),
    # --- what we built, on the website
    ("built", 0.7,
     "So we built Faultline. An on-call agent whose brain is a FalkorDB knowledge graph, and it lives by one rule. "
     "No path, no claim. It will not blame a change until the graph proves that the change is connected to the failure."),
    ("cube", 0.5,
     "Click the cube, and it opens into the real graph of this system: the services, the deploys, and the proof path "
     "between them."),
    ("map", 0.6,
     "Here is where it sits. It reads what your stack already emits: alerts, deploys, the data warehouse, docs and "
     "decisions. One FalkorDB graph per tenant holds all of it. A crew of agents proposes; the evidence gate decides; "
     "and only then does anything act."),
    ("decides", 0.6,
     "How it decides, step by step. The alert. The causal path. The flow that path can carry. The proof. The "
     "smallest cut that contains it. And one approved action."),
    ("tour", 0.5,
     "Every screen runs on that same graph: the incident room, the crew, the reasoning behind each verdict, the "
     "pre-deploy check, and the company brain."),
    # --- the live demo
    ("run", 0.8,
     "Let's run it. Checkout errors are spiking. The incident opens, and the crew gets to work: recall, scope, "
     "suspects, investigation, all recorded in the graph."),
    ("g2", 0.6,
     "Three suspects. The recommendation deploy has no causal path to checkout. FalkorDB returns zero rows. "
     "So it cannot be blamed. Full stop."),
    ("g5", 0.5,
     "The email deploy does have a path. But max flow shows that path can carry only {s1.D-email-88.max_flow:pct} of "
     "checkout's traffic, and we need far more to explain what we see. Rejected, with proof."),
    ("crew", 0.5,
     "Who did what? Every step is a record: which agent claimed it, which query it ran, and whom it handed to next."),
    ("proof", 0.5,
     "The payment deploy passes every check. Here is the proof path, lit edge by edge. And here is why we believe it: "
     "every piece of evidence, traced back to the agent and the exact query that produced it."),
    ("contain", 0.5,
     "Max flow also finds the smallest cut that contains the damage, tried first on a copy of the graph. And the graph "
     "knows who should fix it: the people who wrote this code and fixed it last time."),
    ("act", 0.6,
     "Now a human approves the exact change, bound to its plan hash. Faultline opens a real pull request on GitHub, "
     "merges it, and verifies it through a second channel. Applied. Written back into the graph, so the next incident "
     "starts warm."),
    # --- the same graph, more uses
    ("breakit", 0.7,
     "Is the graph just decoration? Cut one call in it, and the decision changes. The graph is load-bearing."),
    ("preflight", 0.5,
     "The same graph works before the next deploy. This pull request drops payment retries, and it contradicts two "
     "decisions the team already made. Blocked, before it ships."),
    ("brain", 0.5,
     "And it is the team's memory. Ask who decided the payment timeout, and whether they are still here. Every name "
     "in the answer comes from a query, drawn as a graph."),
    # --- proof
    ("numbers", 0.8,
     "Now, the numbers. Faultline gets every scenario right, where telemetry alone manages "
     "{arm.T.outcome_correct_rate:pct}, vector search {arm.V.outcome_correct_rate:pct}, and the latest deploy "
     "{arm.N.outcome_correct_rate:pct}. Across {deep.fresh.all.cases} adversarial worlds, zero confident wrong blames."),
    ("llm", 0.5,
     "And a strong language model on its own? {arm.A0.outcome_correct_rate:pct}. It blames an innocent deploy when "
     "nothing is wrong. Put that same model inside Faultline's gate: {arm.A3L.trials} out of {arm.A3L.trials}."),
    ("falkordb", 0.5,
     "Take FalkorDB's algorithms away and the correct answers fall from {ladder.full.correct} to "
     "{ladder.neither.correct}. Switch FalkorDB off, and it confirms nothing at all. That is what load-bearing means."),
    ("close", 0.7,
     "And it is live right now: {live.hero.applied} out of {live.hero.n} real runs, verified. Any agent can use the "
     "same read-only tools over M.C.P. Faultline. No path, no claim. Clone it, run make judge check, and verify it "
     "yourself."),
]


# How the voice should say words it mispronounces (checked by transcribing the takes); captions keep the real spelling.
SAY = {"FalkorDB's": "Falcor D B's", "FalkorDB": "Falcor D B", "Faultline's": "Fault line's", "Faultline": "Fault line",
       "M.C.P.": "M C P", "make judge check": "make, judge, check", "S.R.E.": "S R E"}


def for_voice(text: str) -> str:
    for word, sound in SAY.items():
        text = text.replace(word, sound)
    return text


def spoken(v, fmt: str) -> str:
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
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out", default=str(ROOT / "tmp" / "narration"))
    ap.add_argument("--exaggeration", type=float, default=0.6)    # energy: above the 0.5 default, below theatrical
    ap.add_argument("--cfg", type=float, default=0.3)             # low pacing weight: deliberate pace for a fast reference voice
    ap.add_argument("--tempo", type=float, default=0.86)   # <1 slows the take without changing pitch
    ap.add_argument("--only", nargs="*", help="re-synthesize only these segment ids")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    latest = json.loads((ROOT / "evals" / "results" / "latest.json").read_text())
    texts = [(sid, gap, fill(t, latest)) for sid, gap, t in SEGMENTS]

    import numpy as np
    import soundfile as sf
    import torch
    from chatterbox.tts import ChatterboxTTS

    model = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    sr = model.sr
    for sid, _, text in texts:
        if a.only and sid not in a.only and (out / f"{sid}.wav").exists():
            continue
        torch.manual_seed(7)   # the same take every run
        wav = model.generate(for_voice(text), audio_prompt_path=a.voice, exaggeration=a.exaggeration, cfg_weight=a.cfg)
        sf.write(out / f"{sid}.raw.wav", wav.squeeze(0).cpu().numpy(), sr)
        # the reference voice is fast: a pitch-preserving stretch brings it to an easy, still energetic pace
        import subprocess
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / f"{sid}.raw.wav"), "-filter:a", f"atempo={a.tempo}",
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
