"""computer.* — mouse, keyboard, window, clipboard tools (spec §5, §6)."""
from __future__ import annotations

from pydantic import BaseModel, Field
from tools._platform import Computer
from tools.base import PermissionLevel, Tool, ToolResult


# ---------------------------------------------------------------------------
# input models
# ---------------------------------------------------------------------------
class _XY(BaseModel):
    x: int
    y: int


class MoveIn(_XY):
    pass


class ClickIn(BaseModel):
    x: int | None = None
    y: int | None = None
    button: str = "left"


class DoubleClickIn(_XY):
    pass


class RightClickIn(BaseModel):
    x: int | None = None
    y: int | None = None


class DragIn(BaseModel):
    x1: int; y1: int; x2: int; y2: int
    duration: float = 0.5


class PressIn(BaseModel):
    keys: list[str] = Field(..., description="single-key presses in order")


class TypeIn(BaseModel):
    text: str = Field(..., min_length=1)
    interval: float = 0.02


class HotkeyIn(BaseModel):
    keys: list[str] = Field(..., description="simultaneous modifier+key combo")


class ScrollIn(BaseModel):
    clicks: int = Field(..., description="negative scrolls down")


class ScreenshotIn(BaseModel):
    path: str | None = None


class WindowTarget(BaseModel):
    title_substring: str = ""
    window_id: str = ""


class ActivateIn(WindowTarget):
    pass


class MinimizeIn(WindowTarget):
    pass


class MaximizeIn(WindowTarget):
    pass


class CloseIn(WindowTarget):
    pass


class LaunchIn(BaseModel):
    command: str = Field(..., min_length=1)


class ClipboardWriteIn(BaseModel):
    text: str


class _ComputerTool(Tool):
    _abstract = True  # never registered as a concrete tool
    category = "computer"
    permission = PermissionLevel.LOW
    backend_name = "auto"

    @property
    def _computer(self) -> Computer:
        cached = getattr(self.ctx, "_computer", None)
        if cached is None:
            cached = Computer(self.backend_name)
            self.ctx._computer = cached
        return cached


class MoveTool(_ComputerTool):
    name = "computer.move"
    description = "Move the mouse pointer to absolute screen coordinates (x, y)."
    input_model = MoveIn
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.move(args.x, args.y))


class ClickTool(_ComputerTool):
    name = "computer.click"
    description = "Left/right click at coordinates (or current position if omitted)."
    input_model = ClickIn
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.click(args.x, args.y, args.button))


class DoubleClickTool(_ComputerTool):
    name = "computer.double_click"
    description = "Double-click at coordinates."
    input_model = DoubleClickIn
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.double_click(args.x, args.y))


class RightClickTool(_ComputerTool):
    name = "computer.right_click"
    description = "Right-click at coordinates (or current position)."
    input_model = RightClickIn
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.right_click(args.x, args.y))


class DragTool(_ComputerTool):
    name = "computer.drag"
    description = "Drag from (x1,y1) to (x2,y2)."
    input_model = DragIn
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.drag(args.x1, args.y1, args.x2, args.y2, args.duration))


class PressTool(_ComputerTool):
    name = "computer.press"
    description = "Press individual keys in sequence (e.g. ['enter'], ['a'])."
    input_model = PressIn
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.press(args.keys))


class TypeTool(_ComputerTool):
    name = "computer.type"
    description = "Type a text string as keyboard input."
    input_model = TypeIn
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.type_text(args.text, args.interval))


class HotkeyTool(_ComputerTool):
    name = "computer.hotkey"
    description = "Press a key combination simultaneously (e.g. ['ctrl','c'], ['alt','tab'])."
    input_model = HotkeyIn
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.hotkey(args.keys))


class ScrollTool(_ComputerTool):
    name = "computer.scroll"
    description = "Scroll the mouse wheel; positive scrolls up, negative down."
    input_model = ScrollIn
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.scroll(args.clicks))


class ScreenshotTool(_ComputerTool):
    name = "computer.screenshot"
    description = "Capture the full screen to a PNG file."
    input_model = ScreenshotIn
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        if self.ctx.settings.get_bool("automation.screenshots_enabled", True) is False:
            return ToolResult.fail("Screenshots disabled in privacy settings", "DISABLED")
        path = args.path or str(self.ctx.settings.screenshots_dir / "capture.png")
        return ToolResult.ok(self._computer.screenshot(path))


