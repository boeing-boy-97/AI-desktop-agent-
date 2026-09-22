/**
 * Memory — NOVA's long-term key/value recall (used by @placeholders in plans).
 */
import { api } from "../api.js";
import { el, icon, toast, emptyState, fmtAgo } from "../components.js";

export function render(mount) {
  mount.append(
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, "Memory"),
        el("p", {}, "Facts NOVA keeps between sessions. Planner shortcuts like " +
                    "@college_projects resolve from here."))),
    el("div", { class: "card glass" },
      el("h3", {}, "Remember something new"),
      el("div", { class: "row" },
        el("input", { id: "mem-key", placeholder: "key (e.g. college_projects)" }),
        el("input", { id: "mem-val", placeholder: "value (e.g. D:/College/Projects)" }),
        el("select", { id: "mem-cat", class: "fixed" },
          ["general", "paths", "people", "preferences"].map((c) => el("option", { value: c }, c))),
        el("button", { class: "btn primary fixed", onClick: remember }, icon("check"), "Save"))),
    el("div", { class: "card", id: "mem-list" }, el("div", { class: "spinner" })));
  load();
}

export function destroy() {}

async function load() {
  const host = document.getElementById("mem-list");
  try {
    const res = await api.memories();
    const rows = res.memories || [];
    if (!rows.length) {
      host.replaceChildren(emptyState("🧠", "Nothing remembered yet."));
      return;
    }
    host.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "Key"), el("th", {}, "Value"), el("th", {}, "Category"),
        el("th", {}, "Updated"), el("th", {}, ""))),
      el("tbody", {}, rows.map((m) => el("tr", {},
        el("td", { class: "mono" }, m.key),
        el("td", { style: "max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" }, m.value),
        el("td", {}, el("span", { class: "chip muted" }, m.category || "general")),
        el("td", { style: "color:var(--faint)" }, fmtAgo(m.updated_at)),
        el("td", {}, el("button", {
          class: "btn small ghost",
          onClick: () => forget(m.key),
        }, icon("trash", 13))))))));
  } catch (err) { host.replaceChildren(emptyState("✗", err.message)); }
}

async function remember() {
  const key = document.getElementById("mem-key").value.trim();
  const value = document.getElementById("mem-val").value.trim();
  const category = document.getElementById("mem-cat").value;
  if (!key || !value) { toast("Both key and value are required", "warn"); return; }
  try {
    await api.remember(key, value, category);
    toast(`Remembered “${key}”`, "ok");
    document.getElementById("mem-key").value = "";
    document.getElementById("mem-val").value = "";
    load();
  } catch (err) { toast(err.message, "err"); }
}

async function forget(key) {
  try {
    await api.forget(key);
    toast(`Forgot “${key}”`, "warn");
    load();
  } catch (err) { toast(err.message, "err"); }
}

export default { render, destroy };
