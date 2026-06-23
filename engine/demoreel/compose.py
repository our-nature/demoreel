"""Composition — turn the raw recording + timeline into the finished video.

  1. Studio framing + camera (stage.py): backdrop, browser window, zoom/pan.
  2. Captions (pill / lower-third / karaoke) overlaid on top.
  3. Brand: corner watermark + optional lower-third.
  4. Audio: VO + SFX + ducked music (audio.py).
  5. Intro/outro title cards with the chosen transition.
  6. Encode mp4 + sidecar srt/vtt/transcript.

moviepy 2.x API throughout.
"""

from __future__ import annotations

from pathlib import Path

from . import brand
from .audio import build_content_audio
from .capture import CaptureResult
from .spec import DemoSpec
from .stage import StageCompositor, _hex
from .subtitles import (
    Cue,
    karaoke_clip,
    render_caption_png,
    resolve_font,
    split_into_cues,
    write_srt,
    write_transcript,
    write_vtt,
)


class ComposeError(RuntimeError):
    pass


def compose(
    spec: DemoSpec,
    cap: CaptureResult,
    scene_texts: dict[int, str],
    build_dir: Path,
    output: Path,
    intro_wav: str | None = None,
    outro_wav: str | None = None,
    word_timings: dict[int, list] | None = None,
) -> Path:
    try:
        import cv2  # noqa: F401
        from moviepy import CompositeVideoClip, VideoClip, VideoFileClip, concatenate_videoclips
    except ImportError as exc:  # pragma: no cover
        raise ComposeError(
            "compose deps missing. `pip install moviepy opencv-python-headless`."
        ) from exc

    word_timings = word_timings or {}
    OW, OH = spec.output_size()
    stage = StageCompositor(spec, cap)

    recording = VideoFileClip(cap.video_path).without_audio()
    duration = recording.duration

    def make_frame(t):
        return stage.frame(recording.get_frame, t)

    content_video = VideoClip(make_frame, duration=duration)

    # captions ----------------------------------------------------------------------
    overlays = []
    srt_cues: list[Cue] = []
    transcript_parts: list[str] = []
    cc = spec.captions
    if cc.enabled:
        font = resolve_font(cc.font, _scaled(cc.size, OH))
        margin = int(OH * 0.06)
        tcol = _hex(cc.color)
        bcol = (*_hex(cc.box), 216)
        accent = _hex(cc.accent)
        for st in cap.scenes:
            text = (scene_texts.get(st.index) or "").strip()
            if st.narration_duration <= 0 or not text:
                continue
            transcript_parts.append(text)
            cue_end = min(st.audio_start + st.narration_duration, duration)
            wt = word_timings.get(st.index)
            if cc.style == "karaoke" and wt:
                _karaoke(overlays, srt_cues, wt, st.audio_start, OW, OH, margin, font,
                         tcol, bcol, accent, cc.max_chars, duration)
            else:
                _static_caps(overlays, srt_cues, text, st.audio_start, cue_end, build_dir,
                             st.index, OW, OH, margin, font, tcol, bcol, accent, cc, duration)

    # brand -------------------------------------------------------------------------
    wm = brand.watermark_clip(spec, duration)
    if wm is not None:
        overlays.append(wm)
    lt = brand.lower_third_clip(spec)
    if lt is not None:
        overlays.append(lt)

    content = CompositeVideoClip([content_video, *overlays], size=(OW, OH)).with_duration(duration)

    audio = build_content_audio(spec, cap, build_dir)
    if audio is not None:
        content = content.with_audio(audio)

    # intro / outro + transitions ---------------------------------------------------
    segments = []
    intro_offset = 0.0
    if spec.intro:
        ic = brand.card_clip(spec, spec.intro, intro_wav)
        segments.append(ic)
        intro_offset = ic.duration
    segments.append(content)
    if spec.outro:
        segments.append(brand.card_clip(spec, spec.outro, outro_wav))

    final = _concat(segments, spec.transition, concatenate_videoclips)

    # encode ------------------------------------------------------------------------
    output.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(output), fps=spec.fps, codec="libx264", audio_codec="aac",
        preset="medium", threads=4,
    )

    # sidecars ----------------------------------------------------------------------
    if srt_cues:
        shifted = [Cue(c.start + intro_offset, c.end + intro_offset, c.text) for c in srt_cues]
        write_srt(shifted, output.with_suffix(".srt"))
        write_vtt(shifted, output.with_suffix(".vtt"))
    if transcript_parts:
        write_transcript(" ".join(transcript_parts), spec.title,
                         output.with_suffix(".transcript.md"))
    return output


