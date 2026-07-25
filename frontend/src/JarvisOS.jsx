/**
 * JarvisOS.jsx — the operating console.
 *
 * This replaces the "app with pages" model. The shell is ALWAYS live: the status
 * strip, the subsystem rail, the activity timeline and the command bar never go
 * away, no matter what you're looking at. Surfaces (Console / Freelance /
 * Computer / Plans / Skills / Diagnostics) render inside it, sharing one visual
 * language — so it reads as a single system, not a set of screens.
 *
 * Everything on screen is driven by ONE backend call (GET /os/state) plus the SSE
 * feed. Nothing is a placeholder: if a subsystem can't report, it says so.
 * Motion appears only when Jarvis is genuinely working.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { API } from "./config.js";

import Chat from "./pages/Chat";
import Agents from "./pages/Agents";
import WorkspaceHub from "./pages/WorkspaceHub";
import Settings from "./pages/Settings";

/* ── One visual language ─────────────────────────────────────────────────── */
export const T = {
  bg: "#080b11", panel: "#0d1220", panelSoft: "rgba(255,255,255,0.028)",
  line: "rgba(255,255,255,0.075)", text: "#e6edf5", dim: "#7d8798",
  cyan: "#54d6ff", green: "#3ee6a8", amber: "#f5b544",
  red: "#ff5f6d", violet: "#a98bff",
};

const card = {
  background: T.panel, border: `1px solid ${T.line}`, borderRadius: 14,
};
const sectionLabel = {
  fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase",
  color: T.dim, marginBottom: 10, fontWeight: 600,
};

const SURFACES = [
  { id: "console",   label: "Console",   icon: "◈" },
  { id: "chat",      label: "Chat",      icon: "◉" },
  { id: "computer",  label: "Computer",  icon: "⬒" },
  { id: "freelance", label: "Earn",      icon: "◆" },
  { id: "diag",      label: "Diagnostics", icon: "◇" },
  { id: "settings",  label: "Settings",  icon: "⚙" },
];

const LEVEL_COLOR = { info: T.cyan, success: T.green, warning: T.amber, error: T.red };

/* Subsystem accent colours — consistent everywhere they appear. */
const SUB_COLOR = {
  brain: T.violet, desktop: T.cyan, vision: T.amber, browser: T.green,
  automation: T.green, memory: T.violet, models: T.cyan,
};

