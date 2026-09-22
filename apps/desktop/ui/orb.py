"""The floating NOVA orb — a tiny, draggable, always-on-top window.

Features (spec §1, §25):
    * small circular/rounded translucent widget
    * draggable + position persistence + multi-monitor aware
    * idle / listening / processing / speaking states with animations
    * click → toggle command panel; click-hold → drag
    * right-click → context menu (panel, hide, tray, emergency stop)
    * global shortcut toggling (handled by the app's hotkey module)
"""
from __future__ import annotations

import time

from PyQt6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QGuiApplication, QPainter
from PyQt6.QtWidgets import QMenu, QWidget

from apps.desktop.theme import ACCENT, ACCENT_2, DANGER


class OrbState:
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"


class Orb(QWidget):
    """Circular draggable orb window (frameless, translucent, on top)."""

    togglePanelRequested = pyqtSignal()
    activateRequested = pyqtSignal()      # click-to-talk
    hideRequested = pyqtSignal()
    showPanelRequested = pyqtSignal()
    emergencyRequested = pyqtSignal()
    positionSaved = pyqtSignal(int, int)

    SIZE = 68

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._scale = 1.0
        self._state = OrbState.IDLE
        self._drag_offset: QPoint | None = None
        self._press_pos: QPoint | None = None
        self._press_time = 0.0
        self._drag_distance = 0
        self._dragged = False

        self._pulse = QTimerlessAnim(self)
        self._pulse_value = 0.0
        self._spin_angle = 0.0

        self._timer = None
        self.setToolTip("NOVA — click to talk · drag to move · right-click for menu")

        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo:
            self.move(geo.right() - self.SIZE - 24, geo.top() + 120)
        self.set_scale(self._scale)

    # ------------------------------------------------------------------
    # appearance / state
    # ------------------------------------------------------------------
    def set_scale(self, scale: float) -> None:
        self._scale = max(0.7, min(1.6, scale))
        size = int(self.SIZE * self._scale)
        self.setFixedSize(size, size)
        self.update()

    def set_state(self, state: str) -> None:
        state = (state or "").lower()
        valid = {OrbState.IDLE, OrbState.LISTENING, OrbState.PROCESSING,
                 OrbState.SPEAKING, OrbState.ERROR, "completed", "failed",
                 "cancelled", "understanding", "planning", "executing",
                 "verifying", "recovering", "waiting_confirmation"}
        if state not in valid:
            state = OrbState.IDLE
        if state != OrbState.IDLE and state not in (OrbState.LISTENING,
                                                    OrbState.PROCESSING):
            # map task states to visual states
            state = ({
                "speaking": OrbState.SPEAKING,
                "failed": OrbState.ERROR,
                "waiting_confirmation": OrbState.PROCESSING,
                "understanding": OrbState.PROCESSING,
                "planning": OrbState.PROCESSING,
                "verifying": OrbState.PROCESSING,
                "recovering": OrbState.PROCESSING,
                "completed": OrbState.IDLE,
                "cancelled": OrbState.IDLE,
            }).get(state, state)
        if state == self._state:
            return
        self._state = state
        if state in (OrbState.LISTENING, OrbState.PROCESSING):
            self._pulse.start()
        else:
            self._pulse.stop()
        self.update()

    @property
    def state(self) -> str:
        return self._state

    # ------------------------------------------------------------------
    # drag handling
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._press_time = time.monotonic()
            self._dragged = False
            self._drag_distance = 0
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = (event.globalPosition().toPoint()
                     - self._press_pos).manhattanLength() if self._press_pos else 0
            self._drag_distance = max(self._drag_distance, delta)
            if self._drag_distance > 6:
                self._dragged = True
            target = event.globalPosition().toPoint() - self._drag_offset
            self._snap_move(target)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            held = time.monotonic() - self._press_time
            if self._dragged:
                self.positionSaved.emit(self.pos().x(), self.pos().y())
            elif held < 0.6:
                # short click → talk
                self.activateRequested.emit()
            self._drag_offset = None
            event.accept()

    # ------------------------------------------------------------------
    def _snap_move(self, target: QPoint) -> None:
        screen = QGuiApplication.screenAt(target) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(max(target.x(), geo.left()), geo.right() - self.width())
        y = min(max(target.y(), geo.top()), geo.bottom() - self.height())
        self.move(x, y)

    def _show_menu(self, global_pos: QPoint) -> None:
        menu = QMenu()
        menu.addAction("🎙  Talk", self.activateRequested.emit)
        menu.addAction("💬  Command panel", self.togglePanelRequested.emit)
        menu.addSeparator()
        act_hide = QAction("🙈  Hide for 1 hour", menu)
        act_hide.triggered.connect(self._hide_hour)
        menu.addAction(act_hide)
        act_stop = QAction("🛑  Emergency stop", menu)
        act_stop.triggered.connect(self._emergency)
        menu.addAction(act_stop)
        menu.exec(global_pos)

    def _hide_hour(self) -> None:
        self.hide()
        self.hidden = time.monotonic()
        QTimerProxy(self).single_shot(3600_000, self._restore)

    def _emergency(self) -> None:
        self.emergencyRequested.emit()

    def _restore(self) -> None:
        self.show()
        self.raise_()

    # ------------------------------------------------------------------
    # painting
    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        import PyQt6.QtGui as G
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(2, 2, self.width() - 4, self.height() - 4)
        pulse = self._pulse_value

        # glow / state ring
        color = ACCENT
        if self._state == OrbState.LISTENING:
            color = ACCENT_2
        elif self._state == OrbState.SPEAKING:
            color = "#e2b93d"
        elif self._state == OrbState.ERROR:
            color = DANGER

        # outer glow
        glow = G.QColor(color)
        glow.setAlpha(40 + int(40 * pulse))
        p.setPen(G.QPen(glow, 3))
        p.drawEllipse(r)

        # fill
        bg = G.QColor(18, 22, 31, 215)
        p.setBrush(bg)
        p.setPen(G.QPen(G.QColor(color), 2))
        p.drawEllipse(r)

        # core orb + ring arc
        cx, cy = r.center().x(), r.center().y()
        rad = r.width() / 2 - 8
        core = G.QColor(color)
        core.setAlpha(200 if self._state == OrbState.IDLE else 170 + int(85 * pulse))
        p.setBrush(core)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), rad, rad)

        # idle dot breathing / activity arc
        p.translate(cx, cy)
        if self._state in (OrbState.PROCESSING, OrbState.LISTENING):
            self._spin_angle = (self._spin_angle + 6) % 360
            arc = G.QPen(G.QColor("#ffffff"))
            arc.setWidth(3)
            arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(arc)
            p.drawArc(QRectF(-rad - 5, -rad - 5, 2 * rad + 10, 2 * rad + 10),
                      int(-self._spin_angle * 16), 100 * 16)
        p.setPen(G.QPen(G.QColor("#ffffff")))
        p.setBrush(G.QColor("#ffffff"))
        d = 6 + 2 * pulse
        p.drawEllipse(QPointF(0, 0), d / 2, d / 2)
        p.end()


class QTimerProxy:
    """Tiny adapter letting the orb schedule a delayed show without importing
    QTimer at module import time."""

    def __init__(self, parent) -> None:
        from PyQt6.QtCore import QTimer
        self._timer = QTimer(parent)

    def single_shot(self, ms: int, callback) -> None:
        self._timer.singleShot(ms, callback)


class QTimerlessAnim:
    """Lightweight 0→1 looping animation driving the orb's pulse value."""

    def __init__(self, orb: Orb) -> None:
        from PyQt6.QtCore import QTimer
        self._orb = orb
        self._phase = 0.0
        self._timer = QTimer(orb)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._orb._pulse_value = 0.0
        self._orb.update()

    def _tick(self) -> None:
        import math
        self._phase += 0.08
        self._orb._pulse_value = 0.5 + 0.5 * math.sin(self._phase)
        self._orb.update()

    def state(self):
        return self._timer.isActive()