class ActiveWindowTool(_ComputerTool):
    name = "computer.active_window"
    description = "Return the title of the currently focused window."
    input_model = None
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.active_window())


class ListWindowsTool(_ComputerTool):
    name = "computer.list_windows"
    description = "List all visible top-level windows with titles."
    input_model = None
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.list_windows())


class ActivateWindowTool(_ComputerTool):
    name = "computer.activate_window"
    description = "Bring a window to front by title substring."
    input_model = ActivateIn
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.activate_window(args.title_substring, args.window_id))


class MinimizeWindowTool(_ComputerTool):
    name = "computer.minimize_window"
    description = "Minimize a window by title substring."
    input_model = MinimizeIn
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.minimize_window(args.title_substring))


class MaximizeWindowTool(_ComputerTool):
    name = "computer.maximize_window"
    description = "Maximize a window by title substring."
    input_model = MaximizeIn
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.maximize_window(args.title_substring))


class LaunchAppTool(_ComputerTool):
    name = "computer.launch_app"
    description = "Launch an application by name or command (e.g. 'notepad', 'explorer')."
    input_model = LaunchIn
    permission = PermissionLevel.LOW
    timeout = 20

    async def run(self, args, task_id=None) -> ToolResult:
        # route through the controlled command layer so dangerous launches are blocked
        from core.exceptions import ExecutionBlocked
        from core.shell import shell as default_shell
        try:
            verdict = default_shell.inspect(args.command)
            if not verdict.allowed:
                raise ExecutionBlocked(default_shell.detector.block_message(verdict),
                                       details=verdict.as_dict())
        except ExecutionBlocked as exc:
            return ToolResult.fail(exc.message, "EXECUTION_BLOCKED", data=exc.details)
        return ToolResult.ok(self._computer.launch(args.command))


class CloseAppTool(_ComputerTool):
    name = "computer.close_app"
    description = "Close an application window by title substring."
    input_model = CloseIn
    permission = PermissionLevel.MEDIUM
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.close_app(args.title_substring, args.window_id))


class ClipboardReadTool(_ComputerTool):
    name = "computer.clipboard_read"
    description = "Read the current clipboard text."
    input_model = None
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.clipboard_read())


class ClipboardWriteTool(_ComputerTool):
    name = "computer.clipboard_write"
    description = "Write text to the clipboard."
    input_model = ClipboardWriteIn
    permission = PermissionLevel.LOW
    timeout = 5

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok(self._computer.clipboard_write(args.text))


class EmergencyStopTool(_ComputerTool):
    name = "computer.emergency_stop"
    description = "Immediately stop all agent activity (global emergency stop)."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 5
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        # Cancel current task here; the API-level stop is the primary path.
        return ToolResult.ok({"stopped": True})


class LockSessionTool(_ComputerTool):
    name = "system.lock"
    description = "Lock the workstation session."
    input_model = None
    permission = PermissionLevel.HIGH
    requires_confirmation = True
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        import asyncio
        import platform
        import subprocess

        def _lock() -> None:
            if platform.system() == "Windows":
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"],
                               timeout=10, check=False)
            elif platform.system() == "Darwin":
                subprocess.run(["pmset", "displaysleepnow"], timeout=10, check=False)
            else:
                subprocess.run(["loginctl", "lock-session"], timeout=10, check=False)

        try:
            # subprocess runs in a worker thread so the asyncio loop never blocks
            await asyncio.to_thread(_lock)
            return ToolResult.ok({"locked": True})
        except Exception as exc:
            return ToolResult.fail(str(exc), "SYSTEM_ERROR")


# export list used by tests
ALL_COMPUTER_TOOLS = [
    MoveTool, ClickTool, DoubleClickTool, RightClickTool, DragTool, PressTool,
    TypeTool, HotkeyTool, ScrollTool, ScreenshotTool, ActiveWindowTool,
    ListWindowsTool, ActivateWindowTool, MinimizeWindowTool, MaximizeWindowTool,
    LaunchAppTool, CloseAppTool, ClipboardReadTool, ClipboardWriteTool,
    EmergencyStopTool, LockSessionTool,
]
