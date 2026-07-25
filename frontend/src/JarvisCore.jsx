import React, { useEffect, useRef, useState } from "react";

const C = {
  bg: "#090B10", surfaceDeep: "#0d1017", text: "#eef0f4", dim: "#7e828d",
  amber: "#F2B84B", emerald: "#3CE6A7", cyan: "#87E7FF", crimson: "#FF5A5F",
};
const STATES = {
  idle:      { label: "Idle",              color: C.cyan,    speed: 0.45, beam: null },
  thinking:  { label: "Thinking",          color: C.cyan,    speed: 1.4,  beam: null },
  scouting:  { label: "Scouting",          color: C.emerald, speed: 1.1,  beam: "left" },
  proposing: { label: "Drafting Proposal", color: C.amber,   speed: 1.0,  beam: "right" },
  executing: { label: "Executing",         color: C.amber,   speed: 1.9,  beam: "bottom" },
  approval:  { label: "Approval Required", color: C.crimson, speed: 0.5,  beam: null },
  speaking:  { label: "Responding",        color: C.emerald, speed: 1.0,  beam: null },
};
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
function drawHex(ctx, x, y, r) {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2, px = x + Math.cos(a) * r, py = y + Math.sin(a) * r;
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
  }
  ctx.closePath(); ctx.stroke();
}

// (Decorative canvas animations removed — status is shown as real text.)

const matDeep  = { background: C.surfaceDeep, border: "1px solid rgba(255,255,255,0.05)", borderRadius: 18 };
const matFrost = { background: "rgba(28,32,40,0.5)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 16, backdropFilter: "blur(24px)", WebkitBackdropFilter: "blur(24px)" };
const matMetal = (c) => ({ background: `linear-gradient(135deg, ${hexA(c,0.16)}, ${hexA(c,0.04)})`, border: `1px solid ${hexA(c,0.35)}`, borderRadius: 16, boxShadow: `inset 0 1px 0 ${hexA("#ffffff",0.08)}, 0 0 24px ${hexA(c,0.12)}` });
const btn = (c, filled) => ({ padding: "12px 20px", borderRadius: 12, border: filled?"none":`1px solid ${hexA(c,0.4)}`, background: filled?c:"transparent", color: filled?"#0a0a0a":c, fontSize: 13, fontWeight: 700, cursor: "pointer", letterSpacing: 0.3 });
const now = () => new Date().toLocaleTimeString("en-GB", { hour12: false });
const greeting = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };

const API = (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_API_URL) || "http://127.0.0.1:8000";

// Consumes /orchestrator/sse. Auto-reconnects. Reports connection state so the
// component can fall back to the demo timer only while disconnected.
function useOrchestratorFeed(onEvent) {
  const [connected, setConnected] = useState(false);
  const esRef = useRef(null);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;
  useEffect(() => {
    let stopped = false;
    let retry;
    const connect = () => {
      if (stopped) return;
      const es = new EventSource(API + "/orchestrator/sse");
      esRef.current = es;
      es.onopen = () => setConnected(true);
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.ping) return;
          cbRef.current && cbRef.current(d);
        } catch (_) { /* ignore malformed frame */ }
      };
      es.onerror = () => {
        setConnected(false);
        es.close();
        if (!stopped) retry = setTimeout(connect, 3000);
      };
    };
    connect();
    return () => { stopped = true; clearTimeout(retry); esRef.current && esRef.current.close(); };
  }, []);
  return { connected };
}

