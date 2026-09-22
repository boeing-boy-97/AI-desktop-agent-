// NOVA Companion — content script.
// Listens for messages from the popup/background and gathers page context.

(() => {
  function selectedText() {
    return window.getSelection ? window.getSelection().toString() : "";
  }

  function pageContext() {
    return {
      title: document.title,
      url: location.href,
      selection: selectedText(),
      text: (document.body ? document.body.innerText : "").slice(0, 8000)
    };
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg) return;
    if (msg.action === "get_context") {
      sendResponse(pageContext());
    } else if (msg.action === "get_selection") {
      sendResponse({ selection: selectedText() });
    }
    return true;
  });

  // Expose a lightweight hook for extension pages that inject script here.
  window.__NOVA_CONTEXT__ = pageContext;
})();
