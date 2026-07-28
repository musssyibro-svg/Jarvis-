/**
 * Earn.jsx — freelance, fully autonomous.
 *
 * The old screen made you run a pipeline: pick platforms, press SCAN, watch a
 * queue, approve, press SUBMIT. That's a chore, and the "approve all" flow was
 * confusing because board items legitimately become "ready to apply" rather than
 * "submitted".
 *
 * This is one switch. Turn Jarvis ON and it scans, scores, drafts and (where it
 * can) submits — continuously. Everything else on this page is just reporting
 * what it did, plus the two things it genuinely needs from you: platform logins
 * and any site you want to add.
 */
import { useEffect, useRef, useState } from "react";
import { API } from "../config.js";

const T = {
  panel: "#0d1220", line: "rgba(255,255,255,0.075)", text: "#e6edf5", dim: "#7d8798",
  cyan: "#54d6ff", green: "#3ee6a8", amber: "#f5b544", red: "#ff5f6d", violet: "#a98bff",
};
const card = { background: T.panel, border: `1px solid ${T.line}`, borderRadius: 14, padding: 16 };
const lbl = { fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: T.dim, marginBottom: 10, fontWeight: 600 };
const field = { background: "rgba(0,0,0,0.3)", color: T.text, border: `1px solid ${T.line}`, borderRadius: 9, padding: "9px 11px", fontSize: 13, outline: "none" };

