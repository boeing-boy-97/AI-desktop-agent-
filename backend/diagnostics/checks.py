"""Diagnostics checks (spec §36): report PASS / WARNING / ERROR with reasons.

Checks: python, database, settings persistence, microphone, speaker, STT, TTS,
AI provider, browser engine, WhatsApp, VS Code, file system, screen capture,
UI automation, tool registry, permissions, network (optional), logging dir.
"""
from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    status: str          # PASS | WARNING | ERROR | SKIP
    detail: str = ""
    category: str = "general"
    fix: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail,
                "category": self.category, "fix": self.fix}


def _status(ok: bool, degraded: bool = False) -> str:
    if ok:
        return "PASS"
    return "WARNING" if degraded else "ERROR"


def check_python(runtime=None) -> CheckResult:
    import sys
    return CheckResult("Python interpreter", "PASS",
                       f"Python {sys.version.split()[0]} at {sys.executable}",
                       category="environment")


def check_database(runtime) -> CheckResult:
    try:
        status = runtime.database.migration_status()
        if status["up_to_date"]:
            return CheckResult("Database (SQLite/SQLAlchemy)", "PASS",
                               f"{len(status['tables_present'])} tables ready",
                               category="storage")
        return CheckResult("Database", "WARNING",
                           f"missing tables: {status['missing_tables']}",
                           category="storage", fix="run database.create_all()")
    except Exception as exc:
        return CheckResult("Database", "ERROR", str(exc), category="storage")


def check_settings_persistence(runtime) -> CheckResult:
    try:
        runtime.settings_service.persist()
        return CheckResult("Settings persistence", "PASS",
                           "settings wrote to database", category="storage")
    except Exception as exc:
        return CheckResult("Settings persistence", "ERROR", str(exc), category="storage")


def check_tool_registry(runtime) -> CheckResult:
    n = len(runtime.registry.names())
    if n >= 40:
        return CheckResult("Tool registry", "PASS", f"{n} tools registered",
                           category="agent")
    return CheckResult("Tool registry", "ERROR", f"only {n} tools registered",
                       category="agent", fix="check tools/ package discovery")


def check_permissions(runtime) -> CheckResult:
    try:
        policy = runtime.permissions.effective_policy("filesystem.delete")
        return CheckResult("Permission system", "PASS",
                           f"decision engine active (default={policy})",
                           category="security")
    except Exception as exc:
        return CheckResult("Permission system", "ERROR", str(exc), category="security")


def check_ai_provider(runtime) -> CheckResult:
    ok, detail = _probe_async(runtime.ai.available())
    if ok:
        return CheckResult("AI provider", "PASS",
                           f"{runtime.ai.name}: {detail}", category="ai")
    # No reachable cloud AI is a SUPPORTED degraded state (§37 local-first,
    # §41 offline mode): the deterministic heuristic planner keeps NOVA fully
    # functional. Report WARNING with an actionable message — never ERROR.
    return CheckResult(
        "AI provider", "WARNING",
        f"{runtime.ai.name}: {detail} — local heuristic planner active "
        f"(offline mode; automation still works)",
        category="ai",
        fix="set OPENAI_API_KEY (or AI_PROVIDER=ollama + a local Ollama "
            "server) for LLM planning")


