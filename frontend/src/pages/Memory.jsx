/**
 * Memory.jsx — everything Jarvis knows, in one place you can edit.
 *
 * Memory was invisible. Facts went in through chat ("remember that…"), documents
 * went in through upload, and the only way to find out what was actually stored
 * was to ask and hope. A memory you can't inspect is a memory you can't trust,
 * and one wrong fact in there quietly steers every future answer.
 *
 * Two kinds of memory, shown separately because they behave differently:
 *
 *   FACTS       short, durable, always in context. A handful of them.
 *               Editable and deletable, with the source of each one shown —
 *               you told me / found on this PC / noticed from use.
 *
 *   DOCUMENTS   longer text, retrieved only when relevant. Searchable, so you
 *               can see exactly what a query would pull up before it gets used
 *               to answer something.
 *
 * The search box runs the real retrieval, not a text filter — what you see here
 * is what the model would be given.
 */
import { useState, useEffect, useCallback } from "react";
import { API } from "../config.js";
import { T } from "../JarvisOS.jsx";

const card = {
  background: "#0d1220", border: `1px solid ${T.line}`, borderRadius: 14,
  padding: 18, marginBottom: 16,
};
const label = {
  fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase",
  color: T.dim, marginBottom: 12, fontWeight: 600,
};
const input = {
  background: "rgba(0,0,0,0.35)", color: T.text, border: `1px solid ${T.line}`,
  borderRadius: 8, padding: "8px 12px", fontSize: 12.5, outline: "none",
};
const btn = (color) => ({
  background: `${color}1f`, border: `1px solid ${color}55`, color,
  borderRadius: 8, padding: "7px 14px", fontSize: 12, fontWeight: 600,
  cursor: "pointer",
});

const SOURCE_WORDS = {
  stated: "you told me",
  observed: "found on this PC",
  inferred: "noticed from how you work",
};

