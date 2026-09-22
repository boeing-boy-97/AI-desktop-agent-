"""Backend API client used by the desktop UI.

Talks to the local NOVA FastAPI server over HTTP + SSE. If the backend is down
the client raises typed errors the UI can surface as a subtle status dot.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable

import httpx


class ApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")
        self._thread = None
        self._stop = threading.Event()
        self.on_event: Callable[[dict], None] | None = None

    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get(self, path: str, **params) -> dict:
        with httpx.Client(timeout=10) as client:
            r = client.get(self._url(path), params=params)
            r.raise_for_status()
            return r.json()

    def post(self, path: str, json_data: dict | None = None, **params) -> dict:
        with httpx.Client(timeout=60) as client:
            r = client.post(self._url(path), json=json_data or {}, params=params)
            r.raise_for_status()
            return r.json()

    def put(self, path: str, json_data: dict) -> dict:
        with httpx.Client(timeout=10) as client:
            r = client.put(self._url(path), json=json_data)
            r.raise_for_status()
            return r.json()

    def delete(self, path: str) -> dict:
        with httpx.Client(timeout=10) as client:
            r = client.delete(self._url(path))
            r.raise_for_status()
            return r.json()

    # ------------------------------------------------------------------
    def status(self) -> dict:
        return self.get("/api/system/status")

    def execute(self, command: str, mode: str = "smart") -> str:
        return self.post("/api/agent/execute",
                         {"command": command, "mode": mode})["task_id"]

    def cancel(self, task_id: str) -> dict:
        return self.post(f"/api/tasks/{task_id}/cancel", {"reason": "user_cancel"})

    def emergency_stop(self) -> dict:
        return self.post("/api/emergency_stop")

    def transcribe(self, audio_b64: str) -> dict:
        return self.post("/api/voice/transcribe", {"audio_base64": audio_b64})

    def resolve_confirmation(self, conf_id: str, approve: bool) -> dict:
        return self.post(f"/api/confirmations/{conf_id}", {"approve": approve})

    def pending_confirmations(self) -> list:
        return self.get("/api/confirmations").get("confirmations", [])

    def diagnostics(self) -> dict:
        return self.get("/api/diagnostics")

    def settings(self) -> dict:
        return self.get("/api/settings")["settings"]

    def update_settings(self, updates: dict) -> dict:
        return self.put("/api/settings", {"updates": updates})

    def task(self, task_id: str) -> dict:
        return self.get(f"/api/tasks/{task_id}")["task"]

    # ------------------------------------------------------------------
    # SSE event stream (background thread → on_event callbacks)
    # ------------------------------------------------------------------
    def start_events(self, on_event: Callable[[dict], None]) -> None:
        self.on_event = on_event
        self._stop.clear()
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()

    def stop_events(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _stream_loop(self) -> None:
        import httpx
        while not self._stop.is_set():
            try:
                with httpx.Client(timeout=None) as client, \
                        client.stream("GET", self._url("/api/events/stream")) as resp:
                    for line in resp.iter_lines():
                        if self._stop.is_set():
                            return
                        if line.startswith("data: "):
                            try:
                                evt = json.loads(line[6:])
                                if self.on_event:
                                    self.on_event(evt)
                            except Exception:
                                pass
            except Exception:
                pass
            self._stop.wait(2.0)
