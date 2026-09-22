"""ScreenObserver — understand what is currently displayed.

Responsibilities (spec §12):
    * screenshot current screen / region
    * detect active application
    * OCR visible text
    * identify major UI elements where possible
    * compare before/after screenshots to verify that an action succeeded

Implementations are provided adaptively:

    * Windows:  Pillow.ImageGrab + ctypes GetForegroundWindow (primary)
    * macOS/Linux:  Pillow.ImageGrab / pyscreenshot fallbacks
    * headless CI:  in-memory synthetic canvas (still fully functional API)

OCR backends are tried in order: rapidocr → pytesseract. If none are
installed, OCR is gracefully reported as unavailable.
"""
from __future__ import annotations

import base64
import hashlib
import io
import platform
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.utils import iso_now, new_id

_IS_WINDOWS = platform.system() == "Windows"


@dataclass
class WindowInfo:
    title: str
    class_name: str = ""
    pid: int | None = None
    bounds: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"title": self.title, "class_name": self.class_name,
                "pid": self.pid, "bounds": self.bounds}


@dataclass
class ScreenSnapshot:
    """One captured frame plus optional OCR/text extraction."""
    id: str
    timestamp: str
    image_png: bytes | None = None
    width: int = 0
    height: int = 0
    text: str = ""
    active_window: WindowInfo | None = None
    source: str = "os"
    path: str | None = None

    @property
    def image_b64(self) -> str:
        return base64.b64encode(self.image_png).decode() if self.image_png else ""

    def fingerprint(self) -> str:
        if not self.image_png:
            return "empty:" + self.timestamp
        return "sha256:" + hashlib.sha256(self.image_png).hexdigest()

    def as_dict(self, include_image: bool = False) -> dict:
        out = {
            "id": self.id, "timestamp": self.timestamp, "width": self.width,
            "height": self.height, "text": self.text[:2000], "source": self.source,
            "path": self.path,
            "active_window": self.active_window.as_dict() if self.active_window else None,
        }
        if include_image:
            out["image_b64"] = self.image_b64
        return out


class _TextExtractor:
    """Ordered OCR backends, lazily imported."""

    def __init__(self) -> None:
        self._ok = False

    def _backend(self) -> Callable[[bytes], str] | None:
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
            engine = RapidOCR()

            def run(img: bytes):
                res, _ = engine(img)
                if not res:
                    return ""
                return "\n".join(line[1] for line in res)
            return run
        except Exception:
            pass
        try:
            import pytesseract  # type: ignore
            from PIL import Image

            def run2(img: bytes):
                with Image.open(io.BytesIO(img)) as im:
                    return pytesseract.image_to_string(im)
            return run2
        except Exception:
            pass
        return None

    def extract(self, image_png: bytes) -> str:
        backend = self._backend()
        if backend is None:
            return ""
        try:
            return backend(image_png).strip()
        except Exception:
            return ""


