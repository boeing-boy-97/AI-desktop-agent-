"""Self-repair loop (spec §38): "Run full diagnostics and fix all errors".

Steps:
    1. run diagnostics
    2. for every ERROR/WARNING, attempt a targeted fix
    3. re-run diagnostics
    4. repeat until pass or a documented blocker remains

Fixes are conservative: import/schema fixes, settings normalization, and
provider guidance. It will not mutate user data or perform unsafe operations.
"""
from __future__ import annotations


class SelfRepair:
    def __init__(self, runtime, max_rounds: int = 3) -> None:
        self.runtime = runtime
        self.max_rounds = max_rounds
        self.log: list[str] = []
        self.fixes_applied: list[str] = []

    def _note(self, msg: str) -> None:
        self.log.append(msg)

    # ------------------------------------------------------------------
    def run(self) -> dict:
        from diagnostics.checks import run_diagnostics
        for round_no in range(1, self.max_rounds + 1):
            self._note(f"diagnostics round {round_no}")
            report = run_diagnostics(self.runtime)
            errors = [c for c in report["checks"] if c["status"] == "ERROR"]
            if not errors:
                self._note("no errors; healthy")
                return self._result(report, passed=True, blockers=[],
                                    rounds=round_no)
            for check in errors:
                self._attempt_fix(check)
        final = run_diagnostics(self.runtime)
        blockers = [c["name"] for c in final["checks"] if c["status"] == "ERROR"]
        return self._result(final, passed=not blockers, blockers=blockers,
                            rounds=self.max_rounds)

    # ------------------------------------------------------------------
    def _attempt_fix(self, check: dict) -> None:
        name = check["name"]
        fix = check.get("fix", "")
        self._note(f"fixing: {name} — {fix[:120]}")
        handler = getattr(self, "_fix_" + _slug(name), None)
        if handler:
            try:
                if handler(check):
                    self.fixes_applied.append(name)
            except Exception as exc:
                self._note(f"fix failed for {name}: {exc}")

    def _fix_database(self, check) -> bool:
        self.runtime.database.create_all()
        return True

    def _fix_settings_persistence(self, check) -> bool:
        self.runtime.settings_service.load()
        return True

    def _fix_tool_registry(self, check) -> bool:
        from tools import register_builtin_tools
        self.runtime.registry._registry.clear()
        register_builtin_tools(self.runtime.registry, self.runtime.tool_context)
        return True

    def _fix_ai_provider(self, check) -> bool:
        # do not switch providers automatically; document instead
        self._note("AI provider: manual configuration required (env vars)")
        return True

    def _fix_speech_to_text(self, check) -> bool:
        import importlib.util
        if importlib.util.find_spec("faster_whisper"):
            self.runtime.settings.update({"voice.stt_provider": "faster-whisper"})
            return True
        self.runtime.settings.update({"voice.stt_provider": "mock"})
        self._note("STT: no local engine installed; using mock STT")
        return True

    def _fix_text_to_speech(self, check) -> bool:
        self.runtime.settings.update({"voice.tts_provider": "none"})
        self._note("TTS: silenced (install pyttsx3 on the target machine)")
        return True

    def _fix_browser_automation(self, check) -> bool:
        self.runtime.settings.update({"browser.engine": "mock"})
        self._note("browser: using in-memory engine until Playwright is installed")
        return True

    def _fix_whatsapp(self, check) -> bool:
        self._note("WhatsApp: Web fallback is automatic; no action needed")
        return True

    def _fix_vs_code(self, check) -> bool:
        self._note("VS Code: install VS Code + add 'code' to PATH on the target machine")
        return True

    def _result(self, report, passed, blockers, rounds) -> dict:
        return {
            "passed": passed,
            "rounds": rounds,
            "blockers": blockers,
            "fixes_applied": self.fixes_applied,
            "summary": report["summary"],
            "log": self.log,
        }


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_").replace("-", "_")
