// NOVA Companion popup logic.
const API = "http://127.0.0.1:8765";

function setStatus(text) {
  document.getElementById("status").textContent = text;
}

document.getElementById("send-page").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.runtime.sendMessage({
    target: "nova",
    payload: { type: "page", url: tab.url, title: tab.title }
  });
  setStatus("Page sent to NOVA ✓");
});

document.getElementById("send-selection").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => window.getSelection().toString()
  });
  const text = results && results[0] ? results[0].result : "";
  chrome.runtime.sendMessage({
    target: "nova",
    payload: { type: "selection", text, url: tab.url, title: tab.title }
  });
  setStatus(text ? "Selection sent to NOVA ✓" : "No selection found.");
});

document.getElementById("open-agent").addEventListener("click", () => {
  // tell the desktop app to show its command panel via the local API
  fetch(`${API}/api/companion/command-panel`, { method: "POST" })
    .then(() => setStatus("Command panel requested."))
    .catch(() => setStatus("Backend offline — start NOVA first."));
});
