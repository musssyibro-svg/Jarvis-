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
import Earn from "./pages/Earn";
import Planner from "./pages/Planner";
import Logs from "./pages/Logs";
import Memory from "./pages/Memory";
import Settings from "./pages/Settings";

/* One visual language. Defined in theme.js, which imports nothing.
 *
 * These used to be declared HERE and imported back out by the pages, which made
 * a cycle: JarvisOS -> Planner -> JarvisOS. Vite's dev server evaluates modules
 * natively, so Planner ran first and hit `T.line` at its top level while `T` was
 * still in the temporal dead zone. That threw before React mounted, leaving a
 * blank white page with every file loaded and nothing rendered. `npm run build`
 * did not catch it, because Rollup bundles into one scope and the cycle resolves
 * at build time. Shared tokens belong in a leaf module. */
export { T } from "./theme.js";
import { T, card, sectionLabel } from "./theme.js";

const SURFACES = [
  { id: "console",   label: "Console",   icon: "◈" },
  { id: "chat",      label: "Chat",      icon: "◉" },
  { id: "planner",   label: "Planner",   icon: "◫" },
  { id: "computer",  label: "Computer",  icon: "⬒" },
  { id: "freelance", label: "Earn",      icon: "◆" },
  { id: "memory",    label: "Memory",    icon: "◧" },
  { id: "logs",      label: "Logs",      icon: "≡" },
  { id: "diag",      label: "Diagnostics", icon: "◇" },
  { id: "settings",  label: "Settings",  icon: "⚙" },
];

const LEVEL_COLOR = { info: T.cyan, success: T.green, warning: T.amber, error: T.red };

/**
 * When did this feed event actually happen? (epoch ms, or null if unknowable)
 *
 * Order matters: `_t` is set once when we receive/create the event, `at` is the
 * backend's own epoch stamp, and `ts` ("HH:MM:SS", UTC) is the last resort for
 * events replayed from the state snapshot. Never fall back to "now" — that is
 * precisely the bug that made the activity graph static.
 */
