"""NOVA desktop application controller — wires orb, panel, tray, API, voice.

This is the heart of the desktop experience:

    orb click      → listen → transcribe → execute → speak result
    panel submit   → execute directly
    SSE events     → live orb/panel state (Listening… Planning… Executing…)
    confirmation   → modal prompt
    tray / hotkey  → activate, pause, emergency stop, restart, exit
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox


class _EventBridge(QObject):
    """Receives backend events on any thread and re-emits them on the Qt main
    thread, so UI updates never race the event loop."""
    received = pyqtSignal(dict)
    stateReceived = pyqtSignal(str)

from apps.desktop.api_client import ApiClient
from apps.desktop.audio import AudioRecorder
from apps.desktop.hotkeys import GlobalHotkeys
from apps.desktop.theme import build_qss
from apps.desktop.ui.history_window import HistoryWindow
from apps.desktop.ui.orb import Orb, OrbState
from apps.desktop.ui.panel import CommandPanel
from apps.desktop.ui.settings_window import SettingsWindow
from apps.desktop.ui.tray import TrayController


class NovaController(QObject):
    orbStateChanged = pyqtSignal(str)

    def __init__(self, base_url: str = "http://127.0.0.1:8765", app=None) -> None:
        super().__init__()
        self.api = ApiClient(base_url)
        self.recorder = AudioRecorder()
        self.hotkeys = GlobalHotkeys()

        self.orb = Orb()
        self.panel = CommandPanel()
        self.tray = TrayController(self._tray_callbacks())
        self.settings_window: SettingsWindow | None = None
        self.history_window: HistoryWindow | None = None

        self._paused = False
        self._active_task: str | None = None
        self._listening = False
        self._backend_up = False

        self._theme = "dark"
        self._load_settings()

        # wire widgets
        self.orb.activateRequested.connect(self._on_talk)
        self.orb.togglePanelRequested.connect(self._toggle_panel)
        self.orb.emergencyRequested.connect(self._emergency)
        self.orb.positionSaved.connect(self._on_position_saved)
        self.panel.commandSubmitted.connect(self._on_command)
        self.panel.stopRequested.connect(self._on_stop)
        self.panel.micRequested.connect(self._on_talk)
        self.panel.openSettingsRequested.connect(self._open_settings)
        self.panel.openHistoryRequested.connect(self._open_history)

        # backend events — bridged onto the Qt main thread
        self._bridge = _EventBridge()
        self._bridge.received.connect(self._on_event,
                                      Qt.ConnectionType.QueuedConnection)
        self._bridge.stateReceived.connect(self._on_state_signal,
                                           Qt.ConnectionType.QueuedConnection)
        self.api.start_events(self._bridge.received.emit)

        # periodic status probe
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._probe_backend)
        self._status_timer.start(4000)
        self._probe_backend()

        # confirmation poller
        self._conf_timer = QTimer(self)
        self._conf_timer.timeout.connect(self._poll_confirmations)
        self._conf_timer.start(1500)

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        try:
            cfg = self.api.settings()
            self._theme = cfg.get("desktop.theme", "dark")
            x = cfg.get("desktop.orb_x", -1)
            y = cfg.get("desktop.orb_y", -1)
            if x and y and float(x) > 0 and float(y) > 0:
                self.orb.move(int(x), int(y))
            self.orb.set_scale(float(cfg.get("desktop.orb_scale", 1.0)))
        except Exception:
            pass

    def apply_theme(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(build_qss(self._theme == "dark"))

    def _on_position_saved(self, x: int, y: int) -> None:
        try:
            self.api.update_settings({"desktop.orb_x": x, "desktop.orb_y": y})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _on_talk(self) -> None:
        if self._paused:
            return
        if not self.recorder.available():
            QMessageBox.information(None, "NOVA",
                                    "No microphone backend found. Install "
                                    "sounddevice or pyaudio, or type your "
                                    "command in the panel.")
            return
        threading.Thread(target=self._talk_worker, daemon=True).start()

    def _talk_worker(self) -> None:
        self._listening = True
        self._ui_set_state("LISTENING")
        try:
            b64 = self.recorder.record_b64(6.0)
            if not b64:
                self._ui_set_state("IDLE"); return
            result = self.api.transcribe(b64)
            text = (result.get("text") or "").strip()
            if text:
                self._run_command(text, "smart")
            else:
                self._ui_set_state("IDLE")
        except Exception:
            self._ui_set_state("ERROR")
        finally:
            self._listening = False

    def _ui_set_state(self, state: str) -> None:
        """Thread-safe state change: defer to the Qt main thread."""
        self._bridge.stateReceived.emit(state)

    def _on_state_signal(self, state: str) -> None:
        self._set_state(state)

    def _on_command(self, text: str, mode: str) -> None:
        self._run_command(text, mode)

    def _run_command(self, text: str, mode: str) -> None:
        try:
            self._active_task = self.api.execute(text, mode)
            self._panel_live("Executing…", [])
        except Exception as exc:
            self._set_state("ERROR")
            QMessageBox.warning(None, "NOVA", f"Backend not reachable:\n{exc}")

    def _on_stop(self) -> None:
        if self._active_task:
            try:
                self.api.cancel(self._active_task)
            except Exception:
                pass
        self._active_task = None
        self._set_state("IDLE")

    def _emergency(self) -> None:
        try:
            self.api.emergency_stop()
        except Exception:
            pass
        self._active_task = None
        self._set_state("ERROR")
        self.tray.notify("NOVA", "Emergency stop triggered — all activity halted.")

    # ------------------------------------------------------------------
    # event handling
    # ------------------------------------------------------------------
    def _on_event(self, evt: dict) -> None:
        event = evt.get("event", "")
        data = evt.get("data", {}) or {}
        if event == "agent.listening":
            self._set_state("LISTENING")
        elif event == "agent.understanding":
            self._set_state("UNDERSTANDING")
        elif event == "agent.planning":
            self._set_state("PLANNING")
            self._panel_live("Planning…", [])
        elif event == "agent.executing":
            self._set_state("EXECUTING")
            tool = data.get("tool", "")
            self._panel_live(f"Working… {tool or ''}", self._step_lines())
        elif event == "agent.verifying":
            self._set_state("VERIFYING")
        elif event == "agent.recovering":
            self._set_state("RECOVERING")
        elif event == "agent.waiting_confirmation":
            self._set_state("WAITING_CONFIRMATION")
        elif event == "agent.speaking":
            self._set_state("SPEAKING")
        elif event == "agent.completed":
            self._set_state("COMPLETED")
            summary = (data.get("result") or "Done.")[:120]
            self._panel_live(summary, [])
            self.tray.notify("NOVA", summary)
        elif event == "agent.failed":
            self._set_state("FAILED")
            self._panel_live("Failed — " + str(data.get("error", "unknown"))[:100], [])
        elif event == "agent.cancelled":
            self._set_state("CANCELLED")
            self._panel_live("Cancelled", [])
        elif event == "agent.step_completed" or event == "agent.step_failed":
            self._panel_live(self.panel.task_label.text(), self._step_lines())

    def _step_lines(self) -> list[str]:
        if not self._active_task:
            return []
        try:
            t = self.api.task(self._active_task)
            lines = []
            for s in t.get("steps", []):
                icon = "✓" if s["status"] == "completed" else ("✗" if s["status"] == "failed" else "•")
                lines.append(f"{icon} {s['tool']}")
            return lines
        except Exception:
            return []

    def _panel_live(self, text: str, steps: list[str]) -> None:
        self.panel.set_live(self._active_task, text, steps)

    # ------------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        self.orbStateChanged.emit(state)
        self.orb.set_state(state)
        self.panel.set_state(state)
        timer = QTimer(self)
        timer.singleShot(3200, self._settle)

    def _settle(self) -> None:
        if self.orb.state in (OrbState.COMPLETED, OrbState.ERROR,
                              OrbState.CANCELLED, OrbState.IDLE):
            pass
        if self._active_task is None and not self._listening:
            self.orb.set_state(OrbState.IDLE)
            self.panel.set_state("IDLE")

    # ------------------------------------------------------------------
    # confirmations (§53)
    # ------------------------------------------------------------------
    def _poll_confirmations(self) -> None:
        try:
            confs = self.api.pending_confirmations()
        except Exception:
            return
        for conf in confs:
            if getattr(self, "_confirming", False):
                return
            self._confirming = True
            q = conf.get("question", "Allow this action?")
            tool = conf.get("tool", "")
            reply = QMessageBox.question(
                None, "NOVA needs confirmation",
                f"{q}\n\n(tool: {tool})",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            try:
                self.api.resolve_confirmation(conf["id"],
                                              reply == QMessageBox.StandardButton.Yes)
            except Exception:
                pass
            self._confirming = False

    # ------------------------------------------------------------------
    # backend probe
    # ------------------------------------------------------------------
    def _probe_backend(self) -> None:
        try:
            self.api.status()
            self._backend_up = True
            if self.orb.state == OrbState.ERROR and not self._listening:
                self.orb.set_state(OrbState.IDLE)
        except Exception:
            self._backend_up = False

    # ------------------------------------------------------------------
    # windows
    # ------------------------------------------------------------------
    def _toggle_panel(self) -> None:
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self._show_panel()

    def _show_panel(self) -> None:
        geo = self.orb.frameGeometry()
        self.panel.adjustSize()
        self.panel.move(geo.left() - self.panel.width() + self.orb.width(),
                        geo.bottom() + 6)
        self.panel.show()
        self.panel.raise_()
        self.panel.input.setFocus()

    def _open_settings(self) -> None:
        try:
            cfg = self.api.settings()
        except Exception:
            cfg = {}
        self.settings_window = SettingsWindow(cfg)
        self.settings_window.saveRequested = self._save_settings
        self.settings_window.show()
        self.settings_window.raise_()

    def _save_settings(self, updates: dict) -> None:
        try:
            self.api.update_settings(updates)
        except Exception as exc:
            QMessageBox.warning(None, "NOVA", f"Could not save: {exc}")
        if "desktop.theme" in updates:
            self._theme = updates["desktop.theme"]
            self.apply_theme()
        if "desktop.orb_scale" in updates:
            self.orb.set_scale(float(updates["desktop.orb_scale"]))

    def _open_history(self) -> None:
        self.history_window = HistoryWindow()
        self.history_window.refreshRequested = self._refresh_history
        self.history_window.clearRequested = self._clear_history
        self._refresh_history()
        self.history_window.show()
        self.history_window.raise_()

    def _refresh_history(self) -> None:
        try:
            with __import__("httpx").Client(timeout=10) as c:
                r = c.get("http://127.0.0.1:8765/api/tasks", params={"limit": 200})
                tasks = r.json().get("tasks", [])
            self.history_window.populate(tasks)
        except Exception:
            self.history_window.populate([])

    def _clear_history(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(None, "NOVA", "Clear all task history?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                with __import__("httpx").Client(timeout=10) as c:
                    c.delete("http://127.0.0.1:8765/api/tasks")
            except Exception:
                pass
            self._refresh_history()

    # ------------------------------------------------------------------
    def _tray_callbacks(self) -> dict:
        return {
            "activate": self._show_panel,
            "pause": self._pause,
            "resume": self._resume,
            "settings": self._open_settings,
            "history": self._open_history,
            "permissions": self._open_settings,
            "diagnostics": self._open_diagnostics,
            "restart": self._restart,
            "emergency": self._emergency,
            "exit": self.quit,
        }

    def _pause(self) -> None:
        self._paused = True
        self.tray.notify("NOVA", "Paused — wake me when needed.")

    def _resume(self) -> None:
        self._paused = False
        self.tray.notify("NOVA", "Resumed.")

    def _open_diagnostics(self) -> None:
        try:
            report = self.api.diagnostics()
            summary = report.get("summary", {})
            lines = ["Diagnostics: PASS={} WARN={} ERROR={}".format(
                summary.get("PASS"), summary.get("WARNING"), summary.get("ERROR"))]
            for check in report.get("checks", []):
                flag = {"PASS": "✓", "WARNING": "⚠", "ERROR": "✗", "SKIP": "·"}.get(check["status"], "?")
                lines.append(f"{flag} {check['name']}: {check['detail'][:70]}")
            QMessageBox.information(None, "NOVA Diagnostics", "\n".join(lines[:24]))
        except Exception as exc:
            QMessageBox.warning(None, "NOVA", f"Diagnostics unavailable: {exc}")

    def _restart(self) -> None:
        pass  # tray "Restart Agent" — backend restart handled by installer/service

    def quit(self) -> None:
        self.api.stop_events()
        self.hotkeys.stop()
        self.tray.close()
        self.orb.hide()
        self.panel.hide()
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()
