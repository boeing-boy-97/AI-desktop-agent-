/**
 * Workflows — user-defined macros: a trigger phrase mapped to fixed tool steps.
 */
import { api } from "../api.js";
import { el, icon, toast, emptyState } from "../components.js";

export function render(mount) {
  mount.append(
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, "Workflows"),
        el("p", {}, "Macros: say the trigger phrase and NOVA runs the exact step list — " +
                    "no planner improvisation."))),
    el("div", { class: "card glass" },
      el("h3", {}, "Create workflow"),
      el("label", { class: "field" }, el("span", { class: "lbl" }, "Name"),
        el("input", { id: "wf-name", placeholder: "standup" })),
      el("label", { class: "field" }, el("span", { class: "lbl" }, "Trigger phrases (comma separated)"),
        el("input", { id: "wf-triggers", placeholder: "start standup, run standup" })),
      el("label", { class: "field" }, el("span", { class: "lbl" },
        "Steps — one JSON object per line: {\"tool\": \"…\", \"arguments\": {…}}"),
        el("textarea", { id: "wf-steps", rows: 4, class: "mono",
          placeholder: '{"tool": "computer.launch_app", "arguments": {"command": "chrome"}}' })),
      el("button", { class: "btn primary", onClick: create }, icon("check"), "Create workflow")),
    el("div", { class: "card", id: "wf-list" }, el("div", { class: "spinner" })));
  load();
}

export function destroy() {}

async function load() {
  const host = document.getElementById("wf-list");
  try {
    const res = await api.workflows();
    const rows = res.workflows || [];
    if (!rows.length) {
      host.replaceChildren(emptyState("⚙", "No workflows defined yet."));
      return;
    }
    host.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "Name"), el("th", {}, "Triggers"), el("th", {}, "Steps"), el("th", {}, ""))),
      el("tbody", {}, rows.map((w) => el("tr", {},
        el("td", { class: "mono" }, w.name),
        el("td", {}, (w.triggers || []).join(", ") || "—"),
        el("td", {}, `${(w.steps || []).length} step(s)`),
        el("td", {}, el("button", {
          class: "btn small ghost",
          onClick: () => remove(w.name),
        }, icon("trash", 13))))))));
  } catch (err) { host.replaceChildren(emptyState("✗", err.message)); }
}

async function create() {
  const name = document.getElementById("wf-name").value.trim();
  const triggers = document.getElementById("wf-triggers").value
    .split(",").map((s) => s.trim()).filter(Boolean);
  const stepsRaw = document.getElementById("wf-steps").value
    .split("\n").map((s) => s.trim()).filter(Boolean);
  if (!name || !stepsRaw.length) { toast("Name and at least one step are required", "warn"); return; }
  let steps;
  try { steps = stepsRaw.map((line) => JSON.parse(line)); }
  catch (err) { toast(`Step JSON invalid: ${err.message}`, "err"); return; }
  try {
    await api.createWorkflow({ name, triggers, steps });
    toast(`Workflow “${name}” created`, "ok");
    for (const id of ["wf-name", "wf-triggers", "wf-steps"]) document.getElementById(id).value = "";
    load();
  } catch (err) { toast(err.message, "err"); }
}

async function remove(name) {
  try { await api.deleteWorkflow(name); toast(`Deleted “${name}”`, "warn"); load(); }
  catch (err) { toast(err.message, "err"); }
}

export default { render, destroy };
