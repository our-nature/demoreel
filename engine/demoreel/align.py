"""Optional word-level alignment via faster-whisper, for karaoke captions.

We already know the narration text; transcribing each VO clip with word timestamps gives
us the per-word timing needed to highlight words as they're spoken. The model is loaded
once and cached. Failures degrade gracefully (compose falls back to plain captions).
"""

from __future__ import annotations

_MODEL = None


class AlignError(RuntimeError):
    pass


def _model(size: str = "base"):
    global _MODEL
    if _MODEL is None:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise AlignError(
                "faster-whisper is not installed. `pip install faster-whisper` "
                "(or `uv sync --extra align`), or use captions.style: pill."
            ) from exc
        _MODEL = WhisperModel(size, device="cpu", compute_type="int8")
    return _MODEL


def align_words(wav_path: str, model_size: str = "base") -> list[tuple[str, float, float]]:
    """Return ``[(word, start, end), ...]`` in seconds relative to the wav."""
    model = _model(model_size)
    segments, _info = model.transcribe(wav_path, word_timestamps=True, beam_size=1)
    out: list[tuple[str, float, float]] = []
    for seg in segments:
        for w in getattr(seg, "words", None) or []:
            token = w.word.strip()
            if token:
                out.append((token, float(w.start), float(w.end)))
    return out
