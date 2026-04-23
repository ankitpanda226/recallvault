import { useEffect, useState } from "react";
import { api } from "../lib/api.js";

/**
 * Right-rail inspector with three tabs:
 *   - Events: the live audit log
 *   - Conflicts: every resolution the system has made
 *   - Search: ad-hoc hybrid search (facts + chunks)
 */
export default function MemoryInspector({ projectId, refreshTick }) {
  const [tab, setTab] = useState("events");
  const [events, setEvents] = useState([]);
  const [conflicts, setConflicts] = useState([]);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);

  useEffect(() => {
    if (!projectId) return;
    api.events(projectId, 50).then(setEvents).catch(() => setEvents([]));
    api.conflicts(projectId).then(setConflicts).catch(() => setConflicts([]));
  }, [projectId, refreshTick]);

  const runSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    try {
      const r = await api.search(projectId, query);
      setSearchResults(r);
    } catch (err) {
      setSearchResults({ error: String(err.message || err) });
    }
  };

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-display text-xs uppercase tracking-widest text-vault-mute">
          Inspector
        </h2>
      </div>

      <div className="flex gap-1 mb-4 border-b border-vault-line">
        <Tab active={tab === "events"} onClick={() => setTab("events")}>events</Tab>
        <Tab active={tab === "conflicts"} onClick={() => setTab("conflicts")}>
          conflicts {conflicts.length > 0 && <Count>{conflicts.length}</Count>}
        </Tab>
        <Tab active={tab === "search"} onClick={() => setTab("search")}>search</Tab>
      </div>

      {tab === "events" && <EventsTab events={events} />}
      {tab === "conflicts" && <ConflictsTab conflicts={conflicts} />}
      {tab === "search" && (
        <SearchTab
          query={query}
          setQuery={setQuery}
          onSubmit={runSearch}
          results={searchResults}
        />
      )}
    </div>
  );
}

function Tab({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`text-xs font-display uppercase tracking-widest px-3 py-2 border-b-2 -mb-px transition-colors ${
        active
          ? "border-vault-accent text-vault-accent"
          : "border-transparent text-vault-mute hover:text-vault-ink"
      }`}
    >
      {children}
    </button>
  );
}

function Count({ children }) {
  return (
    <span className="ml-1 px-1.5 py-0.5 bg-vault-accent text-vault-bg normal-case text-[10px]">
      {children}
    </span>
  );
}

function EventsTab({ events }) {
  if (events.length === 0) {
    return <Empty>No events yet. Tell the vault something.</Empty>;
  }
  return (
    <ul className="space-y-2">
      {events.map((e) => (
        <li key={e.event_id} className="border-l-2 border-vault-line pl-3 py-1">
          <div className="flex items-center gap-2 text-[10px] font-display uppercase tracking-widest">
            <span className={eventClass(e.event_type)}>{e.event_type}</span>
            <span className="text-vault-mute ml-auto">{fmtTime(e.created_at)}</span>
          </div>
          {e.payload && Object.keys(e.payload).length > 0 && (
            <pre className="mt-1 text-[11px] text-vault-mute font-display whitespace-pre-wrap break-all">
              {JSON.stringify(e.payload, null, 0)}
            </pre>
          )}
        </li>
      ))}
    </ul>
  );
}

function ConflictsTab({ conflicts }) {
  if (conflicts.length === 0) {
    return <Empty>No conflicts recorded.</Empty>;
  }
  return (
    <ul className="space-y-3">
      {conflicts.map((c) => (
        <li key={c.conflict_id} className="border border-vault-line p-3">
          <div className="flex justify-between items-baseline">
            <span className="font-display text-sm text-vault-ink">{c.fact_key}</span>
            <span className="text-[10px] font-display uppercase tracking-widest text-vault-cautious">
              {c.resolution}
            </span>
          </div>
          <div className="mt-2 text-[11px] font-display text-vault-mute space-y-0.5">
            <div>old: {c.old_fact_id?.slice(0, 12) ?? "—"}</div>
            <div>new: {c.new_fact_id?.slice(0, 12) ?? "—"}</div>
            <div>{fmtTime(c.created_at)}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function SearchTab({ query, setQuery, onSubmit, results }) {
  return (
    <div>
      <form onSubmit={onSubmit} className="flex gap-2 mb-4">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="hybrid search..."
          className="flex-1 bg-vault-panel border border-vault-line px-3 py-2 text-sm focus:outline-none focus:border-vault-accent"
        />
        <button className="px-3 bg-vault-accent text-vault-bg font-display font-bold text-xs hover:brightness-110">
          go
        </button>
      </form>
      {!results && <Empty>Try a query — facts and chunks are ranked together.</Empty>}
      {results?.error && <div className="text-sm text-vault-abstain">{results.error}</div>}
      {results?.results && (
        <ul className="space-y-3">
          {results.results.length === 0 && <Empty>No matches.</Empty>}
          {results.results.map((hit, i) => (
            <li key={i} className="border-l-2 pl-3 py-1 border-vault-line">
              <div className="flex items-center gap-2 text-[10px] font-display uppercase tracking-widest">
                <span
                  className={
                    hit.kind === "fact" ? "text-vault-verified" : "text-vault-mute"
                  }
                >
                  {hit.kind}
                </span>
                <span className="text-vault-mute">score {hit.score.toFixed(2)}</span>
              </div>
              {hit.kind === "fact" ? (
                <div className="mt-1">
                  <div className="text-sm text-vault-ink">
                    <span className="font-display">{hit.payload.key}</span>
                    <span className="text-vault-mute"> = {JSON.stringify(hit.payload.value)}</span>
                  </div>
                  <div className="text-[10px] font-display text-vault-mute mt-0.5">
                    v{hit.payload.version} · conf {hit.payload.confidence.toFixed(2)} · {hit.payload.source_type}
                  </div>
                </div>
              ) : (
                <div className="mt-1 text-sm text-vault-ink">{hit.payload.text}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Empty({ children }) {
  return <div className="text-xs text-vault-mute italic">{children}</div>;
}

function eventClass(type) {
  if (type.startsWith("FACT_CREATED")) return "text-vault-verified";
  if (type.startsWith("FACT_SUPERSEDED")) return "text-vault-cautious";
  if (type.startsWith("FACT_REJECTED") || type.startsWith("FACT_DELETED"))
    return "text-vault-abstain";
  if (type.startsWith("CONFLICT")) return "text-vault-cautious";
  return "text-vault-mute";
}

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}
