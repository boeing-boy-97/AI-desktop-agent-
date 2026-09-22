"""Settings window — organised into sections (spec §27, §40).

Sections: General, Voice, AI Provider, Automation, Permissions, Privacy,
Appearance, plus inherited hotkeys/logging/startup groups.
The window is keyboard-accessible and DPI-aware; fields map to backend keys.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class SettingsWindow(QWidget):
    saveRequested = None  # assigned by controller

    def __init__(self, current: dict) -> None:
        super().__init__(None)
        self.setWindowTitle("NOVA Settings")
        self._current = current or {}
        self._fields: dict[str, Any] = {}
        self._build(current or {})
        self.resize(720, 560)

    def _build(self, cfg: dict) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(cfg), "General")
        tabs.addTab(self._voice_tab(cfg), "Voice")
        tabs.addTab(self._ai_tab(cfg), "AI Provider")
        tabs.addTab(self._automation_tab(cfg), "Automation")
        tabs.addTab(self._permissions_tab(cfg), "Permissions")
        tabs.addTab(self._privacy_tab(cfg), "Privacy")
        tabs.addTab(self._appearance_tab(cfg), "Appearance")
        layout.addWidget(tabs)

        btns = QHBoxLayout()
        btns.addStretch()
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    # -- tab builders ---------------------------------------------------
    def _scroll(self, widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(widget)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        return area

    def _general_tab(self, cfg):
        w = QWidget()
        form = QFormLayout(w)
        self._checkbox(form, "desktop.start_minimized", cfg, "Start minimized to tray")
        self._checkbox(form, "desktop.always_on_top", cfg, "Keep orb always on top")
        self._checkbox(form, "desktop.confirm_on_exit", cfg, "Confirm before exit")
        self._checkbox(form, "permissions.confirm_messages", cfg, "Confirm before sending messages")
        hotkey = QLineEdit(cfg.get("hotkeys.activate", "ctrl+alt+space"))
        form.addRow("Activate shortcut", hotkey)
        self._fields["hotkeys.activate"] = hotkey
        hotkey2 = QLineEdit(cfg.get("hotkeys.emergency_stop", "ctrl+alt+x"))
        form.addRow("Emergency stop shortcut", hotkey2)
        self._fields["hotkeys.emergency_stop"] = hotkey2
        return self._scroll(w)

    def _voice_tab(self, cfg):
        w = QWidget()
        form = QFormLayout(w)
        stt = QComboBox(); stt.addItems(["faster-whisper", "mock"])
        stt.setCurrentText(cfg.get("voice.stt_provider", "faster-whisper"))
        form.addRow("Speech-to-text", stt); self._fields["voice.stt_provider"] = stt
        model = QComboBox(); model.addItems(["tiny", "base", "small", "medium", "large-v3"])
        model.setCurrentText(cfg.get("voice.stt_model", "base"))
        form.addRow("Whisper model", model); self._fields["voice.stt_model"] = model
        tts = QComboBox(); tts.addItems(["pyttsx3", "none", "kokoro", "piper"])
        tts.setCurrentText(cfg.get("voice.tts_provider", "pyttsx3"))
        form.addRow("Text-to-speech", tts); self._fields["voice.tts_provider"] = tts
        rate = QSpinBox(); rate.setRange(80, 300); rate.setValue(int(cfg.get("voice.rate", 170)))
        form.addRow("Speech rate", rate); self._fields["voice.rate"] = rate
        vol = QDoubleSpinBox(); vol.setRange(0.0, 1.0); vol.setSingleStep(0.1)
        vol.setValue(float(cfg.get("voice.volume", 1.0)))
        form.addRow("Volume", vol); self._fields["voice.volume"] = vol
        return self._scroll(w)

    def _ai_tab(self, cfg):
        w = QWidget()
        form = QFormLayout(w)
        provider = QComboBox(); provider.addItems(["openai", "ollama", "mock"])
        provider.setCurrentText(cfg.get("ai.provider", "openai"))
        form.addRow("Provider", provider); self._fields["ai.provider"] = provider
        base = QLineEdit(cfg.get("ai.openai_base_url", "https://api.openai.com/v1"))
        form.addRow("OpenAI base URL", base); self._fields["ai.openai_base_url"] = base
        model = QLineEdit(cfg.get("ai.openai_model", "gpt-4o-mini"))
        form.addRow("OpenAI model", model); self._fields["ai.openai_model"] = model
        key = QLineEdit(""); key.setEchoMode(QLineEdit.EchoMode.Password)
        key.setPlaceholderText("set via OPENAI_API_KEY (not stored)")
        form.addRow("API key (env)", key)
        ollama = QLineEdit(cfg.get("ai.ollama_base_url", "http://127.0.0.1:11434"))
        form.addRow("Ollama URL", ollama); self._fields["ai.ollama_base_url"] = ollama
        omodel = QLineEdit(cfg.get("ai.ollama_model", "llama3.1"))
        form.addRow("Ollama model", omodel); self._fields["ai.ollama_model"] = omodel
        note = QLabel("API keys are read from environment variables only — never stored in settings.")
        note.setStyleSheet("color: #8b94a7; font-size: 11px;")
        form.addRow(note)
        return self._scroll(w)

    def _automation_tab(self, cfg):
        w = QWidget()
        form = QFormLayout(w)
        retries = QSpinBox(); retries.setRange(0, 6)
        retries.setValue(int(cfg.get("automation.max_retries", 2)))
        form.addRow("Max retries", retries); self._fields["automation.max_retries"] = retries
        timeout = QSpinBox(); timeout.setRange(5, 600)
        timeout.setValue(int(cfg.get("automation.step_timeout_seconds", 60)))
        form.addRow("Step timeout (s)", timeout)
        self._fields["automation.step_timeout_seconds"] = timeout
        dl = QLineEdit(cfg.get("automation.downloads_dir", "~/Downloads"))
        form.addRow("Downloads folder", dl); self._fields["automation.downloads_dir"] = dl
        ss = QLineEdit(cfg.get("automation.screenshot_dir", ""))
        form.addRow("Screenshots folder", ss); self._fields["automation.screenshot_dir"] = ss
        browser = QComboBox(); browser.addItems(["playwright", "mock"])
        browser.setCurrentText(cfg.get("browser.engine", "playwright"))
        form.addRow("Browser engine", browser); self._fields["browser.engine"] = browser
        self._checkbox(form, "browser.headless", cfg, "Headless browser")
        return self._scroll(w)

    def _permissions_tab(self, cfg):
        w = QWidget()
        form = QFormLayout(w)
        default = QComboBox(); default.addItems(["ask", "allow", "deny"])
        default.setCurrentText(cfg.get("permissions.default_mode", "ask"))
        form.addRow("Default policy", default); self._fields["permissions.default_mode"] = default
        self._checkbox(form, "permissions.remember_choice", cfg, "Remember choices per tool")
        self._checkbox(form, "permissions.confirm_delete", cfg, "Confirm file deletion")
        self._checkbox(form, "permissions.confirm_privileged", cfg, "Confirm privileged/system actions")
        note = QLabel("High-risk actions (send messages, deletes, shutdown) always ask "
                      "unless explicitly allowed for the tool.")
        note.setStyleSheet("color: #8b94a7; font-size: 11px;")
        form.addRow(note)
        return self._scroll(w)

    def _privacy_tab(self, cfg):
        w = QWidget()
        form = QFormLayout(w)
        self._checkbox(form, "privacy.cloud_processing_enabled", cfg,
                       "Allow cloud AI processing")
        self._checkbox(form, "automation.screenshots_enabled", cfg,
                       "Enable screen capture")
        self._checkbox(form, "privacy.log_filenames", cfg, "Log file names")
        note = QLabel("NOVA processes your commands locally by default. Voice audio and "
                      "screenshots are never uploaded without the cloud option enabled.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #8b94a7; font-size: 11px;")
        form.addRow(note)
        return self._scroll(w)

    def _appearance_tab(self, cfg):
        w = QWidget()
        form = QFormLayout(w)
        theme = QComboBox(); theme.addItems(["dark", "light"])
        theme.setCurrentText(cfg.get("desktop.theme", "dark"))
        form.addRow("Theme", theme); self._fields["desktop.theme"] = theme
        scale = QDoubleSpinBox(); scale.setRange(0.7, 1.6); scale.setSingleStep(0.05)
        scale.setValue(float(cfg.get("desktop.orb_scale", 1.0)))
        form.addRow("Orb scale", scale); self._fields["desktop.orb_scale"] = scale
        opacity = QDoubleSpinBox(); opacity.setRange(0.5, 1.0); opacity.setSingleStep(0.05)
        opacity.setValue(float(cfg.get("desktop.opacity", 0.92)))
        form.addRow("Opacity", opacity); self._fields["desktop.opacity"] = opacity
        return self._scroll(w)

    def _checkbox(self, form: QFormLayout, key: str, cfg: dict, label: str) -> None:
        cb = QCheckBox(label)
        cb.setChecked(bool(cfg.get(key, True)))
        form.addRow(cb)
        self._fields[key] = cb

    # ------------------------------------------------------------------
    def _save(self) -> None:
        updates = {}
        for key, widget in self._fields.items():
            if isinstance(widget, QCheckBox):
                updates[key] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                updates[key] = widget.value()
            elif isinstance(widget, QComboBox):
                updates[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                updates[key] = widget.text()
        if self.saveRequested:
            self.saveRequested(updates)
        self.close()