export default function JarvisOS() {
  const [surface, setSurface] = useState("console");
  const [os, setOs] = useState(null);
  const [feed, setFeed] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState(null);
  const sseRef = useRef(null);

  const [sessionId] = useState(() => {
    try {
      let s = localStorage.getItem("jarvis_session_id");
      if (!s) { s = `s_${Date.now()}`; localStorage.setItem("jarvis_session_id", s); }
      return s;
    } catch { return "console"; }
  });

  /* ONE poll for the whole console. */
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch(`${API}/os/state?timeline=40`);
        if (r.ok && alive) setOs(await r.json());
      } catch { /* backend down — the strip shows it */ }
    };
    load();
    const t = setInterval(load, 6000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  /* Live activity via SSE — the timeline updates the instant something happens. */
  useEffect(() => {
    const connect = () => {
      const es = new EventSource(`${API}/orchestrator/feed`);
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.ping) return;
          setFeed((f) => [{ ...d, _k: Math.random() }, ...f].slice(0, 120));
        } catch { /* ignore malformed frame */ }
      };
      es.onerror = () => { es.close(); setTimeout(connect, 4000); };
      sseRef.current = es;
    };
    connect();
    return () => sseRef.current?.close();
  }, []);

  const run = useCallback(async (text) => {
    const msg = (text ?? input).trim();
    if (!msg) return;
    setInput(""); setBusy(true); setReply(null);
    setFeed((f) => [{ ts: hhmm(), agent: "you", msg, level: "info", _k: Math.random() }, ...f]);
    try {
      const r = await fetch(`${API}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
      });
      const d = await r.json();
      setReply({ text: d.response || "", intent: d.intent });
      setFeed((f) => [{ ts: hhmm(), agent: "jarvis", msg: d.response || "", level: d.intent === "error" ? "error" : "success", _k: Math.random() }, ...f]);
    } catch (e) {
      setReply({ text: `Backend unreachable: ${e.message}`, intent: "error" });
    } finally { setBusy(false); }
  }, [input, sessionId]);

  const online = !!os;
  const working = !!os?.status?.running || busy;
  const statusLabel = busy ? "Thinking" : (os?.status?.label || (online ? "Ready" : "Offline"));
  const statusColor = !online ? T.red : working ? T.amber : T.green;

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column",
                  background: T.bg, color: T.text,
                  fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif" }}>

      {/* ── Status strip: always visible, always true ── */}
      <header style={{ height: 52, flexShrink: 0, display: "flex", alignItems: "center",
                       gap: 18, padding: "0 18px", borderBottom: `1px solid ${T.line}`,
                       background: "rgba(10,14,22,0.9)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {working
            ? <span className="think-ring" style={{ color: statusColor }} />
            : <span style={{ width: 9, height: 9, borderRadius: "50%", background: statusColor,
                             boxShadow: `0 0 10px ${statusColor}` }} />}
          <span style={{ fontWeight: 700, letterSpacing: "0.2em", fontSize: 14 }}>JARVIS</span>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ color: statusColor, fontSize: 13, fontWeight: 600 }}>{statusLabel}</span>
          {os?.goal && <span style={{ color: T.dim, fontSize: 12 }}>· {os.goal.text}</span>}
        </div>
        <div style={{ flex: 1 }} />
        <Metric label="CPU" value={os?.system?.cpu} unit="%" danger={os?.system?.cpu > 85} />
        <Metric label="RAM" value={os?.system?.ram} unit="%" danger={os?.system?.ram > 85} />
        <div style={{ fontSize: 11, color: T.dim }}>
          {os?.ollama?.online
            ? <span>{(os.ollama.fast || "model").split(":")[0]}</span>
            : <span style={{ color: T.red }}>ollama offline</span>}
        </div>
      </header>

      {/* ── Body: rail · surface · timeline (all persistent) ── */}
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>

        <nav style={{ width: 76, flexShrink: 0, borderRight: `1px solid ${T.line}`,
                      display: "flex", flexDirection: "column", gap: 2, padding: "10px 8px" }}>
          {SURFACES.map((s) => {
            const on = surface === s.id;
            return (
              <button key={s.id} onClick={() => setSurface(s.id)} title={s.label}
                style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
                         padding: "10px 4px", borderRadius: 10, border: "none",
                         background: on ? "rgba(84,214,255,0.12)" : "transparent",
                         color: on ? T.cyan : T.dim, fontSize: 9, letterSpacing: "0.06em" }}>
                <span style={{ fontSize: 16 }}>{s.icon}</span>{s.label}
              </button>
            );
          })}
        </nav>

        <main style={{ flex: 1, minWidth: 0, overflow: "auto" }}>
          {surface === "console"   && <Console os={os} onRun={run} reply={reply} busy={busy} />}
          {surface === "chat"      && <Chat />}
          {surface === "computer"  && <Agents />}
          {surface === "freelance" && <WorkspaceHub />}
          {surface === "diag"      && <Diagnostics />}
          {surface === "settings"  && <Settings />}
        </main>

        {/* Timeline — the sense that something is always happening. */}
        <aside style={{ width: 300, flexShrink: 0, borderLeft: `1px solid ${T.line}`,
                        display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ padding: "12px 14px 8px", ...sectionLabel, marginBottom: 0 }}>Activity</div>
          <div style={{ flex: 1, overflowY: "auto", padding: "4px 10px 12px" }}>
            {feed.length === 0 && (
              <div style={{ color: T.dim, fontSize: 12, padding: 8 }}>
                Quiet. Ask Jarvis something and this fills up live.
              </div>
            )}
            {feed.map((f) => (
              <div key={f._k} className="tl-row"
                   style={{ display: "flex", gap: 8, padding: "6px 4px",
                            borderBottom: `1px solid rgba(255,255,255,0.03)` }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", marginTop: 6, flexShrink: 0,
                               background: LEVEL_COLOR[f.level] || T.dim }} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.08em",
                                textTransform: "uppercase" }}>
                    {f.ts} · {f.agent}
                  </div>
                  <div style={{ fontSize: 12, color: T.text, opacity: 0.9, wordBreak: "break-word" }}>
                    {String(f.msg || "").slice(0, 260)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </div>

      {/* ── Command bar: always there, whatever you're looking at ── */}
      <div style={{ flexShrink: 0, borderTop: `1px solid ${T.line}`, padding: "10px 14px",
                    background: "rgba(10,14,22,0.9)", display: "flex", gap: 10, alignItems: "center" }}>
        <span style={{ color: working ? T.amber : T.cyan, fontSize: 15 }}>{working ? "◐" : "›"}</span>
        <input value={input} onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && run()}
               placeholder="Tell Jarvis what to do —  open notepad and type hello  ·  what's on my screen  ·  teach morning: …"
               style={{ flex: 1, background: "transparent", border: "none", outline: "none",
                        color: T.text, fontSize: 14 }} />
        <button onClick={() => run()} disabled={busy}
                style={{ padding: "8px 18px", borderRadius: 10, border: "none",
                         background: busy ? "rgba(255,255,255,0.08)" : T.cyan,
                         color: busy ? T.dim : "#04202b", fontWeight: 700, fontSize: 13 }}>
          {busy ? "Working…" : "Run"}
        </button>
      </div>
    </div>
  );
}

/* ── Console surface: goal + subsystems + what it just said ─────────────── */
function Console({ os, onRun, reply, busy }) {
  const subs = os?.subsystems || {};
  return (
    <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 20 }}>

      {/* Current goal */}
      <div>
        <div style={sectionLabel}>Current goal</div>
        <div style={{ ...card, padding: 18 }} className={os?.status?.running ? "alive" : ""}>
          {os?.goal ? (
            <>
              <div style={{ fontSize: 17, fontWeight: 600 }}>{os.goal.text}</div>
              <div style={{ fontSize: 12, color: T.dim, marginTop: 4 }}>{os.goal.detail}</div>
              {typeof os.goal.progress === "number" && (
                <div style={{ height: 4, background: "rgba(255,255,255,0.06)",
                              borderRadius: 3, marginTop: 12 }}>
                  <div className="progress-fill"
                       style={{ height: 4, width: `${os.goal.progress}%`,
                                background: T.green, borderRadius: 3 }} />
                </div>
              )}
            </>
          ) : (
            <div style={{ color: T.dim, fontSize: 13 }}>
              No active goal. Give Jarvis one below — or start the income engine in Earn
              and it'll work on its own.
            </div>
          )}
        </div>
      </div>

      {/* Last response */}
      {(reply || busy) && (
        <div>
          <div style={sectionLabel}>Jarvis</div>
          <div style={{ ...card, padding: 16, borderLeft: `2px solid ${reply?.intent === "error" ? T.red : T.cyan}` }}>
            {busy && !reply
              ? <span style={{ color: T.dim, fontSize: 13 }}><span className="think-ring" style={{ color: T.amber, marginRight: 8, verticalAlign: "middle" }} />thinking…</span>
              : <div style={{ fontSize: 13.5, lineHeight: 1.65, whiteSpace: "pre-wrap" }}>{reply?.text}</div>}
          </div>
        </div>
      )}

      {/* Subsystems — what every part of Jarvis is doing right now */}
      <div>
        <div style={sectionLabel}>Subsystems</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(215px, 1fr))", gap: 10 }}>
          {Object.entries(subs).map(([name, s]) => {
            const c = SUB_COLOR[name] || T.cyan;
            const active = ["thinking", "running", "watching", "learning"].includes(s.state);
            return (
              <div key={name} style={{ ...card, padding: 14 }} className={active ? "alive" : ""}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 6 }}>
                  <span className={active ? "livedot" : ""}
                        style={{ width: 6, height: 6, borderRadius: "50%",
                                 background: s.ok ? c : T.dim }} />
                  <span style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase",
                                 color: T.dim, fontWeight: 600 }}>{name}</span>
                  <span style={{ flex: 1 }} />
                  <span style={{ fontSize: 11, color: s.ok ? c : T.dim }}>{s.state}</span>
                </div>
                <div style={{ fontSize: 11.5, color: T.dim, lineHeight: 1.45 }}>{s.detail}</div>
              </div>
            );
          })}
          {Object.keys(subs).length === 0 && (
            <div style={{ color: T.dim, fontSize: 13 }}>Waiting for the backend…</div>
          )}
        </div>
      </div>

      {/* Quick starts */}
      <div>
        <div style={sectionLabel}>Try</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {["what's on my screen", "open notepad and type hello", "what can you do",
            "status", "check my qq messages"].map((q) => (
            <button key={q} onClick={() => onRun(q)}
              style={{ padding: "8px 13px", borderRadius: 10, fontSize: 12,
                       background: "rgba(84,214,255,0.07)", color: T.cyan,
                       border: `1px solid rgba(84,214,255,0.25)` }}>{q}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Diagnostics: the exact execution path of every request ─────────────── */
function Diagnostics() {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  const load = () => fetch(`${API}/os/diagnostics`).then((r) => r.json())
    .then(setData).catch(() => setData(null));
  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, []);

  return (
    <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 18 }}>
      <div>
        <div style={sectionLabel}>Routing health</div>
        <div style={{ ...card, padding: 16, display: "flex", gap: 26 }}>
          {[["requests", data?.traces?.recent ?? "—"],
            ["completed", data?.traces?.completed ?? "—"],
            ["failed", data?.traces?.failed ?? "—"],
            ["worst", data?.traces?.worst_component || "none"]].map(([k, v]) => (
            <div key={k}>
              <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.14em",
                            textTransform: "uppercase" }}>{k}</div>
              <div style={{ fontSize: 16, fontWeight: 700,
                            color: k === "failed" && v > 0 ? T.red : T.text }}>{String(v)}</div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div style={sectionLabel}>Execution paths (most recent first)</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {(data?.recent || []).map((t) => (
            <div key={t.id} style={{ ...card, padding: 13 }}>
              <div onClick={() => setOpen(open === t.id ? null : t.id)}
                   style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%",
                               background: t.ok === false ? T.red : t.ok ? T.green : T.dim }} />
                <span style={{ fontSize: 13, flex: 1 }}>{t.label}</span>
                <span style={{ fontSize: 11, color: T.dim }}>{t.steps?.length || 0} hops</span>
                <span style={{ fontSize: 11, color: T.dim }}>{t.duration_ms ?? "—"}ms</span>
              </div>
              {open === t.id && (
                <div style={{ marginTop: 10, paddingLeft: 16, borderLeft: `1px solid ${T.line}` }}>
                  {(t.steps || []).map((s, i) => (
                    <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "4px 0" }}>
                      <span style={{ color: s.ok === false ? T.red : s.ok ? T.green : T.dim, width: 12 }}>
                        {s.ok === false ? "✕" : s.ok ? "✓" : "·"}
                      </span>
                      <span style={{ color: T.cyan, minWidth: 190 }}>{s.component}</span>
                      <span style={{ color: T.dim, flex: 1 }}>{s.detail}</span>
                      <span style={{ color: T.dim }}>{s.at_ms}ms</span>
                    </div>
                  ))}
                  <div style={{ fontSize: 12, color: t.ok ? T.green : T.red, marginTop: 8 }}>
                    → {t.result}
                  </div>
                </div>
              )}
            </div>
          ))}
          {(!data?.recent || data.recent.length === 0) && (
            <div style={{ color: T.dim, fontSize: 13 }}>
              No requests traced yet. Run a command and its exact path appears here.
            </div>
          )}
        </div>
      </div>

      <div>
        <div style={sectionLabel}>Capabilities</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(210px,1fr))", gap: 8 }}>
          {(data?.capabilities || []).map((c) => (
            <div key={c.name} style={{ ...card, padding: "10px 12px", display: "flex",
                                       alignItems: "center", gap: 8 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%",
                             background: c.available ? T.green : T.amber }} />
              <span style={{ fontSize: 12, flex: 1 }}>{c.name}</span>
              {!c.available && <span style={{ fontSize: 10, color: T.amber }}>
                needs {c.missing.join(", ")}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, unit, danger }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
      <span style={{ fontSize: 9, color: T.dim, letterSpacing: "0.14em" }}>{label}</span>
      <span className="smooth" style={{ fontSize: 13, fontWeight: 600,
                                        color: danger ? T.red : T.text }}>
        {value != null ? `${value}${unit}` : "—"}
      </span>
    </div>
  );
}

const hhmm = () => new Date().toLocaleTimeString("en-GB", { hour12: false });
