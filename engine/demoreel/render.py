"""Orchestration — spec -> voiceover -> capture -> compose -> mp4.

Runs TTS first (so capture knows how long to dwell), normalizes the voiceover, optionally
aligns words for karaoke captions, records, then composes.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .audio import normalize_wav
from .capture import capture
from .compose import compose
from .spec import DemoSpec, ScrollAction, TypeAction, load_spec
from .tts import synthesize

Progress = Callable[[str], None]


def render(
    spec_path: str | Path,
    output: str | Path | None = None,
    keep_build: bool = False,
    progress: Progress | None = None,
    headed: bool = False,
    voice_engine: str | None = None,
    preview: bool = False,
) -> Path:
    spec = load_spec(spec_path)
    if headed:
        spec.headless = False
    if voice_engine:
        spec.voice.engine = voice_engine  # type: ignore[assignment]
    if preview:
        # fast pass: small + low fps, no karaoke/sfx
        spec.quality.resolution = (1280, 720)
        spec.quality.scale = 1
        spec.fps = 15
        spec.captions.style = "pill"
        spec.audio.sfx.enabled = False
    log = progress or (lambda *_: None)

    out = Path(output) if output else Path(spec.output)
    build_dir = out.parent / ".demoreel" / out.stem
    build_dir.mkdir(parents=True, exist_ok=True)

    # 1. voiceover ------------------------------------------------------------------
    log(f"Synthesizing voiceover ({spec.voice.engine}) for {len(spec.scenes)} scenes…")
    narrations: list[tuple[str | None, float]] = []
    scene_texts: dict[int, str] = {}
    for i, scene in enumerate(spec.scenes):
        if scene.narrate:
            wav = build_dir / f"scene_{i:03d}.wav"
            dur = synthesize(scene.narrate, wav, spec.voice)
            if spec.audio.normalize:
                normalize_wav(str(wav))  # amplitude only; duration unchanged
            narrations.append((str(wav), dur))
            scene_texts[i] = scene.narrate
        else:
            narrations.append((None, 0.0))

    intro_wav = _card_voice(spec.intro, build_dir / "intro.wav", spec)
    outro_wav = _card_voice(spec.outro, build_dir / "outro.wav", spec)

    # 2. word alignment (karaoke captions) ------------------------------------------
    word_timings: dict[int, list] = {}
    if spec.captions.style == "karaoke":
        word_timings = _align(spec, narrations, log)

    # 3. capture --------------------------------------------------------------------
    log("Recording browser walkthrough…")
    cap = capture(spec, narrations, build_dir)
    log(f"Captured {cap.duration:.1f}s across {len(cap.scenes)} scenes.")

    # 4. compose --------------------------------------------------------------------
    log("Composing video (framing, camera, captions, audio)…")
    final = compose(spec, cap, scene_texts, build_dir, out, intro_wav, outro_wav, word_timings)

    if not keep_build:
        shutil.rmtree(build_dir, ignore_errors=True)
    log(f"Done → {final}")
    return final


def _card_voice(card, wav_path: Path, spec: DemoSpec) -> str | None:
    if not card or not card.narrate:
        return None
    synthesize(card.narrate, wav_path, spec.voice)
    if spec.audio.normalize:
        normalize_wav(str(wav_path))
    return str(wav_path)


def _align(spec: DemoSpec, narrations, log) -> dict[int, list]:
    try:
        from .align import align_words
    except Exception:  # noqa: BLE001
        return {}
    timings: dict[int, list] = {}
    log("Aligning words for karaoke captions (whisper)…")
    for i, (wav, dur) in enumerate(narrations):
        if not wav or dur <= 0:
            continue
        try:
            timings[i] = align_words(wav)
        except Exception as exc:  # noqa: BLE001
            log(f"  alignment skipped for scene {i}: {exc}")
    return timings


# --------------------------------------------------------------------------- dry run


@dataclass
class PlanRow:
    index: int
    action: str
    zoom: str
    narration: str
    est_seconds: float


def plan(spec_path: str | Path) -> tuple[DemoSpec, list[PlanRow], float]:
    spec = load_spec(spec_path)
    rows: list[PlanRow] = []
    total = (spec.intro.seconds if spec.intro else 0.0) + (
        spec.outro.seconds if spec.outro else 0.0
    )
    for i, scene in enumerate(spec.scenes):
        act = scene.primary_action()
        action = _describe(scene) if act or _has_annotation(scene) else "—"
        z = scene.effective_zoom(spec.camera)
        words = len((scene.narrate or "").split())
        est = max(words / 2.6, 0.0) + (scene.hold if scene.hold is not None else 0.6)
        est = max(est, 1.0) + (scene.pause or 0.0)
        rows.append(
            PlanRow(i, action, f"{z:.2f}×" if z else "—", (scene.narrate or "").strip(), round(est, 1))
        )
        total += est
    return spec, rows, round(total, 1)


def _has_annotation(scene) -> bool:
    return any(getattr(scene, f) is not None for f in ("highlight", "spotlight", "callout", "arrow", "chapter"))


def _describe(scene) -> str:
    parts = []
    act = scene.primary_action()
    if act:
        kind, val = act
        if kind == "type":
            parts.append(f"type {val.text!r}" if isinstance(val, TypeAction) else f"type {val!r}")
        elif kind == "scroll" and isinstance(val, ScrollAction):
            parts.append(f"scroll {'to ' + val.to if val.to else f'by {val.by}px'}")
        elif kind == "wait":
            parts.append(f"wait {val}s")
        else:
            parts.append(f"{kind} {val}")
    for f in ("highlight", "spotlight", "callout", "arrow", "chapter"):
        if getattr(scene, f) is not None:
            parts.append(f"+{f}")
    return " ".join(parts) or "—"