export function eventTime(f) {
  if (!f) return null;
  if (typeof f._t === "number") return f._t;
  if (typeof f.at === "number") return f.at;
  const m = typeof f.ts === "string" && f.ts.match(/^(\d{2}):(\d{2}):(\d{2})$/);
  if (m) {
    const d = new Date();
    const guess = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(),
                           +m[1], +m[2], +m[3]);
    // A stamp "in the future" means it belongs to yesterday (UTC rollover).
    return guess > Date.now() + 60_000 ? guess - 86_400_000 : guess;
  }
  return null;
}

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
  const [history, setHistory] = useState([]);   // rolling CPU/RAM samples
  const [ctrl, setCtrl] = useState(null);       // pause/resume/cancel state
  const [why, setWhy] = useState(null);         // "why are you doing this?"
  const sseRef = useRef(null);

  /* Pause / Resume / Cancel. Optimistic so the button responds immediately,
     then reconciled from the server — a control that lags feels broken, and a
     control that feels broken doesn't get trusted with autonomy. */
  const ctl = useCallback(async (cmd) => {
    setCtrl((c) => ({ ...(c || {}),
                      can_pause: cmd === "resume", can_resume: cmd === "pause",
                      mode: cmd === "pause" ? "pausing"
                          : cmd === "cancel" ? "cancelling" : "running" }));
    try {
      const r = await fetch(`${API}/os/control/${cmd}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (r.ok) setCtrl(await fetch(`${API}/os/control`).then((x) => x.json()));
    } catch { /* the poll below will correct it */ }
  }, []);

  const askWhy = useCallback(async () => {
    if (why) return setWhy(null);               // second press closes it
    try {
      setWhy(await fetch(`${API}/os/explain`).then((r) => r.json()));
    } catch {
      setWhy({ because: ["Couldn't reach the backend to ask."] });
    }
  }, [why]);

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
        if (r.ok && alive) {
          const d = await r.json();
          setOs(d);
          // keep a rolling window of real samples for the vitals graph
          setHistory((h) => [...h, { cpu: d.system?.cpu ?? 0, ram: d.system?.ram ?? 0,
                                     t: Date.now() }].slice(-30));
          // Seed the timeline from what already happened. Without this the
          // console opens blank until the next live event, which reads as
          // "nothing is running" even when Jarvis has been working for hours.
          fetch(`${API}/os/control`).then((x) => x.json()).then(setCtrl).catch(() => {});
          setFeed((f) => (f.length ? f : (d.timeline || []).map((e) => ({
            ...e, _t: eventTime(e), _k: `seed_${e.at || e.ts}_${Math.random()}`,
          }))));
        }
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
          // Stamp with the event's OWN time (backend `at`, epoch ms), falling
          // back to arrival time. Never render time — see activityMarks.
          setFeed((f) => [{ ...d, _t: d.at || Date.now(), _k: Math.random() },
                          ...f].slice(0, 120));
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
    setFeed((f) => [{ ts: hhmm(), agent: "you", msg, level: "info",
                      _t: Date.now(), _k: Math.random() }, ...f]);
    try {
      const r = await fetch(`${API}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
      });
      const d = await r.json();
      setReply({ text: d.response || "", intent: d.intent });
      setFeed((f) => [{ ts: hhmm(), agent: "jarvis", msg: d.response || "",
                        level: d.intent === "error" ? "error" : "success",
                        _t: Date.now(), _k: Math.random() }, ...f]);
    } catch (e) {
      setReply({ text: `Backend unreachable: ${e.message}`, intent: "error" });
    } finally { setBusy(false); }
  }, [input, sessionId]);

  // Activity ticks for the vitals graph: real events from the last 3 minutes,
  // positioned by when they ACTUALLY happened.
  //
  // The previous version stamped every event with the render-time `now` the
  // first time it was drawn. That made the graph a fiction: a backlog replayed
  // on reconnect all landed on the right-hand edge together, and events that
  // arrived seconds apart were indistinguishable. Now each event carries its
  // own time — `at` from the backend, or arrival time for locally-created ones.
  const activityMarks = (() => {
    const now = Date.now(), WINDOW = 180_000;
    return feed.slice(0, 60).map((f) => {
      const t = eventTime(f);
      if (t == null) return null;
      const age = now - t;
      if (age < 0 || age > WINDOW) return null;
      return { x: 1 - age / WINDOW, color: LEVEL_COLOR[f.level] || T.dim };
    }).filter(Boolean);
  })();

  // The newest real event, with how long ago it happened — drives the live
  // strip. Events from Jarvis itself only; echoing the user's own message back
  // as "currently doing" would be a lie.
  const liveNow = (() => {
    const e = feed.find((f) => f.agent && f.agent !== "you" && f.msg);
    if (!e) return null;
    const t = eventTime(e);
    const secs = t ? Math.max(0, Math.round((Date.now() - t) / 1000)) : null;
    const ago = secs == null ? ""
      : secs < 5 ? "just now"
      : secs < 60 ? `${secs}s ago`
      : secs < 3600 ? `${Math.round(secs / 60)}m ago`
      : `${Math.round(secs / 3600)}h ago`;
    return { agent: e.agent, msg: String(e.msg).slice(0, 200), ago };
  })();

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

      {/*
        "What is it doing RIGHT NOW?" — the single most requested thing.

        Jarvis was working perfectly well and saying nothing about it, so from
        the outside a 20-minute scan and a crash look identical. This strip is
        the last real event plus how long ago, so there is always an answer to
        "is something happening?" — visible from every surface, not just Earn.
        It hides itself when genuinely idle rather than inventing reassurance.
      */}
      {liveNow && (
        <div style={{ flexShrink: 0, display: "flex", alignItems: "center", gap: 10,
                      padding: "7px 18px", fontSize: 12.5,
                      borderBottom: `1px solid ${T.line}`,
                      background: working ? "rgba(84,214,255,0.07)" : "rgba(255,255,255,0.02)",
                      color: working ? T.cyan : T.dim }}>
          {working
            ? <span className="think-ring" style={{ color: T.cyan, width: 13, height: 13 }} />
            : <span style={{ width: 6, height: 6, borderRadius: "50%", background: T.dim }} />}
          <span style={{ textTransform: "uppercase", fontSize: 9, letterSpacing: "0.14em",
                         opacity: 0.65 }}>{liveNow.agent}</span>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                         textOverflow: "ellipsis", whiteSpace: "nowrap",
                         color: working ? T.text : T.dim }}>
            {liveNow.msg}
          </span>
          <span style={{ fontSize: 11, opacity: 0.6 }}>{liveNow.ago}</span>

          {/* Being able to STOP is part of trusting it to run on its own.
              Neither button kills anything mid-action — the current step
              always finishes first. */}
          <button onClick={() => ctl(ctrl?.can_resume ? "resume" : "pause")}
            style={{ padding: "3px 10px", borderRadius: 7, fontSize: 11, cursor: "pointer",
                     background: "transparent", color: ctrl?.can_resume ? T.green : T.dim,
                     border: `1px solid ${ctrl?.can_resume ? T.green : T.line}` }}>
            {ctrl?.can_resume ? "Resume" : "Pause"}
          </button>
          {working && (
            <button onClick={() => ctl("cancel")}
              style={{ padding: "3px 10px", borderRadius: 7, fontSize: 11, cursor: "pointer",
                       background: "transparent", color: T.red,
                       border: `1px solid rgba(255,95,109,0.4)` }}>
              Stop
            </button>
          )}
          <button onClick={askWhy} title="Why are you doing this?"
            style={{ padding: "3px 10px", borderRadius: 7, fontSize: 11, cursor: "pointer",
                     background: "transparent", color: T.dim, border: `1px solid ${T.line}` }}>
            Why?
          </button>
        </div>
      )}

      {/* Plain-English answer to "why", built from the real execution trace. */}
      {why && (
        <div style={{ flexShrink: 0, padding: "10px 18px", fontSize: 12.5,
                      borderBottom: `1px solid ${T.line}`,
                      background: "rgba(169,139,255,0.06)", color: T.text }}>
          <div style={{ display: "flex", gap: 10 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              {why.goal && <div style={{ marginBottom: 4 }}>
                <span style={{ color: T.dim }}>Goal: </span>{why.goal}</div>}
              {(why.because || []).map((b, i) => (
                <div key={i} style={{ color: T.dim, lineHeight: 1.6 }}>· {b}</div>
              ))}
            </div>
            <button onClick={() => setWhy(null)}
              style={{ background: "none", border: "none", color: T.dim,
                       cursor: "pointer", fontSize: 15, alignSelf: "flex-start" }}>✕</button>
          </div>
        </div>
      )}

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

        {/*
          Surfaces stay MOUNTED and are hidden with CSS rather than unmounted.

          Conditional rendering destroys a surface the moment you navigate away,
          taking its state with it: the Earn page lost its queue, its scan
          results and the site you were half-way through adding every single
          time you glanced at Diagnostics. Re-fetching on return doesn't fix
          that — there's still a blank flash, in-progress form input is gone,
          and anything the backend doesn't persist is gone for good.

          Keeping them mounted costs one hidden subtree each and means every
          surface keeps its scroll position, its inputs, and its data. It also
          means their polling keeps running, so returning to a tab shows current
          state instead of a spinner.
        */}
        <main style={{ flex: 1, minWidth: 0, overflow: "auto", position: "relative" }}>
          {SURFACES.map(({ id }) => (
            <div key={id}
                 style={{ display: surface === id ? "block" : "none", minHeight: "100%" }}
                 aria-hidden={surface !== id}>
              {id === "console"   && <Console os={os} onRun={run} reply={reply} busy={busy}
                                              history={history} activity={activityMarks} />}
              {id === "chat"      && <Chat />}
              {id === "planner"   && <Planner live={feed} />}
              {id === "computer"  && <Agents live={feed} />}
              {id === "freelance" && <Earn live={feed} />}
              {id === "memory"    && <Memory />}
              {id === "logs"      && <Logs live={feed} />}
              {id === "diag"      && <Diagnostics />}
              {id === "settings"  && <Settings />}
            </div>
          ))}
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

/* ── Vitals graph: a real rolling chart of CPU/RAM + activity spikes ──────
   Visual, but every pixel is data: the line is actual CPU, the fill is RAM,
   and the ticks along the bottom mark moments Jarvis actually did something. */
function VitalsGraph({ history, events, busy }) {
  const W = 520, H = 84, pad = 4;
  const pts = history.length ? history : [{ cpu: 0, ram: 0 }];
  const step = pts.length > 1 ? (W - pad * 2) / (pts.length - 1) : 0;
  const y = (v) => H - pad - (Math.max(0, Math.min(100, v)) / 100) * (H - pad * 2);
  const line = (key) => pts.map((p, i) => `${i === 0 ? "M" : "L"} ${pad + i * step} ${y(p[key])}`).join(" ");
  const area = `${line("ram")} L ${pad + (pts.length - 1) * step} ${H - pad} L ${pad} ${H - pad} Z`;
  const last = pts[pts.length - 1] || { cpu: 0, ram: 0 };

  return (
    <div style={{ ...card, padding: 14, position: "relative", overflow: "hidden" }}>
      {busy && <div className="busy-sweep" style={{ position: "absolute", inset: 0, pointerEvents: "none" }} />}
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 6 }}>
        <span style={{ fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase",
                       color: T.dim, fontWeight: 600 }}>Live vitals</span>
        <span style={{ fontSize: 11, color: T.cyan }}>CPU {Math.round(last.cpu)}%</span>
        <span style={{ fontSize: 11, color: T.violet }}>RAM {Math.round(last.ram)}%</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: T.dim }}>{events.length} events · last 3 min</span>
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
           style={{ display: "block" }}>
        <defs>
          <linearGradient id="ramFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={T.violet} stopOpacity="0.28" />
            <stop offset="100%" stopColor={T.violet} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[25, 50, 75].map((g) => (
          <line key={g} x1={pad} x2={W - pad} y1={y(g)} y2={y(g)}
                stroke="rgba(255,255,255,0.05)" strokeWidth="1" />
        ))}
        <path d={area} fill="url(#ramFill)" />
        <path d={line("ram")} fill="none" stroke={T.violet} strokeWidth="1.2" opacity="0.65" />
        <path d={line("cpu")} fill="none" stroke={T.cyan} strokeWidth="1.8"
              strokeLinejoin="round" strokeLinecap="round" />
        {/* activity ticks — when Jarvis actually did work */}
        {events.map((e, i) => (
          <line key={i} x1={pad + e.x * (W - pad * 2)} x2={pad + e.x * (W - pad * 2)}
                y1={H - pad} y2={H - pad - 10}
                stroke={e.color} strokeWidth="2" opacity="0.85" />
        ))}
      </svg>
    </div>
  );
}

