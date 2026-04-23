import { useEffect, useMemo, useState } from "react";
import { api } from "./lib/api.js";
import ChatPanel from "./components/ChatPanel.jsx";
import MemoryInspector from "./components/MemoryInspector.jsx";
import ProjectSelector from "./components/ProjectSelector.jsx";

export default function App() {
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [stats, setStats] = useState(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const refresh = () => setRefreshTick((n) => n + 1);

  useEffect(() => {
    api.listProjects().then((p) => {
      setProjects(p);
      if (p.length > 0 && !projectId) setProjectId(p[0].id);
    }).catch(() => {});
  }, [refreshTick]);

  useEffect(() => {
    if (!projectId) return;
    api.stats(projectId).then(setStats).catch(() => setStats(null));
  }, [projectId, refreshTick]);

  const activeProject = useMemo(
    () => projects.find((p) => p.id === projectId) || null,
    [projects, projectId]
  );

  return (
    <div className="h-full flex flex-col">
      <header className="border-b border-vault-line bg-vault-panel/60 backdrop-blur-sm">
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center gap-8">
          <div className="flex items-baseline gap-3">
            <span className="font-display text-2xl font-bold tracking-tight">
              <span className="text-vault-accent">RECALL</span>
              <span className="text-vault-ink">VAULT</span>
            </span>
            <span className="text-xs text-vault-mute font-display">v0.1</span>
          </div>
          <div className="hidden md:block text-xs text-vault-mute font-display uppercase tracking-widest">
            verified · local-first · zero fake recall
          </div>

          <div className="ml-auto flex items-center gap-6 text-xs font-display text-vault-mute">
            {stats && (
              <>
                <StatPill label="chunks" value={stats.chunks} />
                <StatPill label="facts" value={stats.active_facts} />
                <StatPill label="superseded" value={stats.superseded_facts} />
                <StatPill label="conflicts" value={stats.conflicts} />
              </>
            )}
          </div>
        </div>
      </header>

      <div className="flex-1 grid grid-cols-12 gap-px bg-vault-line overflow-hidden">
        <aside className="col-span-3 bg-vault-bg overflow-y-auto scroll-thin">
          <ProjectSelector
            projects={projects}
            activeId={projectId}
            onSelect={setProjectId}
            onCreated={(p) => {
              setProjectId(p.id);
              refresh();
            }}
          />
        </aside>

        <main className="col-span-5 bg-vault-bg overflow-hidden flex flex-col">
          {projectId ? (
            <ChatPanel
              projectId={projectId}
              projectName={activeProject?.name ?? projectId}
              onMutation={refresh}
            />
          ) : (
            <EmptyState />
          )}
        </main>

        <aside className="col-span-4 bg-vault-bg overflow-y-auto scroll-thin">
          {projectId && (
            <MemoryInspector projectId={projectId} refreshTick={refreshTick} />
          )}
        </aside>
      </div>
    </div>
  );
}

function StatPill({ label, value }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="uppercase tracking-widest">{label}</span>
      <span className="text-vault-ink font-bold">{value}</span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex items-center justify-center text-center p-8">
      <div>
        <div className="font-display text-vault-mute text-sm uppercase tracking-widest mb-3">
          no vault selected
        </div>
        <div className="text-vault-ink">Create or select a project to begin.</div>
      </div>
    </div>
  );
}
