"""Task history window (spec §22)."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from apps.desktop.theme import DANGER, MONO, OK, WARN


class HistoryWindow(QWidget):
    refreshRequested = None   # assigned by controller
    clearRequested = None

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("NOVA — Task History")
        self.resize(880, 520)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Task History")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        refresh = QPushButton("↻ Refresh")
        clear = QPushButton("Clear history")
        clear.setObjectName("danger")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        header.addWidget(clear)
        layout.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Command", "Mode", "Status", "Actions", "Errors repaired"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        self.detail = QLabel("Select a task to see its steps.")
        self.detail.setStyleSheet(f"font-family: {MONO}; font-size: 11px;")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail, 1)

        refresh.clicked.connect(lambda: self.refreshRequested and self.refreshRequested())
        clear.clicked.connect(lambda: self.clearRequested and self.clearRequested())
        self.table.itemSelectionChanged.connect(self._on_select)

    def populate(self, tasks: list) -> None:
        self.table.setRowCount(0)
        self._tasks = tasks
        for t in tasks:
            row = self.table.rowCount()
            self.table.insertRow(row)
            created = (t.get("created_at") or "")[11:19]
            self.table.setItem(row, 0, QTableWidgetItem(created))
            self.table.setItem(row, 1, QTableWidgetItem(t.get("command", "")))
            self.table.setItem(row, 2, QTableWidgetItem(t.get("mode", "smart")))
            status = t.get("status", "queued")
            item = QTableWidgetItem(status)
            color = {"completed": OK, "failed": DANGER, "cancelled": WARN}.get(status, "#8b94a7")
            item.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(color))
            self.table.setItem(row, 3, item)
            self.table.setItem(row, 4, QTableWidgetItem(str(len(t.get("steps", [])))))
            self.table.setItem(row, 5, QTableWidgetItem(str(t.get("errors_repaired", 0))))

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or not getattr(self, "_tasks", None):
            return
        t = self._tasks[rows[0].row()]
        lines = [f"command: {t.get('command')}", f"goal: {t.get('goal')}",
                 f"status: {t.get('status')}", f"result: {t.get('result') or ''}"]
        if t.get("error"):
            lines.append(f"error: {t['error'][:200]}")
        for s in t.get("steps", []):
            lines.append(f"  [{s['seq']}] {s['tool']} → {s['status']}"
                         + (f" · {s['error'][:60]}" if s.get("error") else ""))
        self.detail.setText("\n".join(lines))
