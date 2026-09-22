"""Text-to-speech provider abstraction.

    * pyttsx3  — cross-platform local TTS (SAPI on Windows, nsss on macOS,
                 espeak on Linux). The default; ships with NOVA.
    * none     — silent TTS (also used by Silent Mode).

Kokoro/Piper are registered dynamically when their CLI binaries are found so
they integrate without hard-coding a single commercial provider.
"""
from __future__ import annotations

import abc
import shutil
import subprocess
from typing import Any

from core.exceptions import ConfigError, VoiceError


class TTSProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def speak(self, text: str, **kwargs) -> bool:
        raise NotImplementedError

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def interrupt(self) -> None:
        return

    def close(self) -> None:
        return


class SilentTTS(TTSProvider):
    name = "none"

    def speak(self, text: str, **kwargs) -> bool:
        return False

    def available(self) -> tuple[bool, str]:
        return True, "silent (no audio produced)"


class Pyttsx3TTS(TTSProvider):
    name = "pyttsx3"

    def __init__(self, settings: Any, _engine: Any | None = None) -> None:
        self.settings = settings
        self._engine = _engine
        self._inited = False
        self._disabled = False  # set once init fails — never retry-spam
        self._voice_id: str | None = None

    def _ensure(self):
        if self._inited:
            return self._engine
        try:
            import pyttsx3  # type: ignore
            engine = pyttsx3.init()
            engine.setProperty("rate", int(self.settings.get_int("voice.rate", 170)))
            engine.setProperty("volume", float(self.settings.get_float("voice.volume", 1.0)))
            self._engine = engine
            self._inited = True
        except Exception as exc:
            raise VoiceError(f"Cannot initialise pyttsx3: {exc}") from exc
        return self._engine

    def _speak_blocking(self, text: str) -> None:
        # runs in its own thread: any failure must degrade silently —
        # voice output is optional and must never surface an unhandled
        # thread exception (spec §39: never crash/freeze for the user)
        try:
            eng = self._ensure()
            eng.say(text)
            eng.runAndWait()
        except Exception:
            self._disabled = True

    def speak(self, text: str, **kwargs) -> bool:
        if self._disabled:
            return False
        if self.settings.get_str("voice.tts_provider", "pyttsx3").lower() == "none":
            return False
        import threading
        t = threading.Thread(target=self._speak_blocking, args=(text,), daemon=True)
        t.start()
        return True

    def available(self) -> tuple[bool, str]:
        if self._disabled:
            return False, "pyttsx3 engine unavailable (disabled after init failure)"
        try:
            self._ensure()
            return True, "pyttsx3 available"
        except Exception as exc:
            self._disabled = True
            return False, str(exc)[:120]

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass


class CliFileTTS(TTSProvider):
    """Speak by rendering WAV with a CLI engine (Kokoro / Piper) and playing it.

    Detected via configuration ``voice.tts_model_path``/``voice.tts_cli``.
    """

    def __init__(self, settings: Any, name: str = "cli"):
        self.settings = settings
        self.name = name
        self.cli = settings.get_str("voice.tts_cli", "")
        self.model = settings.get_str("voice.tts_model", "")

    def available(self) -> tuple[bool, str]:
        if not self.cli or not shutil.which(self.cli.split()[0]):
            return False, f"TTS CLI not found: {self.cli!r}"
        return True, "cli found"

    def speak(self, text: str, **kwargs) -> bool:
        try:
            out = kwargs.get("path") or self.settings.data_dir / "tts_out.wav"
            cmd = [self.cli] if not self.model else [self.cli, self.model]
            cmd += ["--text", text, "--output", str(out)]
            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
            _play_wav(str(out))
            return True
        except Exception as exc:
            raise VoiceError(f"CLI TTS failed: {exc}") from exc


def _play_wav(path: str) -> None:
    import platform
    try:
        if platform.system() == "Windows":
            import winsound  # type: ignore
            winsound.PlaySound(path, winsound.SND_FILENAME)
            return
        import shutil
        for player in ("aplay", "paplay", "afplay"):
            if shutil.which(player):
                subprocess.Popen([player, path])
                return
    except Exception:
        pass


def create_tts_provider(settings: Any) -> TTSProvider:
    provider = (settings.get_str("voice.tts_provider", "pyttsx3") or "none").lower()
    if provider in ("none", "off", "silent", ""):
        return SilentTTS()
    if provider in ("pyttsx3", "sapi", "espeak", "local"):
        return Pyttsx3TTS(settings)
    if provider in ("kokoro", "piper", "cli"):
        return CliFileTTS(settings, name=provider)
    raise ConfigError(f"Unknown TTS provider: {provider} (expected pyttsx3|kokoro|piper|none)")
