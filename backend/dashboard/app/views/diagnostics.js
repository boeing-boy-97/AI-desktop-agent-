/**
 * Diagnostics — health checks + one-click self-repair.
 */
import { api } from "../api.js";
import { el, icon, toast, emptyState } from "../components.js";

const GLYPH = { PASS: "✓", WARNING: "!", ERROR: "✗", SKIP: "·" };
const CHIP = { PASS: "ok", WARNING: "warn", ERROR: "err", SKIP: "muted" };

export function render(mount) {
  mount.append(
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, "Diagnostics"),
        el("p", {}, "Environment probes for every subsystem. Self-repair attempts an " +
                    "automatic fix for each failing check.")),
      el("div", { class: "row" },
        el("button", { class: "btn", id: "diag-refresh", onClick: run }, icon("pulse"), "Re-run checks"),
        el("button", { class: "btn primary", id: "diag-repair", onClick: repair }, icon("tools"), "Self-repair"))),
    el("div", { id: "diag-summary" }),
    el("div", { class: "card", id: "diag-body" }, el("div", { class: "spinner" })),
    // ---- V2 panels -------------------------------------------------------
    el("h3", { style: "margin:20px 0 8px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em" },
      "Engineering health score"),
    el("div", { class: "card", id: "diag-health" }, el("div", { class: "spinner" })),
    el("h3", { style: "margin:20px 0 8px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em" },
      "Startup configuration checks"),
    el("div", { class: "card", id: "diag-startup" }, el("div", { class: "spinner" })),
    el("h3", { style: "margin:20px 0 8px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em" },
      "Recent state transitions (guarded state machine)"),
    el("div", { class: "card", id: "diag-states" }, el("div", { class: "spinner" })));
  run();
  loadHealth();
  loadStartup();
  loadStates();
}

export function destroy() {}

async function loadHealth() {
  const host = document.getElementById("diag-health");
  try {
    const hs = await api.healthScore();
    const comp = hs.components || {};
    host.replaceChildren(
      el("div", { style: "display:flex;align-items:baseline;gap:12px;margin-bottom:8px" },
        el("span", { style: "font-size:30px;font-weight:650;color:var(--" +
           (hs.score >= 80 ? "ok" : hs.score >= 50 ? "warn" : "err") + ")" }, hs.score),
        el("span", { style: "color:var(--muted)" }, "/ 100 · coverage " + hs.coverage + "%")),
      el("div", { class: "grid cols-5" },
        Object.entries(comp).map(([k, v]) => el("div", {},
          el("div", { style: "font-size:11px;color:var(--faint);text-transform:capitalize" }, k),
          el("div", { style: "font-weight:600" }, String(v))))),
      hs.note ? el("p", { style: "margin-top:8px;color:var(--faint);font-size:12px" }, hs.note) : null);
  } catch (err) { host.replaceChildren(emptyState("✗", err.message)); }
}

async function loadStartup() {
  const host = document.getElementById("diag-startup");
  try {
    const sc = await api.startupChecks();
    const rows = sc.checks || [];
    host.replaceChildren(rows.length ? el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Check"), el("th", {}, "Status"),
        el("th", {}, "Detail"), el("th", {}, "Fix"))),
      el("tbody", {}, rows.map((c) => el("tr", {},
        el("td", {}, c.check),
        el("td", {}, el("span", { class: "chip " + (c.ok ? "ok" : c.severity === "error" ? "err" : "warn") },
          c.ok ? "✓ ok" : c.severity)),
        el("td", { style: "max-width:360px;color:var(--muted)" }, c.detail),
        el("td", { style: "max-width:260px;color:var(--faint)" }, c.fix || "—"))))) : emptyState("✓", "No startup checks."));
  } catch (err) { host.replaceChildren(emptyState("✗", err.message)); }
}

async function loadStates() {
  const host = document.getElementById("diag-states");
  try {
    const sh = await api.stateHistory(30);
    const rows = (sh.history || []).slice().reverse();
    host.replaceChildren(rows.length ? el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "From"), el("th", {}, "To"),
        el("th", {}, "Forced"), el("th", {}, "Reason"))),
      el("tbody", {}, rows.map((h) => el("tr", {},
        el("td", { class: "mono" }, h.from),
        el("td", { class: "mono" }, h.to),
        el("td", {}, h.forced ? "yes" : ""),
        el("td", { style: "color:var(--faint)" }, h.reason || ""))))) : emptyState("·", "No transitions yet."));
  } catch (err) { host.replaceChildren(emptyState("✗", err.message)); }
}

async function run() {
  const body = document.getElementById("diag-body");
  try {
    const report = await api.diagnostics();
    drawSummary(report.summary || {});
    const rows = report.checks || [];
    body.replaceChildren(rows.length ? el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "Check"), el("th", {}, "Status"), el("th", {}, "Detail"), el("th", {}, "Suggested fix"))),
      el("tbody", {}, rows.map((c) => el("tr", {},
        el("td", {}, c.name),
        el("td", {}, el("span", { class: `chip ${CHIP[c.status] || "muted"}` },
          `${GLYPH[c.status] || "?"} ${c.status}`)),
        el("td", { style: "max-width:380px;color:var(--muted)" }, c.detail || "—"),
        el("td", { style: "max-width:260px;color:var(--faint)" }, c.fix || "—"))))) : emptyState("✓", "No checks ran."));
  } catch (err) {
    body.replaceChildren(emptyState("✗", err.message));
  }
}

function drawSummary(s) {
  const host = document.getElementById("diag-summary");
  if (!host) return;
  const cell = (label, value, cls) => el("div", { class: "card stat" },
    el("span", { class: "label" }, label),
    el("span", { class: "value", style: cls ? `color:var(--${cls})` : "" }, String(value ?? "—")));
  host.replaceChildren(el("div", { class: "grid cols-4", style: "margin-bottom:16px" },
    cell("PASS", s.PASS, "ok"), cell("WARNING", s.WARNING, "warn"),
    cell("ERROR", s.ERROR, "err"), cell("Healthy", s.healthy ? "yes" : "no", s.healthy ? "ok" : "err")));
}

async function repair() {
  const btn = document.getElementById("diag-repair");
  btn.disabled = true; btn.textContent = "Repairing…";
  try {
    const res = await api.repair();
    toast(res.passed ? "Self-repair finished — healthy" :
          `Repair done; still blocked: ${(res.blockers || []).join(", ") || "see report"}`,
          res.passed ? "ok" : "warn", 6000);
    await run();
  } catch (err) { toast(err.message, "err"); }
  finally { btn.disabled = false; btn.replaceChildren(icon("tools"), "Self-repair"); }
}

export default { render, destroy };
