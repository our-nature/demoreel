"""Theme presets — one-line polished looks.

A preset is a partial spec dict deep-merged *under* the user's YAML (user fields always
win). Presets mostly set backgrounds, accent colors, and the framing style; the model
defaults in spec.py already encode the Studio look, so presets stay small.
"""

from __future__ import annotations

import copy
from typing import Any

# Each preset is a partial DemoSpec dict. Only deviations from the model defaults.
PRESETS: dict[str, dict[str, Any]] = {
    # Default — indigo-tinted dark Studio backdrop with a browser window.
    "studio": {
        "frame": {
            "style": "studio",
            "chrome": "browser",
            "background": {"colors": ["#1B1B2E", "#0B0B12"], "angle": 135},
        },
        "camera": {"easing": "spring"},
        "cursor": {"color": "#6C5CE7"},
        "captions": {"accent": "#6C5CE7"},
        "brand": {"color": "#6C5CE7"},
    },
    # Neutral, untinted dark with a teal accent.
    "dark": {
        "frame": {
            "style": "studio",
            "chrome": "browser",
            "background": {"colors": ["#15151A", "#070709"], "angle": 135},
        },
        "cursor": {"color": "#5EE0C8"},
        "captions": {"accent": "#5EE0C8"},
        "brand": {"color": "#5EE0C8"},
    },
    # Light Studio look for product/leadership audiences.
    "light": {
        "frame": {
            "style": "studio",
            "chrome": "browser",
            "background": {"colors": ["#EEF1F6", "#D9DEE8"], "angle": 135},
            "shadow_opacity": 0.28,
        },
        "cursor": {"color": "#4338CA"},
        "captions": {"color": "#10101A", "box": "#FFFFFF", "accent": "#4338CA"},
        "brand": {"color": "#4338CA"},
    },
    # Edge-to-edge, no chrome, no backdrop — fast and neutral.
    "minimal": {
        "frame": {"style": "full_bleed", "chrome": "none", "background": "#0B0B12"},
        "camera": {"idle_drift": False, "easing": "cubic"},
        "captions": {"accent": "#6C5CE7"},
        "brand": {"watermark": False},
    },
}

DEFAULT_PRESET = "studio"


def apply_preset(raw: dict[str, Any]) -> dict[str, Any]:
    name = raw.get("preset", DEFAULT_PRESET)
    base = copy.deepcopy(PRESETS.get(name, PRESETS[DEFAULT_PRESET]))
    return _deep_merge(base, raw)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