export default function JarvisCore() {
  const [state, setState] = useState("idle");
  const [panel, setPanel] = useState("Command");
  const [sys, setSys] = useState(null);          // REAL cpu/ram/disk from /stats
  const [health, setHealth] = useState(null);    // REAL model/provider from /health
  const [incomeStat, setIncomeStat] = useState(null);
  const [agents, setAgents] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [brainStatus, setBrainStatus] = useState(null);
  const [brainDocs, setBrainDocs] = useState([]);
  const [brainQuery, setBrainQuery] = useState("");
  const [brainResults, setBrainResults] = useState(null);
  const [noteText, setNoteText] = useState("");
  const [noteProject, setNoteProject] = useState("");
  const [noteKind, setNoteKind] = useState("note");
  const [workflows, setWorkflows] = useState([]);
  const [wfName, setWfName] = useState("");
  const [wfText, setWfText] = useState("");
  const [wfMsg, setWfMsg] = useState("");
  const loadWorkflows = () => fetch(API + "/workflows").then(r => r.json())
    .then(d => setWorkflows(d.workflows || [])).catch(() => setWorkflows([]));
  const teachWorkflow = async () => {
    if (!wfName.trim() || !wfText.trim()) { setWfMsg("Give it a name and describe what to do."); return; }
    try {
      const r = await fetch(API + "/workflows", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: wfName.trim(), text: wfText.trim() }) });
      const d = await r.json();
      setWfMsg(r.ok ? `Learned "${d.name}" (${d.step_count} steps). Say "run my ${d.name}".` : (d.detail || "couldn't learn that"));
      if (r.ok) { setWfName(""); setWfText(""); loadWorkflows(); }
    } catch (e) { setWfMsg(String(e)); }
  };
  const runWorkflow = (n) => fetch(API + `/workflows/${encodeURIComponent(n)}/run`, { method: "POST" }).then(() => loadWorkflows());
  const delWorkflow = (n) => fetch(API + `/workflows/${encodeURIComponent(n)}`, { method: "DELETE" }).then(() => loadWorkflows());
  const loadBrain = () => {
    fetch(API + "/brain/status").then(r => r.json()).then(setBrainStatus).catch(() => setBrainStatus(null));
    fetch(API + "/brain/documents").then(r => r.json()).then(d => setBrainDocs(d.documents || [])).catch(() => setBrainDocs([]));
  };
  const saveNote = async () => {
    if (!noteText.trim()) return;
    await fetch(API + "/brain/ingest", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: noteText.slice(0, 60), text: noteText,
                             project: noteProject.trim(), source: noteKind }) }).catch(() => {});
    setNoteText(""); loadBrain();
  };
  const uploadBrainFile = async (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    await fetch(API + "/brain/upload", { method: "POST", body: fd }).catch(() => {});
    e.target.value = ""; loadBrain();
  };
  const searchBrain = async () => {
    if (!brainQuery.trim()) { setBrainResults(null); return; }
    const r = await fetch(API + "/brain/search?q=" + encodeURIComponent(brainQuery) + "&k=5")
      .then(r => r.json()).catch(() => null);
    setBrainResults(r);
  };
  const deleteBrainDoc = async (id) => {
    await fetch(API + "/brain/document/" + id, { method: "DELETE" }).catch(() => {});
    loadBrain();
  };
  const [plans, setPlans] = useState([]);
  const [planGoal, setPlanGoal] = useState("");
  const [planName, setPlanName] = useState("");
  const [doctor, setDoctor] = useState(null);
  const loadPlans = () => {
    fetch(API + "/planner/projects").then(r => r.json()).then(d => setPlans(d.projects || [])).catch(() => setPlans([]));
  };
  const createPlan = async () => {
    if (!planName.trim()) return;
    await fetch(API + "/planner/project", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: planName.trim(), goal: planGoal.trim(), title: planName.trim() }) }).catch(() => {});
    setPlanName(""); setPlanGoal(""); loadPlans();
  };
  const cycleStep = async (stepId, cur) => {
    const order = ["todo", "doing", "done", "blocked"];
    const next = order[(order.indexOf(cur) + 1) % order.length];
    await fetch(API + "/planner/step/" + stepId, { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: next }) }).catch(() => {});
    loadPlans();
  };
  const deletePlan = async (id) => {
    await fetch(API + "/planner/project/" + id, { method: "DELETE" }).catch(() => {});
    loadPlans();
  };
  const [runningPlans, setRunningPlans] = useState({});
  const runPlan = async (id) => {
    setRunningPlans((r) => ({ ...r, [id]: true }));
    await fetch(API + "/planner/project/" + id + "/execute", { method: "POST" }).catch(() => {});
    // poll progress while it runs, then refresh a final time
    const poll = setInterval(async () => {
      loadPlans();
      try {
        const r = await fetch(API + "/planner/project/" + id + "/executing");
        const d = await r.json();
        if (!d.executing) {
          clearInterval(poll);
          setRunningPlans((x) => ({ ...x, [id]: false }));
          loadPlans();
        }
      } catch { clearInterval(poll); setRunningPlans((x) => ({ ...x, [id]: false })); }
    }, 3000);
  };
  const loadDoctor = () => {
    fetch(API + "/system/doctor").then(r => r.json()).then(setDoctor).catch(() => setDoctor(null));
  };
  useEffect(() => {
    if (panel === "Brain") loadBrain();
    if (panel === "Plans") loadPlans();
    if (panel === "Skills") loadWorkflows();
    if (panel === "Settings") loadDoctor();
    if (panel === "Agents") {
      fetch(API + "/agents/status").then(r => r.json())
        .then(d => {
          // backend shape: {commander:"online", desktop:{...}, vision:{...}, intent_map:[...]}
          const list = [];
          Object.entries(d || {}).forEach(([k, v]) => {
            if (k === "intent_map") return;
            if (v && typeof v === "object" && !Array.isArray(v)) {
              list.push({ name: k, status: v.status || v.state || (v.available ? "online" : "idle"), ...v });
            } else {
              list.push({ name: k, status: String(v) });
            }
          });
          setAgents(list);
        })
        .catch(() => setAgents([]));
    }
    if (panel === "Tasks") {
      fetch(API + "/automation/platform-jobs?limit=25").then(r => r.json())
        .then(d => setJobs(d.jobs || []))
        .catch(() => setJobs([]));
    }
  }, [panel]);
  const [input, setInput] = useState("");
  const [feed, setFeed] = useState([]);
  // One session shared with the Chat tab, persisted in localStorage — so Core
  // and Chat are the same conversation and messages survive a refresh.
  const [sessionId] = useState(() => {
    try {
      let s = localStorage.getItem("jarvis_session_id");
      if (!s) { s = `s_${Date.now()}`; localStorage.setItem("jarvis_session_id", s); }
      return s;
    } catch { return "core"; }
  });
  // Restore prior conversation from the backend on mount (fixes "Core doesn't
  // save messages" — they were saved server-side but never loaded back).
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/chat/history/${sessionId}`);
        if (!r.ok) return;
        const d = await r.json();
        const hist = (d.messages || []).map((m) => ({
          t: "", a: m.role === "assistant" ? "JARVIS" : "YOU",
          c: m.role === "assistant" ? C.amber : C.cyan, m: m.content,
        })).reverse(); // feed renders newest-first
        if (hist.length) setFeed((f) => [...hist, ...f].slice(0, 50));
      } catch {}
      // Pulse: proactive notifications that fired while the app was closed
      // (briefing, plan nudges, new jobs, system warnings).
      try {
        const r = await fetch(`${API}/pulse/recent?unseen=1&limit=10`);
        if (!r.ok) return;
        const d = await r.json();
        const lvl = { info: C.cyan, success: C.emerald, warning: C.amber, error: C.crimson };
        const ev = (d.events || []).map((e) => ({
          t: (e.created_at || "").slice(11, 19), a: "PULSE",
          c: lvl[e.level] || C.emerald, m: e.msg,
        }));
        if (ev.length) {
          setFeed((f) => [...ev, ...f].slice(0, 50));
          fetch(`${API}/pulse/seen`, { method: "POST" }).catch(() => {});
        }
      } catch {}
    })();
  }, [sessionId]);
  // Live event from /orchestrator/sse -> drive core state + live feed panel.
  const onEvent = (d) => {
    if (d.state && STATES[d.state]) setState(d.state);
    const colorMap = { info: C.cyan, success: C.emerald, warning: C.amber, error: C.crimson };
    setFeed((prev) => [{
      t: (d.ts && String(d.ts).slice(11, 19)) || now(),
      a: (d.agent || "SYS").toUpperCase(),
      c: colorMap[d.level] || C.dim,
      m: d.msg || "",
    }, ...prev].slice(0, 50));
  };
  const { connected } = useOrchestratorFeed(onEvent);

  // Demo timer runs ONLY while the feed is disconnected (pure-frontend preview).
  useEffect(() => {
    if (connected) return;
    const seq = ["idle","thinking","scouting","proposing","executing","approval","speaking"];
    let i = 0;
    const id = setInterval(() => { i = (i+1)%seq.length; setState(seq[i]); }, 3800);
    return () => clearInterval(id);
  }, [connected]);
  const [worldSummary, setWorldSummary] = useState("");
  const [brainEvents, setBrainEvents] = useState([]);
  // Real system telemetry — replaces the hardcoded "9.9 / 16 GB" fake numbers.
  useEffect(() => {
    const poll = () => {
      fetch(API + "/stats").then(r => r.json()).then(setSys).catch(() => {});
      fetch(API + "/health").then(r => r.json()).then(setHealth).catch(() => {});
      fetch(API + "/automation/income/status").then(r => r.json()).then(setIncomeStat).catch(() => {});
      fetch(API + "/world/summary").then(r => r.json()).then(d => setWorldSummary(d.summary || "")).catch(() => {});
      fetch(API + "/events/recent?limit=6").then(r => r.json()).then(d => setBrainEvents(d.events || [])).catch(() => {});
    };
    poll(); const t = setInterval(poll, 8000); return () => clearInterval(t);
  }, []);

  const runCommand = async (msg) => {
    if (!msg || !msg.trim()) return;
    setFeed((f) => [{ t: now(), a: "YOU", c: C.cyan, m: msg }, ...f].slice(0, 50));
    setState("thinking");
    try {
      const res = await fetch(API + "/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
      });
      const data = await res.json();
      const reply = data.response || data.reply || "";
      if (reply) setFeed((f) => [{ t: now(), a: "JARVIS", c: C.amber, m: reply }, ...f].slice(0, 50));
    } catch (err) {
      setFeed((f) => [{ t: now(), a: "ERROR", c: C.crimson, m: "Backend unreachable" }, ...f].slice(0, 50));
    } finally { setState("idle"); }
  };
  const send = async () => {
    if (!input.trim()) return;
    const msg = input; setInput("");
    await runCommand(msg);
  };
  const s = STATES[state];
  return (
    <div style={{ height: "100%", display: "flex", background: C.bg, color: C.text, fontFamily: "Inter, system-ui, sans-serif", overflow: "hidden" }}>
      <aside style={{ width: "18%", minWidth: 190, padding: 20, display: "flex", flexDirection: "column", gap: 6, borderRight: "1px solid rgba(255,255,255,0.04)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 22 }}>
          <div style={{ width: 36, height: 36, ...matMetal(C.amber), display: "grid", placeItems: "center" }}>
            <span style={{ color: C.amber, fontSize: 16 }}>◆</span>
          </div>
          <div>
            <div style={{ fontWeight: 800, letterSpacing: 3, color: C.amber, fontSize: 15 }}>JARVIS</div>
            <div style={{ fontSize: 9, color: C.dim, letterSpacing: 1 }}>LOCAL CORE</div>
          </div>
        </div>
        {["Command","Agents","Skills","Brain","Plans","Settings"].map((x) => (
          <div key={x} onClick={() => setPanel(x)} style={{ padding: "11px 12px", borderRadius: 10, fontSize: 13, cursor: "pointer", color: panel===x?C.amber:C.dim, background: panel===x?hexA(C.amber,0.07):"transparent", borderLeft: panel===x?`2px solid ${C.amber}`:"2px solid transparent" }}>{x}</div>
        ))}
        <div style={{ marginTop: "auto", ...matFrost, padding: 12, fontSize: 11, color: C.dim }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span>RAM</span>
            <span style={{ color: sys && sys.ram > 85 ? C.crimson : C.emerald }}>{sys ? `${Math.round(sys.ram)}%` : "—"}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
            <span>CPU</span><span style={{ color: C.cyan }}>{sys ? `${Math.round(sys.cpu)}%` : "—"}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
            <span>Model</span><span style={{ color: C.amber }}>{health?.model ? String(health.model).split(":")[0] : "—"}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
            <span>Ollama</span><span style={{ color: health?.ollama ? C.emerald : C.crimson }}>{health?.ollama ? "up" : "down"}</span>
          </div>
        </div>
      </aside>
      <main style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, position: "relative", minHeight: 0, overflow: "auto" }}>
          {/* Real status board — replaces the fake animated core. Everything here
              is live data, not decoration. */}
          {panel === "Command" && (() => {
            const busy = ["thinking","executing","scouting","proposing"].includes(state);
            const sectionLabel = { fontSize: 10, color: C.dim, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 9 };
            return (
            <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
              {/* ── State banner: the living heart. Animates ONLY when working. ── */}
              <div className={busy ? "alive" : ""} style={{
                ...matMetal(s.color), padding: "18px 22px",
                display: "flex", alignItems: "center", gap: 16, position: "relative", overflow: "hidden",
              }}>
                {busy && <div className="busy-sweep" style={{ position: "absolute", inset: 0, pointerEvents: "none" }} />}
                {busy
                  ? <span className="think-ring" style={{ color: s.color }} />
                  : <span style={{ width: 14, height: 14, borderRadius: "50%", background: s.color, boxShadow: `0 0 10px ${s.color}` }} />}
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: C.dim, letterSpacing: 1 }}>{greeting()} · Jarvis is</div>
                  <div style={{ fontSize: 21, fontWeight: 700, color: s.color }}>{s.label}</div>
                  {worldSummary && <div style={{ fontSize: 12, color: C.dim, marginTop: 3 }}>{worldSummary}</div>}
                </div>
                {incomeStat?.enabled && (
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 9, color: C.dim, letterSpacing: 1 }}>INCOME ENGINE</div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: C.emerald }}>{incomeStat.cycles ?? 0} <span style={{ fontSize: 11, color: C.dim }}>cycles</span></div>
                  </div>
                )}
              </div>

              {/* ── System status: real telemetry, smooth transitions ── */}
              <div>
                <div style={sectionLabel}>System status</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
                  {[
                    ["CPU", sys ? Math.round(sys.cpu) : null, "%", sys && sys.cpu > 85 ? C.crimson : C.cyan],
                    ["RAM", sys ? Math.round(sys.ram) : null, "%", sys && sys.ram > 85 ? C.crimson : C.emerald],
                    ["OLLAMA", null, health?.ollama ? "online" : "offline", health?.ollama ? C.emerald : C.crimson],
                    ["MODEL", null, health?.model ? String(health.model).split(":")[0] : "—", C.amber],
                  ].map(([l, v, unit, c]) => (
                    <div key={l} style={{ ...matDeep, padding: "12px 14px" }}>
                      <div style={{ fontSize: 9, color: C.dim, letterSpacing: 1.4, marginBottom: 6 }}>{l}</div>
                      <div className="smooth" style={{ fontSize: 17, fontWeight: 700, color: c }}>
                        {v != null ? v : ""}<span style={{ fontSize: v != null ? 11 : 14, color: v != null ? C.dim : c, marginLeft: v != null ? 1 : 0 }}>{unit}</span>
                      </div>
                      {typeof v === "number" && (
                        <div style={{ height: 3, background: "rgba(255,255,255,0.06)", borderRadius: 2, marginTop: 7 }}>
                          <div className="progress-fill" style={{ height: 3, width: `${v}%`, background: c, borderRadius: 2 }} />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* ── Ask / quick actions ── */}
              <div>
                <div style={sectionLabel}>Ask Jarvis</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {["what's on my screen","open notepad and type hello","scan freelance jobs now","what can you do","check my qq messages"].map((q) => (
                    <button key={q} onClick={() => runCommand(q)}
                      style={{ ...btn(C.cyan), background: hexA(C.cyan, 0.07), fontSize: 12, padding: "8px 13px", borderRadius: 10 }}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>

              {/* ── Activity timeline: the living record (chat + real events, newest first) ── */}
              <div style={{ flex: 1, minHeight: 0 }}>
                <div style={sectionLabel}>Activity timeline</div>
                <div style={{ ...matDeep, padding: "6px 4px", maxHeight: 260, overflowY: "auto" }}>
                  {feed.length === 0 && brainEvents.length === 0 && (
                    <div style={{ color: C.dim, fontSize: 12, padding: 12 }}>Nothing yet — ask Jarvis something, or it'll show what it notices here.</div>
                  )}
                  {feed.slice(0, 40).map((f, i) => (
                    <div key={i} className="tl-row" style={{ display: "flex", gap: 10, alignItems: "baseline", padding: "6px 12px", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: f.c, marginTop: 5, flexShrink: 0 }} />
                      <span style={{ color: C.dim, fontSize: 10, width: 58, flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>{f.t}</span>
                      <span style={{ color: f.c, fontSize: 10, textTransform: "uppercase", width: 62, flexShrink: 0 }}>{f.a}</span>
                      <span style={{ color: C.text, fontSize: 12, opacity: 0.9 }}>{f.m}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            );
          })()}
          {panel !== "Command" && (
            <div style={{ position: "absolute", inset: 0, ...matFrost, borderRadius: 0, padding: 22, overflowY: "auto" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <span style={{ fontSize: 16, fontWeight: 700, color: C.amber, letterSpacing: 1 }}>{panel}</span>
                <span onClick={() => setPanel("Command")} style={{ cursor: "pointer", color: C.dim, fontSize: 18 }}>✕</span>
              </div>
              {panel === "Agents" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {agents.length === 0 && <div style={{ color: C.dim, fontSize: 13 }}>No agents reported by backend.</div>}
                  {agents.map((a, i) => (
                    <div key={i} style={{ ...matDeep, padding: 14, display: "flex", justifyContent: "space-between" }}>
                      <span style={{ fontWeight: 600 }}>{a.name || a.id || `agent ${i}`}</span>
                      <span style={{ color: (a.status === "online" || a.online) ? C.emerald : C.dim, fontSize: 11, textTransform: "uppercase" }}>
                        {a.status || (a.online ? "online" : "idle")}
                      </span>
                    </div>
                  ))}
                  <div style={{ ...matDeep, padding: 14, color: C.dim, fontSize: 12, borderStyle: "dashed" }}>
                    + Add Agent — coming with the agent registry (backend/agents/registry.py)
                  </div>
                </div>
              )}
              {panel === "Skills" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ ...matDeep, padding: 14 }}>
                    <div style={{ fontSize: 12, color: C.cyan, letterSpacing: 1, marginBottom: 8 }}>TEACH A TASK ONCE</div>
                    <div style={{ fontSize: 12, color: C.dim, marginBottom: 10, lineHeight: 1.6 }}>
                      Describe it in plain words — Jarvis turns it into real steps and remembers it.
                      Later just say <span style={{ color: C.amber }}>"run my &lt;name&gt;"</span>. You can also type
                      <span style={{ color: C.amber }}> teach &lt;name&gt;: …</span> in chat.
                    </div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <input value={wfName} onChange={(e) => setWfName(e.target.value)} placeholder="name (e.g. morning)"
                        style={{ width: 150, background: "rgba(0,0,0,0.3)", color: C.text, border: `1px solid ${hexA(C.cyan, 0.2)}`, borderRadius: 8, padding: 10, fontSize: 13 }} />
                      <input value={wfText} onChange={(e) => setWfText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && teachWorkflow()}
                        placeholder="open chrome, open notepad, type my notes"
                        style={{ flex: 1, minWidth: 200, background: "rgba(0,0,0,0.3)", color: C.text, border: `1px solid ${hexA(C.cyan, 0.2)}`, borderRadius: 8, padding: 10, fontSize: 13 }} />
                      <button onClick={teachWorkflow} style={btn(C.emerald)}>Learn it</button>
                    </div>
                    {wfMsg && <div style={{ fontSize: 12, color: C.emerald, marginTop: 8 }}>{wfMsg}</div>}
                  </div>
                  {workflows.length === 0 && <div style={{ color: C.dim, fontSize: 13 }}>No saved tasks yet. Teach one above.</div>}
                  {workflows.map((w) => (
                    <div key={w.id} style={{ ...matDeep, padding: 14 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontWeight: 700, color: C.amber }}>{w.name}</span>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <span style={{ fontSize: 11, color: C.dim }}>{w.step_count} steps · ran {w.runs || 0}×{w.last_status ? ` · ${w.last_status}` : ""}</span>
                          <button onClick={() => runWorkflow(w.name)} style={{ ...btn(C.emerald), padding: "5px 12px", fontSize: 12 }}>▶ Run</button>
                          <span onClick={() => delWorkflow(w.name)} style={{ cursor: "pointer", color: C.crimson, fontSize: 14 }} title="Delete">✕</span>
                        </div>
                      </div>
                      {w.description && <div style={{ fontSize: 11, color: C.dim, marginTop: 4 }}>{w.description}</div>}
                    </div>
                  ))}
                </div>
              )}
              {panel === "Tasks" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {jobs.length === 0 && <div style={{ color: C.dim, fontSize: 13 }}>No jobs scraped yet — run "scan jobs" or start the pipeline, then reopen this panel.</div>}
                  {jobs.map((j, i) => (
                    <div key={j.id || i} style={{ ...matDeep, padding: 14 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>{j.title || j.name || "Untitled job"}</span>
                        {(j.score != null) && <span style={{ color: C.amber, fontSize: 12 }}>{j.score}</span>}
                      </div>
                      <div style={{ display: "flex", gap: 12, marginTop: 6, fontSize: 11, color: C.dim }}>
                        <span style={{ color: C.cyan, textTransform: "uppercase" }}>{j.platform || "?"}</span>
                        {j.budget && <span>{j.budget}</span>}
                        {j.link && <a href={j.link} target="_blank" rel="noreferrer" style={{ color: C.emerald }}>open ↗</a>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {panel === "Brain" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ fontSize: 12, color: C.dim }}>
                    {brainStatus
                      ? `${brainStatus.documents} documents · ${brainStatus.facts || 0} facts · ${brainStatus.decisions || 0} decisions · ${brainStatus.chat_summaries || 0} learned · mode: ${brainStatus.mode}`
                      : "Brain status unavailable — is the backend running?"}
                    {brainStatus && brainStatus.hint && (
                      <div style={{ color: C.amber, marginTop: 4 }}>{brainStatus.hint}</div>
                    )}
                  </div>
                  <div style={{ ...matDeep, padding: 14 }}>
                    <div style={{ fontSize: 12, color: C.cyan, marginBottom: 8, letterSpacing: 1 }}>FEED YOUR BRAIN</div>
                    <textarea value={noteText} onChange={(e) => setNoteText(e.target.value)}
                      placeholder="Paste anything you want Jarvis to know — notes, project info, research, contacts..."
                      style={{ width: "100%", minHeight: 70, background: "rgba(0,0,0,0.3)", color: C.text,
                               border: `1px solid ${hexA(C.cyan, 0.2)}`, borderRadius: 8, padding: 10, fontSize: 13, resize: "vertical" }} />
                    <div style={{ display: "flex", gap: 10, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <select value={noteKind} onChange={(e) => setNoteKind(e.target.value)}
                        style={{ background: "rgba(0,0,0,0.3)", color: C.text, border: `1px solid ${hexA(C.cyan, 0.2)}`,
                                 borderRadius: 8, padding: "8px 10px", fontSize: 12 }}>
                        <option value="note">Knowledge</option>
                        <option value="fact">Fact about me</option>
                        <option value="decision">Decision (why)</option>
                      </select>
                      <input value={noteProject} onChange={(e) => setNoteProject(e.target.value)}
                        placeholder="project (optional)"
                        style={{ width: 140, background: "rgba(0,0,0,0.3)", color: C.text,
                                 border: `1px solid ${hexA(C.cyan, 0.2)}`, borderRadius: 8, padding: "8px 10px", fontSize: 12 }} />
                      <button onClick={saveNote} style={{ background: hexA(C.amber, 0.15), color: C.amber,
                        border: `1px solid ${hexA(C.amber, 0.4)}`, borderRadius: 8, padding: "8px 16px", cursor: "pointer", fontSize: 13 }}>
                        Save to Brain
                      </button>
                      <label style={{ color: C.cyan, fontSize: 12, cursor: "pointer", textDecoration: "underline" }}>
                        or upload a .txt / .md file
                        <input type="file" accept=".txt,.md,.markdown,.pdf" onChange={uploadBrainFile} style={{ display: "none" }} />
                      </label>
                    </div>
                  </div>
                  <div style={{ ...matDeep, padding: 14 }}>
                    <div style={{ fontSize: 12, color: C.cyan, marginBottom: 8, letterSpacing: 1 }}>SEARCH YOUR BRAIN</div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input value={brainQuery} onChange={(e) => setBrainQuery(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && searchBrain()}
                        placeholder="What do I know about..."
                        style={{ flex: 1, background: "rgba(0,0,0,0.3)", color: C.text,
                                 border: `1px solid ${hexA(C.cyan, 0.2)}`, borderRadius: 8, padding: 10, fontSize: 13 }} />
                      <button onClick={searchBrain} style={{ background: hexA(C.cyan, 0.15), color: C.cyan,
                        border: `1px solid ${hexA(C.cyan, 0.4)}`, borderRadius: 8, padding: "8px 16px", cursor: "pointer", fontSize: 13 }}>
                        Search
                      </button>
                    </div>
                    {brainResults && (
                      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                        {(brainResults.results || []).length === 0 && (
                          <div style={{ color: C.dim, fontSize: 12 }}>No matches.</div>
                        )}
                        {(brainResults.results || []).map((r, i) => (
                          <div key={i} style={{ background: "rgba(0,0,0,0.25)", borderRadius: 8, padding: 10, fontSize: 12 }}>
                            <div style={{ color: C.amber, marginBottom: 4 }}>{r.title} <span style={{ color: C.dim }}>· {r.score}</span></div>
                            <div style={{ color: C.text, whiteSpace: "pre-wrap" }}>{r.text.slice(0, 400)}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div style={{ fontSize: 12, color: C.cyan, letterSpacing: 1 }}>STORED KNOWLEDGE</div>
                  {brainDocs.length === 0 && <div style={{ color: C.dim, fontSize: 13 }}>Brain is empty. Feed it above, or say "remember ..." in chat.</div>}
                  {brainDocs.map((d) => (
                    <div key={d.id} style={{ ...matDeep, padding: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{d.title}</div>
                        <div style={{ fontSize: 11, color: C.dim, marginTop: 3 }}>
                          <span style={{ color: d.source === "fact" ? C.emerald : d.source === "decision" ? C.amber : d.source === "chat_summary" ? C.cyan : C.dim }}>{d.source}</span>
                          {d.project ? <span style={{ color: C.cyan }}> · {d.project}</span> : null}
                          {" · "}{d.chars} chars · {d.chunks} chunks{d.embedded ? ` · ${d.embedded} embedded` : ""}
                        </div>
                      </div>
                      <span onClick={() => deleteBrainDoc(d.id)}
                        style={{ cursor: "pointer", color: C.crimson, fontSize: 16, padding: "0 6px" }} title="Forget">✕</span>
                    </div>
                  ))}
                </div>
              )}
              {panel === "Plans" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ ...matDeep, padding: 14 }}>
                    <div style={{ fontSize: 12, color: C.cyan, marginBottom: 8, letterSpacing: 1 }}>NEW PROJECT PLAN</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <input value={planName} onChange={(e) => setPlanName(e.target.value)}
                        placeholder="project name (e.g. mistore)"
                        style={{ width: 170, background: "rgba(0,0,0,0.3)", color: C.text,
                                 border: `1px solid ${hexA(C.cyan, 0.2)}`, borderRadius: 8, padding: 10, fontSize: 13 }} />
                      <input value={planGoal} onChange={(e) => setPlanGoal(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && createPlan()}
                        placeholder="goal — Jarvis breaks it into steps"
                        style={{ flex: 1, minWidth: 180, background: "rgba(0,0,0,0.3)", color: C.text,
                                 border: `1px solid ${hexA(C.cyan, 0.2)}`, borderRadius: 8, padding: 10, fontSize: 13 }} />
                      <button onClick={createPlan} style={{ background: hexA(C.amber, 0.15), color: C.amber,
                        border: `1px solid ${hexA(C.amber, 0.4)}`, borderRadius: 8, padding: "8px 16px", cursor: "pointer", fontSize: 13 }}>
                        Plan it
                      </button>
                    </div>
                  </div>
                  {plans.length === 0 && <div style={{ color: C.dim, fontSize: 13 }}>No plans yet. Create one above, or say "plan project mistore to launch the store" in chat.</div>}
                  {plans.map((p) => (
                    <div key={p.id} style={{ ...matDeep, padding: 14 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontWeight: 700, color: C.amber }}>{p.title || p.name}</span>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <span style={{ fontSize: 11, color: C.dim }}>{p.done}/{p.total} · {p.progress}%</span>
                          <button onClick={() => runPlan(p.id)} disabled={runningPlans[p.id]}
                            title="Jarvis executes every step: desktop actions run for real, think-steps get their deliverable written and attached"
                            style={{ background: hexA(C.emerald, 0.15), color: runningPlans[p.id] ? C.dim : C.emerald,
                                     border: `1px solid ${hexA(C.emerald, 0.4)}`, borderRadius: 6,
                                     padding: "4px 12px", cursor: runningPlans[p.id] ? "wait" : "pointer", fontSize: 11 }}>
                            {runningPlans[p.id] ? "⟳ running…" : "▶ RUN"}
                          </button>
                          <span onClick={() => deletePlan(p.id)} style={{ cursor: "pointer", color: C.crimson, fontSize: 14 }} title="Delete plan">✕</span>
                        </div>
                      </div>
                      {p.goal && <div style={{ fontSize: 11, color: C.dim, marginTop: 3 }}>{p.goal}</div>}
                      <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 3, margin: "8px 0" }}>
                        <div style={{ height: 4, width: `${p.progress}%`, background: C.emerald, borderRadius: 3 }} />
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 6 }}>
                        {p.steps.map((s) => {
                          const col = s.status === "done" ? C.emerald : s.status === "doing" ? C.amber : s.status === "blocked" ? C.crimson : C.dim;
                          return (
                            <div key={s.id} onClick={() => cycleStep(s.id, s.status)}
                              style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer", fontSize: 12 }}
                              title="Click to change status">
                              <span style={{ width: 58, color: col, textTransform: "uppercase", fontSize: 10 }}>{s.status}</span>
                              <span style={{ color: s.status === "done" ? C.dim : C.text, textDecoration: s.status === "done" ? "line-through" : "none" }}>{s.text}</span>
                              {s.note && <span style={{ color: C.dim, fontSize: 10 }} title={s.note}>📎</span>}
                            </div>
                          );
                        })}
                        {p.steps.some((s) => s.note) && (
                          <details style={{ marginTop: 4 }}>
                            <summary style={{ fontSize: 10, color: C.dim, cursor: "pointer" }}>step outputs / notes</summary>
                            {p.steps.filter((s) => s.note).map((s) => (
                              <div key={"n" + s.id} style={{ fontSize: 11, color: C.text, background: "rgba(0,0,0,0.3)",
                                borderLeft: `2px solid ${C.emerald}`, borderRadius: 4, padding: 8, margin: "6px 0", whiteSpace: "pre-wrap" }}>
                                <div style={{ color: C.dim, fontSize: 10, marginBottom: 3 }}>step {s.seq}: {s.text}</div>
                                {s.note}
                              </div>
                            ))}
                          </details>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {panel === "Settings" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ fontSize: 12, color: C.cyan, letterSpacing: 1 }}>SYSTEM DOCTOR</div>
                  <div style={{ fontSize: 12, color: C.dim }}>
                    {doctor ? doctor.summary : "Running diagnostics..."}
                  </div>
                  {doctor && doctor.checks.map((c, i) => (
                    <div key={i} style={{ ...matDeep, padding: 12 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>
                          <span style={{ color: c.ok ? C.emerald : C.crimson, marginRight: 8 }}>{c.ok ? "✓" : "✕"}</span>
                          {c.name}
                        </span>
                        <span style={{ fontSize: 11, color: C.dim }}>{c.detail}</span>
                      </div>
                      {!c.ok && c.fix && (
                        <div style={{ fontSize: 11, color: C.amber, marginTop: 6, fontFamily: "monospace" }}>→ {c.fix}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {panel !== "Agents" && panel !== "Tasks" && panel !== "Brain" && panel !== "Plans" && panel !== "Settings" && (
                <div style={{ color: C.dim, fontSize: 13 }}>
                  {panel} panel — wired to backend next. (This view confirms the sidebar navigation now works.)
                </div>
              )}
            </div>
          )}
        </div>
        {state === "approval" && (
          <div style={{ margin: "0 32px 12px", ...matMetal(C.crimson), padding: 18 }}>
            <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.crimson, textTransform: "uppercase", marginBottom: 8 }}>⬡ Approval Required</div>
            <div style={{ fontSize: 13, color: C.text, marginBottom: 14, opacity: 0.85 }}>Submit application to RemoteOK — Python Developer. This sends a real proposal.</div>
            <div style={{ display: "flex", gap: 10 }}>
              <button style={btn(C.amber, true)}>Approve &amp; Submit</button>
              <button style={btn(C.dim, false)}>Review First</button>
            </div>
          </div>
        )}
        <div style={{ margin: "0 32px 28px", ...matFrost, padding: 8, display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: C.amber, padding: "0 8px", fontSize: 18 }}>◆</span>
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Command Jarvis…  open chrome · what's on my screen · remember … · plan project …"
            style={{ flex: 1, background: "transparent", border: "none", color: C.text, fontSize: 14, outline: "none" }} />
          <button onClick={send} style={btn(C.amber, true)}>Send</button>
        </div>
      </main>
      <aside style={{ width: "25%", minWidth: 250, padding: 20, display: "flex", flexDirection: "column", gap: 14, borderLeft: "1px solid rgba(255,255,255,0.04)" }}>
        <div style={{ ...matFrost, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: 1.5, textTransform: "uppercase" }}>System</div>
          {[
            ["State", s.label, s.color],
            ["CPU", sys ? `${Math.round(sys.cpu)}%` : "—", C.cyan],
            ["RAM", sys ? `${Math.round(sys.ram)}%` : "—", sys && sys.ram > 85 ? C.crimson : C.emerald],
            ["Disk", sys ? `${Math.round(sys.disk)}%` : "—", C.dim],
            ["Ollama", health?.ollama ? "online" : "offline", health?.ollama ? C.emerald : C.crimson],
            ["Income", incomeStat?.enabled ? `on · ${incomeStat.cycles ?? 0}` : "off", incomeStat?.enabled ? C.emerald : C.dim],
          ].map(([k, v, c]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
              <span style={{ color: C.dim }}>{k}</span><span style={{ color: c }}>{v}</span>
            </div>
          ))}
        </div>
        <div style={{ ...matDeep, padding: 14, flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 12 }}>Live Feed</div>
          <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 9 }}>
            {feed.map((f, i) => (
              <div key={i} style={{ display: "flex", gap: 8, fontSize: 11, fontFamily: "monospace" }}>
                <span style={{ color: C.dim }}>{f.t}</span>
                <span style={{ color: f.c, textTransform: "uppercase" }}>[{f.a}]</span>
                <span>{f.m}</span>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </div>
  );
}
