"""The demo video's background track, composed here (so it is ours, with no licence to clear): an uplifting tech bed in
A minor at 100 bpm, Am-F-C-G, with sections that follow the story: intro (pad), build (pad + arpeggio), main (+ bass,
kick, hats), a breakdown, a last lift, and an outro. Pure numpy; writes a 44.1 kHz stereo WAV.

    python frontend/scripts/compose_music.py --seconds 330 --out tmp/narration/music.wav
"""

from __future__ import annotations

import argparse

import numpy as np

SR = 44100
BPM = 100
BEAT = 60 / BPM
BAR = 4 * BEAT
# A minor progression, one chord per bar: (root midi, chord tones in midi)
CHORDS = [(45, [57, 60, 64]), (41, [53, 57, 60]), (48, [55, 60, 64]), (43, [55, 59, 62])]   # Am F C G


def hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    t = np.arange(n) / SR
    e = np.ones(n) * s
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    e[:na] = np.linspace(0, 1, max(na, 1))[:na]
    e[na:na + nd] = np.linspace(1, s, max(nd, 1))[: max(0, min(nd, n - na))]
    if nr and n > nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e * (t >= 0)


def saw(f: float, n: int, detune: float = 0.0, phase: float = 0.0) -> np.ndarray:
    t = np.arange(n) / SR
    x = (t * f * (1 + detune) + phase) % 1.0
    return 2 * x - 1


def lp_fast(x: np.ndarray, cutoff: float) -> np.ndarray:
    """Cheap FFT low-pass for long buffers (pads)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def pad(chord: list[int], n: int, rng) -> np.ndarray:
    out = np.zeros(n)
    for m in chord + [chord[0] - 12]:
        for det in (-0.004, 0.0, 0.0045):
            out += saw(hz(m), n, det, rng.random())
    out = lp_fast(out, 1400) / 9
    return out * env_adsr(n, 0.9, 0.5, 0.85, 0.9)


def pluck(f: float, n: int) -> np.ndarray:
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * f * t) + 0.45 * np.sin(4 * np.pi * f * t) + 0.18 * np.sin(6 * np.pi * f * t))
    return x * np.exp(-t * 7.5) * np.minimum(1, t * 400)


def bass(f: float, n: int) -> np.ndarray:
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t)) * env_adsr(n, 0.01, 0.15, 0.7, 0.08)


def kick(n: int) -> np.ndarray:
    t = np.arange(n) / SR
    f = 46 + 90 * np.exp(-t * 32)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def hat(n: int, rng) -> np.ndarray:
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = noise - np.concatenate([[0], noise[:-1]]) * 0.95   # crude high-pass
    return noise * np.exp(-t * 60) * 0.25


def reverb(x: np.ndarray, rng, seconds: float = 2.2, mix: float = 0.22) -> np.ndarray:
    n = int(seconds * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 3.2)
    ir /= np.sqrt((ir ** 2).sum())
    wet = np.fft.irfft(np.fft.rfft(x, len(x) + n) * np.fft.rfft(ir, len(x) + n), len(x) + n)[: len(x)]
    return (1 - mix) * x + mix * wet


def section(bar: int, total_bars: int) -> dict:
    """Which layers play in this bar (the arc of the story)."""
    p = bar / total_bars
    if bar < 4:   # intro: the problem
        return dict(pad=1.0, arp=0.0, bass=0.0, drums=0.0)
    if bar < 12:  # build: who has it
        return dict(pad=1.0, arp=0.7, bass=0.0, drums=0.0)
    if p < 0.55:  # main: what we built, the demo
        return dict(pad=0.9, arp=0.9, bass=1.0, drums=0.8)
    if p < 0.62:  # breakdown
        return dict(pad=1.0, arp=0.5, bass=0.0, drums=0.0)
    if p < 0.93:  # last lift: the proof
        return dict(pad=0.9, arp=1.0, bass=1.0, drums=1.0)
    return dict(pad=0.8, arp=0.4, bass=0.0, drums=0.0)   # outro


def compose(seconds: float, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    total_bars = int(np.ceil(seconds / BAR))
    n_bar = int(BAR * SR)
    L = np.zeros(total_bars * n_bar + SR * 3)
    R = np.zeros_like(L)
    for b in range(total_bars):
        root, chord = CHORDS[b % 4]
        lv = section(b, total_bars)
        s0 = b * n_bar
        if lv["pad"]:
            p = pad(chord, n_bar + SR // 2, rng) * 0.55 * lv["pad"]
            L[s0:s0 + len(p)] += p
            R[s0:s0 + len(p)] += p * 0.96
        if lv["arp"]:
            notes = [chord[0] + 12, chord[1] + 12, chord[2] + 12, chord[1] + 24]
            step = BEAT / 2
            for k in range(8):
                f = hz(notes[k % 4])
                n = int(step * 1.8 * SR)
                x = pluck(f, n) * 0.16 * lv["arp"]
                at = s0 + int(k * step * SR)
                pan = 0.5 + 0.35 * np.sin(k * 0.9)   # the arpeggio moves across the stereo field
                L[at:at + n] += x * (1 - pan) * 1.6
                R[at:at + n] += x * pan * 1.6
        if lv["bass"]:
            for k in (0, 1.5, 2, 3.5):
                n = int(BEAT * 0.9 * SR)
                x = bass(hz(root - 12), n) * 0.30 * lv["bass"]
                at = s0 + int(k * BEAT * SR)
                L[at:at + n] += x
                R[at:at + n] += x
        if lv["drums"]:
            for k in range(4):
                n = int(0.45 * SR)
                x = kick(n) * 0.42 * lv["drums"]
                at = s0 + int(k * BEAT * SR)
                L[at:at + n] += x
                R[at:at + n] += x
            for k in range(8):
                n = int(0.08 * SR)
                x = hat(n, rng) * (0.10 if k % 2 else 0.05) * lv["drums"]
                at = s0 + int((k + 0.5) * (BEAT / 2) * SR)
                L[at:at + n] += x * 0.8
                R[at:at + n] += x
    L, R = reverb(L, rng), reverb(R, rng)
    out = np.stack([L, R], axis=1)[: int(seconds * SR)]
    fade_in, fade_out = int(3 * SR), int(6 * SR)
    out[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    out[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    out /= np.max(np.abs(out)) / 0.89
    return out


def write_wav(path: str, x: np.ndarray) -> None:
    """16-bit stereo PCM with the standard library (no audio package needed)."""
    import wave

    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=330)
    ap.add_argument("--out", default="tmp/narration/music.wav")
    a = ap.parse_args()
    write_wav(a.out, compose(a.seconds))
    print(f"wrote {a.out} ({a.seconds:.0f} s, {BPM} bpm, Am-F-C-G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
