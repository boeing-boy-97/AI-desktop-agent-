"""Windows system tray integration (spec §26).

Degrades gracefully on platforms without a tray: actions are still wired, and
the tray is simply not created.
"""
from __future__ import annotations

from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


def make_tray_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#4fd1c5"))
    p.setPen(QColor("#0b0e14"))
    p.drawEllipse(6, 6, 52, 52)
    p.setBrush(QColor("#0b0e14"))
    p.drawEllipse(26, 26, 12, 12)
    p.end()
    return QIcon(pm)


class TrayController:
    """Owns the QSystemTrayIcon and routes its menu actions to callbacks."""

    def __init__(self, callbacks: dict) -> None:
        self.callbacks = callbacks
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_tray_icon())
        self.tray.setToolTip("NOVA — desktop AI voice agent")
        menu = QMenu()
        for label, cb_name in [
            ("Activate", "activate"), ("Pause", "pause"), ("Resume", "resume"),
            ("Settings", "settings"), ("Task History", "history"),
            ("Permissions", "permissions"), ("Diagnostics", "diagnostics"),
            ("Restart Agent", "restart"),
        ]:
            act = QAction(label, menu)
            act.triggered.connect(self._make_handler(cb_name))
            menu.addAction(act)
        menu.addSeparator()
        stop = QAction("🛑 Emergency stop", menu)
        stop.triggered.connect(self._make_handler("emergency"))
        menu.addAction(stop)
        menu.addSeparator()
        exit_act = QAction("Exit", menu)
        exit_act.triggered.connect(self._make_handler("exit"))
        menu.addAction(exit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def _make_handler(self, name):
        def _h():
            cb = self.callbacks.get(name)
            if cb:
                cb()
        return _h

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            cb = self.callbacks.get("activate")
            if cb:
                cb()

    def notify(self, title: str, message: str) -> None:
        if self.tray:
            self.tray.showMessage(title, message,
                                  QSystemTrayIcon.MessageIcon.Information, 3000)

    def hide(self) -> None:
        if self.tray:
            self.tray.hide()

    def close(self) -> None:
        if self.tray:
            self.tray.hide()
