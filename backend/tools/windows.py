"""windows.* — Windows control tools (spec §6): settings, snap, volume, brightness.

On non-Windows platforms these return structured "not available" results rather
than raising, so the agent can recover gracefully.
"""
from __future__ import annotations

import asyncio
import platform
import subprocess
from typing import ClassVar

from tools.base import PermissionLevel, Tool, ToolResult

_IS_WINDOWS = platform.system() == "Windows"


async def _run(*argv: str, timeout: float = 10.0,
               text: bool = False) -> subprocess.CompletedProcess:
    """Run an external command in a worker thread (never blocks the loop)."""
    return await asyncio.to_thread(
        subprocess.run, list(argv), capture_output=True, text=text,
        timeout=timeout, check=False)



class _WindowsTool(Tool):
    _abstract = True
    category = "windows"


class OpenSettingsTool(_WindowsTool):
    name = "windows.open_settings"
    description = "Open a Windows Settings page (e.g. 'settings', 'network', 'system')."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 15

    _PAGES: ClassVar[dict[str, str]] = {
        "": "ms-settings:",
        "settings": "ms-settings:",
        "system": "ms-settings:system",
        "display": "ms-settings:display",
        "network": "ms-settings:network",
        "wifi": "ms-settings:network-wifi",
        "bluetooth": "ms-settings:bluetooth",
        "privacy": "ms-settings:privacy",
        "microphone": "ms-settings:privacy-microphone",
        "sound": "ms-settings:sound",
        "apps": "ms-settings:appsfeatures",
    }

    async def run(self, args, task_id=None) -> ToolResult:
        page = (args or {}).get("page", "settings")
        uri = self._PAGES.get(page, "ms-settings:")
        if not _IS_WINDOWS:
            return ToolResult.ok({"opened": False, "reason": "Windows-only tool",
                                  "page": page})
        try:
            await asyncio.create_subprocess_exec("cmd", "/c", "start", "", uri)
            return ToolResult.ok({"opened": True, "uri": uri})
        except OSError as exc:
            return ToolResult.fail(str(exc), "IO_ERROR")


class SnapWindowTool(_WindowsTool):
    name = "windows.snap"
    description = "Snap the active window using Win+Arrow (direction: left|right|up|down)."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        direction = (args or {}).get("direction", "left")
        key = {"left": "left", "right": "right", "up": "up", "down": "down"}.get(direction)
        if not key:
            return ToolResult.fail(f"invalid direction {direction!r}", "INVALID_ARGS")
        if not _IS_WINDOWS:
            return ToolResult.ok({"snapped": False, "reason": "Windows-only"})
        try:
            await _run("powershell", "-NoProfile", "-Command",
                       "$w = New-Object -ComObject WScript.Shell; "
                       f"$w.SendKeys('#{{{key.upper()}}}')")
        except Exception as exc:
            return ToolResult.ok({"snapped": False, "reason": str(exc)})
        return ToolResult.ok({"snapped": direction})


