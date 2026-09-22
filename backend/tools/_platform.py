"""Cross-platform backend for computer-control tools.

Real implementations are used on Windows (pyautogui / pygetwindow via uiautomation),
and a deterministic in-memory stand-in is used on headless/Linux CI so tests can
assert full behaviour. Every method returns a dict; raising is avoided so the
agent's error-recovery sees structured failures.
"""
from __future__ import annotations

import platform
from pathlib import Path

_IS_WINDOWS = platform.system() == "Windows"


class Computer:
    """One facade exposing mouse/keyboard/window APIs.

    Choose the backend once at construction; the rest of the agent is agnostic.
    """

    def __init__(self, backend: str = "auto") -> None:
        if backend == "auto":
            backend = "real" if _IS_WINDOWS else "memory"
        self.backend = backend
        self.history: list[dict] = []
        self._lazy = None

    # -- internal plumbing ----------------------------------------------
    def _record(self, action: str, **kw) -> dict:
        rec = {"action": action, **kw}
        self.history.append(rec)
        return dict(rec)

    def _imp(self):
        if self._lazy is None:
            if self.backend == "real":
                self._lazy = _RealComputer()
            else:
                self._lazy = _MemoryComputer()
        return self._lazy

    # -- public API (all safe, all dict-returning) ----------------------
    def move(self, x: int, y: int) -> dict:
        out = dict(self._imp().move(x, y)); out.pop("x", None); out.pop("y", None)
        return self._record("move", x=x, y=y, **out)

    def click(self, x: int | None = None, y: int | None = None, button: str = "left") -> dict:
        out = dict(self._imp().click(x, y, button)); out.pop("button", None); out.pop("x", None); out.pop("y", None)
        return self._record("click", x=x, y=y, button=button, **out)

    def double_click(self, x: int | None = None, y: int | None = None) -> dict:
        out = self._imp().double_click(x, y)
        return self._record("double_click", x=x, y=y, **out)

    def right_click(self, x: int | None = None, y: int | None = None) -> dict:
        out = self._imp().right_click(x, y)
        return self._record("right_click", x=x, y=y, **out)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> dict:
        out = self._imp().drag(x1, y1, x2, y2, duration)
        return self._record("drag", x1=x1, y1=y1, x2=x2, y2=y2, **out)

    def press(self, keys: list[str]) -> dict:
        out = self._imp().press(keys)
        return self._record("press", keys=keys, **out)

    def type_text(self, text: str, interval: float = 0.0) -> dict:
        out = self._imp().type_text(text, interval)
        return self._record("type", text=text, **out)

    def hotkey(self, keys: list[str]) -> dict:
        out = self._imp().hotkey(keys)
        return self._record("hotkey", keys=keys, **out)

    def scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> dict:
        out = self._imp().scroll(clicks, x, y)
        return self._record("scroll", clicks=clicks, **out)

    def screenshot(self, path: str) -> dict:
        out = dict(self._imp().screenshot(path)); out.pop("path", None)
        return self._record("screenshot", path=path, **out)

    def active_window(self) -> dict:
        out = self._imp().active_window()
        return self._record("active_window", **out)

    def list_windows(self) -> dict:
        out = self._imp().list_windows()
        return self._record("list_windows", **out)

    def activate_window(self, title_substring: str = "", window_id: str = "") -> dict:
        out = self._imp().activate_window(title_substring, window_id)
        return self._record("activate_window", title_substring=title_substring, **out)

    def minimize_window(self, title_substring: str = "") -> dict:
        out = self._imp().minimize_window(title_substring)
        return self._record("minimize_window", title_substring=title_substring, **out)

    def maximize_window(self, title_substring: str = "") -> dict:
        out = self._imp().maximize_window(title_substring)
        return self._record("maximize_window", title_substring=title_substring, **out)

    def launch(self, command: str) -> dict:
        out = self._imp().launch(command)
        out = dict(out)
        out.pop("command", None)
        return self._record("launch", command=command, **out)

    def close_app(self, title_substring: str = "", window_id: str = "") -> dict:
        out = self._imp().close_app(title_substring, window_id)
        return self._record("close_app", title_substring=title_substring, **out)

    def clipboard_read(self) -> dict:
        out = self._imp().clipboard_read()
        return self._record("clipboard_read", **out)

    def clipboard_write(self, text: str) -> dict:
        out = self._imp().clipboard_write(text)
        return self._record("clipboard_write", **out)