export default function Memory() {
  const [persona, setPersona] = useState(null);
  const [docs, setDocs] = useState([]);
  const [status, setStatus] = useState(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState(null);
  const [busy, setBusy] = useState(false);
  const [newNote, setNewNote] = useState({ title: "", body: "" });
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const get = async (p, set, pick = (x) => x) => {
      try { set(pick(await fetch(`${API}${p}`).then((r) => r.json()))); } catch {}
    };
    get("/os/persona", setPersona);
    get("/brain/documents", setDocs, (j) => j.documents || j || []);
    get("/brain/status", setStatus);
  }, []);
  useEffect(() => { load(); }, [load]);

  const search = async () => {
    if (!q.trim()) return setHits(null);
    setBusy(true);
    try {
      const r = await fetch(`${API}/brain/search?q=${encodeURIComponent(q)}&k=6`);
      setHits(await r.json());
    } catch { setHits({ results: [], error: "couldn't reach the backend" }); }
    setBusy(false);
  };

  const forget = async (field) => {
    await fetch(`${API}/os/persona/${field}`, { method: "DELETE" }).catch(() => {});
    load();
  };

  const removeDoc = async (id) => {
    await fetch(`${API}/brain/document/${id}`, { method: "DELETE" }).catch(() => {});
    load();
  };

  const addNote = async () => {
    if (!newNote.body.trim()) return;
    setNote("");
    try {
      const r = await fetch(`${API}/brain/ingest`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newNote.title || "note", text: newNote.body,
                               source: "you" }),
      });
      const j = await r.json().catch(() => ({}));
      setNote(r.ok ? `Saved — split into ${j.chunks ?? "?"} searchable piece(s).`
                   : (j.detail || "Couldn't save that."));
      if (r.ok) setNewNote({ title: "", body: "" });
    } catch { setNote("Backend didn't answer."); }
    load();
  };

  const known = persona?.known || [];

  return (
    <div style={{ padding: 22, maxWidth: 900 }}>

      {/* ── Facts ──────────────────────────────────────────────────────── */}
      <section style={card}>
        <div style={label}>Facts it always knows</div>
        <div style={{ fontSize: 12, color: T.dim, marginBottom: 14, lineHeight: 1.5 }}>
          These go into every answer without being retrieved. Kept short on
          purpose — a prompt stuffed with remembered trivia produces answers
          about the trivia.
        </div>
        {known.length === 0 && (
          <div style={{ fontSize: 12.5, color: T.dim }}>
            Nothing yet. Say "remember that I…" in chat, or add facts in Settings.
          </div>
        )}
        {known.map((f) => (
          <div key={f.field} style={{ display: "flex", gap: 12, alignItems: "baseline",
                                      padding: "8px 0",
                                      borderBottom: `1px solid ${T.line}` }}>
            <div style={{ width: 130, fontSize: 11.5, color: T.dim, flexShrink: 0 }}>
              {f.field.replace(/_/g, " ")}
            </div>
            <div style={{ flex: 1, fontSize: 12.5, color: T.text, minWidth: 0 }}>
              {f.value}
              <div style={{ fontSize: 10.5, color: T.dim, marginTop: 2 }}>
                {SOURCE_WORDS[f.source] || f.source}
                {f.evidence ? ` — ${f.evidence}` : ""}
              </div>
            </div>
            <button onClick={() => forget(f.field)}
                    style={{ ...btn(T.dim), padding: "3px 10px", fontSize: 10.5 }}>
              Forget
            </button>
          </div>
        ))}
      </section>

      {/* ── Search ─────────────────────────────────────────────────────── */}
      <section style={card}>
        <div style={label}>What would it recall?</div>
        <div style={{ fontSize: 12, color: T.dim, marginBottom: 12, lineHeight: 1.5 }}>
          This runs the real retrieval. What comes back is exactly what the model
          would be handed if you asked this in chat.
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && search()}
                 placeholder="try: my rate, freelance profile, what I decided about…"
                 style={{ ...input, flex: 1 }} />
          <button style={btn(T.cyan)} onClick={search} disabled={busy}>
            {busy ? "…" : "Search"}
          </button>
        </div>
        {status && (
          <div style={{ fontSize: 11, color: T.dim, marginTop: 8 }}>
            {status.documents ?? docs.length} document(s) ·{" "}
            {status.embeddings || status.vector
              ? "meaning-based search is on"
              : "keyword search only — pull nomic-embed-text for meaning-based search"}
          </div>
        )}
        {hits && (
          <div style={{ marginTop: 14 }}>
            {!(hits.results || []).length && (
              <div style={{ fontSize: 12.5, color: T.dim }}>
                Nothing came back. It would answer from general knowledge only.
              </div>
            )}
            {(hits.results || []).map((h, i) => (
              <div key={i} style={{ padding: "10px 0",
                                    borderTop: `1px solid ${T.line}` }}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                  <span style={{ fontSize: 12.5, color: T.text, flex: 1 }}>
                    {h.title || h.source || "untitled"}
                  </span>
                  {h.score != null && (
                    <span style={{ fontSize: 10.5, color: T.dim }}>
                      match {typeof h.score === "number" ? h.score.toFixed(2) : h.score}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                  {(h.text || h.chunk || "").slice(0, 400)}
                  {(h.text || "").length > 400 ? "…" : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Teach it something in writing ──────────────────────────────── */}
      <section style={card}>
        <div style={label}>Tell it something longer</div>
        <div style={{ fontSize: 12, color: T.dim, marginBottom: 12, lineHeight: 1.5 }}>
          For anything too long to be a fact — your rates and terms, how you like
          proposals written, notes on a client. Retrieved when relevant.
        </div>
        <input value={newNote.title} placeholder="what is this? e.g. my rates"
               onChange={(e) => setNewNote((n) => ({ ...n, title: e.target.value }))}
               style={{ ...input, width: "100%", marginBottom: 8 }} />
        <textarea value={newNote.body} rows={5}
                  placeholder="write it here…"
                  onChange={(e) => setNewNote((n) => ({ ...n, body: e.target.value }))}
                  style={{ ...input, width: "100%", resize: "vertical",
                           fontFamily: "inherit", lineHeight: 1.5 }} />
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 10 }}>
          <button style={btn(T.green)} onClick={addNote}>Remember this</button>
          {note && <span style={{ fontSize: 12, color: T.dim }}>{note}</span>}
        </div>
      </section>

      {/* ── Everything stored ──────────────────────────────────────────── */}
      <section style={card}>
        <div style={label}>Everything stored ({docs.length})</div>
        {docs.length === 0 && (
          <div style={{ fontSize: 12.5, color: T.dim }}>Nothing stored yet.</div>
        )}
        {docs.map((d) => (
          <div key={d.id} style={{ display: "flex", gap: 12, alignItems: "baseline",
                                   padding: "8px 0",
                                   borderBottom: `1px solid ${T.line}` }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, color: T.text }}>
                {d.title || "untitled"}
              </div>
              <div style={{ fontSize: 10.5, color: T.dim, marginTop: 2 }}>
                {d.source || "note"}
                {d.project ? ` · ${d.project}` : ""}
                {d.chunks ? ` · ${d.chunks} pieces` : ""}
                {d.created_at ? ` · ${String(d.created_at).slice(0, 10)}` : ""}
              </div>
            </div>
            <button onClick={() => removeDoc(d.id)}
                    style={{ ...btn(T.red), padding: "3px 10px", fontSize: 10.5 }}>
              Delete
            </button>
          </div>
        ))}
      </section>
    </div>
  );
}
