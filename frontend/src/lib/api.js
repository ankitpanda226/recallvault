async function request(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/health"),

  listProjects: () => request("/projects/list"),
  createProject: (body) =>
    request("/projects/create", { method: "POST", body: JSON.stringify(body) }),

  sendMessage: (body) =>
    request("/chat/message", { method: "POST", body: JSON.stringify(body) }),
  respond: (body) =>
    request("/chat/respond", { method: "POST", body: JSON.stringify(body) }),

  search: (project_id, q) =>
    request(`/memory/search?project_id=${encodeURIComponent(project_id)}&q=${encodeURIComponent(q)}`),
  history: (project_id, key) =>
    request(`/memory/history/${encodeURIComponent(key)}?project_id=${encodeURIComponent(project_id)}`),
  forget: (body) =>
    request("/memory/forget", { method: "POST", body: JSON.stringify(body) }),

  stats: (project_id) =>
    request(`/admin/stats?project_id=${encodeURIComponent(project_id)}`),
  events: (project_id, limit = 50) =>
    request(`/admin/events?project_id=${encodeURIComponent(project_id)}&limit=${limit}`),
  conflicts: (project_id) =>
    request(`/admin/conflicts?project_id=${encodeURIComponent(project_id)}`),
};
