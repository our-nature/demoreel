"""Subtitle rendering — on-screen caption images (PIL) and a sidecar .srt file.

We render captions ourselves with Pillow (rounded translucent pill, soft shadow, word
wrap) rather than moviepy's TextClip, so styling is fully under our control and there is
no system-font/ImageMagick dependency.

Long narration is split into timed cues spread across its scene, so captions track the
voiceover instead of dumping a wall of text.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from PIL import Image, ImageDraw, ImageFont

FontT = Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Avenir Next.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


@dataclass
class Cue:
    start: float
    end: float
    text: str


def resolve_font(path: str | None, size: int) -> FontT:
    candidates = [path] if path else []
    candidates += _FONT_CANDIDATES
    for c in candidates:
        if c and Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1 returns a sized font
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def split_into_cues(text: str, start: float, end: float, max_chars: int = 90) -> list[Cue]:
    """Split narration into time-proportional caption cues across [start, end]."""
    text = " ".join((text or "").split())
    if not text:
        return []
    chunks = _chunk_sentences(text, max_chars)
    total_chars = sum(len(c) for c in chunks) or 1
    cues: list[Cue] = []
    t = start
    span = max(end - start, 0.01)
    for chunk in chunks:
        share = span * (len(chunk) / total_chars)
        cues.append(Cue(t, min(t + share, end), chunk))
        t += share
    cues[-1].end = end
    return cues


def _chunk_sentences(text: str, max_chars: int) -> list[str]:
    # Prefer sentence boundaries, then fall back to width-based wrapping.
    import re

    parts = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            chunks.append(part)
        else:
            chunks.extend(textwrap.wrap(part, width=max_chars, break_long_words=False))
    return [c for c in chunks if c]


def render_caption_png(
    text: str,
    out_path: str | Path,
    video_w: int,
    font: FontT,
    max_width_ratio: float = 0.82,
    text_color: tuple = (245, 245, 250),
    box_color: tuple = (8, 8, 16, 200),
    accent_edge: tuple | None = None,
) -> tuple[Path, int, int]:
    """Render one caption to a transparent PNG. Returns (path, width, height)."""
    out_path = Path(out_path)
    pad_x, pad_y = 34, 20
    max_text_w = int(video_w * max_width_ratio) - 2 * pad_x

    lines = _wrap_to_width(text, font, max_text_w)
    line_h = _line_height(font) + 8
    text_w = max((_text_width(font, ln) for ln in lines), default=1)
    box_w = text_w + 2 * pad_x
    box_h = line_h * len(lines) + 2 * pad_y

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = min(26, box_h // 2)
    draw.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=radius, fill=box_color)
    if accent_edge:
        draw.rounded_rectangle([0, 0, 6, box_h - 1], radius=3, fill=accent_edge)

    align_left = accent_edge is not None
    y = pad_y
    for ln in lines:
        w = _text_width(font, ln)
        x = (pad_x + 6) if align_left else (box_w - w) // 2
        draw.text((x + 1, y + 2), ln, font=font, fill=(0, 0, 0, 150))  # shadow
        draw.text((x, y), ln, font=font, fill=(*text_color, 255))
        y += line_h

    img.save(out_path)
    return out_path, box_w, box_h


def karaoke_clip(words, start: float, end: float, video_w: int, font: FontT,
                 text_color: tuple, box_color: tuple, accent: tuple):
    """A moviepy clip that highlights each word as it's spoken.

    ``words`` is a list of ``(word, w_start, w_end)`` in absolute seconds.
    """
    import numpy as np
    from moviepy import VideoClip

    pad_x, pad_y = 34, 20
    line = " ".join(w for w, _, _ in words)
    line_h = _line_height(font) + 8
    text_w = _text_width(font, line)
    box_w = min(text_w + 2 * pad_x, int(video_w * 0.9))
    box_h = line_h + 2 * pad_y

    # precompute x offset of each word
    offsets = []
    x = pad_x
    for w, _, _ in words:
        offsets.append(x)
        x += _text_width(font, w + " ")

    dim = (text_color[0], text_color[1], text_color[2])

    def make(t):
        ab = start + t
        img = Image.new("RGB", (box_w, box_h), box_color[:3])
        d = ImageDraw.Draw(img)
        for (w, ws, we), ox in zip(words, offsets):
            if ws <= ab <= we:
                col = accent
            elif ab >= ws:
                col = text_color
            else:
                col = tuple(int(c * 0.55) for c in dim)
            d.text((ox, pad_y), w, font=font, fill=col)
        return np.asarray(img)

    return VideoClip(make, duration=max(end - start, 0.4)), box_w, box_h


def write_srt(cues: list[Cue], out_path: str | Path) -> None:
    _write_timed(cues, out_path, vtt=False)


def write_vtt(cues: list[Cue], out_path: str | Path) -> None:
    _write_timed(cues, out_path, vtt=True)


def write_transcript(text: str, title: str, out_path: str | Path) -> None:
    Path(out_path).write_text(f"# {title} — transcript\n\n{text.strip()}\n", encoding="utf-8")


def _text_width(font: FontT, text: str) -> int:
    box = font.getbbox(text)
    return int(box[2] - box[0])


def _line_height(font: FontT) -> int:
    if isinstance(font, ImageFont.FreeTypeFont):
        ascent, descent = font.getmetrics()
        return int(ascent + descent)
    box = font.getbbox("Ayg")
    return int(box[3] - box[1])


def _wrap_to_width(text: str, font: FontT, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if _text_width(font, trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [text]


def _write_timed(cues: list[Cue], out_path: str | Path, vtt: bool) -> None:
    sep = "." if vtt else ","
    lines: list[str] = ["WEBVTT", ""] if vtt else []
    for i, cue in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{_ts(cue.start, sep)} --> {_ts(cue.end, sep)}")
        lines.append(cue.text)
        lines.append("")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


def _ts(seconds: float, sep: str = ",") -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"
