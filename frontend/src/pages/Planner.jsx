/**
 * Planner.jsx — watch Jarvis think, on the same screen as what it's doing.
 *
 * The complaint this answers: "I press run and I can't see if it's active."
 * Plans lived on one screen and activity on another, so following a task meant
 * switching back and forth and reconstructing the order in your head.
 *
 * Everything is here at once:
 *
 *   PLAN        every step, its live status, how long it took, how many tries
 *   CONTROLS    skip a step, retry a step, stop — all cooperative
 *   WHY         the chain of what actually happened, assembled from records
 *   CONFIDENCE  how sure it was about recent runs, and what it changed
 *   TEACH       start/stop learning a task by watching
 *
 * Nothing here animates unless something is genuinely running. A spinner that
 * spins when nothing is happening is the same lie as a progress bar that
 * reaches 90% and waits.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { API } from "../config.js";
import { T } from "../JarvisOS.jsx";

const card = { background: "#0d1220", border: `1px solid ${T.line}`, borderRadius: 14 };
const label = {
  fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase",
  color: T.dim, marginBottom: 10, fontWeight: 600,
};

const STATUS = {
  pending: { c: T.dim,    mark: "○", word: "waiting"  },
  running: { c: T.cyan,   mark: "◐", word: "running"  },
  done:    { c: T.green,  mark: "●", word: "done"     },
  failed:  { c: T.red,    mark: "✕", word: "failed"   },
  skipped: { c: T.amber,  mark: "⊘", word: "skipped"  },
};

function btn(color, disabled) {
  return {
    background: disabled ? "rgba(255,255,255,0.04)" : `${color}1f`,
    border: `1px solid ${disabled ? T.line : `${color}55`}`,
    color: disabled ? T.dim : color,
    borderRadius: 8, padding: "5px 11px", fontSize: 11, fontWeight: 600,
    cursor: disabled ? "default" : "pointer", letterSpacing: "0.04em",
  };
}

const secs = (ms) => (ms == null ? "" : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`);

export default function Planner({ live = [] }) {
  const [plan, setPlan] = useState(null);
  const [why, setWhy] = useState(null);
  const [evalx, setEvalx] = useState(null);
  const [teach, setTeach] = useState(null);
  const [teachName, setTeachName] = useState("");
  const [preview, setPreview] = useState(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const timer = useRef(null);

  const load = useCallback(async () => {
    try {
      const p = await fetch(`${API}/os/plan`).then((r) => r.json());
      setPlan(p);
    } catch { /* the next tick retries */ }
    try { setTeach(await fetch(`${API}/os/teach`).then((r) => r.json())); } catch {}
  }, []);

  /* Poll fast while something is running, slowly when idle. A fixed 1s poll
     against an idle backend is pure waste on a 16GB machine that is also
     running local models. */
  useEffect(() => {
    load();
    const tick = () => {
      load();
      const running = plan?.status === "running";
      timer.current = setTimeout(tick, running ? 900 : 4000);
    };
    timer.current = setTimeout(tick, 900);
    return () => clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan?.status]);

  const loadWhy = useCallback(async () => {
    try { setWhy(await fetch(`${API}/os/why`).then((r) => r.json())); } catch {}
  }, []);
  const loadEval = useCallback(async () => {
    try { setEvalx(await fetch(`${API}/os/selfeval`).then((r) => r.json())); } catch {}
  }, []);
  useEffect(() => { loadWhy(); loadEval(); }, [plan?.status, loadWhy, loadEval]);

  const control = async (cmd, step) => {
    setNote("");
    try {
      const r = await fetch(`${API}/os/plan/${cmd}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) setNote(j.detail || j.error || "Couldn't do that.");
    } catch { setNote("Backend didn't answer."); }
    load();
  };

  const doPreview = async () => {
    if (!draft.trim()) return;
    try {
      const r = await fetch(`${API}/os/plan/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: draft }),
      });
      setPreview(await r.json());
    } catch { setPreview({ plan: [], unresolved: [draft] }); }
  };

  const teachToggle = async () => {
    setNote("");
    const on = teach?.recording;
    try {
      const r = await fetch(`${API}/os/teach/${on ? "stop" : "start"}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(on ? { save: true } : { name: teachName || "untitled task" }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) setNote(j.detail || "Couldn't start recording.");
      else if (on) setNote(j.ok
        ? `Learned "${j.name}" — ${j.step_count} steps. Say "run my ${j.name}".`
        : (j.error || "Nothing replayable was captured."));
      setTeachName("");
    } catch { setNote("Backend didn't answer."); }
    load();
  };

  const running = plan?.status === "running";
  const steps = plan?.steps || [];
  /* Feed entries from the executor and planner only — the whole point is to see
     this plan's activity next to the plan, not the entire system's chatter. */
  const relevant = (live || []).filter((f) =>
    ["planner", "executor", "desktop", "vision", "selfeval", "teach"].includes(f.agent));

  return (
    <div style={{ padding: 22, display: "grid", gap: 16,
                  gridTemplateColumns: "minmax(0,1.35fr) minmax(280px,1fr)",
                  alignItems: "start" }}>

      {/* ── The plan ─────────────────────────────────────────────────────── */}
      <section style={{ ...card, padding: 18, gridColumn: "1 / 2" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
          <div style={{ ...label, marginBottom: 0 }}>Plan</div>
          {running && (
            <span style={{ fontSize: 10, color: T.cyan }}>
              running · step {(plan.current ?? 0) + 1} of {plan.total}
            </span>
          )}
          <div style={{ flex: 1 }} />
          {plan?.status && plan.status !== "none" && (
            <button style={btn(T.red, !running)} disabled={!running}
                    onClick={() => control("stop")}>Stop</button>
          )}
        </div>

        <div style={{ fontSize: 14, color: T.text, marginBottom: 14, lineHeight: 1.4 }}>
          {plan?.goal || <span style={{ color: T.dim }}>
            Nothing running. Type a command below to see the plan before it runs.
          </span>}
        </div>

        {plan?.total > 0 && (
          <div style={{ height: 3, background: "rgba(255,255,255,0.06)", borderRadius: 2,
                        overflow: "hidden", marginBottom: 16 }}>
            <div style={{ height: "100%", width: `${plan.progress}%`,
                          background: plan.status === "failed" ? T.red : T.green,
                          transition: "width .35s ease" }} />
          </div>
        )}

        {steps.map((s) => {
          const st = STATUS[s.status] || STATUS.pending;
          const isNow = s.status === "running";
          return (
            <div key={s.i}
                 style={{ display: "flex", gap: 11, padding: "9px 10px", borderRadius: 10,
                          alignItems: "flex-start", marginBottom: 3,
                          background: isNow ? "rgba(84,214,255,0.07)" : "transparent",
                          border: `1px solid ${isNow ? "rgba(84,214,255,0.22)" : "transparent"}` }}>
              <span style={{ color: st.c, fontSize: 13, lineHeight: "18px", width: 14 }}>
                {st.mark}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: s.status === "pending" ? T.dim : T.text }}>
                  {s.text}
                </div>
                {(s.error || s.detail) && (
                  <div style={{ fontSize: 11, marginTop: 3,
                                color: s.error ? T.red : T.dim }}>
                    {s.error || s.detail}
                  </div>
                )}
                <div style={{ fontSize: 10, color: T.dim, marginTop: 3 }}>
                  {st.word}
                  {s.ms ? ` · ${secs(s.ms)}` : ""}
                  {s.attempts > 1 ? ` · ${s.attempts} tries` : ""}
                </div>
              </div>
              <div style={{ display: "flex", gap: 5, flexShrink: 0 }}>
                {s.status === "pending" && running && (
                  <button style={btn(T.amber)} onClick={() => control("skip", s.i)}>Skip</button>
                )}
                {(s.status === "failed" || s.status === "skipped") && (
                  <button style={btn(T.cyan)} onClick={() => control("retry", s.i)}>Retry</button>
                )}
              </div>
            </div>
          );
        })}

        {note && (
          <div style={{ marginTop: 12, fontSize: 12, color: T.amber,
                        background: "rgba(245,181,68,0.08)", padding: "8px 11px",
                        borderRadius: 8 }}>{note}</div>
        )}

        {/* Dry run — see how a sentence will be understood before it acts. */}
        <div style={{ marginTop: 18, borderTop: `1px solid ${T.line}`, paddingTop: 14 }}>
          <div style={label}>Check a command first</div>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && doPreview()}
                   placeholder="open browser and search BMW M4 and analyze the page"
                   style={{ flex: 1, background: "rgba(0,0,0,0.35)", color: T.text,
                            border: `1px solid ${T.line}`, borderRadius: 8,
                            padding: "8px 11px", fontSize: 12, outline: "none" }} />
            <button style={btn(T.cyan)} onClick={doPreview}>Show plan</button>
          </div>
          {preview && (
            <div style={{ marginTop: 10, fontSize: 12 }}>
              {(preview.plan || []).map((p, i) => (
                <div key={i} style={{ color: T.text, padding: "3px 0" }}>
                  <span style={{ color: T.dim, marginRight: 8 }}>{i + 1}.</span>{p}
                </div>
              ))}
              {!preview.plan?.length && (
                <div style={{ color: T.dim }}>
                  No deterministic plan — this would go to the language model.
                </div>
              )}
              {preview.unresolved?.length > 0 && (
                <div style={{ color: T.amber, marginTop: 6 }}>
                  Wouldn't understand: {preview.unresolved.join("; ")}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* ── Right column ─────────────────────────────────────────────────── */}
      <div style={{ display: "grid", gap: 16 }}>

        {/* Why */}
        <section style={{ ...card, padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center" }}>
            <div style={{ ...label, marginBottom: 0, flex: 1 }}>Why</div>
            <button style={btn(T.violet)} onClick={loadWhy}>Refresh</button>
          </div>
          <div style={{ fontSize: 12.5, color: T.text, marginTop: 10, lineHeight: 1.5 }}>
            {why?.headline || "Nothing to explain yet."}
          </div>
          {why?.cause && (
            <div style={{ marginTop: 10, fontSize: 12, color: T.red }}>
              Cause: {why.cause}
            </div>
          )}
          {why?.machine_reason && (
            <div style={{ marginTop: 6, fontSize: 12, color: T.amber }}>
              On this PC: {why.machine_reason}
            </div>
          )}
          {why?.fix && (
            <div style={{ marginTop: 6, fontSize: 12, color: T.green }}>
              Fix: {why.fix}
            </div>
          )}
          {why?.code_path?.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary style={{ fontSize: 11, color: T.dim, cursor: "pointer" }}>
                Code path it took
              </summary>
              <div style={{ marginTop: 8 }}>
                {why.code_path.map((c, i) => (
                  <div key={i} style={{ fontSize: 11, color: c.ok === false ? T.red : T.dim,
                                        padding: "2px 0" }}>
                    {c.text} {c.detail ? `— ${c.detail}` : ""}
                  </div>
                ))}
              </div>
            </details>
          )}
        </section>

        {/* Confidence + what it changed about itself */}
        <section style={{ ...card, padding: 16 }}>
          <div style={label}>Confidence</div>
          {evalx?.average_confidence == null ? (
            <div style={{ fontSize: 12, color: T.dim }}>No runs graded yet.</div>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <div style={{ fontSize: 30, fontWeight: 700,
                              color: evalx.average_confidence >= 70 ? T.green : T.amber }}>
                  {evalx.average_confidence}%
                </div>
                <div style={{ fontSize: 11, color: T.dim }}>average, last {evalx.runs.length} runs</div>
              </div>
              {evalx.runs.slice(0, 4).map((r, i) => (
                <div key={i} style={{ marginTop: 9, fontSize: 11.5 }}>
                  <div style={{ color: r.ok ? T.text : T.red }}>
                    {r.confidence}% · {r.goal || "task"}
                  </div>
                  <div style={{ color: T.dim, marginTop: 2 }}>{(r.reasons || [])[0]}</div>
                </div>
              ))}
              {evalx.changes?.length > 0 && (
                <div style={{ marginTop: 14, borderTop: `1px solid ${T.line}`, paddingTop: 10 }}>
                  <div style={{ ...label, marginBottom: 6 }}>What it changed</div>
                  {evalx.changes.slice(0, 3).map((c, i) => (
                    <div key={i} style={{ fontSize: 11.5, color: T.green, marginBottom: 6 }}>
                      {c.effect}
                      <div style={{ color: T.dim, marginTop: 2 }}>{c.why}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>

        {/* Teach by demonstration */}
        <section style={{ ...card, padding: 16 }}>
          <div style={label}>Teach by showing</div>
          {teach?.ok === false ? (
            <div style={{ fontSize: 12, color: T.amber }}>
              {teach.error}
              <div style={{ color: T.dim, marginTop: 4 }}>{teach.fix}</div>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 12, color: T.dim, lineHeight: 1.5, marginBottom: 10 }}>
                Press record, do the task once the way you want it done, then stop.
                Jarvis saves it as a workflow you can run by name.
                Passwords are never recorded.
              </div>
              {!teach?.recording && (
                <input value={teachName} onChange={(e) => setTeachName(e.target.value)}
                       placeholder="name it, e.g. apply for a job"
                       style={{ width: "100%", background: "rgba(0,0,0,0.35)", color: T.text,
                                border: `1px solid ${T.line}`, borderRadius: 8,
                                padding: "8px 11px", fontSize: 12, outline: "none",
                                marginBottom: 9 }} />
              )}
              <button style={btn(teach?.recording ? T.red : T.green)} onClick={teachToggle}>
                {teach?.recording
                  ? `Stop — ${teach.events} things seen in ${Math.round(teach.seconds)}s`
                  : "Watch me do it"}
              </button>
            </>
          )}
        </section>

        {/* This plan's activity, right next to the plan. */}
        <section style={{ ...card, padding: 16 }}>
          <div style={label}>Activity</div>
          {relevant.length === 0 && (
            <div style={{ fontSize: 12, color: T.dim }}>Quiet.</div>
          )}
          {relevant.slice(0, 14).map((f) => (
            <div key={f._k} style={{ display: "flex", gap: 8, padding: "5px 0" }}>
              <span style={{ fontSize: 9, color: T.dim, width: 52, flexShrink: 0 }}>{f.ts}</span>
              <span style={{ fontSize: 11.5,
                             color: f.level === "error" ? T.red
                                  : f.level === "warning" ? T.amber : T.text }}>
                {f.msg}
              </span>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
