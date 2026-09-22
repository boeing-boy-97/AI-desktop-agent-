# NOVA Companion — permissions rationale

- `activeTab` — read the current page context only when the user clicks a NOVA action.
- `scripting`  — execute small read/click helpers on the active tab on demand.
- `storage`    — persist the extension's connection state locally.
- `contextMenus` — add "Send selection/page to NOVA" menu items.
- Host permission for `http://127.0.0.1:8765/*` — the **local only** NOVA API.
  No remote hosts are contacted; data never leaves the machine through this extension.

The extension is a companion: it does not operate the browser on its own. All
automation intent originates from the desktop agent over the local bridge.
