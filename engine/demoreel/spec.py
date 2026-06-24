"""Declarative demo spec — the YAML that Claude (or a human) authors to make a video.

A spec is a small, diffable document: global settings + an ordered list of scenes. Each
scene is one beat of the demo: narration + at most one primary browser action
(goto/click/type/...) + optional annotations (highlight/spotlight/callout/...) +
presentation hints (zoom, hold, pause, transition).

Defaults come from a named `preset` (see themes.py); explicit fields always win. The
default preset (`studio`) yields the Studio look: the recording floated on a gradient
backdrop inside a macOS browser window, with spring-eased zoom-to-click.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------- actions


class TypeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: str | None = None
    text: str
    delay: int = 45


class ScrollAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str | None = None
    by: int | None = None


# ----------------------------------------------------------------------- annotations


class Callout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    at: str | None = None  # selector to point at; None = centered banner
    placement: Literal["auto", "top", "bottom", "left", "right"] = "auto"


class Arrow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str  # selector the arrow points at
    text: str | None = None
    dir: Literal["up", "down", "left", "right"] = "up"


class Chapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    subtitle: str | None = None
    seconds: float = 1.8


# --------------------------------------------------------------------------- scene


class Scene(BaseModel):
    """One beat: narration + at most one primary action + optional annotations/hints."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = None
    narrate: str | None = None
    narrate_after: bool = False

    # primary action (at most one)
    goto: str | None = None
    click: str | None = None
    hover: str | None = None
    type: TypeAction | str | None = None
    press: str | None = None
    scroll: ScrollAction | None = None
    wait: float | None = None

    # annotations / overlays (may combine with an action)
    highlight: str | None = None
    spotlight: str | None = None
    callout: Callout | str | None = None
    arrow: Arrow | None = None
    chapter: Chapter | str | None = None
    persist: bool = False  # keep annotations into the next scene (default: clear)

    # timing / presentation
    wait_for: str | None = None
    zoom: float | None = None
    no_zoom: bool = False
    focus: str | None = None  # explicit selector to frame the zoom on
    hold: float | None = None
    pause: float | None = None  # extra silent dwell before the action
    transition: str | None = None  # override transition INTO this scene (cut|crossfade|dip)

    _ACTION_FIELDS = ("goto", "click", "hover", "type", "press", "scroll", "wait")
    _FOCUS_FIELDS = ("focus", "callout", "arrow", "highlight", "spotlight", "click", "hover", "type")

    @model_validator(mode="after")
    def _at_most_one_action(self) -> "Scene":
        present = [f for f in self._ACTION_FIELDS if getattr(self, f) is not None]
        if len(present) > 1:
            raise ValueError(
                f"scene has multiple actions {present}; use one action per scene"
            )
        return self

    def primary_action(self) -> tuple[str, object] | None:
        for f in self._ACTION_FIELDS:
            v = getattr(self, f)
            if v is not None:
                return f, v
        return None

    def focus_selector(self) -> str | None:
        """The selector the camera should frame for this scene's zoom, if any."""
        if self.focus:
            return self.focus
        if isinstance(self.callout, Callout) and self.callout.at:
            return self.callout.at
        if self.arrow:
            return self.arrow.to
        if self.highlight:
            return self.highlight
        if self.spotlight:
            return self.spotlight
        if self.click:
            return self.click
        if self.hover:
            return self.hover
        if isinstance(self.type, TypeAction) and self.type.selector:
            return self.type.selector
        return None

    def has_focus_point(self) -> bool:
        return self.focus_selector() is not None

    def effective_zoom(self, cam: "CameraConfig") -> float | None:
        if self.no_zoom:
            return None
        if self.zoom is not None:
            return self.zoom
        if cam.auto_zoom and self.has_focus_point():
            return cam.zoom
        return None


# --------------------------------------------------------------------------- config blocks


class GradientBg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colors: list[str] = Field(min_length=2)
    angle: float = 135.0


class FrameConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: Literal["studio", "full_bleed"] = "studio"
    background: Union[str, GradientBg, None] = None  # hex | gradient | image path
    padding: float = 0.055  # fraction of min(OW, OH)
    radius: int = 14
    shadow: bool = True
    shadow_blur: int = 48
    shadow_opacity: float = 0.55
    chrome: Literal["browser", "none"] = "browser"
    chrome_url: str | None = None
    chrome_title: str | None = None


class CameraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_zoom: bool = True
    zoom: float = 1.6
    easing: Literal["smoothstep", "cubic", "spring"] = "spring"
    overshoot: float = 0.0  # no overshoot by default — overshoot reads as an unwanted shift
    idle_drift: bool = False  # off by default — the continuous wander reads as drift
    drift_amount: float = 0.006
    framing: Literal["element", "point"] = "element"
    settle: float = 0.38


class CursorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    show: bool = True
    style: Literal["pointer", "dot"] = "pointer"
    size: int = 22
    color: str = "#6C5CE7"
    glide: Literal["ease", "linear"] = "ease"
    keycast: bool = True


class CaptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    style: Literal["pill", "lower_third", "karaoke"] = "pill"
    font: str | None = None
    size: int = 40
    position: Literal["bottom", "top"] = "bottom"
    color: str = "#F5F5FA"
    box: str = "#08080F"
    accent: str = "#6C5CE7"
    max_chars: int = 92


class SfxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    click: bool = True
    typing: bool = True
    volume: float = 0.22


class AudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    music: str | None = None
    music_volume: float = 0.12
    duck: bool = True
    normalize: bool = True
    sfx: SfxConfig = Field(default_factory=SfxConfig)


class BrandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logo: str | None = None
    color: str | None = None
    watermark: bool = True
    watermark_position: Literal["bottom-right", "bottom-left", "top-right", "top-left"] = (
        "bottom-right"
    )
    watermark_opacity: float = 0.5
    name: str | None = None  # lower-third name
    title: str | None = None  # lower-third title


class Prelude(BaseModel):
    """Determinism + stabilization applied before/while recording."""

    model_config = ConfigDict(extra="forbid")
    hide: list[str] = Field(default_factory=list)  # selectors to hide (cookie banners, etc.)
    mask: list[str] = Field(default_factory=list)  # selectors to cover (dynamic regions)
    freeze_anim: bool = False
    inject_css: str | None = None
    inject_js: str | None = None


# Module-level so both the validator (classmethod) and the .size property can read it.
# Defining this inside the model as ``_PRESETS`` turns it into a pydantic
# ModelPrivateAttr descriptor, which ``cls._PRESETS`` then can't iterate over.
_RESOLUTION_PRESETS = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
}


class Quality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Union[str, tuple[int, int]] = "1080p"
    scale: int = 1  # multiplies the capture viewport for a higher-res recording

    @field_validator("resolution")
    @classmethod
    def _check(cls, v):
        if isinstance(v, str) and v.lower() not in _RESOLUTION_PRESETS:
            raise ValueError(
                f"unknown resolution {v!r}; use {list(_RESOLUTION_PRESETS)} or [w,h]"
            )
        return v

    @property
    def size(self) -> tuple[int, int]:
        # Normalize at access time: field validators don't run on default values, so
        # the default "1080p" may still be a string here.
        r = self.resolution
        if isinstance(r, str):
            return _RESOLUTION_PRESETS[r.lower()]
        return (int(r[0]), int(r[1]))


class TransitionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cut", "crossfade", "dip"] = "crossfade"
    duration: float = 0.5


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["piper", "say", "openai", "elevenlabs"] = "piper"
    model: str | None = None
    rate: float = 1.0
    volume: float = 1.0


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    subtitle: str | None = None
    seconds: float = 2.5
    narrate: str | None = None
    cta: str | None = None  # outro call-to-action line


# --------------------------------------------------------------------------- top-level


class DemoSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: str = "Demo"
    url: str | None = None
    viewport: tuple[int, int] = (1600, 900)
    fps: int = 30
    output: str = "demo.mp4"
    headless: bool = True
    storage_state: str | None = None
    preset: str = "studio"

    quality: Quality = Field(default_factory=Quality)
    frame: FrameConfig = Field(default_factory=FrameConfig)
    camera: CameraConfig = Field(default_factory=CameraConfig)
    cursor: CursorConfig = Field(default_factory=CursorConfig)
    captions: CaptionConfig = Field(default_factory=CaptionConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    brand: BrandConfig = Field(default_factory=BrandConfig)
    prelude: Prelude = Field(default_factory=Prelude)
    transition: TransitionConfig = Field(default_factory=TransitionConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)

    intro: Card | None = None
    outro: Card | None = None
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_first_navigation(self) -> "DemoSpec":
        first = self.scenes[0]
        if first.goto is None and self.url is None:
            raise ValueError(
                "the first scene must `goto` a URL (or set a top-level `url`)"
            )
        return self

    def output_size(self) -> tuple[int, int]:
        return self.quality.size


def load_spec(path: str | Path) -> DemoSpec:
    """Parse a YAML spec, merge the selected preset under it, and validate."""
    from .themes import apply_preset

    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    merged = apply_preset(raw)
    return DemoSpec.model_validate(merged)
