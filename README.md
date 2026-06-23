# demoreel

**Studio-quality demo videos, generated from a YAML spec.** A [Claude Code](https://claude.com/claude-code)
skill + a standalone Python engine that drives a real browser (Playwright) and renders a
finished `.mp4` that looks hand-made — the kind of polished product walkthrough you'd
normally make in Screen Studio, but scripted, diffable, and reproducible.

```yaml
scenes:
  - { narrate: "Start a new project.", click: "text=New Project" }
  - { narrate: "Seconds later — you're live.", spotlight: "#status", callout: { text: "Provisioned", at: ".badge" } }
```

→ a 1080p video with the page floated on a gradient backdrop inside a macOS browser window,
the camera zooming to each click, an animated cursor, a voiceover, and synced captions.

## What you get

- 🎬 **Studio framing** — gradient backdrop, browser chrome, rounded window, drop shadow;
  the camera zooms *past* the window edge into the content.
- 🎯 **Auto zoom-to-click** — element-aware, spring-eased; it follows what you do.
- 🖱️ **Animated cursor + keycast** — a glowing pointer that glides to each target.
- ✨ **Annotations** — `highlight`, `spotlight` (dim the rest), `callout`, `arrow`, `chapter`.
- 🔊 **Voiceover** — local open-source Piper (default), macOS `say`, OpenAI, or ElevenLabs;
  normalized, with optional ducked music and procedural SFX.
- 📝 **Captions** — `pill`, `lower_third`, or word-by-word **karaoke** (Whisper); plus
  `.srt` / `.vtt` / `.transcript.md` sidecars.
- 🎨 **Brand kit** — logo watermark, lower-third, outro CTA. **Themes:** `studio` · `dark`
  · `light` · `minimal`.

No system `ffmpeg` needed (bundled via `imageio-ffmpeg`).

## Install as a Claude Code skill

Mount this repo at `.claude/skills/demo` in your project — as a submodule:

```bash
git submodule add https://github.com/alexnodeland/demoreel .claude/skills/demo
cd .claude/skills/demo/engine
uv sync --extra piper && uv run playwright install chromium
```

Then ask Claude Code to `/demo <what to demo>`. The skill (`SKILL.md`) is a craft playbook:
it scouts the live app for real selectors, storyboards a narrative, renders a preview, and
reviews its own frames before the final cut. If your project ships a *demo house-style* doc,
the skill reads and applies it (preset/branding, voice, default URL, which flows matter).

## Use the engine directly (no skill)

```bash
cd engine
uv sync --extra piper && uv run playwright install chromium
uv run demoreel init my-demo.yaml      # starter spec
uv run demoreel validate my-demo.yaml  # parse + scene plan
uv run demoreel check    my-demo.yaml  # verify selectors against the live page
uv run demoreel render   my-demo.yaml -o out.mp4
```

See [`engine/README.md`](engine/README.md) for the full spec reference and
[`SKILL.md`](SKILL.md) for the authoring playbook.

## Layout

```
SKILL.md            the Claude Code skill (authoring playbook)
engine/             the demoreel Python package
  demoreel/         spec · capture · stage · compose · audio · subtitles · brand · …
  examples/         a runnable example spec
  README.md         full spec reference
```

## License

MIT — see [LICENSE](LICENSE).
