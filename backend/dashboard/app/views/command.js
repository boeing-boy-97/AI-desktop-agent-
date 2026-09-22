/**
 * Command console — the hero view.
 * Send a natural-language command and watch the agent pipeline live:
 * planning → permission gate → executing → verifying → result.
 */
import { api } from "../api.js";
import { store, subscribe, set } from "../store.js";
import { el, icon, statusChip, riskChip, toast, fmtTime } from "../components.js";

const QUICK = [
  "create a folder called ~/Nova Projects",
  "take a screenshot",
  "open VS Code",
  "what is my largest file",
  "open chrome and search for AI news",
];

let root = null;
let currentTaskId = null;
let pollTimer = null;

export function render(mount) {
  root = el("div", {},
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, "Command Console"),
        el("p", {}, "Talk to NOVA in plain language. Every action passes the permission " +
                    "layer — high-risk operations pause for your approval first."))),
    commandBox(),
    el("div", { class: "grid cols-2", style: "margin-top:16px" },
      el("div", { class: "card glass" },
        el("h3", {}, "Live agent state"),
        el("div", { id: "console-state" }, idleHint())),
      el("div", { class: "card glass" },
        el("h3", {}, "Pending confirmations"),
        el("div", { id: "console-confirms" }, noConfirmations()))));
  mount.append(root);
  renderConfirmations();
  subscribe(onStoreChange);
  refreshConfirmations();
}

export function destroy() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

/* ---------------------------------------------------------------------- */
function idleHint() {
  return el("div", { class: "empty" },
    el("div", { class: "glyph" }, "◉"),
    "Type a command to see NOVA plan, ask, execute and verify.");
}

function noConfirmations() {
  return el("div", { class: "empty" },
    el("div", { class: "glyph" }, "🛡"),
    "No pending confirmations — the safety gate is quiet.");
}

function commandBox() {
  const input = el("textarea", {
    rows: 2,
    placeholder: "Ask NOVA… e.g. “create a file called notes.txt with my meeting notes”",
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });

  async function send() {
    const command = input.value.trim();
    if (!command) return;
    input.value = "";
    try {
      const res = await api.execute(command);
      currentTaskId = res.task_id;
      toast(`Task ${res.task_id} started`, "ok");
      beginPolling();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  return el("div", {},
    el("div", { class: "console" },
      input,
      el("button", { class: "btn primary", onClick: send }, icon("send"), "Send")),
    el("div", { class: "quick-chips" },
      QUICK.map((q) => el("button", {
        class: "btn ghost small",
        onClick: () => { input.value = q; input.focus(); },
      }, q))));
}

/* live state panel ------------------------------------------------------ */
function onStoreChange(patch) {
  if (!root || !root.isConnected) return;
  if (patch.events?.length) renderStateFromEvents();
}

function renderStateFromEvents() {
  const host = document.getElementById("console-state");
  if (!host) return;
  const mine = store.events.filter((e) =>
    !currentTaskId || !e.data?.task_id || e.data.task_id === currentTaskId);
  if (!mine.length) { host.replaceChildren(idleHint()); return; }

  const items = mine.slice(0, 14).map((e) => {
    const name = (e.event || "").replace(/^agent\./, "");
    const cls = name === "completed" ? "done"
      : name === "failed" ? "failed"
      : name === "waiting_confirmation" ? "active" : "done";
    return el("div", { class: `tl-item ${cls}` },
      el("div", { class: "tl-title" }, name.replace(/_/g, " ")),
      el("div", { class: "tl-meta" },
        `${fmtTime(e.at)}${e.data?.tool ? ` · ${e.data.tool}` : ""}${e.data?.step !== undefined ? ` · step ${e.data.step}` : ""}`),
      e.data?.question ? el("div", { class: "tl-body" },
        el("pre", { class: "code" }, e.data.question)) : null);
  });
  host.replaceChildren(el("div", { class: "timeline" }, items.reverse()));
}

/* confirmations ---------------------------------------------------------- */
async function refreshConfirmations() {
  try {
    const res = await api.confirmations();
    set({ confirmations: res.confirmations || [] });
    renderConfirmations();
  } catch { /* backend briefly unreachable — SSE will catch up */ }
}

function renderConfirmations() {
  const host = document.getElementById("console-confirms");
  if (!host) return;
  const confs = store.confirmations;
  if (!confs.length) { host.replaceChildren(noConfirmations()); return; }
  host.replaceChildren(confs.map(confirmCard));
}

function confirmCard(conf) {
  const high = conf.risk === "high";
  async function decide(approve) {
    try {
      await api.resolve(conf.id, approve);
      toast(approve ? "Approved — proceeding" : "Declined — task cancelled",
            approve ? "ok" : "warn");
      refreshConfirmations();
      if (pollTimer) beginPolling();   // keep the console live after the decision
    } catch (err) { toast(err.message, "err"); }
  }
  return el("div", { class: `confirm-card${high ? " high" : ""}` },
    el("div", { class: "row" },
      el("span", { class: "mono", style: "color:var(--muted)" }, conf.tool),
      el("span", { class: `chip ${high ? "err" : "warn"}` }, `${conf.risk} risk`)),
    el("div", { class: "q" }, conf.question),
    el("div", { class: "row" },
      el("button", { class: "btn primary", onClick: () => decide(true) }, icon("check"), "Approve"),
      el("button", { class: "btn danger", onClick: () => decide(false) }, icon("x"), "Decline"),
      el("span", { class: "mono", style: "margin-left:auto;color:var(--faint)" },
        fmtTime(conf.created_at))));
}

/* poll the active task so the console shows the terminal state ---------- */
function beginPolling() {
  if (pollTimer) clearInterval(pollTimer);
  let ticks = 0;
  pollTimer = setInterval(async () => {
    ticks += 1;
    if (!currentTaskId || ticks > 120) { clearInterval(pollTimer); pollTimer = null; return; }
    try {
      const res = await api.task(currentTaskId);
      const status = res.task?.status;
      if (["completed", "failed", "cancelled"].includes(status)) {
        clearInterval(pollTimer); pollTimer = null;
        const kind = status === "completed" ? "ok" : status === "cancelled" ? "warn" : "err";
        toast(`Task ${status}: ${res.task.result || res.task.error || ""}`, kind, 5200);
      }
    } catch { /* transient */ }
    refreshConfirmations();
    renderStateFromEvents();
  }, 900);
}

export default { render, destroy };
