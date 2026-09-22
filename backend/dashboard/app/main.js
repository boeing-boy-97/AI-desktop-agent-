/**
 * NOVA Control Center — app shell.
 * Hash-based router (works from any static host), live topbar bound to SSE,
 * and the always-available emergency stop.
 */
import { api } from "./api.js";
import { store, subscribe } from "./store.js";
import { startStream } from "./sse.js";
import { el, icon, toast } from "./components.js";

import overview from "./views/overview.js";
import command from "./views/command.js";
import tasks from "./views/tasks.js";
import tools from "./views/tools.js";
import memory from "./views/memory.js";
import workflows from "./views/workflows.js";
import settings from "./views/settings.js";
import diagnostics from "./views/diagnostics.js";

const VIEWS = {
  console:     { mod: command,     label: "Console",     icon: "console" },
  overview:    { mod: overview,    label: "Overview",    icon: "grid" },
  tasks:       { mod: tasks,       label: "Tasks",       icon: "tasks" },
  tools:       { mod: tools,       label: "Tools",       icon: "tools" },
  memory:      { mod: memory,      label: "Memory",      icon: "memory" },
  workflows:   { mod: workflows,   label: "Workflows",   icon: "flows" },
  settings:    { mod: settings,    label: "Settings",    icon: "settings" },
  diagnostics: { mod: diagnostics, label: "Diagnostics", icon: "pulse" },
};

let currentView = null;
let currentName = "";

/* ---------------------------------------------------------------- shell */
function shell() {
  const nav = el("nav", { class: "nav" },
    Object.entries(VIEWS).map(([name, v]) => el("button", {
      id: `nav-${name}`,
      onClick: () => { location.hash = `#/${name}`; },
    }, icon(v.icon), v.label)));

  return el("div", { class: "layout" },
    el("aside", { class: "sidebar" },
      el("div", { class: "brand" },
        el("div", { class: "orb", id: "brand-orb" }),
        el("div", {},
          el("div", { class: "brand-name" }, "NOVA"),
          el("div", { class: "brand-sub" }, "Control Center"))),
      nav,
      el("div", { class: "sidebar-foot" },
        el("div", { class: "topbar" },
          el("span", { class: "pill", id: "pill-state" },
            el("span", { class: "dot" }), "…"),
          el("span", { class: "pill", id: "pill-link" },
            el("span", { class: "dot" }), "link")),
        el("button", { class: "btn danger", id: "estop", style: "width:100%;justify-content:center", onClick: onEstop },
          icon("stop"), "Emergency stop"))),
    el("main", { class: "main", id: "view" }));
}

/* ---------------------------------------------------------------- router */
function route() {
  const name = (location.hash || "#/console").replace(/^#\//, "") || "console";
  const target = VIEWS[name] ? name : "console";
  if (target === currentName) return;

  const mount = document.getElementById("view");
  try { currentView?.destroy?.(); } catch { /* view teardown best-effort */ }
  mount.replaceChildren();
  currentName = target;
  currentView = VIEWS[target].mod;
  currentView.render(mount);

  for (const key of Object.keys(VIEWS)) {
    document.getElementById(`nav-${key}`)?.classList.toggle("active", key === target);
  }
  mount.scrollTop = 0;
}

/* ---------------------------------------------------------------- topbar */
const BUSY_STATES = new Set(["LISTENING", "UNDERSTANDING", "PLANNING", "EXECUTING",
  "WAITING_CONFIRMATION", "VERIFYING", "RECOVERING", "SPEAKING"]);

function updateTopbar() {
  const s = store.status;
  const pill = document.getElementById("pill-state");
  const orb = document.getElementById("brand-orb");
  if (!pill) return;
  const state = s?.state || "OFFLINE";
  pill.className = "pill " + (s?.emergency_active ? "stopped"
    : BUSY_STATES.has(state) ? "busy" : s ? "live" : "");
  pill.replaceChildren(el("span", { class: "dot" }),
    s?.emergency_active ? "STOPPED" : state.toLowerCase());
  if (orb) orb.className = "orb" + (s?.emergency_active ? " error" : BUSY_STATES.has(state) ? " busy" : "");

  const link = document.getElementById("pill-link");
  if (link) {
    link.className = "pill " + (store.connected ? "live" : "");
    link.replaceChildren(el("span", { class: "dot" }), store.connected ? "live feed" : "reconnecting…");
  }
}

async function onEstop() {
  try {
    const s = store.status;
    if (s?.emergency_active) {
      await api.emergencyRelease();
      toast("Emergency stop released", "ok");
    } else {
      await api.emergencyStop();
      toast("EMERGENCY STOP — all agent activity halted", "err", 6000);
    }
    const status = await api.status();
    Object.assign(store, { status });
    updateTopbar();
  } catch (err) { toast(err.message, "err"); }
}

/* ----------------------------------------------------------------- boot */
async function boot() {
  document.body.replaceChildren(shell());
  window.addEventListener("hashchange", route);
  route();
  startStream();
  subscribe(updateTopbar);
  updateTopbar();

  // poll status slowly so the pill stays honest even if events are quiet
  setInterval(async () => {
    try {
      const status = await api.status();
      Object.assign(store, { status });
      updateTopbar();
    } catch { /* offline — pill already shows reconnect state */ }
  }, 3000);
}

boot();
