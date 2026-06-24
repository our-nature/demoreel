"""Brand + title cards — intro/outro cards (themed to match the Studio backdrop), a corner
logo watermark, and an optional lower-third name/title bar.

Cards reuse the frame backdrop so the whole video feels like one piece.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .spec import Card, DemoSpec
from .stage import _build_background, _hex, _is_light
from .subtitles import resolve_font


def card_clip(spec: DemoSpec, card: Card, narration_wav: str | None):
    """A title card as a moviepy clip (fades + optional narration)."""
    from moviepy import AudioFileClip, ImageClip
    from moviepy.video.fx import FadeIn, FadeOut

    arr = _render_card(spec, card)
    duration = card.seconds
    if narration_wav and Path(narration_wav).exists():
        from .tts import wav_duration

        duration = max(card.seconds, wav_duration(narration_wav) + 0.8)

    clip = ImageClip(arr).with_duration(duration).with_effects([FadeIn(0.45), FadeOut(0.45)])
    if narration_wav and Path(narration_wav).exists():
        clip = clip.with_audio(AudioFileClip(narration_wav).with_start(0.35))
    return clip


def _render_card(spec: DemoSpec, card: Card) -> np.ndarray:
    w, h = spec.output_size()
    bg = _build_background(spec.frame.background, w, h)
    img = Image.fromarray(bg, "RGB")
    d = ImageDraw.Draw(img)
    light = _is_light(spec.frame.background)
    accent = _hex(spec.brand.color or spec.captions.accent)
    title_col = (24, 24, 32) if light else (242, 242, 248)
    sub_col = (90, 90, 105) if light else (170, 170, 190)

    # accent bar
    bar_w = int(w * 0.10)
    bx = (w - bar_w) // 2
    by = int(h * 0.39)
    d.rounded_rectangle([bx, by, bx + bar_w, by + 6], radius=3, fill=accent)

    title_font = resolve_font(spec.captions.font, int(h * 0.085))
    sub_font = resolve_font(spec.captions.font, int(h * 0.036))
    _centered(d, card.title, title_font, w, int(h * 0.43), title_col)
    if card.subtitle:
        _centered(d, card.subtitle, sub_font, w, int(h * 0.55), sub_col)
    if card.cta:
        cta_font = resolve_font(spec.captions.font, int(h * 0.030))
        _pill(d, card.cta, cta_font, w, int(h * 0.66), accent)

    _paste_logo(img, spec)
    return np.asarray(img)


def watermark_clip(spec: DemoSpec, duration: float):
    """A small logo watermark over the whole video, or None."""
    if not spec.brand.watermark or not spec.brand.logo:
        return None
    logo_path = Path(spec.brand.logo)
    if not logo_path.exists():
        return None
    try:
        from moviepy import ImageClip

        w, h = spec.output_size()
        logo = Image.open(logo_path).convert("RGBA")
        target_h = int(h * 0.05)
        scale = target_h / logo.height
        logo = logo.resize((int(logo.width * scale), target_h))
        if spec.brand.watermark_opacity < 1.0:
            alpha = logo.split()[3].point(lambda a: int(a * spec.brand.watermark_opacity))
            logo.putalpha(alpha)
        arr = np.asarray(logo)
        margin = int(h * 0.03)
        pos = _corner_pos(spec.brand.watermark_position, w, h, logo.width, logo.height, margin)
        return ImageClip(arr, transparent=True).with_duration(duration).with_position(pos)
    except Exception:  # noqa: BLE001
        return None


def lower_third_clip(spec: DemoSpec, show_seconds: float = 4.0):
    """An animated name/title bar near the bottom-left, or None."""
    b = spec.brand
    if not b.name and not b.title:
        return None
    try:
        from moviepy import ImageClip
        from moviepy.video.fx import FadeIn, FadeOut

        w, h = spec.output_size()
        arr = _render_lower_third(spec)
        margin = int(h * 0.07)
        clip = (
            ImageClip(arr, transparent=True)
            .with_duration(show_seconds)
            .with_start(0.6)
            .with_position((int(w * 0.06), h - arr.shape[0] - margin))
            .with_effects([FadeIn(0.4), FadeOut(0.5)])
        )
        return clip
    except Exception:  # noqa: BLE001
        return None


def _render_lower_third(spec: DemoSpec) -> np.ndarray:
    b = spec.brand
    h = spec.output_size()[1]
    accent = _hex(b.color or spec.captions.accent)
    name_font = resolve_font(spec.captions.font, int(h * 0.034))
    title_font = resolve_font(spec.captions.font, int(h * 0.024))

    name = b.name or ""
    title = b.title or ""
    pad = 18
    nw = int(name_font.getbbox(name)[2]) if name else 0
    tw = int(title_font.getbbox(title)[2]) if title else 0
    bar_w = max(nw, tw) + 2 * pad + 12
    bar_h = int(h * 0.105)
    img = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, bar_w - 1, bar_h - 1], radius=14, fill=(10, 10, 18, 215))
    d.rounded_rectangle([0, 0, 6, bar_h - 1], radius=3, fill=(*accent, 255))
    if name:
        d.text((pad + 8, int(bar_h * 0.18)), name, font=name_font, fill=(245, 245, 250))
    if title:
        d.text((pad + 8, int(bar_h * 0.56)), title, font=title_font, fill=(165, 165, 185))
    return np.asarray(img)


# --------------------------------------------------------------------------- helpers


def _paste_logo(img: Image.Image, spec: DemoSpec) -> None:
    if not spec.brand.logo:
        return
    p = Path(spec.brand.logo)
    if not p.exists():
        return
    try:
        w, h = img.size
        logo = Image.open(p).convert("RGBA")
        target_h = int(h * 0.07)
        scale = target_h / logo.height
        logo = logo.resize((int(logo.width * scale), target_h))
        x = (w - logo.width) // 2
        y = int(h * 0.72)
        img.paste(logo, (x, y), logo)
    except Exception:  # noqa: BLE001
        pass


def _corner_pos(position: str, w, h, lw, lh, margin):
    if position == "bottom-left":
        return (margin, h - lh - margin)
    if position == "top-right":
        return (w - lw - margin, margin)
    if position == "top-left":
        return (margin, margin)
    return (w - lw - margin, h - lh - margin)


def _centered(d, text, font, w, y, fill) -> None:
    # y = top of the text; anchor "ma" centers horizontally and avoids bbox-offset drift.
    d.text((w // 2, y), text, font=font, fill=fill, anchor="ma")


def _pill(d, text, font, w, y, accent) -> None:
    # Filled, contrast-aware CTA pill with the label optically centered.
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = int(th * 1.15), int(th * 0.62)
    pill_w, pill_h = tw + 2 * pad_x, th + 2 * pad_y
    x0 = (w - pill_w) // 2
    d.rounded_rectangle([x0, y, x0 + pill_w, y + pill_h], radius=pill_h // 2, fill=(*accent, 255))
    lum = 0.299 * accent[0] + 0.587 * accent[1] + 0.114 * accent[2]
    tcol = (12, 12, 18) if lum > 150 else (255, 255, 255)
    d.text((w // 2, y + pill_h // 2), text, font=font, fill=tcol, anchor="mm")
