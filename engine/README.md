# demoreel — engine

The rendering engine behind the demo skill. A declarative YAML spec drives a real browser
(Playwright) and the engine produces a finished `.mp4` that looks hand-made:

- **Studio framing** — the recording floats on a gradient backdrop inside a macOS browser
  window (traffic lights + URL bar), rounded corners + soft drop shadow. The camera zooms
  *past* the window edge into the content.
- **Smart camera** — spring/cubic/smoothstep easing, **element-aware zoom** (small targets
  zoom harder), subtle idle drift. Zoom follows clicks/annotations automatically.
- **Animated cursor + keycast**, **annotations** (`highlight`, `spotlight`, `callout`,
  `arrow`, `chapter`), **voiceover** (Piper/say/OpenAI/ElevenLabs, normalized), **audio**
  (ducked music + procedural SFX), **captions** (`pill`/`lower_third`/`karaoke`), a **brand
  kit**, and themed **intro/outro cards** with transitions.

## Pipeline

```
scenes.yaml ─▶ TTS (per-scene wav + durations, normalized)
            ─▶ [optional] Whisper word alignment (karaoke)
            ─▶ Playwright capture (drive + record; click/annotation track → camera keyframes)
            ─▶ compose: stage framing + camera → captions → brand → audio → cards/transitions
            ─▶ demo.mp4 (+ .srt / .vtt / .transcript.md)
```

## Setup (one-time)

```bash
cd engine
uv sync --extra piper                 # + --extra align (karaoke), --extra cloud (OpenAI)
uv run playwright install chromium
uv run demoreel doctor
```

`ffmpeg` is provided via `imageio-ffmpeg` — no system install required.

## Usage

```bash
uv run demoreel validate examples/playwright-tour.yaml   # parse + scene plan (no browser/TTS)
uv run demoreel check    examples/playwright-tour.yaml   # open the page, verify selectors
uv run demoreel render   examples/playwright-tour.yaml -o out.mp4
uv run demoreel render   examples/playwright-tour.yaml --preview     # fast low-res pass
uv run demoreel render   examples/playwright-tour.yaml --storyboard  # also a contact sheet
uv run demoreel init my-demo.yaml             # starter spec
uv run demoreel voices
```

## Spec reference

### Top level

| Key | Meaning |
|-----|---------|
| `title` | Demo title (default intro card) |
| `url` | Base URL; scene `goto` may be absolute or relative |
| `viewport` | `[w, h]` page/recording size (default `1600×900` — ~1:1 with a 1080p studio window) |
| `fps` | Output frame rate (default `30`) |
| `output` | Output `.mp4` path |
| `preset` | `studio` (default) · `dark` · `light` · `minimal` |
| `storage_state` | Playwright `storageState` JSON for pre-authed demos |
| `quality` | `{ resolution: 720p\|1080p\|1440p\|4k\|[w,h], scale }` (default `1080p`) |
| `frame` | `{ style: studio\|full_bleed, chrome: browser\|none, background, padding, radius, shadow }` |
| `camera` | `{ auto_zoom, zoom, easing: spring\|cubic\|smoothstep, framing: element\|point, idle_drift }` |
| `cursor` | `{ show, style: pointer\|dot, size, color, keycast }` |
| `captions` | `{ enabled, style: pill\|lower_third\|karaoke, size, position, color, box, accent }` |
| `audio` | `{ music, music_volume, duck, normalize, sfx: { enabled, click, typing, volume } }` |
| `brand` | `{ logo, color, watermark, watermark_position, name, title }` |
| `prelude` | `{ hide: [sel], mask: [sel], freeze_anim, inject_css, inject_js }` |
| `transition` | `{ type: crossfade\|dip\|cut, duration }` |
| `voice` | `{ engine: piper\|say\|openai\|elevenlabs, model, rate, volume }` |
| `intro` / `outro` | `{ title, subtitle, seconds, narrate, cta }` |
| `scenes` | Ordered list of scene beats |

### Scene — narration + at most one action + optional annotations + hints

| Key | Meaning |
|-----|---------|
| `narrate` / `narrate_after` | Voiceover + caption (after the action if `narrate_after`) |
| `goto` `click` `hover` `type` `press` `scroll` `wait` | The one primary action |
| `highlight` `spotlight` | Outline / dim-around a selector |
| `callout` | `{ text, at: <sel>, placement }` (or a bare string banner) |
| `arrow` | `{ to: <sel>, text, dir }` |
| `chapter` | `{ title, subtitle, seconds }` (or a bare string) — full-screen section card |
| `focus` | Selector to frame the zoom on (defaults to the action/annotation target) |
| `zoom` / `no_zoom` | Override or disable this scene's zoom |
| `hold` / `pause` | Extra dwell after / silent pause before the action |
| `wait_for` | Await a selector before the scene ends |
| `persist` | Keep annotations into the next scene |

`type` is `{ selector, text, delay }` or a bare string. `scroll` is `{ to: <sel> }` or `{ by: <px> }`.

## Authenticated demos

```bash
uv run playwright open --save-storage=auth.json https://your-app.example.com
# log in, close the window
```
Set `storage_state: auth.json`.

## Notes

- Prefer `text=` / `role=` selectors — they survive redesigns. Run `demoreel check` first.
- Render time scales with resolution × duration. Use `--preview` while iterating; keep
  `viewport` ≈ the studio window width so the page stays crisp (no upscaling).
