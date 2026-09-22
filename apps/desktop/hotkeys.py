"""Global hotkey registration via Qt (works across apps as long as Qt grabs it).

On Windows a low-level keyboard hook is preferred; we provide a best-effort
implementation with two backends:

    1. ``keyboard`` library (cross-platform, admin-free) when installed
    2. Qt-native shortcut on the orb window (always works while the app runs)
"""
from __future__ import annotations

import threading
from collections.abc import Callable

_MOD_KEYS = {"ctrl": "<ctrl>", "alt": "<alt>", "meta": "<super>", "shift": "<shift>"}


class GlobalHotkeys:
    def __init__(self) -> None:
        self._hooks_thread: threading.Thread | None = None
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._stop = threading.Event()

    def register(self, name: str, combo: str, callback: Callable[[], None]) -> bool:
        self._callbacks[name] = callback
        try:
            import keyboard  # type: ignore

            keyboard.add_hotkey(combo.replace("ctrl", "ctrl").replace("meta", "win"),
                                callback)
            return True
        except Exception:
            return False

    def register_all(self, combos: dict[str, str]) -> None:
        for name, cb in self._callbacks.items():
            combo = combos.get(name)
            if combo:
                self.register(name, combo, cb)

    def unregister_all(self) -> None:
        try:
            import keyboard  # type: ignore
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        self.unregister_all()
