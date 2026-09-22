"""Compact command panel — the secondary UI (spec §23, §47).

Contains: mic button, text command input, current-task status line, live step
list, stop button, and quick links to settings/history. Not a chat app.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from apps.desktop.theme import ACCENT, DANGER, MONO, OK, WARN

STATE_LABELS = {
    "IDLE": "Idle",
    "LISTENING": "Listening…",
    "UNDERSTANDING": "Understanding…",
    "PLANNING": "Planning…",
    "EXECUTING": "Executing…",
    "WAITING_CONFIRMATION": "Awaiting confirmation",
    "VERIFYING": "Verifying…",
    "RECOVERING": "Recovering…",
    "SPEAKING": "Speaking…",
    "COMPLETED": "Completed",
    "FAILED": "Failed",
    "CANCELLED": "Cancelled",
}


class CommandPanel(QWidget):
    commandSubmitted = pyqtSignal(str, str)   # (command_text, mode)
    stopRequested = pyqtSignal()
    openSettingsRequested = pyqtSignal()
    openHistoryRequested = pyqtSignal()
    micRequested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._task_id: str | None = None
        self._build()
        self.resize(360, 300)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        self.frame = QFrame()
        self.frame.setObjectName("panel")
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # header
        header = QHBoxLayout()
        self.title = QLabel("NOVA")
        self.title.setStyleSheet(f"font-weight: 700; font-size: 15px; color: {ACCENT};")
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {ACCENT}; font-size: 12px;")
        self.state_label = QLabel("Idle")
        self.state_label.setStyleSheet("color: #8b94a7; font-size: 11px;")
        close = QPushButton("✕")
        close.setObjectName("ghost")
        close.setFixedSize(26, 26)
        close.clicked.connect(self.hide)
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.status_dot)
        header.addWidget(self.state_label)
        header.addSpacing(8)
        header.addWidget(close)
        layout.addLayout(header)

        # command input
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command…  (e.g. “Open VS Code”)")
        self.input.returnPressed.connect(self._submit)
        layout.addWidget(self.input)

        row = QHBoxLayout()
        self.mic_btn = QPushButton("🎙  Talk")
        self.mic_btn.setObjectName("primary")
        self.mic_btn.clicked.connect(self.micRequested.emit)
        self.mode = QLabel("smart")
        self.mode.setStyleSheet("color: #8b94a7; font-size: 10px;")
        self.go_btn = QPushButton("Run")
        self.go_btn.clicked.connect(self._submit)
        row.addWidget(self.mic_btn)
        row.addWidget(self.mode)
        row.addStretch()
        row.addWidget(self.go_btn)
        layout.addLayout(row)

        # live status
        self.task_label = QLabel("Awaiting command…")
        self.task_label.setWordWrap(True)
        self.task_label.setStyleSheet("color: #c7cede; font-size: 12px;")
        layout.addWidget(self.task_label)

        self.steps_label = QLabel("")
        self.steps_label.setStyleSheet(f"font-family: {MONO}; font-size: 10px; color: #8b94a7;")
        self.steps_label.setWordWrap(True)
        layout.addWidget(self.steps_label, 1)

        # footer
        footer = QHBoxLayout()
        self.stop_btn = QPushButton("⏹  Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stopRequested.emit)
        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("ghost")
        settings_btn.clicked.connect(self.openSettingsRequested.emit)
        history_btn = QPushButton("🕘")
        history_btn.setObjectName("ghost")
        history_btn.clicked.connect(self.openHistoryRequested.emit)
        footer.addWidget(self.stop_btn)
        footer.addStretch()
        footer.addWidget(history_btn)
        footer.addWidget(settings_btn)
        layout.addLayout(footer)

        outer.addWidget(self.frame)
        self._drag_offset = None

    # ------------------------------------------------------------------
    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.commandSubmitted.emit(text, "smart")

    def set_state(self, state: str) -> None:
        label = STATE_LABELS.get(state, state)
        self.state_label.setText(label)
        colors = {
            "LISTENING": "#7c9af2", "EXECUTING": ACCENT, "PROCESSING": ACCENT,
            "SPEAKING": "#e2b93d", "COMPLETED": OK, "FAILED": DANGER,
            "CANCELLED": WARN, "WAITING_CONFIRMATION": WARN,
        }
        self.status_dot.setStyleSheet(f"color: {colors.get(state, ACCENT)}; font-size: 12px;")

    def set_live(self, task_id: str | None, text: str, steps: list[str]) -> None:
        self._task_id = task_id
        self.task_label.setText(text)
        shown = "\n".join(("• " + s) for s in steps[-6:])
        self.steps_label.setText(shown)
        self.stop_btn.setEnabled(task_id is not None)

    # ------------------------------------------------------------------
    # drag support (frameless window)
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        event.accept()
