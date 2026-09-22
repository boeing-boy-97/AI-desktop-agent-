/**
 * Settings — providers, permission policy, automation and privacy toggles.
 * Secrets (API keys) are never displayed — only via environment variables.
 */
import { api } from "../api.js";
import { el, icon, toast } from "../components.js";

const CHOICES = {
  "ai.provider": ["openai", "ollama", "mock"],
  "voice.stt_provider": ["faster-whisper", "mock"],
  "voice.tts_provider": ["pyttsx3", "kokoro", "piper", "none"],
  "permissions.default_mode": ["ask", "allow"],
  "browser.engine": ["playwright", "inmemory"],
};

const TOGGLES = [
  ["permissions.remember_choice", "Remember my choices per tool (this session)"],
  ["permissions.confirm_delete", "Confirm before deleting files"],
  ["permissions.confirm_messages", "Confirm before sending messages"],
  ["permissions.confirm_privileged", "Confirm privileged / system actions"],
  ["automation.screenshots_enabled", "Screen capture for verification"],
  ["desktop.always_on_top", "Orb always on top"],
  ["browser.headless", "Browser runs headless"],
  ["privacy.cloud_processing_enabled", "Allow cloud AI providers"],
  ["privacy.log_filenames", "Log file names in activity history"],
];

const NUMBERS = [
  ["automation.max_retries", "Max automatic retries per step"],
  ["automation.step_timeout_seconds", "Step timeout (seconds)"],
];

let snapshot = {};

export async function render(mount) {
  mount.append(
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, "Settings"),
        el("p", {}, "Stored in SQLite and applied live. API keys stay in environment " +
                    "variables — they are never shown or stored here."))),
    el("div", { id: "settings-body" }, el("div", { class: "spinner" })));
  try {
    snapshot = (await api.settings()).settings || {};
    draw();
  } catch (err) {
    document.getElementById("settings-body").replaceChildren(
      el("div", { class: "card" }, "✗ ", err.message));
  }
}

export function destroy() {}

function draw() {
  const body = document.getElementById("settings-body");

  const choiceCard = (title, keys) => el("div", { class: "card glass" },
    el("h3", {}, title),
    keys.map((k) => el("label", { class: "field" },
      el("span", { class: "lbl" }, k),
      selectFor(k))));

  const toggleCard = el("div", { class: "card glass" },
    el("h3", {}, "Safety & privacy"),
    TOGGLES.map(([k, label]) => el("label", { class: "checkbox-row" },
      el("input", {
        type: "checkbox",
        ...(snapshot[k] ? { checked: true } : {}),
        onchange: (e) => save({ [k]: e.target.checked }),
      }),
      el("span", {}, label),
      el("span", { class: "mono", style: "margin-left:auto;color:var(--faint);font-size:11px" }, k))));

  const numbersCard = el("div", { class: "card glass" },
    el("h3", {}, "Automation"),
    NUMBERS.map(([k, label]) => el("label", { class: "field" },
      el("span", { class: "lbl" }, label),
      el("input", {
        type: "number", value: String(snapshot[k] ?? ""),
        onchange: (e) => save({ [k]: Number(e.target.value) }),
      }))));

  body.replaceChildren(
    el("div", { class: "grid cols-2" },
      choiceCard("AI provider", ["ai.provider"]),
      choiceCard("Voice", ["voice.stt_provider", "voice.tts_provider"])),
    el("div", { class: "grid cols-2", style: "margin-top:16px" },
      choiceCard("Permissions", ["permissions.default_mode"]),
      numbersCard),
    el("div", { style: "margin-top:16px" }, toggleCard));
}

function selectFor(key) {
  const options = CHOICES[key] || [];
  const sel = el("select", { onchange: (e) => save({ [key]: e.target.value }) },
    options.map((o) => el("option", { ...(snapshot[key] === o ? { selected: true } : {}), value: o }, o)));
  if (!options.includes(snapshot[key]) && snapshot[key]) {
    sel.prepend(el("option", { selected: true, value: snapshot[key] }, String(snapshot[key])));
  }
  return sel;
}

async function save(updates) {
  try {
    const res = await api.updateSettings(updates);
    snapshot = res.settings || snapshot;
    toast("Saved ✓", "ok", 1800);
  } catch (err) { toast(err.message, "err"); }
}

export default { render, destroy };
