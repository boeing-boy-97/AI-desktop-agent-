"""Microphone capture for the desktop UI (click-to-talk).

Uses sounddevice/pyaudio when available and records a short WAV clip
(16 kHz mono 16-bit), which is base64-encoded and sent to the backend STT.
"""
from __future__ import annotations

import base64
import io
import wave


class AudioRecorder:
    def __init__(self) -> None:
        self._backend = None
        self._mod = None
        self._init_backend()

    def _init_backend(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
            self._backend, self._mod = "sounddevice", sd
            return
        except Exception:
            pass
        try:
            import pyaudio as pa  # type: ignore
            self._backend, self._mod = "pyaudio", pa
            return
        except Exception:
            self._backend, self._mod = None, None

    def available(self) -> bool:
        return self._backend is not None

    def record_wav(self, seconds: float = 6.0, rate: int = 16000) -> bytes:
        """Return a complete WAV file's bytes."""
        if self._backend == "sounddevice":
            rec = self._mod.rec(int(seconds * rate), samplerate=rate,
                                channels=1, dtype="int16")
            self._mod.wait()
            return _pcm_to_wav(rec.tobytes(), rate)
        if self._backend == "pyaudio":
            audio = self._mod.PyAudio()
            stream = audio.open(format=self._mod.paInt16, channels=1, rate=rate,
                                input=True, frames_per_buffer=1024)
            frames = []
            for _ in range(int(rate / 1024 * seconds)):
                frames.append(stream.read(1024))
            stream.stop_stream(); stream.close(); audio.terminate()
            return _pcm_to_wav(b"".join(frames), rate)
        return b""

    def record_b64(self, seconds: float = 6.0, rate: int = 16000) -> str:
        data = self.record_wav(seconds, rate)
        return base64.b64encode(data).decode() if data else ""


def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()