class SystemVolumeTool(_WindowsTool):
    name = "system.volume"
    description = "Set or mute system volume (0-100 or 'mute'/'unmute'). Requires privilege."
    input_model = None
    permission = PermissionLevel.MEDIUM
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        args = args or {}
        action = args.get("action", "get")
        if not _IS_WINDOWS:
            return ToolResult.ok({"volume": None, "reason": "Windows-only tool"})

        # 1. pycaw path (full volume control when installed)
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            if action == "mute":
                volume.SetMute(1, None)
                return ToolResult.ok({"volume": "muted"})
            if action == "unmute":
                volume.SetMute(0, None)
                return ToolResult.ok({"volume": "unmuted"})
            if action in ("set",) and args.get("level") is not None:
                level = max(0.0, min(1.0, float(args["level"]) / 100.0))
                volume.SetMasterVolumeLevelScalar(level, None)
                return ToolResult.ok({"volume": int(level * 100)})
            if action == "toggle_mute":
                muted = volume.GetMute()
                volume.SetMute(0 if muted else 1, None)
                return ToolResult.ok({"volume": "unmuted" if muted else "muted"})
            return ToolResult.ok({"volume": int(volume.GetMasterVolumeLevelScalar() * 100)})
        except Exception:
            # 2. PowerShell SendKeys fallback (coarse +/- only)
            try:
                if action in ("up", "inc"):
                    await _run("powershell", "-NoProfile", "-Command",
                               "$w = New-Object -ComObject WScript.Shell; "
                               "$w.SendKeys([char]175)")
                    return ToolResult.ok({"volume": "up"})
                if action in ("down", "dec"):
                    await _run("powershell", "-NoProfile", "-Command",
                               "$w = New-Object -ComObject WScript.Shell; "
                               "$w.SendKeys([char]174)")
                    return ToolResult.ok({"volume": "down"})
            except Exception:
                pass
            return ToolResult.ok({
                "volume": None,
                "note": "Volume control requires the optional 'pycaw' package "
                        "(documented platform limitation). Supported actions: "
                        "get/set/mute/unmute/up/down.",
            })


class SystemBrightnessTool(_WindowsTool):
    name = "system.brightness"
    description = "Adjust screen brightness (Windows: requires pywinauto/powershell)."
    input_model = None
    permission = PermissionLevel.MEDIUM
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        if not _IS_WINDOWS:
            return ToolResult.ok({"brightness": None, "reason": "Windows-only tool"})
        try:
            level = (args or {}).get("level")
            if level is None:
                try:
                    out = await _run(
                        "powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "(Get-CimInstance -Namespace root/WMI -ClassName "
                        "WmiMonitorBrightness).CurrentBrightness",
                        text=True)
                    value = out.stdout.strip()
                    if not value or not value.lstrip("-").isdigit():
                        return ToolResult.ok({"brightness": None,
                                              "reason": "brightness query returned no value"})
                    return ToolResult.ok({"brightness": int(value)})
                except (ValueError, OSError):
                    return ToolResult.ok({"brightness": None,
                                          "reason": "brightness query unsupported"})
            await _run(
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance -Namespace root/WMI -ClassName "
                f"WmiMonitorBrightnessMethods).WmiSetBrightness(1,{int(level)})")
            return ToolResult.ok({"brightness": int(level)})
        except Exception as exc:
            return ToolResult.fail(str(exc), "SYSTEM_ERROR")


class RestartComputerTool(_WindowsTool):
    name = "system.restart"
    description = "Restart the computer. HIGH RISK — always requires confirmation."
    input_model = None
    permission = PermissionLevel.HIGH
    requires_confirmation = True
    confirm_message_tpl = "Restart the computer now?"
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        delay = (args or {}).get("delay_seconds", 30)
        if not _IS_WINDOWS:
            return ToolResult.ok({"scheduled": False, "reason": "Windows-only tool"})
        try:
            await _run("shutdown", "/r", "/t", str(int(delay)))
            return ToolResult.ok({"scheduled": True, "delay_seconds": int(delay)})
        except Exception as exc:
            return ToolResult.fail(str(exc), "SYSTEM_ERROR")


class ShutdownComputerTool(_WindowsTool):
    name = "system.shutdown"
    description = "Shut down the computer. HIGH RISK — always requires confirmation."
    input_model = None
    permission = PermissionLevel.HIGH
    requires_confirmation = True
    confirm_message_tpl = "Shut down the computer now?"
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        delay = (args or {}).get("delay_seconds", 30)
        if not _IS_WINDOWS:
            return ToolResult.ok({"scheduled": False, "reason": "Windows-only tool"})
        try:
            await _run("shutdown", "/s", "/t", str(int(delay)))
            return ToolResult.ok({"scheduled": True, "delay_seconds": int(delay)})
        except Exception as exc:
            return ToolResult.fail(str(exc), "SYSTEM_ERROR")
