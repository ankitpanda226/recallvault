import { useState } from "react";
import { api } from "../lib/api.js";

/**
 * Chat panel. Two actions:
 *   - "remember"  -> POST /chat/message  (ingests, extracts facts)
 *   - "ask"       -> POST /chat/respond  (retrieval + guard)
 *
 * The panel renders a ledger of turns so it's obvious which mode produced
 * which response, and shows the guard mode for every answer.
 */
export default function ChatPanel({ projectId, projectName, onMutation }) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState("tell"); // "tell" | "ask"
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);

  const submit = async () => {
    const value = text.trim();
    if (!value) return;
    setBusy(true);
    try {
      if (mode === "tell") {
        const res = await api.sendMessage({ project_id: projectId, text: value });
        setLog((l) => [
          ...l,
          { kind: "tell", input: value, output: res, ts: new Date().toISOString() },
        ]);
        onMutation();
      } else {
        const res = await api.respond({ project_id: projectId, query: value });
        setLog((l) => [
          ...l,
          { kind: "ask", input: value, output: res, ts: new Date().toISOString() },
        ]);
      }
      setText("");
    } catch (e) {
      setLog((l) => [
        ...l,
        { kind: "err", input: value, output: String(e.message || e), ts: new Date().toISOString() },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const onKey = (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-4 border-b border-vault-line flex items-baseline gap-4">
        <h2 className="font-display text-sm uppercase tracking-widest text-vault-mute">
          Ledger
        </h2>
        <div className="text-sm text-vault-ink">{projectName}</div>
      </div>

      <div className="flex-1 overflow-y-auto scroll-thin px-6 py-5 space-y-6">
        {log.length === 0 ? (
          <WelcomeNote />
        ) : (
          log.map((entry, i) => <LogEntry key={i} entry={entry} />)
        )}
      </div>

      <div className="border-t border-vault-line p-4 bg-vault-panel/40">
        <div className="flex gap-2 mb-3">
          <ModeButton active={mode === "tell"} onClick={() => setMode("tell")}>
            tell the vault
          </ModeButton>
          <ModeButton active={mode === "ask"} onClick={() => setMode("ask")}>
            ask the vault
          </ModeButton>
        </div>
        <div className="flex gap-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            placeholder={
              mode === "tell"
                ? "State a fact to remember. e.g., 'I prefer backend engineer roles.'"
                : "Ask something. e.g., 'What roles am I targeting?'"
            }
            className="flex-1 bg-vault-bg border border-vault-line px-3 py-2 text-sm resize-none h-20 focus:outline-none focus:border-vault-accent"
          />
          <button
            disabled={busy || !text.trim()}
            onClick={submit}
            className="px-5 bg-vault-accent text-vault-bg font-display font-bold text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110"
          >
            {busy ? "..." : mode === "tell" ? "store" : "recall"}
          </button>
        </div>
        <div className="mt-2 text-[10px] font-display uppercase tracking-widest text-vault-mute">
          cmd/ctrl + enter
        </div>
      </div>
    </div>
  );
}

function ModeButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`text-xs font-display uppercase tracking-widest px-3 py-1 border transition-colors ${
        active
          ? "border-vault-accent text-vault-accent"
          : "border-vault-line text-vault-mute hover:text-vault-ink"
      }`}
    >
      {children}
    </button>
  );
}

function WelcomeNote() {
  return (
    <div className="max-w-md">
      <div className="font-display text-xs uppercase tracking-widest text-vault-mute mb-3">
        Protocol
      </div>
      <ol className="space-y-2 text-sm text-vault-ink leading-relaxed list-decimal list-inside">
        <li>Use <span className="text-vault-accent">tell</span> to store a statement. The vault extracts durable facts, verifies them, and logs everything.</li>
        <li>Use <span className="text-vault-accent">ask</span> to query. The guard decides: <VerifiedTag /> · <CautiousTag /> · <AbstainTag />.</li>
        <li>Verified answers always carry a source trail. Nothing is ever guessed.</li>
      </ol>
    </div>
  );
}

function LogEntry({ entry }) {
  const ts = entry.ts.slice(11, 19);
  if (entry.kind === "err") {
    return (
      <div className="border-l-2 border-vault-abstain pl-4">
        <div className="text-[10px] font-display uppercase tracking-widest text-vault-abstain">
          error · {ts}
        </div>
        <div className="text-sm text-vault-abstain mt-1">{entry.output}</div>
      </div>
    );
  }
  if (entry.kind === "tell") {
    const r = entry.output;
    return (
      <div>
        <div className="text-[10px] font-display uppercase tracking-widest text-vault-mute">
          tell · {ts}
        </div>
        <div className="mt-1 text-sm text-vault-ink">{entry.input}</div>
        <div className="mt-2 text-xs font-display text-vault-mute">
          {r.chunk_ids.length} chunk(s) stored · {r.accepted} fact(s) accepted · {r.rejected} rejected
        </div>
        {r.facts.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs font-display">
            {r.facts.map((f, i) => (
              <li key={i} className="flex gap-2">
                <span
                  className={`uppercase tracking-widest ${
                    f.action === "rejected"
                      ? "text-vault-abstain"
                      : f.action === "superseded"
                      ? "text-vault-cautious"
                      : "text-vault-verified"
                  }`}
                >
                  {f.action}
                </span>
                <span className="text-vault-ink">{f.key}</span>
                <span className="text-vault-mute">= {JSON.stringify(f.value)}</span>
                {f.version && <span className="text-vault-mute">v{f.version}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  // ask
  const r = entry.output;
  const tag =
    r.mode === "verified" ? <VerifiedTag /> :
    r.mode === "cautious" ? <CautiousTag /> : <AbstainTag />;
  return (
    <div>
      <div className="text-[10px] font-display uppercase tracking-widest text-vault-mute">
        ask · {ts}
      </div>
      <div className="mt-1 text-sm text-vault-ink">{entry.input}</div>
      <div className="mt-3 border-l-2 border-vault-line pl-4">
        <div className="mb-1">{tag}</div>
        <div className="text-sm text-vault-ink leading-relaxed">{r.answer}</div>
        {r.provenance && r.provenance.length > 0 && (
          <div className="mt-2 text-[10px] font-display uppercase tracking-widest text-vault-mute">
            provenance:
            {r.provenance.map((p, i) => (
              <span key={i} className="ml-2 normal-case tracking-normal text-vault-mute">
                fact {p.fact_id?.slice(0, 8)} v{p.version} · chunk {p.source_chunk_id?.slice(0, 8)} · {p.source_type}
              </span>
            ))}
          </div>
        )}
        {r.matched_keys && r.matched_keys.length > 0 && (
          <div className="mt-1 text-[10px] font-display uppercase tracking-widest text-vault-mute">
            matched keys: <span className="text-vault-ink normal-case tracking-normal">{r.matched_keys.join(", ")}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function VerifiedTag() {
  return (
    <span className="inline-block text-[10px] font-display uppercase tracking-widest px-2 py-0.5 border border-vault-verified text-vault-verified">
      verified
    </span>
  );
}
function CautiousTag() {
  return (
    <span className="inline-block text-[10px] font-display uppercase tracking-widest px-2 py-0.5 border border-vault-cautious text-vault-cautious">
      cautious
    </span>
  );
}
function AbstainTag() {
  return (
    <span className="inline-block text-[10px] font-display uppercase tracking-widest px-2 py-0.5 border border-vault-abstain text-vault-abstain">
      abstain
    </span>
  );
}
