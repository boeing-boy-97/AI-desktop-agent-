# NOVA Companion — Chrome extension (Manifest V3)

An **optional companion** for the desktop agent (spec §48). It is **not** the
product's automation core — it shares page context and tab control with NOVA.

## Load in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select this `apps/browser-extension` folder
4. Pin the NOVA icon

## What it does

| Surface            | Capability                                                        |
|--------------------|-------------------------------------------------------------------|
| Popup              | Send current page / selected text to NOVA; open NOVA command panel |
| Context menu       | "Send selection to NOVA" / "Send this page to NOVA"                |
| Background worker  | Polls the local API for tab commands (navigate, read, click, fill) |

## Security

- Communicates only with `http://127.0.0.1:8765` (the local NOVA API).
- No remote hosts; no tracking; page data never leaves the machine.
- MV3 service worker; minimal permissions (activeTab, scripting, storage,
  contextMenus + loopback host permission).

The desktop agent must be running (`python -m backend.main --port 8765`) for
the bridge to work.