export default function Earn() {
  const [income, setIncome] = useState(null);
  const [queue, setQueue] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [custom, setCustom] = useState([]);
  const [profile, setProfile] = useState(null);
  const [msg, setMsg] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ label: "", jobs_url: "", login_url: "", kind: "board", username: "", password: "" });
  const [switching, setSwitching] = useState(false);
  const [receipt, setReceipt] = useState(null);   // "what did it actually send?"

  /**
   * Pending intent. The switch used to flip back and forth: you pressed Start,
   * the POST went out, and the 7-second poll — which had left before the backend
   * finished starting the engine — landed with `enabled:false` and moved the
   * switch back. It looked broken because the UI and the backend genuinely
   * disagreed for a few seconds.
   *
   * So: when you press the switch we show what you asked for immediately, and
   * we keep showing it until either the server agrees or the request fails.
   * Stale poll responses can't override an intent that hasn't resolved.
   */
  const wantOn = useRef(null);   // { want: bool, at: number }
  const PENDING_TTL = 20_000;     // give the engine this long to come up

  const load = async () => {
    try {
      const [i, q, s, c, p] = await Promise.all([
        fetch(`${API}/automation/income/status`).then(r => r.json()).catch(() => null),
        fetch(`${API}/automation/queue?limit=100`).then(r => r.json()).catch(() => ({ queue: [] })),
        fetch(`${API}/sessions/status`).then(r => r.json()).catch(() => ({ platforms: [] })),
        fetch(`${API}/sessions/custom`).then(r => r.json()).catch(() => ({ platforms: [] })),
        fetch(`${API}/automation/profile`).then(r => r.json()).catch(() => null),
      ]);
      // Resolve the pending intent once the server reports what we asked for
      // (or once we've waited long enough that it clearly isn't going to).
      if (wantOn.current) {
        const { want, at } = wantOn.current;
        if (i && !!i.enabled === want) wantOn.current = null;
        else if (Date.now() - at > PENDING_TTL) {
          wantOn.current = null;
          setMsg(`The engine didn't ${want ? "start" : "stop"}. Check Diagnostics for why.`);
        }
      }
      setIncome(i); setQueue(q.queue || []); setSessions(s.platforms || []);
      setCustom(c.platforms || []); setProfile(p);
    } catch { /* backend down */ }
  };
  useEffect(() => { load(); const t = setInterval(load, 7000); return () => clearInterval(t); }, []);

  const toggle = async () => {
    if (switching) return;                       // no double-fire
    const want = !on;
    setSwitching(true);
    wantOn.current = { want, at: Date.now() };
    setMsg("");
    try {
      const r = await fetch(`${API}/automation/income/${want ? "start" : "stop"}`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (!r.ok) {
        wantOn.current = null;                   // put the switch back honestly
        const d = await r.json().catch(() => ({}));
        setMsg(d.detail || d.error || `Couldn't ${want ? "start" : "stop"} the engine.`);
      }
    } catch (e) {
      wantOn.current = null;
      setMsg(`Backend unreachable: ${e.message}`);
    } finally {
      setSwitching(false);
      load();
    }
  };
  const runNow = async () => { await fetch(`${API}/automation/income/run-now`, { method: "POST" }); setMsg("Running a cycle now…"); load(); };

  const setAutoSubmit = async (want) => {
    const before = profile;
    setProfile((p) => ({ ...(p || {}), auto_submit: want }));   // instant feedback
    try {
      const r = await fetch(`${API}/automation/profile`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...(profile || {}), auto_submit: want }),
      });
      if (!r.ok) throw new Error("save failed");
    } catch {
      setProfile(before);                                        // revert, don't lie
      setMsg("Couldn't save that setting.");
      return;
    }
    load();
  };

  const addPlatform = async () => {
    if (!form.label || !form.jobs_url) { setMsg("Name and jobs URL are required."); return; }
    const r = await fetch(`${API}/sessions/custom`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const d = await r.json();
    setMsg(r.ok ? `Added ${d.label}${d.credentials_saved ? " (login saved, encrypted)" : ""}. It'll be scanned from the next cycle.` : (d.detail || "Couldn't add that site."));
    if (r.ok) { setForm({ label: "", jobs_url: "", login_url: "", kind: "board", username: "", password: "" }); setShowAdd(false); }
    load();
  };

  const openReceipt = async (id) => {
    setReceipt({ loading: true, id });
    try {
      setReceipt(await fetch(`${API}/automation/queue/${id}/receipt`).then(r => r.json()));
    } catch (e) {
      setReceipt({ id, error: String(e.message || e) });
    }
  };

  const openLogin = async (slug) => {
    const r = await fetch(`${API}/sessions/open-login/${slug}`, { method: "POST" });
    const d = await r.json(); setMsg(d.message || d.error || "");
  };

  // What you asked for wins until the server confirms it — see `pending`.
  const on = wantOn.current ? wantOn.current.want : !!income?.enabled;
  const confirming = !!wantOn.current;
  const count = (s) => queue.filter(q => q.status === s).length;
  const submitted = count("done"), ready = count("ready"), pending = count("pending"), needLogin = count("needs_login");

  return (
    <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 18 }}>

      {/* THE switch */}
      <div style={{ ...card, borderColor: on ? "rgba(62,230,168,0.4)" : T.line }} className={on ? "alive" : ""}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: on ? T.green : T.text }}>
              {confirming ? (on ? "Starting…" : "Stopping…")
                          : on ? "Jarvis is earning for you" : "Autonomous earning is off"}
            </div>
            <div style={{ fontSize: 12.5, color: T.dim, marginTop: 4, lineHeight: 1.6 }}>
              {on
                ? `Scanning, scoring and writing proposals on its own every ${income?.interval_min ?? 20} minutes. You don't need to press anything.`
                : "Turn this on and Jarvis works continuously in the background — finding jobs, filtering bad fits, and drafting proposals."}
            </div>
          </div>
          <button onClick={toggle} disabled={switching}
            style={{ padding: "12px 26px", borderRadius: 12, border: "none", fontSize: 14, fontWeight: 700,
                     cursor: switching ? "wait" : "pointer", opacity: switching ? 0.6 : 1,
                     background: on ? "rgba(255,95,109,0.15)" : T.green, color: on ? T.red : "#052018" }}>
            {switching ? "…" : on ? "Stop" : "Start earning"}
          </button>
          {on && <button onClick={runNow} style={{ padding: "12px 16px", borderRadius: 12, fontSize: 13,
                     background: "transparent", border: `1px solid ${T.line}`, color: T.cyan }}>Run now</button>}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))", gap: 10, marginTop: 16 }}>
          {[["Cycles", income?.cycles ?? 0, T.cyan],
            ["Submitted", submitted, T.green],
            ["Ready to apply", ready, T.amber],
            ["Drafted", pending, T.violet]].map(([k, v, c]) => (
            <div key={k} style={{ background: "rgba(0,0,0,0.25)", borderRadius: 10, padding: "10px 12px" }}>
              <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.12em", textTransform: "uppercase" }}>{k}</div>
              <div className="smooth" style={{ fontSize: 20, fontWeight: 700, color: c }}>{v}</div>
            </div>
          ))}
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 9, marginTop: 14, fontSize: 12.5,
                        color: profile?.auto_submit ? T.amber : T.dim, cursor: "pointer" }}>
          <input type="checkbox" checked={!!profile?.auto_submit}
                 onChange={(e) => setAutoSubmit(e.target.checked)} style={{ accentColor: T.amber }} />
          Also submit bids automatically (no approval step). Only applies to bid sites you're logged into.
        </label>
      </div>

      {msg && <div style={{ ...card, borderColor: "rgba(84,214,255,0.3)", fontSize: 12.5, color: T.cyan }}>{msg}</div>}

      {/* Receipt: the evidence panel. */}
      {receipt && (
        <div style={{ ...card, borderColor: "rgba(84,214,255,0.35)" }}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
            <div style={{ ...lbl, flex: 1, marginBottom: 0 }}>
              What Jarvis actually sent
            </div>
            <button onClick={() => setReceipt(null)}
              style={{ background: "none", border: "none", color: T.dim,
                       cursor: "pointer", fontSize: 16 }}>✕</button>
          </div>

          {receipt.loading && <div style={{ color: T.dim, fontSize: 13 }}>Loading…</div>}
          {receipt.error && <div style={{ color: T.red, fontSize: 13 }}>{receipt.error}</div>}

          {!receipt.loading && !receipt.error && (
            <>
              <div style={{ fontSize: 13, marginBottom: 8 }}>{receipt.job_title}</div>
              {receipt.note && (
                <div style={{ fontSize: 12.5, color: T.amber, marginBottom: 10 }}>
                  {receipt.note}
                </div>
              )}

              {receipt.proposal_text && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 10, color: T.dim, letterSpacing: "0.12em",
                                textTransform: "uppercase", marginBottom: 6 }}>
                    Proposal text
                  </div>
                  <div style={{ background: "rgba(0,0,0,0.3)", borderRadius: 9, padding: 12,
                                fontSize: 12.5, lineHeight: 1.65, whiteSpace: "pre-wrap",
                                maxHeight: 260, overflowY: "auto" }}>
                    {receipt.proposal_text}
                  </div>
                </div>
              )}

              {receipt.receipt && (
                <div style={{ fontSize: 12.5, color: T.dim, lineHeight: 1.8 }}>
                  <div>Sent: {receipt.receipt.at}</div>
                  <div>Outcome: <span style={{
                    color: receipt.receipt.outcome === "sent" ? T.green : T.red }}>
                    {receipt.receipt.outcome}</span></div>
                  <div>Site confirmed it:{" "}
                    <span style={{ color: receipt.receipt.confirmed_by_site ? T.green : T.amber }}>
                      {receipt.receipt.confirmed_by_site ? "yes" : "no - check the screenshot"}
                    </span></div>
                  {receipt.receipt.final_url && (
                    <div style={{ wordBreak: "break-all" }}>
                      Ended on: {receipt.receipt.final_url}</div>
                  )}
                </div>
              )}

              {receipt.proof_url && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 10, color: T.dim, letterSpacing: "0.12em",
                                textTransform: "uppercase", marginBottom: 6 }}>
                    The page after submitting
                  </div>
                  <a href={`${API}${receipt.proof_url}`} target="_blank" rel="noreferrer">
                    <img src={`${API}${receipt.proof_url}`} alt="submission proof"
                         style={{ maxWidth: "100%", borderRadius: 9,
                                  border: `1px solid ${T.line}` }} />
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* What it needs from you */}
      {(needLogin > 0 || sessions.some(s => s.logged_in === false)) && (
        <div style={{ ...card, borderColor: "rgba(245,181,68,0.35)" }}>
          <div style={{ ...lbl, color: T.amber }}>Needs you</div>
          <div style={{ fontSize: 12.5, color: T.dim, marginBottom: 10 }}>
            Jarvis can only submit on sites you're logged into. Log in once — the session is reused forever.
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {sessions.filter(s => s.logged_in !== true).map(s => (
              <button key={s.platform} onClick={() => openLogin(s.platform)}
                style={{ padding: "7px 13px", borderRadius: 9, fontSize: 12, background: "rgba(245,181,68,0.1)",
                         border: `1px solid rgba(245,181,68,0.35)`, color: T.amber }}>
                Log in to {s.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Results */}
      <div>
        <div style={lbl}>What Jarvis has done</div>
        <div style={{ ...card, padding: 0, overflow: "hidden" }}>
          {queue.length === 0 && (
            <div style={{ padding: 16, color: T.dim, fontSize: 13 }}>
              Nothing yet. {on ? "The first cycle will appear here shortly." : "Turn on autonomous earning above."}
            </div>
          )}
          {queue.slice(0, 25).map(q => {
            const c = { done: T.green, ready: T.cyan, pending: T.violet, needs_login: T.amber,
                        failed: T.red, approved: T.green, executing: T.amber }[q.status] || T.dim;
            const what = { done: "submitted", ready: "ready — apply via link", pending: "proposal drafted",
                           needs_login: "needs login", failed: "failed", approved: "approved",
                           executing: "submitting…" }[q.status] || q.status;
            const link = q.payload?.job?.link;
            return (
              <div key={q.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
                                       borderBottom: `1px solid rgba(255,255,255,0.04)` }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: c, flexShrink: 0 }} />
                <span style={{ fontSize: 13, flex: 1, minWidth: 0, overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{q.job_title}</span>
                <span style={{ fontSize: 11, color: T.dim }}>{q.platform}</span>
                <span style={{ fontSize: 11, color: c, minWidth: 130, textAlign: "right" }}>{what}</span>
                {link && <a href={link} target="_blank" rel="noreferrer"
                            style={{ fontSize: 11, color: T.cyan, textDecoration: "none" }}>open ↗</a>}
                {/* Proof. "It says it submitted" is not evidence — this opens the
                    exact text sent, the URL it landed on, and a screenshot of the
                    page after clicking submit. */}
                <button onClick={() => openReceipt(q.id)}
                  style={{ fontSize: 11, padding: "2px 9px", borderRadius: 7,
                           cursor: "pointer", background: "transparent",
                           border: `1px solid ${T.line}`, color: T.dim }}>
                  Proof
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Your sites */}
      <div>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ ...lbl, flex: 1 }}>Your freelance sites</div>
          <button onClick={() => setShowAdd(!showAdd)}
            style={{ padding: "6px 12px", borderRadius: 9, fontSize: 12, background: "rgba(84,214,255,0.08)",
                     border: `1px solid rgba(84,214,255,0.3)`, color: T.cyan }}>
            {showAdd ? "Cancel" : "+ Add a site"}
          </button>
        </div>

        {showAdd && (
          <div style={{ ...card, marginBottom: 10 }}>
            <div style={{ fontSize: 12.5, color: T.dim, marginBottom: 12, lineHeight: 1.6 }}>
              Add any freelance site. Jarvis will scan it every cycle. If you add a login it's
              encrypted on this PC and only used to fill that site's own login form.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <input style={field} placeholder="Site name (e.g. Toptal)" value={form.label}
                     onChange={e => setForm({ ...form, label: e.target.value })} />
              <select style={{ ...field, cursor: "pointer" }} value={form.kind}
                      onChange={e => setForm({ ...form, kind: e.target.value })}>
                <option value="board">Job board — apply via their link</option>
                <option value="bid">Bid site — Jarvis can submit proposals</option>
                <option value="talent">Talent profile — clients contact you</option>
              </select>
              <input style={{ ...field, gridColumn: "1 / -1" }} placeholder="Jobs page URL (where listings are)"
                     value={form.jobs_url} onChange={e => setForm({ ...form, jobs_url: e.target.value })} />
              <input style={{ ...field, gridColumn: "1 / -1" }} placeholder="Login page URL (optional)"
                     value={form.login_url} onChange={e => setForm({ ...form, login_url: e.target.value })} />
              <input style={field} placeholder="Username / email (optional)" value={form.username}
                     onChange={e => setForm({ ...form, username: e.target.value })} />
              <input style={field} type="password" placeholder="Password (optional, encrypted)"
                     value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} />
            </div>
            <button onClick={addPlatform}
              style={{ marginTop: 12, padding: "10px 20px", borderRadius: 10, border: "none",
                       background: T.cyan, color: "#04202b", fontWeight: 700, fontSize: 13 }}>
              Add site
            </button>
          </div>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {sessions.map(s => (
            <div key={s.platform} style={{ ...card, padding: "9px 13px", display: "flex",
                                           alignItems: "center", gap: 8 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%",
                             background: s.logged_in === true ? T.green : s.logged_in === false ? T.red : T.dim }} />
              <span style={{ fontSize: 12.5 }}>{s.label}</span>
              <span style={{ fontSize: 10, color: T.dim }}>
                {s.logged_in === true ? "logged in" : s.logged_in === false ? "logged out" : "unknown"}
              </span>
            </div>
          ))}
          {custom.map(p => (
            <div key={p.slug} style={{ ...card, padding: "9px 13px", display: "flex",
                                       alignItems: "center", gap: 8, borderColor: "rgba(169,139,255,0.3)" }}>
              <span style={{ fontSize: 12.5, color: T.violet }}>{p.label}</span>
              <span style={{ fontSize: 10, color: T.dim }}>{p.kind} · yours</span>
              <span onClick={() => fetch(`${API}/sessions/custom/${p.slug}`, { method: "DELETE" }).then(load)}
                    style={{ cursor: "pointer", color: T.red, fontSize: 13 }}>✕</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
