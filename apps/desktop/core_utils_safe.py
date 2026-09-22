"""Tiny helpers duplicated from the backend so the desktop app can run even if
it is launched from a different working directory than the backend package."""


def parse_hotkey(value: str) -> list[str]:
    if not value:
        return []
    tokens = [t.strip().lower() for t in value.split("+") if t.strip()]
    aliases = {"control": "ctrl", "cmd": "ctrl", "win": "meta", "super": "meta"}
    return sorted({aliases.get(t, t) for t in tokens})
