// NOVA Companion — Manifest V3 service worker.
// Bridges the desktop agent (localhost API) and the active browser tab.

const API = "http://127.0.0.1:8765";

// Keep a connection-id so the desktop agent can distinguish this browser.
let connectionId = null;

async function registerConnection() {
  try {
    const resp = await fetch(`${API}/api/companion/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tab: 0, user_agent: navigator.userAgent })
    });
    const data = await resp.json();
    connectionId = data.connection_id;
  } catch (e) {
    console.warn("[NOVA] backend not reachable", e);
  }
}

registry_fencing(registerConnection);

chrome.runtime.onInstalled.addListener(() => {
  registerConnection();
  chrome.contextMenus.create({
    id: "nova-send-selection",
    title: "Send selection to NOVA",
    contexts: ["selection"]
  });
  chrome.contextMenus.create({
    id: "nova-send-page",
    title: "Send this page to NOVA",
    contexts: ["page"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "nova-send-selection") {
    postToNova({
      type: "selection",
      text: info.selectionText,
      url: tab.url,
      title: tab.title
    });
  } else if (info.menuItemId === "nova-send-page") {
    const page = await getPageContext(tab);
    postToNova({ type: "page", ...page });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.target === "nova") {
    postToNova(msg.payload || {});
    sendResponse({ ok: true });
  }
  return true;
});

// Background loop (fires every ~10s) — polls for automation commands.
async function pollCommands() {
  if (!connectionId) return;
  try {
    const r = await fetch(`${API}/api/companion/${connectionId}/commands`);
    if (!r.ok) return;
    const data = await r.json();
    for (const cmd of data.commands || []) {
      await dispatch(cmd);
    }
  } catch (e) {
    /* backend offline */
  }
}

async function dispatch(cmd) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  switch (cmd.action) {
    case "navigate":
      if (tab && cmd.url) chrome.tabs.update(tab.id, { url: cmd.url });
      break;
    case "read_text":
    case "get_context":
      const page = await getPageContext(tab);
      postToNova({ type: "page_context", ...page, request_id: cmd.request_id });
      break;
    case "click":
      if (tab) chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => { const el = document.querySelector(sel); if (el) el.click(); },
        args: [cmd.selector]
      });
      break;
    case "fill":
      if (tab) chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel, val) => {
          const el = document.querySelector(sel);
          if (el) { el.value = val; el.dispatchEvent(new Event("input", { bubbles: true })); }
        },
        args: [cmd.selector, cmd.value]
      });
      break;
    default:
      console.warn("[NOVA] unknown command", cmd.action);
  }
}

async function getPageContext(tab) {
  let text = "";
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({ text: document.body ? document.body.innerText.slice(0, 8000) : "", title: document.title })
    });
    if (results && results[0] && results[0].result) text = results[0].result.text;
  } catch (e) {
    /* restricted page */
  }
  return { url: tab.url, title: tab.title, text };
}

async function postToNova(payload) {
  try {
    await fetch(`${API}/api/companion/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ connection_id: connectionId, payload })
    });
  } catch (e) {
    /* backend offline */
  }
}

// The MV3 environment may not define chrome.runtime in workers under the
// test harness; guard everything behind a helper that no-ops safely.
function registry_fencing(fn) {
  try {
    fn();
  } catch (e) { /* no-op */ }
}

// keep-alive-ish churn
setInterval(() => {
  registry_fencing(registerConnection);
  registry_fencing(pollCommands);
}, 8000);