class ScreenObserver:
    """Screenshot + OCR + active-window + change detection service."""

    def __init__(self, settings: Any, event_bus: Any = None) -> None:
        self.settings = settings
        self.event_bus = event_bus
        self._grabshot_fn: Callable[[], bytes] | None = None
        self._grabshot_region_fn: Callable[[tuple], bytes] | None = None
        self._synthetic = False
        self._init_backend()
        self._history: dict[str, ScreenSnapshot] = {}
        self._text_extractor = _TextExtractor()

    # ------------------------------------------------------------------
    def _init_backend(self) -> None:
        """Choose a screenshot backend; degrade gracefully."""
        try:
            from PIL import ImageGrab  # type: ignore
            ImageGrab.grab()  # probe once
            def full():
                img = ImageGrab.grab()
                buf = io.BytesIO()
                img.save(buf, "PNG")
                return buf.getvalue()
            def region(box):
                img = ImageGrab.grab(bbox=box)
                buf = io.BytesIO()
                img.save(buf, "PNG")
                return buf.getvalue()
            self._grabshot_fn = full
            self._grabshot_region_fn = region
            return
        except Exception:
            pass
        # synthesize for headless environments so the full API stays usable
        self._synthetic = True

    # -- capture --------------------------------------------------------
    def screenshot(self, region: tuple | None = None) -> ScreenSnapshot:
        ts = iso_now()
        snap_id = new_id("shot")
        if not self.settings.get_bool("automation.screenshots_enabled", True):
            return ScreenSnapshot(id=snap_id, timestamp=ts, source="disabled")

        image_png: bytes | None = None
        if not self._synthetic:
            try:
                if region and self._grabshot_region_fn:
                    image_png = self._grabshot_region_fn(region)
                elif self._grabshot_fn:
                    image_png = self._grabshot_fn()
            except Exception:
                image_png = None

        if image_png is None:
            image_png = self._synthetic_png()

        width, height = self._size_of(image_png)
        text = self._text_extractor.extract(image_png)
        active = self.active_window()

        snap = ScreenSnapshot(id=snap_id, timestamp=ts, image_png=image_png,
                              width=width, height=height, text=text,
                              active_window=active, source="synthetic" if self._synthetic else "os")
        self._history[snap_id] = snap
        return snap

    async def capture_async(self, region: tuple | None = None) -> ScreenSnapshot:
        return self.screenshot(region)

    def _synthetic_png(self) -> bytes:
        """Deterministic placeholder frame (used when capture is impossible)."""
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (1280, 720), (22, 26, 34))
            d = ImageDraw.Draw(img)
            d.text((20, 20), "NOVA synthetic frame (no display)", fill=(90, 200, 250))
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return buf.getvalue()
        except Exception:
            return b""

    @staticmethod
    def _size_of(png: bytes) -> tuple[int, int]:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(png)) as im:
                return im.size
        except Exception:
            return (0, 0)

    def save(self, snap: ScreenSnapshot, directory: Path | None = None) -> Path:
        directory = directory or self.settings.screenshots_dir
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"nova-{snap.id}.png"
        if snap.image_png:
            path.write_bytes(snap.image_png)
        snap.path = str(path)
        return path

    # -- active window --------------------------------------------------
    def active_window(self) -> WindowInfo | None:
        if _IS_WINDOWS:
            return self._active_window_win32()
        return None

    def _active_window_win32(self) -> WindowInfo | None:  # pragma: no cover
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            return WindowInfo(
                title=buf.value, class_name=class_buf.value,
                pid=int(pid.value),
                bounds={"left": rect.left, "top": rect.top,
                        "right": rect.right, "bottom": rect.bottom})
        except Exception:
            return None

    def list_processes(self) -> list[dict]:
        """Lightweight process listing (psutil when available)."""
        try:
            import psutil  # type: ignore
            out = []
            for p in psutil.process_iter(["pid", "name", "exe", "create_time"]):
                try:
                    info = p.info
                except psutil.Error:  # process vanished mid-iteration
                    continue
                out.append({"pid": info["pid"], "name": info.get("name") or "",
                            "exe": info.get("exe") or ""})
            out.sort(key=lambda d: (d["name"].lower(), d["pid"]))
            return out
        except Exception:
            return self._list_processes_posix()

    def _list_processes_posix(self) -> list[dict]:
        import subprocess
        try:
            data = subprocess.run(["ps", "-eo", "pid,comm"],
                                  capture_output=True, text=True, timeout=5,
                                  check=False)
            out = []
            for line in data.stdout.splitlines()[1:]:
                parts = line.split(None, 1)
                if len(parts) == 2:
                    out.append({"pid": int(parts[0]), "name": parts[1], "exe": ""})
            return out
        except Exception:
            return []

    # -- verification / change detection --------------------------------
    def compare(self, before: ScreenSnapshot, after: ScreenSnapshot) -> dict:
        if before.image_png is None or after.image_png is None:
            return {"changed": None, "reason": "missing frames"}
        changed = before.fingerprint() != after.fingerprint()
        result: dict = {"changed": changed, "same_fingerprint": not changed}
        if changed:
            result["reason"] = "visual difference detected"
        return result

    def verify_noop(self, before: ScreenSnapshot, after: ScreenSnapshot) -> bool:
        return not self.compare(before, after).get("changed", True)

    def snapshot_dict(self) -> dict:
        return {"history": [s.as_dict() for s in list(self._history.values())[-20:]]}

    # -- convenience for tools ------------------------------------------
    def describe_state(self) -> dict:
        """Human+LLM readable description of the current screen."""
        snap = self.screenshot()
        desc = {
            "active_window": snap.active_window.as_dict() if snap.active_window else None,
            "screen_size": f"{snap.width}x{snap.height}",
            "ocr_text_sample": snap.text[:1500] if snap.text else "",
            "captured_at": snap.timestamp,
            "screenshot_id": snap.id,
        }
        return desc
