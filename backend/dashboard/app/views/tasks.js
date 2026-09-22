/**
 * Tasks — filterable history + detail modal (plan, steps, result).
 */
import { api } from "../api.js";
import { el, icon, statusChip, toast, modal, fmtTime, emptyState, kv } from "../components.js";

const FILTERS = ["", "queued", "executing", "paused", "waiting_confirmation", "completed", "failed", "cancelled"];
let current = "";

export function render(mount) {
  mount.append(
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, "Task History"),
        el("p", {}, "Every command NOVA has run, with its plan, steps and outcome. " +
                    "Click a row for the full record.")),
      el("div", { class: "row" },
        FILTERS.map((f) => el("button", {
          class: `btn small ${f === current ? "primary" : "ghost"}`,
          onClick: () => { current = f; rerender(mount); },
        }, f || "all")))),
    el("div", { class: "card", id: "tasks-body" }, el("div", { class: "spinner" })));
  load();
}

export function destroy() {}

function rerender(mount) {
  mount.replaceChildren();
  render(mount);
}

async function load() {
  const body = document.getElementById("tasks-body");
  try {
    const res = await api.tasks(120, current || undefined);
    const rows = res.tasks || [];
    if (!rows.length) {
      body.replaceChildren(emptyState("🗂", current ? `No ${current} tasks.` : "No tasks yet."));
      return;
    }
    body.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "Task"), el("th", {}, "Command"), el("th", {}, "Status"),
        el("th", {}, "Result"), el("th", {}, "Created"))),
      el("tbody", {}, rows.map((t) => el("tr", {
        class: "clickable",
        onClick: () => openDetail(t.id),
      },
        el("td", { class: "mono" }, t.id),
        el("td", { style: "max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" },
          t.command),
        el("td", {}, statusChip(t.status)),
        el("td", { style: "max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)" },
          t.result || t.error || "—"),
        el("td", { style: "color:var(--faint)" }, fmtTime(t.created_at)))))));
  } catch (err) {
    body.replaceChildren(emptyState("✗", err.message));
  }
}

async function openDetail(id) {
  let rec;
  try { rec = (await api.task(id)).task; }
  catch (err) { toast(err.message, "err"); return; }

  const steps = (rec.steps || []).map((s) => el("div", { class: "tl-body" },
    el("div", { class: `tl-item ${s.status === "completed" ? "done" : s.status === "failed" ? "failed" : ""}` },
      el("div", { class: "tl-title", style: "display:flex;gap:8px;align-items:center" },
        el("span", { class: "mono" }, `#${s.seq}`), s.tool, statusChip(s.status)),
      el("div", { class: "tl-meta" },
        `${s.attempts || 1} attempt(s)${s.duration_ms ? ` · ${s.duration_ms} ms` : ""}`),
      s.error ? el("pre", { class: "code" }, s.error) : null,
      s.output && Object.keys(s.output).length
        ? el("pre", { class: "code" }, JSON.stringify(s.output, null, 2)) : null)));

  const body = el("div", {},
    el("p", { style: "margin:0 0 12px;color:var(--muted)" }, rec.command),
    kv("Status", rec.status), kv("Created", fmtTime(rec.created_at)),
    kv("Started", fmtTime(rec.started_at)), kv("Finished", fmtTime(rec.finished_at)),
    rec.result ? kv("Result", rec.result) : null,
    rec.error ? kv("Error", rec.error) : null,
    rec.files_changed?.length ? kv("Files", rec.files_changed.join(", ")) : null,
    el("h3", { style: "margin:16px 0 6px;font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.09em" },
      `Steps (${(rec.steps || []).length})`),
    el("div", { class: "timeline" }, steps.length ? steps : "—"));

  const actions = [];
  const running = ["executing", "queued", "waiting_confirmation",
                   "verifying", "planning"].includes(rec.status);
  if (running) {
    actions.push({ label: rec.status === "paused" ? "Resume" : "Pause",
      kind: "ghost",
      fn: async () => {
        try {
          if (rec.status === "paused") { await api.resumeTask(rec.id); toast("Task resumed", "ok"); }
          else { await api.pauseTask(rec.id); toast("Task paused", "warn"); }
        } catch (err) { toast(err.message, "err"); }
      } });
  }
  if (!["completed", "failed", "cancelled"].includes(rec.status)) {
    actions.push({ label: "Cancel task", kind: "danger",
      fn: async () => {
        try { await api.cancelTask(rec.id); toast("Task cancelled", "warn"); }
        catch (err) { toast(err.message, "err"); }
      } });
  }
  modal(`Task ${rec.id}`, body, actions);
}

export default { render, destroy };
