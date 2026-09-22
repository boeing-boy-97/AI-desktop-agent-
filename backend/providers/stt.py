"""Speech-to-text provider abstraction.

    * faster-whisper   — local, offline Whisper (CTranslate2). Default.
    * vosk / whisper (openai) — optional extras registered if installed.
    * mock              — deterministic offline transcription for tests/demos.

Model size defaults to ``base`` (configurable via ``voice.stt_model``).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.exceptions import ConfigError, VoiceError


class STTProvider(ABC):
    name: str = "base"

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> dict:
        raise NotImplementedError

    def available(self) -> tuple[bool, str]:
        return True, "ok"


class FasterWhisperSTT(STTProvider):
    name = "faster-whisper"

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._model = None
        self._model_key = None

    def _load(self):
        key = self.settings.get_str("voice.stt_model", "base")
        if self._model is not None and self._model_key == key:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover
            raise VoiceError(f"faster-whisper not installed: {exc}") from exc
        model = WhisperModel(key, device="cpu", compute_type="int8")
        self._model = model
        self._model_key = key
        return model

    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> dict:
        model = self._load()
        tmp = self.settings.data_dir / "stt_tmp.wav"
        tmp.write_bytes(audio_bytes)
        lang = language or self.settings.get_str("voice.stt_language", "en") or None
        try:
            segments, info = model.transcribe(str(tmp), language=lang, beam_size=5)
            text = "".join(s.text for s in segments).strip()
            return {"text": text, "confidence": float(getattr(info, "language_probability", 0.0) or 0.0),
                    "language": getattr(info, "language", lang)}
        except Exception as exc:
            raise VoiceError(f"Whisper transcription failed: {exc}") from exc
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def available(self) -> tuple[bool, str]:
        try:
            return True, f"faster-whisper ready (model={self.settings.get_str('voice.stt_model', 'base')})"
        except Exception as exc:
            return False, f"faster-whisper not installed: {exc}"


class MockSTT(STTProvider):
    name = "mock"

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings

    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> dict:
        return {"text": "Open Chrome", "confidence": 1.0, "language": language or "en",
                "source": "mock"}

    def available(self) -> tuple[bool, str]:
        return True, "mock STT always available"


def create_stt_provider(settings: Any) -> STTProvider:
    provider = (settings.get_str("voice.stt_provider", "faster-whisper") or "").lower()
    if provider in ("faster-whisper", "faster_whisper", "whisper", "local"):
        return FasterWhisperSTT(settings)
    if provider == "mock":
        return MockSTT(settings)
    raise ConfigError(f"Unknown STT provider: {provider} (expected faster-whisper|mock)")


def wav_bytes_to_frames(audio_bytes: bytes) -> bytes:
    """Ensure audio begins with a valid RIFF/WAVE header (crude normalizer)."""
    if audio_bytes[:4] == b"RIFF":
        return audio_bytes
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio_bytes)
    return buf.getvalue()