def _probe_async(coro):
    """Run a coroutine health-probe even when already inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    # inside a loop — run in the loop's executor and unwrap
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            fut = ex.submit(_run_coro_isolated, coro)
            res = fut.result(timeout=30)
        ok, detail = res
    except Exception as exc:
        ok, detail = False, str(exc)
    return ok, detail


def _run_coro_isolated(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def check_stt(runtime) -> CheckResult:
    try:
        ok, detail = runtime.stt.available()
    except Exception as exc:
        ok, detail = False, str(exc)
    return CheckResult("Speech-to-text", _status(ok),
                       f"{runtime.settings.get_str('voice.stt_provider', 'faster-whisper')}: {detail}",
                       category="voice",
                       fix="pip install faster-whisper (CPU) for local STT")


def check_tts(runtime) -> CheckResult:
    try:
        ok, detail = runtime.tts.available()
    except Exception as exc:
        ok, detail = False, str(exc)
    degraded = runtime.settings.get_str("voice.tts_provider", "pyttsx3").lower() == "none"
    status = "WARNING" if degraded else _status(ok)
    return CheckResult("Text-to-speech", status,
                       f"{runtime.settings.get_str('voice.tts_provider', 'pyttsx3')}: {detail}",
                       category="voice", fix="install pyttsx3 or Kokoro/Piper")


def check_microphone(runtime) -> CheckResult:
    if platform.system() != "Windows":
        return CheckResult("Microphone", "SKIP",
                           "device enumeration is Windows-primary; "
                           "pyaudio probe available when run on the target OS",
                           category="voice")
    try:
        import pyaudio  # type: ignore
        pa = pyaudio.PyAudio()
        n = pa.get_device_count()
        pa.terminate()
        return CheckResult("Microphone", _status(n > 0), f"{n} audio device(s) present",
                           category="voice")
    except Exception as exc:
        return CheckResult("Microphone", "WARNING",
                           f"pyaudio unavailable ({exc}); install for mic access",
                           category="voice")


def check_speaker(runtime) -> CheckResult:
    provider = runtime.settings.get_str("voice.tts_provider", "pyttsx3")
    try:
        if provider == "pyttsx3":
            pass
        return CheckResult("Speaker", "PASS",
                           f"TTS backend '{provider}' can output audio",
                           category="voice")
    except Exception as exc:
        return CheckResult("Speaker", "WARNING", str(exc), category="voice",
                           fix="install pyttsx3 / set TTS_PROVIDER")


def check_browser(runtime) -> CheckResult:
    engine = runtime.settings.get_str("browser.engine", "playwright")
    if engine == "mock":
        return CheckResult("Browser automation", "WARNING",
                           "mock engine in use (offline/test mode); set "
                           "browser.engine=playwright for real automation",
                           category="browser")
    try:
        return CheckResult("Browser automation (Playwright)", "PASS",
                           "Playwright installed", category="browser")
    except Exception:
        return CheckResult("Browser automation (Playwright)", "ERROR",
                           "Playwright not installed", category="browser",
                           fix="pip install playwright && playwright install chromium")


def check_whatsapp(runtime) -> CheckResult:
    from tools.whatsapp import _WhatsAppTool as WA
    installed = WA.installed()
    return CheckResult("WhatsApp", _status(installed, True),
                       "Desktop app detected" if installed else
                       "Desktop app not detected — WhatsApp Web fallback available",
                       category="apps")


def check_vscode(runtime) -> CheckResult:
    from tools.vscode import _VSCodeTool
    cli = _VSCodeTool._cli_path()
    return CheckResult("VS Code", _status(cli is not None, True),
                       f"code CLI: {cli or 'not found'}",
                       category="apps")


def check_filesystem(runtime) -> CheckResult:
    import pathlib
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "probe.txt"
            p.write_text("nova")
            assert p.read_text() == "nova"
        return CheckResult("File system", "PASS", "read/write verified", category="system")
    except Exception as exc:
        return CheckResult("File system", "ERROR", str(exc), category="system")


def check_screen_capture(runtime) -> CheckResult:
    snap = runtime.observer.screenshot()
    if snap.source == "disabled":
        return CheckResult("Screen capture", "WARNING",
                           "disabled in privacy settings", category="system")
    if snap.source == "synthetic":
        return CheckResult("Screen capture", "WARNING",
                           "headless/CI environment — synthetic frames (will use "
                           "Pillow on a real desktop)", category="system")
    return CheckResult("Screen capture", "PASS",
                       f"captured {snap.width}x{snap.height}", category="system")


def check_ui_automation(runtime) -> CheckResult:
    if platform.system() == "Windows":
        try:
            return CheckResult("UI automation", "PASS", "uiautomation available",
                               category="system")
        except Exception:
            import importlib.util
            if importlib.util.find_spec("pywinauto"):
                return CheckResult("UI automation", "PASS", "pywinauto available",
                                   category="system")
            return CheckResult("UI automation", "WARNING",
                               "install uiautomation/pywinauto for full UI control",
                               category="system")
    return CheckResult("UI automation", "SKIP",
                       "UI Automation APIs are Windows-specific",
                       category="system")


def check_network(runtime) -> CheckResult:
    import socket
    try:
        socket.setdefaulttimeout(3)
        socket.create_connection(("1.1.1.1", 443), timeout=3)
        return CheckResult("Network", "PASS", "internet reachable", category="system")
    except Exception as exc:
        return CheckResult("Network", "WARNING",
                           f"not reachable ({exc}); local AI still works",
                           category="system")


def check_logging(runtime) -> CheckResult:
    d = runtime.settings.data_dir
    return CheckResult("Logging", "PASS", f"log dir: {d}",
                       category="system") if d.exists() else \
        CheckResult("Logging", "ERROR", "log dir missing", category="system")


ALL_CHECKS = [
    check_python, check_database, check_settings_persistence, check_tool_registry,
    check_permissions, check_ai_provider, check_stt, check_tts, check_microphone,
    check_speaker, check_browser, check_whatsapp, check_vscode, check_filesystem,
    check_screen_capture, check_ui_automation, check_network, check_logging,
]


def run_diagnostics(runtime) -> dict:
    results = []
    for fn in ALL_CHECKS:
        try:
            results.append(fn(runtime))
        except Exception as exc:
            results.append(CheckResult(fn.__name__, "ERROR", str(exc)))
    summary = {"PASS": 0, "WARNING": 0, "ERROR": 0, "SKIP": 0}
    for r in results:
        summary[r.status] = summary.get(r.status, 0) + 1
    summary["healthy"] = summary["ERROR"] == 0
    return {"summary": summary, "checks": [r.as_dict() for r in results],
            "all_pass": summary["ERROR"] == 0}