# --------------------------------------------------------------------------- captions


def _static_caps(overlays, srt_cues, text, start, end, build_dir, idx, OW, OH, margin, font,
                 tcol, bcol, accent, cc, duration) -> None:
    from moviepy import ImageClip

    lower = cc.style == "lower_third"
    for j, cue in enumerate(split_into_cues(text, start, end, cc.max_chars)):
        png, w, h = render_caption_png(
            cue.text, build_dir / f"cap_{idx}_{j}.png", OW, font,
            text_color=tcol, box_color=bcol,
            accent_edge=(*accent, 255) if lower else None,
        )
        dur = max(min(cue.end, duration) - cue.start, 0.4)
        y = margin if cc.position == "top" else OH - h - margin
        x = int(OW * 0.06) if lower else "center"
        clip = (
            ImageClip(str(png), transparent=True)
            .with_start(cue.start)
            .with_duration(dur)
            .with_position((x, y))
        )
        overlays.append(clip)
        srt_cues.append(cue)


def _karaoke(overlays, srt_cues, word_timings, audio_start, OW, OH, margin, font,
             tcol, bcol, accent, max_chars, duration) -> None:
    words = [(w, audio_start + ws, audio_start + we) for (w, ws, we) in word_timings]
    for line in _group_words(words, max_chars):
        ls, le = line[0][1], min(line[-1][2], duration)
        clip, _w, h = karaoke_clip(line, ls, le, OW, font, tcol, bcol, accent)
        clip = clip.with_start(ls).with_position(("center", OH - h - margin))
        overlays.append(clip)
        srt_cues.append(Cue(ls, le, " ".join(w for w, _, _ in line)))


def _group_words(words, max_chars):
    lines, cur, count = [], [], 0
    for w in words:
        if cur and count + len(w[0]) > max_chars:
            lines.append(cur)
            cur, count = [], 0
        cur.append(w)
        count += len(w[0]) + 1
    if cur:
        lines.append(cur)
    return lines


# ------------------------------------------------------------------------ transitions


def _concat(clips, tcfg, concatenate_videoclips):
    if len(clips) == 1:
        return clips[0]
    if tcfg.type == "cut":
        return concatenate_videoclips(clips, method="compose")
    d = tcfg.duration
    try:
        if tcfg.type == "dip":
            from moviepy.video.fx import FadeIn, FadeOut

            out = []
            for i, c in enumerate(clips):
                fx = []
                if i > 0:
                    fx.append(FadeIn(d / 2))
                if i < len(clips) - 1:
                    fx.append(FadeOut(d / 2))
                out.append(c.with_effects(fx) if fx else c)
            return concatenate_videoclips(out, method="compose")
        # crossfade
        from moviepy.video.fx import CrossFadeIn

        out = [clips[0]]
        for c in clips[1:]:
            out.append(c.with_effects([CrossFadeIn(d)]))
        return concatenate_videoclips(out, method="compose", padding=-d)
    except Exception:  # noqa: BLE001 - never fail the render on a transition
        return concatenate_videoclips(clips, method="compose")


def _scaled(size: int, out_h: int) -> int:
    return max(14, int(round(size * out_h / 1080.0)))
