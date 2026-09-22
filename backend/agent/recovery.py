"""Self-healing execution support (V2 §12): failure classification and
bounded recovery strategy selection.

The TaskManager retry loop calls :func:`classify_failure` after every failed
attempt.  The returned :class:`FailureClassification` names the failure kind
and the strategy the agent applies — this keeps recovery explainable in the
event stream and the dashboard instead of being blind re-execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FailureClassification:
    kind: str                 # stable machine label
    human: str                # actionable human message (§57)
    strategy: str             # what the agent will try next
    retryable: bool = True
    evidence: dict = field(default_factory=dict)


_RULES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    # kind, needles in error text, human, strategy — order matters
    ("app_not_found",
     ("no such app", "unknown application", "application was not found",
      "app was not found", "executable was not found", "is not recognized",
      "cannot find application", "could not find application"),
     "The application could not be found on this computer.",
     "search the installed application catalog for an alias and retry"),
    ("path_missing",
     ("no such file", "does not exist", "not a directory", "no items could",
      "cannot find the path", "enoent", "path does not exist",
      "source not found", "not found: /", "not found: c:", "not found: ~"),
     "The target file or folder does not exist.",
     "search likely directories for the name and retry with the match"),
    ("permission_denied",
     ("permission denied", "access is denied", "access denied", "eacces",
      "operation not permitted", "requires administrator"),
     "The operating system denied the operation.",
     "escalate to the user with an exact explanation (no silent retry)"),
    ("network",
     ("timed out", "timeout", "connection refused", "name resolution",
      "network is unreachable", "temporary failure in name resolution",
      "err_connection", "ssl"),
     "A network request failed.",
     "wait briefly and retry; if persistent, report connectivity problem"),
    ("element_not_found",
     ("element not found", "no element", "selector", "locator",
      "could not find element", "stale element", "not visible"),
     "The UI element was not where the plan expected it.",
     "re-observe the screen/page and re-locate the element semantically"),
    ("build_error",
     ("compile", "syntaxerror", "typeerror", "cannot find module",
      "module not found", "import error", "npm err", "exit code 1",
      "exited 1", "build failed", "traceback"),
     "A build, install or script reported an error.",
     "inspect the command output with the error analyzer and repair"),
    ("locked",
     ("being used by another process", "locked", "resource busy",
      "file is open"),
     "The file is locked by another application.",
     "wait for the lock to clear, then retry"),
)


_LAUNCH_TOOLS = ("computer.launch", "windows.open_app", "vscode.open",
                 "process.launch")


def classify_failure(tool: str, error: str, data: dict | None = None) -> FailureClassification:
    """Classify a failed tool attempt. Pure function — safe to test."""
    text = (error or "").lower()
    data = data or {}

    # tool-aware shortcut: launch failures mentioning "not found" are about
    # the application, not a filesystem path
    if tool.startswith(_LAUNCH_TOOLS) and "not found" in text:
        return FailureClassification(
            kind="app_not_found",
            human="The application could not be found on this computer.",
            strategy="search the installed application catalog for an alias "
                     "and retry",
            evidence={"tool": tool})

    for kind, needles, human, strategy in _RULES:
        if any(n in text for n in needles):
            retryable = kind != "permission_denied"
            return FailureClassification(kind=kind, human=human,
                                         strategy=strategy, retryable=retryable,
                                         evidence={"tool": tool})

    code = str(data.get("returncode") or "")
    if code and code != "0":
        return FailureClassification(
            kind="exit_code",
            human=f"The command exited with code {code}.",
            strategy="inspect stdout/stderr with the error analyzer and repair",
            evidence={"tool": tool, "returncode": code})

    if not (error or "").strip():
        return FailureClassification(
            kind="unknown",
            human=f"{tool} failed without an error message.",
            strategy="retry once, then surface the failure to the user",
            evidence={"tool": tool})

    return FailureClassification(
        kind="unknown",
        human=f"{tool} failed: {error[:180]}",
        strategy="retry once, then surface the failure to the user",
        evidence={"tool": tool})
