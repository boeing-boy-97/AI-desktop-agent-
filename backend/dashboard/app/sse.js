/**
 * SSE client — subscribes to /api/events/stream with auto-reconnect.
 * The browser retries natively via `retry:` hints, but we also detect a dead
 * link (no event for 25s) and re-establish it so the UI never silently stalls.
 */
import { set, pushEvent } from "./store.js";

let es = null;
let lastBeat = Date.now();
let watchdog = null;

function connect() {
  if (es) es.close();
  es = new EventSource("/api/events/stream");
  es.onopen = () => { lastBeat = Date.now(); set({ connected: true }); };
  es.onmessage = (msg) => {
    lastBeat = Date.now();
    try { pushEvent(JSON.parse(msg.data)); } catch { /* ignore malformed frame */ }
  };
  es.onerror = () => {
    set({ connected: false });
    es.close();
    setTimeout(connect, 1500);   // brief backoff, then retry
  };
}

export function startStream() {
  connect();
  watchdog = setInterval(() => {
    if (Date.now() - lastBeat > 25000) {   // link went quiet — force reconnect
      set({ connected: false });
      connect();
    }
  }, 10000);
}

export function stopStream() {
  if (watchdog) clearInterval(watchdog);
  if (es) es.close();
}