# ---------------------------------------------------------------------------
# Real backend (Windows primary, POSIX best-effort via pyautogui + pygetwindow)
# ---------------------------------------------------------------------------
class _RealComputer:
    def __init__(self) -> None:
        self._pg = None
        self._pw = None

    def _pyautogui(self):
        if self._pg is None:
            import pyautogui as pg
            pg.FAILSAFE = True
            self._pg = pg
        return self._pg

    def _pygetwindow(self):
        if self._pw is None:
            import pygetwindow as pw
            self._pw = pw
        return self._pw

    def move(self, x, y): return {"moved": True, "x": x, "y": y} if self._pg_move(x, y) else {"moved": False}
    def _pg_move(self, x, y):
        pg = self._pyautogui()
        pg.moveTo(x, y, duration=0.1)
        return True

    def click(self, x, y, button):
        pg = self._pyautogui()
        if x is not None and y is not None:
            pg.click(x, y, button=button)
        else:
            pg.click(button=button)
        return {"clicked": True}

    def double_click(self, x, y):
        pg = self._pyautogui()
        target = (x, y) if x is not None and y is not None else ()
        pg.doubleClick(*target) if target else pg.doubleClick()
        return {"clicked": True}

    def right_click(self, x, y):
        pg = self._pyautogui()
        if x is not None and y is not None:
            pg.rightClick(x, y)
        else:
            pg.rightClick()
        return {"clicked": True}

    def drag(self, x1, y1, x2, y2, duration):
        pg = self._pyautogui()
        pg.moveTo(x1, y1)
        pg.dragTo(x2, y2, duration=duration)
        return {"dragged": True}

    def press(self, keys):
        pg = self._pyautogui()
        for k in keys:
            pg.press(k)
        return {"pressed": keys}

    def type_text(self, text, interval):
        pg = self._pyautogui()
        pg.write(text, interval=interval)
        return {"typed": len(text)}

    def hotkey(self, keys):
        pg = self._pyautogui()
        pg.hotkey(*keys)
        return {"pressed": keys}

    def scroll(self, clicks, x, y):
        pg = self._pyautogui()
        pg.scroll(clicks, x=x, y=y)
        return {"scrolled": clicks}

    def screenshot(self, path):
        pg = self._pyautogui()
        img = pg.screenshot()
        img.save(path)
        return {"path": path, "captured": True}

    def active_window(self):
        try:
            pw = self._pygetwindow()
            win = pw.getActiveWindow()
            return {"title": win.title if win else ""}
        except Exception as exc:
            return {"title": "", "error": str(exc)}

    def list_windows(self):
        try:
            pw = self._pygetwindow()
            wins = [{"title": w.title, "visible": w.visible} for w in pw.getAllWindows() if w.title.strip()]
            return {"windows": wins[:100]}
        except Exception as exc:
            return {"windows": [], "error": str(exc)}

    def _find(self, title_substring):
        pw = self._pygetwindow()
        wins = [w for w in pw.getAllWindows() if w.title.strip()]
        if title_substring:
            wins = [w for w in wins if title_substring.lower() in w.title.lower()]
        return wins

    def activate_window(self, title_substring, window_id):
        wins = self._find(title_substring)
        if window_id and window_id.isdigit():
            wins = wins[int(window_id):int(window_id) + 1]
        if not wins:
            return {"activated": False, "reason": "no matching window"}
        try:
            wins[0].activate()
            return {"activated": True, "title": wins[0].title}
        except Exception as exc:
            return {"activated": False, "reason": str(exc)}

    def minimize_window(self, title_substring):
        wins = self._find(title_substring)
        if not wins:
            return {"minimized": False, "reason": "no matching window"}
        try:
            wins[0].minimize()
            return {"minimized": True, "title": wins[0].title}
        except Exception as exc:
            return {"minimized": False, "reason": str(exc)}

    def maximize_window(self, title_substring):
        wins = self._find(title_substring)
        if not wins:
            return {"maximized": False, "reason": "no matching window"}
        try:
            wins[0].maximize()
            return {"maximized": True, "title": wins[0].title}
        except Exception as exc:
            return {"maximized": False, "reason": str(exc)}

    def launch(self, command):
        import subprocess
        try:
            subprocess.Popen(command, shell=True)
            return {"launched": True, "command": command}
        except Exception as exc:
            return {"launched": False, "reason": str(exc)}

    def close_app(self, title_substring, window_id):
        wins = self._find(title_substring)
        if window_id and window_id.isdigit():
            wins = wins[int(window_id):int(window_id) + 1]
        if not wins:
            return {"closed": False, "reason": "no matching window"}
        try:
            wins[0].close()
            return {"closed": True, "title": wins[0].title}
        except Exception as exc:
            return {"closed": False, "reason": str(exc)}

    def clipboard_read(self):
        try:
            from tkinter import Tk
            root = Tk(); root.withdraw()
            text = root.clipboard_get()
            root.destroy()
            return {"text": text}
        except Exception as exc:
            return {"text": "", "reason": str(exc)}

    def clipboard_write(self, text):
        try:
            from tkinter import Tk
            root = Tk(); root.withdraw()
            root.clipboard_clear(); root.clipboard_append(text); root.update()
            root.destroy()
            return {"written": True}
        except Exception as exc:
            return {"written": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Memory backend (deterministic; used in CI/headless and as mock)
# ---------------------------------------------------------------------------
class _MemoryComputer:
    def __init__(self) -> None:
        self.pos = (0, 0)
        self.windows = [
            {"title": "Chrome", "visible": True},
            {"title": "VS Code", "visible": True},
            {"title": "WhatsApp", "visible": False},
        ]
        self.active = "Chrome"
        self.clipboard = ""
        self.typed = ""
        self.pressed = []

    def move(self, x, y):
        self.pos = (x, y)
        return {"moved": True, "x": x, "y": y}

    def click(self, x, y, button):
        if x is not None and y is not None:
            self.pos = (x, y)
        return {"clicked": True, "button": button}

    def double_click(self, x, y):
        return {"clicked": True, "double": True}

    def right_click(self, x, y):
        return {"clicked": True, "button": "right"}

    def drag(self, x1, y1, x2, y2, duration):
        self.pos = (x2, y2)
        return {"dragged": True}

    def press(self, keys):
        self.pressed += list(keys)
        return {"pressed": list(keys)}

    def type_text(self, text, interval):
        self.typed += text
        return {"typed": len(text)}

    def hotkey(self, keys):
        self.pressed += list(keys)
        return {"pressed": list(keys), "combo": True}

    def scroll(self, clicks, x, y):
        return {"scrolled": clicks}

    def screenshot(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"fake-png")
        return {"path": path, "captured": True, "backend": "memory"}

    def active_window(self):
        return {"title": self.active}

    def list_windows(self):
        return {"windows": self.windows[:]}

    def activate_window(self, title_substring, window_id):
        hits = [w for w in self.windows if title_substring.lower() in w["title"].lower()]
        if not hits:
            return {"activated": False, "reason": "no matching window"}
        self.active = hits[0]["title"]
        hits[0]["visible"] = True
        return {"activated": True, "title": hits[0]["title"]}

    def minimize_window(self, title_substring):
        hits = [w for w in self.windows if title_substring.lower() in w["title"].lower()]
        if not hits:
            return {"minimized": False, "reason": "no matching window"}
        hits[0]["visible"] = False
        return {"minimized": True, "title": hits[0]["title"]}

    def maximize_window(self, title_substring):
        hits = [w for w in self.windows if title_substring.lower() in w["title"].lower()]
        if not hits:
            return {"maximized": False, "reason": "no matching window"}
        hits[0]["visible"] = True
        return {"maximized": True, "title": hits[0]["title"]}

    def launch(self, command):
        return {"launched": True, "command": command, "backend": "memory"}

    def close_app(self, title_substring, window_id):
        hits = [w for w in self.windows if title_substring.lower() in w["title"].lower()]
        if not hits:
            return {"closed": False, "reason": "no matching window"}
        hits[0]["visible"] = False
        return {"closed": True, "title": hits[0]["title"]}

    def clipboard_read(self):
        return {"text": self.clipboard}

    def clipboard_write(self, text):
        self.clipboard = text
        return {"written": True}
