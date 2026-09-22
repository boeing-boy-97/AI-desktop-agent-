/**
 * Tiny reactive store — single source of truth for shared app state.
 * Views subscribe; SSE events and API responses mutate it through set().
 */

const listeners = new Set();

export const store = {
  status: null,              // /api/system/status
  confirmations: [],         // pending confirmation gates
  events: [],                // recent agent events (newest first)
  activeTask: null,          // task record currently tracked in the console
  connected: false,          // SSE link state
};

export function set(patch) {
  Object.assign(store, patch);
  for (const fn of listeners) {
    try { fn(patch); } catch (err) { console.error("store listener", err); }
  }
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Push a live event into the ring buffer (keeps the newest 200). */
export function pushEvent(evt) {
  const events = [evt, ...store.events].slice(0, 200);
  set({ events });
}
