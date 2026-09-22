/**
 * Shared UI building blocks. Everything is plain DOM — no framework —
 * so the app has zero dependencies and loads instantly.
 */

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (v !== null && v !== undefined && v !== false) {
      node.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(child));
  }
  return node;
}

/* icons (inline SVG, stroke style) -------------------------------------- */
const PATHS = {
  console: "M4 17l6-5-6-5M12 19h8",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  tasks: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4",
  tools: "M14.7 6.3a4 4 0 00-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 005.4-5.4L15 12l-3-3 2.7-2.7z",
  memory: "M12 8c-2.2 0-4 1.3-4 3s1.8 3 4 3 4 1.3 4 3-1.8 3-4 3m0-12c2.2 0 4-1.3 4-3M12 2v2m0 16v2m-7-9H3m18 0h-2",
  flows: "M4 6h4v4H4zM16 6h4v4h-4zM10 14h4v4h-4zM8 10v2h8v-2",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zm7.4-3a7.4 7.4 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7.5 7.5 0 00-2-1.2L14.5 3h-5l-.4 2.6a7.5 7.5 0 00-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 000 2.4l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 002 1.2l.4 2.6h5l.4-2.6a7.5 7.5 0 002-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z",
  pulse: "M3 12h4l2-7 4 14 2-7h6",
  stop: "M12 2a10 10 0 100 20 10 10 0 000-20zm-3 7h6v6H9z",
  send: "M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z",
  search: "M21 21l-4.3-4.3M17 10.5a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z",
  trash: "M3 6h18M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6",
  x: "M18 6L6 18M6 6l12 12",
  check: "M20 6L9 17l-5-5",
};

export function icon(name, size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", PATHS[name] || PATHS.grid);
  svg.append(p);
  return svg;
}

/* status helpers --------------------------------------------------------- */
const STATUS_CHIP = {
  completed: ["ok", "completed"],
  failed: ["err", "failed"],
  cancelled: ["warn", "cancelled"],
  executing: ["grad", "executing"],
  planning: ["grad", "planning"],
  queued: ["muted", "queued"],
  waiting_confirmation: ["warn", "waiting"],
  verifying: ["grad", "verifying"],
  recovering: ["warn", "recovering"],
  speaking: ["grad", "speaking"],
  paused: ["warn", "paused"],
};

export function statusChip(status) {
  const [cls, label] = STATUS_CHIP[status] || ["muted", status || "?"];
  return el("span", { class: `chip ${cls}` }, label);
}

export function riskChip(level) {
  return el("span", { class: `chip risk-${level || "low"}` }, (level || "low").toUpperCase());
}

/* toasts ------------------------------------------------------------------ */
export function toast(message, kind = "info", ms = 3800) {
  let host = document.getElementById("toasts");
  if (!host) { host = el("div", { id: "toasts" }); document.body.append(host); }
  const t = el("div", { class: `toast ${kind}` }, message);
  host.append(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, ms - 300);
  setTimeout(() => t.remove(), ms);
}

/* modal ------------------------------------------------------------------- */
export function modal(title, bodyNode, actions = []) {
  const back = el("div", { class: "modal-back" });
  const close = () => back.remove();
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  const box = el("div", { class: "modal" },
    el("h2", {}, title),
    bodyNode,
    el("div", { class: "row", style: "margin-top:16px; justify-content:flex-end" },
      actions.map((a) => el("button", { class: `btn ${a.kind || ""}`, onClick: () => { a.fn?.(); close(); } }, a.label)),
      el("button", { class: "btn ghost", onClick: close }, "Close")));
  back.append(box);
  document.body.append(back);
  return close;
}

/* empty state ------------------------------------------------------------- */
export function emptyState(glyph, text) {
  return el("div", { class: "empty" }, el("div", { class: "glyph" }, glyph), text);
}

/* key/value row ------------------------------------------------------------ */
export function kv(k, v) {
  return el("div", { class: "kv" },
    el("span", { class: "k" }, k),
    el("span", { class: "v" }, v ?? "—"));
}

export function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString(); } catch { return iso; }
}

export function fmtAgo(iso) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
