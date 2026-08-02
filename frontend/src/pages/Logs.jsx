/**
 * Logs.jsx — every decision, with a timestamp and a reason.
 *
 * The activity strip on the right of the shell is a glance: the last few things
 * that happened, no filtering, no depth. That's right for a glance and useless
 * when something has gone wrong and you need to find out where.
 *
 * This is the full record. Three sources, deliberately kept separate because
 * they answer different questions:
 *
 *   LIVE FEED   what each subsystem announced, as it happened (SSE)
 *   TRACES      the code path a request actually took, step by step
 *   GRADES      confidence in each finished run, and what changed as a result
 *
 * Filters are on the things you actually filter by when hunting a problem:
 * which subsystem, how bad, and free text. Errors-only is one click, because
 * that is the first thing anyone does.
 *
 * The feed arrives through the shell's existing SSE connection rather than
 * opening a second one. Two EventSources to the same endpoint would double the
 * server's fan-out for no benefit, and this page has to be cheap enough to
 * leave open.
 */
import { useState, useMemo, useEffect, useCallback } from "react";
import { API } from "../config.js";
import { T } from "../theme.js";

const card = { background: "#0d1220", border: `1px solid ${T.line}`, borderRadius: 14 };
const label = {
  fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase",
  color: T.dim, marginBottom: 10, fontWeight: 600,
};
const LEVEL = { info: T.cyan, success: T.green, warning: T.amber, error: T.red };

const chip = (on, color) => ({
  background: on ? `${color}22` : "transparent",
  border: `1px solid ${on ? `${color}66` : T.line}`,
  color: on ? color : T.dim,
  borderRadius: 999, padding: "3px 11px", fontSize: 11, cursor: "pointer",
  letterSpacing: "0.03em",
});

const TABS = [
  { id: "feed", label: "Live feed" },
  { id: "traces", label: "Request traces" },
  { id: "grades", label: "Confidence" },
];

