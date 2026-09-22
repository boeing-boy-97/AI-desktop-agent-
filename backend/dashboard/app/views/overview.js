/**
 * Overview — system pulse: status cards, live event feed, emergency stop.
 */
import { api } from "../api.js";
import { store, subscribe, set } from "../store.js";
import { el, icon, statusChip, toast, fmtTime, emptyState } from "../components.js";

let timer = null;

export function render(mount) {
  mount.append(
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, "Overview"),
        el("p", {}, "Live pulse of the NOVA agent — providers, tools, tasks and the raw event stream."))),
    el("div", { class: "grid cols-5", id: "ov-stats" }),
    el("div", { class: "grid cols-2", style: "margin-top:16px" },
      el("div", { class: "card glass" },
        el("h3", {}, "Recent tasks"),
        el("div", { id: "ov-tasks" }, el("div", { class: "spinner" }))),
      el("div", { class: "card glass" },
        el("h3", {}, "Live event stream"),
        el("div", { class: "events", id: "ov-events" },
          emptyState("◉", "Waiting for events…")))));
  refresh();
  timer = setInterval(refresh, 4000);
  subscribe(onStoreChange);
  renderEvents();
}

export function destroy() { if (timer) clearInterval(timer); timer = null; }

async function refresh() {
  try {
    const [status, tasks] = await Promise.all([api.status(), api.tasks(6)]);
    set({ status });
    renderStats(status);
    renderTasks(tasks.tasks || []);
  } catch { /* handled by the SSE watchdog */ }
}

function renderStats(s) {
  const host = document.getElementById("ov-stats");
  if (!host) return;
  const stat = (label, value, sub, grad = false) =>
    el("div", { class: "card stat" },
      el("span", { class: "label" }, label),
      el("span", { class: `value${grad ? " grad" : ""}` }, String(value)),
      sub ? el("span", { class: "sub" }, sub) : null);
  host.replaceChildren(
    stat("Agent state", s.state, s.active_task ? `task ${s.active_task}` : "no active task", true),
    stat("Task queue", s.queued ?? 0, (s.queued ? `${s.queued} waiting for the computer` : "single-flight idle")),
    stat("Tools", s.tool_count, "registered plugins"),
    stat("AI provider", s.ai_provider, `stt ${s.stt_provider} · tts ${s.tts_provider}`),
    stat("Uptime", fmtUptime(s.uptime_seconds), `v${s.version} · ${s.platform}`));
}

function fmtUptime(sec) {
  if (!sec && sec !== 0) return "—";
  const m = Math.floor(sec / 60), h = Math.floor(m / 60);
  if (h) return `${h}h ${m % 60}m`;
  if (m) return `${m}m ${Math.floor(sec % 60)}s`;
  return `${Math.floor(sec)}s`;
}

function renderTasks(rows) {
  const host = document.getElementById("ov-tasks");
  if (!host) return;
  if (!rows.length) { host.replaceChildren(emptyState("🗂", "No tasks yet — try the console.")); return; }
  host.replaceChildren(el("table", {},
    el("tbody", {}, rows.map((t) => el("tr", {},
      el("td", { class: "mono", style: "max-width:120px;overflow:hidden;text-overflow:ellipsis" }, t.id),
      el("td", { style: "max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" }, t.command),
      el("td", {}, statusChip(t.status)))))));
}

function onStoreChange(patch) {
  if (patch.events?.length) renderEvents();
}

function renderEvents() {
  const host = document.getElementById("ov-events");
  if (!host) return;
  if (!store.events.length) return;
  host.replaceChildren(store.events.slice(0, 60).map((e) => {
    const cls = (e.event || "").replace(/\./g, "-");
    const detail = e.data ? Object.entries(e.data)
      .filter(([k]) => !["task_id"].includes(k))
      .map(([k, v]) => `${k}=${typeof v === "object" ? "…" : v}`)
      .join(" ") : "";
    return el("div", { class: `evt ${cls}` },
      el("span", { class: "t" }, fmtTime(e.at)),
      el("span", { class: "n" }, e.event),
      el("span", { class: "d", title: detail }, detail || ""));
  }));
}

export default { render, destroy };
