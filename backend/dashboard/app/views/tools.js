/**
 * Tools — searchable catalog of every registered tool plugin.
 */
import { api } from "../api.js";
import { el, icon, riskChip, emptyState, modal, kv } from "../components.js";

let catalog = null;
let query = "";
let category = "";

export async function render(mount) {
  mount.append(
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, "Tool Registry"),
        el("p", {}, "Every capability NOVA can invoke. Permission level controls the gate: " +
                    "low runs silently, medium depends on your default mode, high always asks."))),
    el("div", { class: "search" },
      icon("search"),
      el("input", {
        placeholder: "Search 85 tools… (name, description, category)",
        oninput: (e) => { query = e.target.value.toLowerCase(); draw(); },
      })),
    el("div", { class: "quick-chips", id: "tool-cats" }),
    el("div", { class: "tool-grid", id: "tool-grid" }, el("div", { class: "spinner" })));

  try {
    catalog = (await api.catalog()).tools || [];
  } catch (err) {
    document.getElementById("tool-grid").replaceChildren(emptyState("✗", err.message));
    return;
  }
  const cats = [...new Set(catalog.map((t) => t.category))].sort();
  document.getElementById("tool-cats").replaceChildren(
    el("button", { class: "btn small primary", onClick: (e) => pick(e, "") }, "all"),
    cats.map((c) => el("button", {
      class: "btn small ghost",
      onClick: (e) => pick(e, c),
    }, c)));
  draw();
}

export function destroy() { catalog = null; }

function pick(e, cat) {
  category = cat;
  for (const b of e.target.parentElement.children) {
    b.className = "btn small ghost";
  }
  e.target.className = "btn small primary";
  draw();
}

function draw() {
  const grid = document.getElementById("tool-grid");
  if (!grid || !catalog) return;
  const rows = catalog.filter((t) =>
    (!category || t.category === category) &&
    (!query || `${t.name} ${t.description} ${t.category}`.toLowerCase().includes(query)));
  if (!rows.length) { grid.replaceChildren(emptyState("🔍", "No tools match.")); return; }
  grid.replaceChildren(rows.map((t) => el("div", {
    class: "tool-card",
    onClick: () => detail(t),
  },
    el("div", { class: "name" }, t.name),
    el("div", { class: "desc" }, t.description || "—"),
    el("div", { class: "foot" },
      riskChip(t.permission_level),
      t.requires_confirmation ? el("span", { class: "chip warn" }, "asks") : null,
      el("span", { class: "chip muted" }, t.category)))));
}

function detail(t) {
  modal(t.name, el("div", {},
    el("p", { style: "color:var(--muted);margin:0 0 12px" }, t.description || "—"),
    kv("Category", t.category),
    kv("Permission", t.permission_level),
    kv("Confirmation", t.requires_confirmation ? "always asks" : "policy-based"),
    el("h3", { style: "margin:16px 0 6px;font-size:11.5px;color:var(--muted);text-transform:uppercase" },
      "Input schema"),
    el("pre", { class: "code" },
      JSON.stringify(t.input_schema ?? {}, null, 2) || "{}")));
}

export default { render, destroy };
