"""Text-to-speech backends.

Every backend produces a mono/stereo PCM **WAV** file so the compose stage can read
durations with the stdlib ``wave`` module and mux without an extra decode step.

Backends:
  - piper     : local, open-source neural TTS (recommended default). Auto-downloads voices.
  - say       : macOS built-in `say` (+ `afconvert`). Zero install, robotic, great for iterating.
  - openai    : cloud TTS (gpt-4o-mini-tts). Needs OPENAI_API_KEY. Highest polish.
  - elevenlabs: cloud TTS via REST (PCM). Needs ELEVENLABS_API_KEY. Experimental.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import urllib.request
import wave
from pathlib import Path

from .spec import VoiceConfig

CACHE_DIR = Path(os.environ.get("DEMOREEL_CACHE", Path.home() / ".cache" / "demoreel"))
PIPER_DIR = CACHE_DIR / "piper"
DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


class TTSError(RuntimeError):
    pass


def _normalize_text(text: str) -> str:
    """Collapse whitespace and ensure terminal punctuation.

    Clean, sentence-terminated text gives every TTS engine better prosody and avoids the
    dropped/garbled words you get from stray whitespace or run-on input.
    """
    text = " ".join(text.split())
    if text and text[-1] not in ".!?:;,—-":
        text += "."
    return text


def wav_duration(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
    return frames / float(rate) if rate else 0.0


def synthesize(text: str, out_wav: str | Path, voice: VoiceConfig) -> float:
    """Render ``text`` to ``out_wav`` and return its duration in seconds."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    text = _normalize_text(text or "")
    if not text:
        _write_silence(out_wav, 0.3)
        return wav_duration(out_wav)

    engine = voice.engine
    if engine == "piper":
        _piper(text, out_wav, voice)
    elif engine == "say":
        _macos_say(text, out_wav, voice)
    elif engine == "openai":
        _openai(text, out_wav, voice)
    elif engine == "elevenlabs":
        _elevenlabs(text, out_wav, voice)
    else:  # pragma: no cover - guarded by the spec's Literal
        raise TTSError(f"unknown TTS engine: {engine}")
    return wav_duration(out_wav)


# --------------------------------------------------------------------------- piper


def _piper_voice_urls(name: str) -> tuple[str, str]:
    """Derive the HuggingFace download URLs for a piper voice name.

    ``en_US-lessac-medium`` -> ``.../en/en_US/lessac/medium/en_US-lessac-medium.onnx``
    """
    try:
        locale, speaker, quality = name.split("-")
        lang = locale.split("_")[0]
    except ValueError as exc:
        raise TTSError(
            f"cannot parse piper voice name {name!r}; expected '<locale>-<speaker>-<quality>' "
            "(e.g. en_US-lessac-medium) or a path to a .onnx file"
        ) from exc
    stem = f"{_HF_BASE}/{lang}/{locale}/{speaker}/{quality}/{name}"
    return f"{stem}.onnx", f"{stem}.onnx.json"


def _ensure_piper_model(model: str) -> Path:
    """Resolve a piper voice to a local .onnx path, downloading if needed."""
    p = Path(model)
    if p.suffix == ".onnx" and p.exists():
        return p
    name = p.name if p.suffix == ".onnx" else model
    name = name[:-5] if name.endswith(".onnx") else name
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    onnx = PIPER_DIR / f"{name}.onnx"
    cfg = PIPER_DIR / f"{name}.onnx.json"
    if onnx.exists() and cfg.exists():
        return onnx
    onnx_url, cfg_url = _piper_voice_urls(name)
    for url, dest in ((onnx_url, onnx), (cfg_url, cfg)):
        if dest.exists():
            continue
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, tmp)  # noqa: S310 - trusted HF host
            tmp.replace(dest)
        except Exception as exc:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            raise TTSError(
                f"failed to download piper voice {name!r} from {url}: {exc}. "
                "Pass voice.model as a path to a local .onnx instead, or pick another engine."
            ) from exc
    return onnx