export default function Logs({ live = [] }) {
  const [tab, setTab] = useState("feed");
  const [agent, setAgent] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [q, setQ] = useState("");
  const [traces, setTraces] = useState(null);
  const [grades, setGrades] = useState(null);
  const [openTrace, setOpenTrace] = useState(null);

  const load = useCallback(async () => {
    try { setTraces(await fetch(`${API}/os/traces?limit=30`).then((r) => r.json())); } catch {}
    try { setGrades(await fetch(`${API}/os/selfeval?limit=25`).then((r) => r.json())); } catch {}
  }, []);
  useEffect(() => { load(); }, [load, tab]);

  const agents = useMemo(
    () => [...new Set((live || []).map((f) => f.agent).filter(Boolean))].sort(),
    [live]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (live || []).filter((f) => {
      if (agent && f.agent !== agent) return false;
      if (errorsOnly && !["error", "warning"].includes(f.level)) return false;
      if (needle && !`${f.agent} ${f.msg}`.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [live, agent, errorsOnly, q]);

  const download = () => window.open(`${API}/os/report`, "_blank");

  return (
    <div style={{ padding: 22, display: "flex", flexDirection: "column",
                  gap: 14, height: "100%", minHeight: 0 }}>

      {/* Tabs + actions */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} style={chip(tab === t.id, T.cyan)}>
            {t.label}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <button onClick={load} style={chip(false, T.violet)}>Refresh</button>
        <button onClick={download} style={chip(false, T.green)}>Download full report</button>
      </div>

      {/* Filters — only meaningful for the feed */}
      {tab === "feed" && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button onClick={() => setAgent("")} style={chip(!agent, T.dim)}>everything</button>
          {agents.map((a) => (
            <button key={a} onClick={() => setAgent(a === agent ? "" : a)}
                    style={chip(a === agent, T.cyan)}>{a}</button>
          ))}
          <button onClick={() => setErrorsOnly((v) => !v)} style={chip(errorsOnly, T.red)}>
            problems only
          </button>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="find…"
                 style={{ background: "rgba(0,0,0,0.35)", color: T.text, marginLeft: "auto",
                          border: `1px solid ${T.line}`, borderRadius: 8,
                          padding: "6px 11px", fontSize: 12, outline: "none", width: 180 }} />
        </div>
      )}

      <section style={{ ...card, flex: 1, minHeight: 0, overflow: "auto", padding: 4 }}>

        {/* ── Live feed ─────────────────────────────────────────────────── */}
        {tab === "feed" && (
          rows.length === 0 ? (
            <Empty>
              {live.length === 0
                ? "Nothing yet. Ask Jarvis to do something and it fills up live."
                : "Nothing matches that filter."}
            </Empty>
          ) : rows.map((f) => (
            <div key={f._k} style={{ display: "flex", gap: 12, padding: "7px 12px",
                                     borderBottom: `1px solid rgba(255,255,255,0.03)`,
                                     alignItems: "baseline" }}>
              <span style={{ fontSize: 10.5, color: T.dim, width: 62, flexShrink: 0,
                             fontVariantNumeric: "tabular-nums" }}>{f.ts}</span>
              <span style={{ fontSize: 10, width: 82, flexShrink: 0,
                             color: LEVEL[f.level] || T.dim, letterSpacing: "0.06em",
                             textTransform: "uppercase" }}>{f.agent}</span>
              <span style={{ fontSize: 12.5, color: f.level === "error" ? T.red
                                    : f.level === "warning" ? T.amber : T.text,
                             wordBreak: "break-word" }}>{f.msg}</span>
            </div>
          ))
        )}

        {/* ── Traces ────────────────────────────────────────────────────── */}
        {tab === "traces" && (
          !traces?.traces?.length ? (
            <Empty>No requests traced yet.</Empty>
          ) : (
            <>
              {traces.summary && (
                <div style={{ padding: "10px 14px", fontSize: 12, color: T.dim,
                              borderBottom: `1px solid ${T.line}` }}>
                  {traces.summary.total} traced ·{" "}
                  <span style={{ color: traces.summary.failed ? T.red : T.green }}>
                    {traces.summary.failed || 0} failed
                  </span>
                </div>
              )}
              {traces.traces.map((t) => (
                <div key={t.id} style={{ borderBottom: `1px solid rgba(255,255,255,0.03)` }}>
                  <button onClick={() => setOpenTrace(openTrace === t.id ? null : t.id)}
                          style={{ display: "flex", gap: 12, width: "100%", padding: "9px 14px",
                                   background: "transparent", border: "none", cursor: "pointer",
                                   alignItems: "baseline", textAlign: "left" }}>
                    <span style={{ color: t.ok === false ? T.red : T.green, fontSize: 12 }}>
                      {t.ok === false ? "✕" : "●"}
                    </span>
                    <span style={{ fontSize: 12.5, color: T.text, flex: 1, minWidth: 0 }}>
                      {t.label || t.kind}
                    </span>
                    <span style={{ fontSize: 11, color: T.dim }}>
                      {t.steps?.length || 0} steps
                      {t.ms ? ` · ${(t.ms / 1000).toFixed(1)}s` : ""}
                    </span>
                  </button>
                  {openTrace === t.id && (
                    <div style={{ padding: "2px 14px 12px 38px" }}>
                      {(t.steps || []).map((s, i) => (
                        <div key={i} style={{ display: "flex", gap: 10, padding: "3px 0",
                                              fontSize: 11.5 }}>
                          <span style={{ color: s.ok === false ? T.red
                                              : s.ok === true ? T.green : T.dim }}>
                            {s.ok === false ? "✕" : s.ok === true ? "✓" : "·"}
                          </span>
                          <span style={{ color: T.text, width: 210, flexShrink: 0 }}>
                            {s.component}
                          </span>
                          <span style={{ color: T.dim, wordBreak: "break-word" }}>
                            {s.detail}
                          </span>
                        </div>
                      ))}
                      {t.result && (
                        <div style={{ fontSize: 11.5, marginTop: 6,
                                      color: t.ok === false ? T.red : T.dim }}>
                          → {t.result}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </>
          )
        )}

        {/* ── Confidence ────────────────────────────────────────────────── */}
        {tab === "grades" && (
          !grades?.runs?.length ? (
            <Empty>No finished runs graded yet.</Empty>
          ) : (
            <>
              <div style={{ padding: "12px 14px", fontSize: 12, color: T.dim,
                            borderBottom: `1px solid ${T.line}`, lineHeight: 1.5 }}>
                {grades.note}
              </div>
              {grades.runs.map((r, i) => (
                <div key={i} style={{ padding: "10px 14px",
                                      borderBottom: `1px solid rgba(255,255,255,0.03)` }}>
                  <div style={{ display: "flex", gap: 12, alignItems: "baseline" }}>
                    <span style={{ fontSize: 15, fontWeight: 700, width: 46,
                                   color: r.confidence >= 70 ? T.green : T.amber }}>
                      {r.confidence}%
                    </span>
                    <span style={{ fontSize: 12.5, color: r.ok ? T.text : T.red, flex: 1 }}>
                      {r.goal}
                    </span>
                    <span style={{ fontSize: 10.5, color: T.dim }}>
                      {r.verified}/{r.steps} verified
                    </span>
                  </div>
                  {(r.reasons || []).map((why, j) => (
                    <div key={j} style={{ fontSize: 11.5, color: T.dim, marginLeft: 58 }}>
                      {why}
                    </div>
                  ))}
                  {r.applied?.applied && (
                    <div style={{ fontSize: 11.5, color: T.green, marginLeft: 58, marginTop: 3 }}>
                      Changed for next time: {r.applied.effect}
                    </div>
                  )}
                </div>
              ))}
            </>
          )
        )}
      </section>
    </div>
  );
}

function Empty({ children }) {
  return <div style={{ padding: 24, fontSize: 12.5, color: T.dim }}>{children}</div>;
}
