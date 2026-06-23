"""demoreel command-line interface.

    demoreel render scenes.yaml [-o out.mp4] [--headed] [--engine say] [--preview]
                               [--storyboard] [--keep]
    demoreel validate scenes.yaml      # parse + print the scene plan (no browser/TTS)
    demoreel check scenes.yaml         # open the page and verify every selector resolves
    demoreel init [path.yaml]          # write a starter spec
    demoreel voices                    # list available TTS voices
    demoreel doctor                    # check the environment is ready
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "guide-walkthrough.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demoreel", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("render", help="render a demo video from a YAML spec")
    pr.add_argument("spec")
    pr.add_argument("-o", "--output", help="output mp4 path (overrides spec.output)")
    pr.add_argument("--headed", action="store_true", help="show the browser window")
    pr.add_argument("--engine", help="override voice engine (piper|say|openai|elevenlabs)")
    pr.add_argument("--preview", action="store_true", help="fast low-res pass for iteration")
    pr.add_argument("--storyboard", action="store_true", help="also write a contact sheet png")
    pr.add_argument("--keep", action="store_true", help="keep the .demoreel build dir")

    pv = sub.add_parser("validate", help="parse a spec and print the plan")
    pv.add_argument("spec")

    pc = sub.add_parser("check", help="open the page and verify selectors resolve")
    pc.add_argument("spec")
    pc.add_argument("--headed", action="store_true")

    pi = sub.add_parser("init", help="write a starter spec")
    pi.add_argument("path", nargs="?", default="demo.yaml")

    sub.add_parser("voices", help="list available TTS voices")
    sub.add_parser("doctor", help="check the environment")

    args = parser.parse_args(argv)
    return {
        "render": _render,
        "validate": _validate,
        "check": _check,
        "init": _init,
        "voices": lambda _a: _voices(),
        "doctor": lambda _a: _doctor(),
    }[args.cmd](args)


def _render(args) -> int:
    from .render import render

    try:
        out = render(
            args.spec, output=args.output, keep_build=args.keep, headed=args.headed,
            voice_engine=args.engine, preview=args.preview,
            progress=lambda m: print(f"  • {m}"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ render failed: {exc}", file=sys.stderr)
        return 1
    print(f"✓ {out}")
    for side in (out.with_suffix(".srt"), out.with_suffix(".vtt"),
                 out.parent / (out.stem + ".transcript.md")):
        if side.exists():
            print(f"✓ {side}")
    if args.storyboard:
        sb = out.with_suffix(".storyboard.png")
        if _storyboard(str(out), str(sb)):
            print(f"✓ {sb}")
    return 0


def _validate(args) -> int:
    from .render import plan

    try:
        spec, rows, total = plan(args.spec)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ invalid spec: {exc}", file=sys.stderr)
        return 1
    print(f"\n{spec.title}  —  {len(rows)} scenes, ~{total:.0f}s estimated  ·  preset: {spec.preset}\n")
    print(f"  {'#':>2}  {'zoom':<6} {'action':<42} narration")
    print(f"  {'-' * 2}  {'-' * 6} {'-' * 42} {'-' * 28}")
    for r in rows:
        nar = (r.narration[:56] + "…") if len(r.narration) > 56 else r.narration
        act = (r.action[:40] + "…") if len(r.action) > 40 else r.action
        print(f"  {r.index:>2}  {r.zoom:<6} {act:<42} {nar}")
    w, h = spec.output_size()
    print(f"\n  voice: {spec.voice.engine}  •  {w}×{h} @ {spec.fps}fps  •  "
          f"frame: {spec.frame.style}/{spec.frame.chrome}  •  captions: {spec.captions.style}")
    print("  ✓ spec is valid\n")
    return 0


def _check(args) -> int:
    from .check import check_live
    from .spec import load_spec

    try:
        spec = load_spec(args.spec)
        if args.headed:
            spec.headless = False
        rows = check_live(spec)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ check failed: {exc}", file=sys.stderr)
        return 1
    bad = [r for r in rows if not r.ok]
    print(f"\nselector check — {len(rows)} selectors, {len(bad)} missing\n")
    for r in rows:
        mark = "✓" if r.ok else "✗"
        print(f"  {mark} scene {r.scene:>2}: {r.selector}" + (f"  ({r.note})" if not r.ok else ""))
    print()
    return 0 if not bad else 1


def _init(args) -> int:
    dest = Path(args.path)
    if dest.exists():
        print(f"✗ {dest} already exists", file=sys.stderr)
        return 1
    if not EXAMPLE.exists():
        print(f"✗ bundled example not found at {EXAMPLE}", file=sys.stderr)
        return 1
    dest.write_text(EXAMPLE.read_text())
    print(f"✓ wrote starter spec → {dest}\n  edit it, then: demoreel render {dest}")
    return 0


def _voices() -> int:
    from .tts import DEFAULT_PIPER_VOICE, list_say_voices

    print(f"\npiper (local OSS, default): {DEFAULT_PIPER_VOICE}")
    print("  more at https://huggingface.co/rhasspy/piper-voices (e.g. en_US-ryan-high)")
    say = list_say_voices()
    if say:
        print(f"\nmacOS `say` ({len(say)}): {', '.join(say[:20])}" + (" …" if len(say) > 20 else ""))
    print("\nopenai: alloy, echo, fable, onyx, nova, shimmer (needs OPENAI_API_KEY)")
    print("elevenlabs: <voice_id> (needs ELEVENLABS_API_KEY)\n")
    return 0


def _doctor() -> int:
    ok = True
    print("\ndemoreel doctor\n")

    def check(label, fn):
        nonlocal ok
        try:
            detail = fn()
            print(f"  ✓ {label}{f'  ({detail})' if detail else ''}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  ✗ {label}: {exc}")

    check("pydantic", lambda: __import__("pydantic").VERSION)
    check("pyyaml", lambda: __import__("yaml").__version__)
    check("numpy", lambda: __import__("numpy").__version__)
    check("Pillow", lambda: __import__("PIL").__version__)
    check("opencv", lambda: __import__("cv2").__version__)
    check("moviepy", lambda: __import__("moviepy").__version__)
    check("ffmpeg (imageio)", lambda: __import__("imageio_ffmpeg").get_ffmpeg_exe())
    check("playwright chromium", _check_chromium)

    print("\n  optional:")
    for label, mod in [("piper-tts", "piper"), ("openai", "openai"), ("faster-whisper", "faster_whisper")]:
        try:
            __import__(mod)
            print(f"  ✓ {label}")
        except Exception:  # noqa: BLE001
            print(f"  – {label} (not installed)")
    import shutil as _sh

    print(f"  {'✓' if _sh.which('say') else '–'} macOS say")
    print("\n" + ("  ready ✓\n" if ok else "  missing required deps — `uv sync` in the engine dir\n"))
    return 0 if ok else 1


def _check_chromium() -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        path = p.chromium.executable_path
    if not path or not Path(path).exists():
        raise RuntimeError("run `playwright install chromium`")
    return "installed"


def _storyboard(video_path: str, out_png: str, cols: int = 3, rows: int = 3) -> bool:
    """Tile evenly-spaced frames into a contact sheet."""
    try:
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        n = cols * rows
        idxs = [int(total * (k + 0.5) / n) for k in range(n)]
        tiles = []
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            tiles.append(cv2.resize(frame, (640, 360)))
        cap.release()
        if not tiles:
            return False
        while len(tiles) < n:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(rows)])
        cv2.imwrite(out_png, grid)
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    raise SystemExit(main())