/* ── Console surface: goal + subsystems + what it just said ─────────────── */
function Console({ os, onRun, reply, busy, history, activity }) {
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

      {/* Live vitals graph — visual, and every mark on it is real data */}
      <VitalsGraph history={history || []} events={activity || []}
                   busy={busy || !!os?.status?.running} />

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
  const [health, setHealth] = useState(null);
  const [exp, setExp] = useState(null);
  const [open, setOpen] = useState(null);
  const load = () => {
    fetch(`${API}/os/diagnostics`).then((r) => r.json()).then(setData).catch(() => setData(null));
    fetch(`${API}/os/health-check`).then((r) => r.json()).then(setHealth).catch(() => setHealth(null));
    fetch(`${API}/os/experience`).then((r) => r.json()).then(setExp).catch(() => setExp(null));
  };
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);

  const grouped = {};
  (health?.checks || []).forEach((c) => { (grouped[c.group] ||= []).push(c); });

  return (
    <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 18 }}>

      {/* System diagnosis — what's installed, what's missing, how to fix */}
      <div>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ ...sectionLabel, flex: 1 }}>System diagnosis</div>
          <a href={`${API}/os/report`} download
             style={{ padding: "7px 14px", borderRadius: 9, fontSize: 12, textDecoration: "none",
                      background: "rgba(84,214,255,0.1)", border: `1px solid rgba(84,214,255,0.35)`,
                      color: T.cyan }}>
            ⤓ Download full report
          </a>
        </div>
        <div style={{ ...card, padding: 16, marginBottom: 10,
                      borderColor: health?.ok ? "rgba(62,230,168,0.35)" : "rgba(245,181,68,0.35)" }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: health?.ok ? T.green : T.amber }}>
            {health?.summary || "Checking…"}
          </div>
          <div style={{ fontSize: 11.5, color: T.dim, marginTop: 6 }}>
            The report includes this diagnosis, live state, recent activity, execution traces and
            log tail — send it when something misbehaves.
          </div>
          {(health?.fixes || []).length > 0 && (
            <div style={{ marginTop: 12, background: "rgba(0,0,0,0.3)", borderRadius: 9, padding: 12 }}>
              <div style={{ fontSize: 10, color: T.dim, letterSpacing: "0.12em",
                            textTransform: "uppercase", marginBottom: 7 }}>Run these to fix</div>
              {health.fixes.map((f, i) => (
                <div key={i} style={{ fontFamily: "monospace", fontSize: 12, color: T.amber,
                                      padding: "2px 0" }}>{f}</div>
              ))}
            </div>
          )}
        </div>
        {Object.entries(grouped).map(([g, items]) => (
          <div key={g} style={{ ...card, padding: 14, marginBottom: 8 }}>
            <div style={{ fontSize: 10, color: T.dim, letterSpacing: "0.14em",
                          textTransform: "uppercase", marginBottom: 9 }}>{g}</div>
            {items.map((c) => (
              <div key={c.name} style={{ display: "flex", gap: 10, alignItems: "baseline",
                                         padding: "4px 0", fontSize: 12.5 }}>
                <span style={{ color: c.ok ? T.green : T.amber, width: 14 }}>{c.ok ? "✓" : "!"}</span>
                <span style={{ minWidth: 180 }}>{c.name}</span>
                <span style={{ color: T.dim, flex: 1 }}>{c.detail}</span>
                {!c.ok && c.fix && <span style={{ color: T.amber, fontFamily: "monospace",
                                                  fontSize: 11 }}>{c.fix}</span>}
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* What Jarvis has learned by doing — measured on this machine, not claimed */}
      <div>
        <div style={sectionLabel}>What Jarvis has learned here</div>
        <div style={{ ...card, padding: 16 }}>
          {!exp?.overall?.samples ? (
            <div style={{ fontSize: 12.5, color: T.dim }}>
              Nothing observed yet. Once Jarvis has run a few tasks, this shows how
              reliable each app really is on your PC and what actually goes wrong.
            </div>
          ) : (
            <>
              <div style={{ fontSize: 14, fontWeight: 600,
                            color: exp.overall.rate >= 0.8 ? T.green
                                 : exp.overall.rate >= 0.5 ? T.amber : T.red }}>
                {Math.round((exp.overall.rate || 0) * 100)}% of the last {exp.overall.samples} actions
                succeeded
              </div>
              {exp.overall.top_failure_cause && (
                <div style={{ fontSize: 12, color: T.dim, marginTop: 5 }}>
                  Most common problem: {exp.overall.top_failure_cause}
                </div>
              )}

              {(exp.apps || []).length > 0 && (
                <div style={{ marginTop: 14 }}>
                  {exp.apps.map((a) => (
                    <div key={a.app} style={{ display: "flex", gap: 12, alignItems: "baseline",
                                              padding: "5px 0", fontSize: 12.5,
                                              borderTop: `1px solid ${T.line}` }}>
                      <span style={{ minWidth: 130 }}>{a.app}</span>
                      <span style={{ color: a.success_rate >= 0.8 ? T.green : T.amber,
                                     minWidth: 46 }}>
                        {Math.round(a.success_rate * 100)}%
                      </span>
                      <span style={{ color: T.dim, minWidth: 70 }}>{a.runs} runs</span>
                      <span style={{ color: T.cyan, flex: 1 }}>
                        {a.learned_wait_s ? `waits ${a.learned_wait_s}s for it` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {(exp.recent_failures || []).length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ ...sectionLabel, marginBottom: 8 }}>Recent problems, and the fix</div>
                  {exp.recent_failures.slice(0, 5).map((f, i) => (
                    <div key={i} style={{ background: "rgba(0,0,0,0.25)", borderRadius: 9,
                                          padding: "9px 12px", marginBottom: 6 }}>
                      <div style={{ fontSize: 12.5 }}>
                        <span style={{ color: T.amber }}>{f.app || f.action}</span>
                        <span style={{ color: T.dim }}> — {f.cause}</span>
                      </div>
                      <div style={{ fontSize: 12, color: T.cyan, marginTop: 4 }}>{f.remedy}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

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
