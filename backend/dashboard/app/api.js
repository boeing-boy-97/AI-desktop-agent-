/**
 * NOVA API client — typed wrappers over every backend endpoint.
 * All calls are same-origin (the frontend is served by the backend).
 */

class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `HTTP ${status}`);
    this.status = status;
    this.code = body?.code || "HTTP_ERROR";
    this.details = body?.details;
  }
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* 204 / empty */ }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  // system ------------------------------------------------------------------
  health:            ()        => request("GET", "/api/health"),
  status:            ()        => request("GET", "/api/system/status"),
  catalog:           ()        => request("GET", "/api/agent/catalog"),

  // agent -------------------------------------------------------------------
  execute:           (command, mode = "smart") =>
                     request("POST", "/api/agent/execute", { command, mode }),
  plan:              (command, mode = "smart") =>
                     request("POST", "/api/agent/plan", { command, mode }),

  // tasks -------------------------------------------------------------------
  tasks:             (limit = 100, status) =>
                     request("GET", `/api/tasks?limit=${limit}${status ? `&status=${status}` : ""}`),
  task:              (id)      => request("GET", `/api/tasks/${id}`),
  cancelTask:        (id, reason = "user_cancel") =>
                     request("POST", `/api/tasks/${id}/cancel`, { reason }),
  pauseTask:         (id)      => request("POST", `/api/tasks/${id}/pause`),
  resumeTask:        (id)      => request("POST", `/api/tasks/${id}/resume`),
  stateHistory:      (limit = 50) =>
                     request("GET", `/api/system/state_history?limit=${limit}`),
  sessionContext:    ()        => request("GET", "/api/system/session"),
  startupChecks:     ()        => request("GET", "/api/system/startup_checks"),
  healthScore:       ()        => request("GET", "/api/system/health_score"),

  // confirmations -----------------------------------------------------------
  confirmations:     ()        => request("GET", "/api/confirmations"),
  resolve:           (id, approve) =>
                     request("POST", `/api/confirmations/${id}`, { approve }),

  // memory / workflows ------------------------------------------------------
  memories:          ()        => request("GET", "/api/memory"),
  remember:          (key, value, category = "general") =>
                     request("POST", "/api/memory", { key, value, category }),
  forget:            (key)     => request("DELETE", `/api/memory/${encodeURIComponent(key)}`),
  workflows:         ()        => request("GET", "/api/workflows"),
  createWorkflow:    (w)       => request("POST", "/api/workflows", w),
  deleteWorkflow:    (name)    => request("DELETE", `/api/workflows/${encodeURIComponent(name)}`),

  // settings / diagnostics / safety ----------------------------------------
  settings:          ()        => request("GET", "/api/settings"),
  updateSettings:    (updates) => request("PUT", "/api/settings", { updates }),
  diagnostics:       ()        => request("GET", "/api/diagnostics"),
  repair:            ()        => request("POST", "/api/diagnostics/repair"),
  emergencyStop:     ()        => request("POST", "/api/emergency_stop"),
  emergencyRelease:  ()        => request("POST", "/api/emergency_stop/release"),

  // events ------------------------------------------------------------------
  events:            (limit = 100) => request("GET", `/api/events?limit=${limit}`),
};

export { ApiError };
