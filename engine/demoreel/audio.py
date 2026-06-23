"""Audio polish — VO normalization + de-click, procedural SFX, and music ducking.

SFX are synthesized with numpy (a short filtered click, a soft key tick) so nothing binary
needs to be bundled. Music is ducked under the voiceover with smooth ramps. Everything is
best-effort: if a step fails it's skipped rather than failing the render.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .capture import CaptureResult
from .spec import DemoSpec

_RATE = 44100


# --------------------------------------------------------------------------- wav io


def _read_wav(path: str) -> tuple[np.ndarray, int, int]:
    with wave.open(path, "rb") as w:
        n, ch, rate, sw = w.getnframes(), w.getnchannels(), w.getframerate(), w.getsampwidth()
        raw = w.readframes(n)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sw, np.int16)
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if dtype != np.float32:
        data /= float(np.iinfo(dtype).max)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, rate, ch


def _write_wav(path: str, data: np.ndarray, rate: int) -> None:
    clipped = np.clip(data, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def normalize_wav(path: str, target_dbfs: float = -2.5, edge_ms: float = 6.0) -> None:
    """Peak-normalize a VO clip and apply short edge fades to kill clicks."""
    try:
        data, rate, _ = _read_wav(path)
        if data.size == 0:
            return
        peak = float(np.max(np.abs(data)))
        if peak > 1e-5:
            data *= (10 ** (target_dbfs / 20.0)) / peak
        n = int(rate * edge_ms / 1000.0)
        if n > 0 and data.size > 2 * n:
            ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
            data[:n] *= ramp
            data[-n:] *= ramp[::-1]
        _write_wav(path, data, rate)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- sfx synth


def synth_click(volume: float) -> np.ndarray:
    t = np.linspace(0, 0.06, int(_RATE * 0.06), endpoint=False)
    env = np.exp(-t * 90.0)
    tone = 0.6 * np.sin(2 * np.pi * 2400 * t) + 0.4 * np.sin(2 * np.pi * 1200 * t)
    return _stereo((tone * env * volume).astype(np.float32))


def synth_key(volume: float) -> np.ndarray:
    t = np.linspace(0, 0.035, int(_RATE * 0.035), endpoint=False)
    env = np.exp(-t * 160.0)
    tone = np.sin(2 * np.pi * 1700 * t)
    return _stereo((tone * env * volume * 0.7).astype(np.float32))


def _stereo(mono: np.ndarray) -> np.ndarray:
    return np.column_stack([mono, mono])


# --------------------------------------------------------------------------- compose


def build_content_audio(spec: DemoSpec, cap: CaptureResult, build_dir: Path):
    """Build the content segment's audio: VO + SFX + ducked music. Returns a clip or None."""
    from moviepy import AudioFileClip, CompositeAudioClip

    a = spec.audio
    clips = []
    vo_intervals: list[tuple[float, float]] = []

    for st in cap.scenes:
        if st.narration_wav and Path(st.narration_wav).exists():
            clip = AudioFileClip(st.narration_wav).with_start(st.audio_start)
            clips.append(_scale(clip, spec.voice.volume))
            vo_intervals.append((st.audio_start, st.audio_start + st.narration_duration))

    if a.sfx.enabled:
        clips += _sfx_clips(spec, cap, build_dir)

    if a.music:
        music = _music_clip(a.music, cap.duration, a.music_volume, vo_intervals if a.duck else [])
        if music is not None:
            clips.append(music)

    if not clips:
        return None
    return CompositeAudioClip(clips)


def _sfx_clips(spec: DemoSpec, cap: CaptureResult, build_dir: Path) -> list:
    # In-memory AudioArrayClips — tiny on-disk clips trip moviepy's file reader at edges.
    from moviepy import AudioArrayClip

    sfx = spec.audio.sfx
    out = []
    if sfx.click and cap.clicks:
        arr = synth_click(sfx.volume)
        for t in cap.clicks:
            out.append(AudioArrayClip(arr, fps=_RATE).with_start(max(0.0, t)))
    if sfx.typing and cap.type_spans:
        arr = synth_key(sfx.volume)
        for t0, t1 in cap.type_spans:
            n = min(int((t1 - t0) / 0.11) + 1, 14)
            for i in range(n):
                out.append(AudioArrayClip(arr, fps=_RATE).with_start(t0 + i * 0.11))
    return out


def _music_clip(path: str, duration: float, base: float, duck_intervals):
    try:
        from moviepy import AudioFileClip

        music = AudioFileClip(path)
        if music.duration > duration:
            music = music.subclipped(0, duration)
        music = _scale(music, base)
        if duck_intervals:
            music = _duck(music, duck_intervals)
        return music.with_start(0.0)
    except Exception:  # noqa: BLE001 - music is a nicety
        return None


def _duck(music, intervals, duck_factor: float = 0.32, ramp: float = 0.18):
    ivs = list(intervals)

    def env(t):
        t = np.asarray(t, dtype=np.float64)
        g = np.ones_like(t)
        for a, b in ivs:
            down = np.clip((t - (a - ramp)) / ramp, 0.0, 1.0)
            up = np.clip(((b + ramp) - t) / ramp, 0.0, 1.0)
            inside = np.minimum(down, up)
            g = np.minimum(g, 1.0 - (1.0 - duck_factor) * inside)
        return g

    def make(get_frame, t):
        frame = get_frame(t)
        e = env(t)
        return frame * e[:, None] if getattr(frame, "ndim", 1) == 2 else frame * e

    try:
        return music.transform(make)
    except Exception:  # noqa: BLE001
        return music


def _scale(clip, factor: float):
    if abs(factor - 1.0) < 1e-3:
        return clip
    try:
        return clip.with_volume_scaled(factor)
    except AttributeError:
        from moviepy.audio.fx import MultiplyVolume

        return clip.with_effects([MultiplyVolume(factor)])
