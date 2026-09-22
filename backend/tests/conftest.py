"""Shared test fixtures.

An isolated Runtime is created per test with an in-memory SQLite database, the
mock AI/STT/TTS/browser providers and a temporary data directory — so the full
stack (planner → executor → permissions → tools → DB) runs offline.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(__file__) + "/..")

from runtime import Runtime


@pytest.fixture()
def runtime():
    tmp = tempfile.mkdtemp(prefix="nova-test-")
    rt = Runtime(for_testing=True, force_heuristic=True)
    rt.settings.load({"storage.data_dir": tmp})
    yield rt
    rt.shutdown()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def allow_all(runtime):
    """Session rules that auto-allow the most common tests' tools."""
    for tool in ("filesystem.create_folder", "filesystem.write_file",
                 "filesystem.read_file", "filesystem.list", "filesystem.move",
                 "filesystem.copy", "filesystem.rename", "filesystem.search",
                 "filesystem.metadata", "shell.run", "shell.run_argv",
                 "computer.launch_app", "computer.screenshot",
                 "computer.active_window", "computer.list_windows",
                 "filesystem.largest", "filesystem.find_duplicates",
                 "process.list", "process.detect", "web.search", "web.fetch",
                 "browser.open", "browser.read_text", "browser.search",
                 "memory.remember", "memory.recall", "memory.list",
                 "filesystem.open", "filesystem.reveal"):
        runtime.permissions.set_session_rule(tool, "allow")
    return runtime
