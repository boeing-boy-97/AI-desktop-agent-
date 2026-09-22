"""Voice pipeline (spec §16): mic → VAD → STT → agent → TTS.

The pipeline is provider-based and interruption-aware:

    * input  — microphone capture (sounddevice/pyaudio) with a caller-supplied
               recorder on Windows; a deterministic fake source in tests
    * VAD    — energy threshold detection (offline WAV scan)
    * STT    — faster-whisper / mock
    * output — TTS provider abstraction (pyttsx3 / none / kokoro / piper)

"stop speaking when the user speaks" is implemented via the ``interruption``
check: before each synthesis we sample mic energy.
"""
from __future__ import annotations

import array
import math
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.exceptions import VoiceError
from providers.stt import STTProvider
from providers.tts import TTSProvider


@dataclass
class Transcript:
    text: str
    confidence: float = 0.0
    language: str | None = None

    def as_dict(self) -> dict:
        return {"text": self.text, "confidence": self.confidence,
                "language": self.language}


class VoiceActivityDetector:
    """Simple energy-based VAD over 16-bit mono PCM samples."""

    def __init__(self, threshold: float = 300.0, chunk_ms: int = 30,
                 min_speech_ms: int = 120) -> None:
        self.threshold = threshold
        self.chunk_ms = chunk_ms
        self.min_speech_ms = min_speech_ms

    def speech_windows(self, samples: bytes, rate: int = 16000) -> list[tuple[int, int]]:
        """Return (start_ms, end_ms) speech regions in raw PCM bytes."""
        values = array.array("h")
        values.frombytes(samples)
        if getattr(array, "H", None) and len(samples) % 2 != 0:
            return []
        chunk = max(1, int(rate * self.chunk_ms / 1000))
        windows: list[tuple[int, int]] = []
        start: int | None = None
        for i in range(0, len(values) - chunk, chunk):
            energy = math.sqrt(sum(v * v for v in values[i:i + chunk]) / chunk)
            ms = int(i / rate * 1000)
            if energy > self.threshold and start is None:
                start = ms
            elif energy <= self.threshold and start is not None:
                if ms - start >= self.min_speech_ms:
                    windows.append((start, ms))
                start = None
        if start is not None:
            ms = int(len(values) / rate * 1000)
            if ms - start >= self.min_speech_ms:
                windows.append((start, ms))
        return windows


class Microphone:
    """Cross-platform mic capture wrapper."""

    def __init__(self, settings: Any, device: int | None = None) -> None:
        self.settings = settings
        self.device = device

    def _backend(self):
        try:
            import sounddevice as sd  # type: ignore
            return ("sounddevice", sd)
        except Exception:
            pass
        try:
            import pyaudio as pa  # type: ignore
            return ("pyaudio", pa)
        except Exception:
            pass
        return (None, None)

    def available(self) -> tuple[bool, str]:
        name, _ = self._backend()
        if name:
            return True, f"{name} ready"
        return False, "no audio backend (install sounddevice or pyaudio)"

    def record(self, seconds: float = 6.0, rate: int = 16000) -> bytes:
        name, mod = self._backend()
        if name == "sounddevice":
            return self._record_sounddevice(mod, seconds, rate)
        if name == "pyaudio":
            return self._record_pyaudio(mod, seconds, rate)
        raise VoiceError("No microphone backend available. Install sounddevice or pyaudio.")

    def _record_sounddevice(self, sd, seconds: float, rate: int) -> bytes:
        rec = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="int16")
        sd.wait()
        return rec.tobytes()

    def _record_pyaudio(self, pa, seconds: float, rate: int) -> bytes:
        audio = pa.PyAudio()
        stream = audio.open(format=pa.paInt16, channels=1, rate=rate,
                            input=True, frames_per_buffer=1024)
        frames = []
        for _ in range(int(rate / 1024 * seconds)):
            frames.append(stream.read(1024))
        stream.stop_stream()
        stream.close()
        audio.terminate()
        return b"".join(frames)

    def energy_le(self, seconds: float = 0.5, rate: int = 16000) -> float:
        """Sample ambient mic energy (used for interruption detection)."""
        try:
            data = self.record(seconds, rate)
            std = math.sqrt(sum(v * v for v in array.array("h", data)) / max(1, len(data) // 2))
            return float(std)
        except Exception:
            return 0.0


class VoicePipeline:
    def __init__(self, stt: STTProvider, tts: TTSProvider,
                 settings: Any, mic: Microphone | None = None) -> None:
        self.stt = stt
        self.tts = tts
        self.settings = settings
        self.mic = mic or Microphone(settings)
        self.vad = VoiceActivityDetector()

    # ------------------------------------------------------------------
    def transcribe_audio(self, audio: bytes, language: str | None = None) -> Transcript:
        out = self.stt.transcribe(audio, language=language)
        return Transcript(out.get("text", "").strip(),
                          float(out.get("confidence", 0.0) or 0.0),
                          out.get("language"))

    def transcribe_file(self, path: str, language: str | None = None) -> Transcript:
        data = _read_wav(path)
        return self.transcribe_audio(data, language)

    def listen(self, seconds: float = 6.0) -> Transcript:
        """Capture mic audio and transcribe it."""
        if self.settings.get_str("voice.stt_provider", "") == "mock":
            return self.stt.transcribe(b"", None) and Transcript(
                "Open Chrome", 1.0, "en")
        audio = self.mic.record(seconds, 16000)
        vad = self.vad.speech_windows(audio)
        if not vad:
            return Transcript("")
        return self.transcribe_audio(_pcm_to_wav(audio, 16000))

    def speak(self, text: str, *, interrupt_if: Callable[[], bool] | None = None) -> bool:
        if interrupt_if and interrupt_if():
            return False
        if not text.strip():
            return False
        try:
            return bool(self.tts.speak(text))
        except VoiceError:
            return False

    def stop_speaking(self) -> None:
        self.tts.interrupt()

    def interruption_check(self) -> Callable[[], bool]:
        """Return a callable that flags user speech (naive ambient-energy check)."""
        def _check() -> bool:
            if self.settings.get_str("voice.interruption", "none") == "none":
                return False
            return self.mic.energy_le(0.4) > 1500.0
        return _check


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _read_wav(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        return w.readframes(w.getnframes())
