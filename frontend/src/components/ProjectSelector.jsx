import { useState } from "react";
import { api } from "../lib/api.js";

export default function ProjectSelector({ projects, activeId, onSelect, onCreated }) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [err, setErr] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      const body = {
        id: id.trim() || name.trim().toLowerCase().replace(/[^a-z0-9_\-]+/g, "_"),
        name: name.trim(),
        description: "",
      };
      if (!body.name) {
        setErr("name required");
        return;
      }
      const p = await api.createProject(body);
      onCreated(p);
      setCreating(false);
      setName("");
      setId("");
    } catch (e) {
      setErr(String(e.message || e));
    }
  };

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-display text-xs uppercase tracking-widest text-vault-mute">
          Vaults
        </h2>
        <button
          className="text-xs font-display text-vault-accent hover:underline"
          onClick={() => setCreating((c) => !c)}
        >
          {creating ? "cancel" : "+ new"}
        </button>
      </div>

      {creating && (
        <form onSubmit={submit} className="mb-5 space-y-2">
          <input
            className="w-full bg-vault-panel border border-vault-line px-3 py-2 text-sm focus:outline-none focus:border-vault-accent"
            placeholder="display name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="w-full bg-vault-panel border border-vault-line px-3 py-2 text-sm font-display focus:outline-none focus:border-vault-accent"
            placeholder="id (optional, e.g. coding_agent)"
            value={id}
            onChange={(e) => setId(e.target.value)}
          />
          {err && (
            <div className="text-xs text-vault-abstain font-display">{err}</div>
          )}
          <button
            type="submit"
            className="w-full bg-vault-accent text-vault-bg font-display font-bold text-sm py-2 hover:brightness-110"
          >
            create vault
          </button>
        </form>
      )}

      {projects.length === 0 ? (
        <div className="text-sm text-vault-mute italic">
          No vaults yet. Create one to start.
        </div>
      ) : (
        <ul className="space-y-1">
          {projects.map((p) => {
            const active = p.id === activeId;
            return (
              <li key={p.id}>
                <button
                  onClick={() => onSelect(p.id)}
                  className={`w-full text-left px-3 py-2 border transition-colors ${
                    active
                      ? "border-vault-accent bg-vault-panel"
                      : "border-transparent hover:bg-vault-panel/50 hover:border-vault-line"
                  }`}
                >
                  <div className="text-sm">{p.name}</div>
                  <div className="text-[10px] font-display uppercase tracking-widest text-vault-mute">
                    {p.id}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-8 pt-5 border-t border-vault-line">
        <h3 className="font-display text-xs uppercase tracking-widest text-vault-mute mb-2">
          about
        </h3>
        <p className="text-xs text-vault-mute leading-relaxed">
          Each vault is a fully isolated memory space — its own SQLite file,
          its own vector index. No cross-project contamination.
        </p>
      </div>
    </div>
  );
}