def _piper(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    try:
        from piper import PiperVoice  # type: ignore
    except ImportError as exc:
        raise TTSError(
            "piper is not installed. Install it with `pip install piper-tts` "
            "(or `uv sync --extra piper`), or choose voice.engine: say."
        ) from exc

    model = _ensure_piper_model(voice.model or DEFAULT_PIPER_VOICE)
    pv = PiperVoice.load(str(model))
    length_scale = 1.0 / max(voice.rate, 0.1)  # piper: smaller = faster

    # piper-tts >= 1.3 replaced ``synthesize(text, wav_file)`` with
    # ``synthesize_wav(text, wav_file, syn_config=...)``; the old call against the
    # new build silently writes nothing, leaving the wave header unset
    # ("# channels not specified"). Prefer the new API, fall back to the old one.
    syn_config = None
    try:  # length_scale moved into SynthesisConfig on the new API
        try:
            from piper import SynthesisConfig  # type: ignore
        except ImportError:
            from piper.config import SynthesisConfig  # type: ignore
        syn_config = SynthesisConfig(length_scale=length_scale)
    except Exception:
        syn_config = None

    with wave.open(str(out_wav), "wb") as wf:
        if hasattr(pv, "synthesize_wav"):
            try:
                pv.synthesize_wav(text, wf, syn_config=syn_config)
            except TypeError:
                pv.synthesize_wav(text, wf)
        else:  # legacy piper API
            try:
                pv.synthesize(text, wf, length_scale=length_scale)
            except TypeError:
                pv.synthesize(text, wf)


# ----------------------------------------------------------------------- macos say


def _macos_say(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    if not shutil.which("say"):
        raise TTSError("`say` is only available on macOS. Choose voice.engine: piper.")
    aiff = out_wav.with_suffix(".aiff")
    wpm = str(int(175 * max(voice.rate, 0.1)))
    cmd = ["say", "-r", wpm, "-o", str(aiff)]
    if voice.model:
        cmd += ["-v", voice.model]
    cmd += [text]
    subprocess.run(cmd, check=True)
    # Convert AIFF -> 16-bit PCM WAV. Prefer afconvert (built-in); fall back to ffmpeg.
    if shutil.which("afconvert"):
        subprocess.run(
            ["afconvert", str(aiff), str(out_wav), "-f", "WAVE", "-d", "LEI16@44100"],
            check=True,
        )
    else:  # pragma: no cover
        _ffmpeg_to_wav(aiff, out_wav)
    aiff.unlink(missing_ok=True)


# -------------------------------------------------------------------------- openai


def _openai(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise TTSError(
            "openai is not installed. `pip install openai` (or `uv sync --extra cloud`)."
        ) from exc
    if not os.environ.get("OPENAI_API_KEY"):
        raise TTSError("OPENAI_API_KEY is not set.")
    client = OpenAI()
    model = "gpt-4o-mini-tts"
    with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice.model or "alloy",
        input=text,
        response_format="wav",
    ) as resp:
        resp.stream_to_file(str(out_wav))


# ---------------------------------------------------------------------- elevenlabs


def _elevenlabs(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise TTSError("ELEVENLABS_API_KEY is not set.")
    voice_id = voice.model or "21m00Tcm4TlvDq8ikWAM"  # "Rachel" default
    rate = 22050
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        f"?output_format=pcm_{rate}"
    )
    body = (
        '{"text": %s, "model_id": "eleven_turbo_v2"}' % _json_str(text)
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 - trusted API host
        url,
        data=body,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        pcm = resp.read()
    _pcm_to_wav(pcm, out_wav, rate=rate)


# -------------------------------------------------------------------------- helpers


def _json_str(s: str) -> str:
    import json

    return json.dumps(s)


def _pcm_to_wav(pcm: bytes, out_wav: Path, rate: int, channels: int = 1) -> None:
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(rate)
        w.writeframes(pcm)


def _write_silence(out_wav: Path, seconds: float, rate: int = 44100) -> None:
    n = int(seconds * rate)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n, *([0] * n)))


def _ffmpeg_to_wav(src: Path, out_wav: Path) -> None:  # pragma: no cover
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-i", str(src), str(out_wav)], check=True)


def list_say_voices() -> list[str]:  # pragma: no cover - macOS only
    if not shutil.which("say"):
        return []
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return [line.split()[0] for line in out.splitlines() if line.strip()]
