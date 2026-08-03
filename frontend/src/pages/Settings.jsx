/**
 * Settings.jsx — the control centre.
 *
 * The old version was four text boxes and a Save button, and it had the worst
 * possible property: it said "SAVED" whether or not the running system ever
 * read the value. So this screen now shows, for every setting, the value that
 * is ACTUALLY IN EFFECT and where it came from — what you set, an environment
 * variable, or a built-in default. "I set it and nothing happened" becomes a
 * visible fact rather than a mystery.
 *
 * Five sections, in the order you'd want them:
 *
 *   About you     durable facts, so Jarvis stops re-asking things it knows
 *   This PC       what was actually found on the machine, and the consequences
 *   Behaviour     models, browser, search engine, provider overrides
 *   Security      what is protecting this instance right now
 *   Live values   every setting, its effective value, and its source
 */
import { useState, useEffect, useCallback } from "react";
import { API } from "../config.js";
import { T } from "../theme.js";

const card = {
  background: "#0d1220", border: `1px solid ${T.line}`, borderRadius: 14,
  padding: 20, marginBottom: 16,
};
const label = {
  fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase",
  color: T.dim, marginBottom: 12, fontWeight: 600,
};
const input = {
  width: "100%", background: "rgba(0,0,0,0.35)", color: T.text,
  border: `1px solid ${T.line}`, borderRadius: 8, padding: "9px 12px",
  fontSize: 12.5, outline: "none",
};
const btn = (color) => ({
  background: `${color}1f`, border: `1px solid ${color}55`, color,
  borderRadius: 9, padding: "8px 16px", fontSize: 12, fontWeight: 600,
  cursor: "pointer", letterSpacing: "0.04em",
});
const LEVEL = { error: T.red, warning: T.amber, info: T.dim };

function Field({ label: l, hint, value, onChange, type = "text", placeholder }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11, color: T.text, marginBottom: 4 }}>{l}</div>
      {hint && <div style={{ fontSize: 10.5, color: T.dim, marginBottom: 5 }}>{hint}</div>}
      <input type={type} value={value || ""} placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)} style={input} />
    </div>
  );
}

export default function Settings() {
  const [cfg, setCfg] = useState({});
  const [effective, setEffective] = useState([]);
  const [persona, setPersona] = useState(null);
  const [env, setEnv] = useState(null);
  const [sec, setSec] = useState(null);
  const [providers, setProviders] = useState(null);
  const [ai, setAi] = useState(null);
  const [saved, setSaved] = useState("");
  const [newFact, setNewFact] = useState({ field: "", value: "" });

  const load = useCallback(async () => {
    const grab = async (path, set, pick = (x) => x) => {
      try { set(pick(await fetch(`${API}${path}`).then((r) => r.json()))); } catch {}
    };
    grab("/settings", (s) => {
      const map = {};
      (s || []).forEach((r) => { map[r.key] = r.value; });
      setCfg((c) => ({ ...c, ...map }));
    }, (j) => j.settings);
    // effective() returns an object keyed by setting; flatten it for display.
    grab("/settings/effective", setEffective,
         (j) => Object.entries(j.settings || {})
           .map(([key, v]) => ({ key, ...v })));
    grab("/os/persona", setPersona);
    grab("/os/environment", setEnv);
    grab("/auth/status", setSec);
    grab("/os/providers", setProviders);
    grab("/os/ai", setAi);
  }, []);

  useEffect(() => { load(); }, [load]);

  const set = (k) => (v) => setCfg((c) => ({ ...c, [k]: v }));

  const save = async () => {
    for (const [key, value] of Object.entries(cfg)) {
      await fetch(`${API}/settings/${key}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: String(value ?? "") }),
      }).catch(() => {});
    }
    setSaved("Saved — the values below now show what's actually in effect.");
    setTimeout(() => setSaved(""), 4000);
    load();
  };

  const addFact = async () => {
    if (!newFact.field || !newFact.value) return;
    await fetch(`${API}/os/persona`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(newFact),
    }).catch(() => {});
    setNewFact({ field: "", value: "" });
    load();
  };

  const forget = async (field) => {
    await fetch(`${API}/os/persona/${field}`, { method: "DELETE" }).catch(() => {});
    load();
  };

  const rescan = async () => {
    try { setEnv(await fetch(`${API}/os/environment?refresh=true`).then((r) => r.json())); }
    catch {}
  };

  return (
    <div style={{ padding: 22, maxWidth: 860 }}>

      {/* ── About you ──────────────────────────────────────────────────── */}
      <section style={card}>
        <div style={label}>About you</div>
        <div style={{ fontSize: 12, color: T.dim, marginBottom: 14, lineHeight: 1.5 }}>
          What Jarvis remembers so it stops asking. Anything you set here beats
          what it detected, and a machine scan will never overwrite it.
        </div>

        {(persona?.known || []).map((f) => (
          <div key={f.field} style={{ display: "flex", gap: 10, alignItems: "baseline",
                                      padding: "7px 0", borderBottom: `1px solid ${T.line}` }}>
            <div style={{ width: 130, fontSize: 11.5, color: T.dim, flexShrink: 0 }}>
              {f.field.replace(/_/g, " ")}
            </div>
            <div style={{ flex: 1, fontSize: 12.5, color: T.text }}>
              {f.value}
              <span style={{ color: T.dim, fontSize: 10.5, marginLeft: 8 }}>
                {f.source === "stated" ? "you told me"
                  : f.source === "observed" ? "found on this PC" : "noticed from use"}
              </span>
            </div>
            <button onClick={() => forget(f.field)}
                    style={{ ...btn(T.dim), padding: "3px 9px", fontSize: 10.5 }}>
              Forget
            </button>
          </div>
        ))}

        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <select value={newFact.field}
                  onChange={(e) => setNewFact((f) => ({ ...f, field: e.target.value }))}
                  style={{ ...input, width: 190 }}>
            <option value="">add a fact…</option>
            {(persona?.unknown || []).map((u) => (
              <option key={u.field} value={u.field}>{u.field.replace(/_/g, " ")}</option>
            ))}
            {(persona?.known || []).map((u) => (
              <option key={`k-${u.field}`} value={u.field}>
                {u.field.replace(/_/g, " ")} (replace)
              </option>
            ))}
          </select>
          <input value={newFact.value} placeholder="value"
                 onChange={(e) => setNewFact((f) => ({ ...f, value: e.target.value }))}
                 onKeyDown={(e) => e.key === "Enter" && addFact()} style={input} />
          <button style={btn(T.green)} onClick={addFact}>Add</button>
        </div>
        {newFact.field && (
          <div style={{ fontSize: 11, color: T.dim, marginTop: 6 }}>
            {(persona?.unknown || []).concat(persona?.known || [])
              .find((u) => u.field === newFact.field)?.answers}
          </div>
        )}
      </section>

      {/* ── This PC ────────────────────────────────────────────────────── */}
      <section style={card}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ ...label, flex: 1, marginBottom: 0 }}>This PC</div>
          <button style={btn(T.cyan)} onClick={rescan}>Scan again</button>
        </div>
        <div style={{ fontSize: 12, color: T.dim, margin: "12px 0 14px", lineHeight: 1.5 }}>
          What was actually found here. Jarvis adapts to this instead of assuming.
        </div>

        {env && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))",
                        gap: 12, marginBottom: 16 }}>
            <Fact k="Browsers" v={Object.keys(env.browsers || {}).join(", ") || "none found"} />
            <Fact k="Messaging" v={["qq", "wechat", "telegram", "dingtalk", "discord", "slack"]
              .filter((a) => env.apps?.[a]).join(", ") || "none found"} />
            <Fact k="Memory" v={`${env.memory?.total_gb} GB (${env.memory?.free_gb} GB free)`} />
            <Fact k="GPU" v={env.gpu?.name || "none usable for models"} />
            <Fact k="Language" v={env.locale?.language || "unknown"} />
            <Fact k="Models" v={`${env.ollama?.models?.length || 0} pulled · ${env.ollama?.total_gb || 0} GB`} />
          </div>
        )}

        {(env?.constraints || []).map((c) => (
          <div key={c.key} style={{ padding: "9px 12px", borderRadius: 9, marginBottom: 7,
                                    background: "rgba(255,255,255,0.025)",
                                    borderLeft: `2px solid ${LEVEL[c.level] || T.dim}` }}>
            <div style={{ fontSize: 12, color: T.text }}>{c.fact}</div>
            <div style={{ fontSize: 11.5, color: T.dim, marginTop: 3 }}>{c.effect}</div>
            {c.fix && <div style={{ fontSize: 11.5, color: T.green, marginTop: 3 }}>Fix: {c.fix}</div>}
          </div>
        ))}
      </section>

      {/* ── Behaviour ──────────────────────────────────────────────────── */}
      <section style={card}>
        <div style={label}>Behaviour</div>

        <Field l="Reasoning model" value={cfg.ollama_reasoning_model}
               onChange={set("ollama_reasoning_model")}
               hint="Used for proposals and planning. Bigger = slower but far better."
               placeholder="qwen2.5:3b" />
        <Field l="Fast model" value={cfg.ollama_fast_model} onChange={set("ollama_fast_model")}
               hint="Used for quick replies and composition."
               placeholder="qwen2.5:3b" />
        <Field l="Vision model" value={cfg.ollama_vision_model} onChange={set("ollama_vision_model")}
               hint="Reads the screen. llava:7b is the practical minimum."
               placeholder="llava:7b" />

        <Field l="Search engine" value={cfg.search_engine} onChange={set("search_engine")}
               hint="bing-cn, baidu, bing, google or duckduckgo. Google does not load from mainland China."
               placeholder="bing-cn" />

        <div style={{ marginTop: 18, marginBottom: 10, ...label }}>Which app for what</div>
        <div style={{ fontSize: 12, color: T.dim, marginBottom: 12, lineHeight: 1.5 }}>
          Leave blank and Jarvis picks whatever is installed and has been working.
          Set one to force it.
        </div>
        {Object.entries(providers?.capabilities || {}).map(([capName, c]) => (
          <div key={capName} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11.5, color: T.text, marginBottom: 4 }}>
              {c.capability?.replace(/_/g, " ")}
              <span style={{ color: T.dim, marginLeft: 8 }}>
                now using {c.provider || "nothing"} — {c.why}
              </span>
            </div>
            <input value={cfg[`provider_${capName}`] || ""} style={input}
                   placeholder={`auto (${(c.installed || []).join(", ") || "nothing detected"})`}
                   onChange={(e) => set(`provider_${capName}`)(e.target.value)} />
          </div>
        ))}

        <button style={{ ...btn(T.green), marginTop: 8 }} onClick={save}>Save</button>
        {saved && <span style={{ color: T.green, fontSize: 12, marginLeft: 12 }}>{saved}</span>}
      </section>

      {/* ── Which AI answers what ──────────────────────────────────────── */}
      <section style={card}>
        <div style={label}>Which AI answers what</div>
        <div style={{ fontSize: 12, color: T.dim, marginBottom: 14, lineHeight: 1.5 }}>
          Everything runs on your own PC unless you add a key below. Nothing is
          sent anywhere by default. If a paid one fails or runs out of credit,
          Jarvis falls back to the local model rather than stopping.
        </div>

        {ai && Object.entries(ai.routing || {}).map(([task, provider]) => (
          <div key={task} style={{ display: "flex", gap: 10, alignItems: "center",
                                   marginBottom: 8 }}>
            <div style={{ width: 96, fontSize: 11.5, color: T.dim }}>{task}</div>
            <select value={cfg[`ai_route_${task}`] || ""} style={{ ...input, flex: 1 }}
                    onChange={(e) => set(`ai_route_${task}`)(e.target.value)}>
              <option value="">auto ({provider})</option>
              {Object.entries(ai.providers || {}).map(([name, p]) => (
                <option key={name} value={name} disabled={!p.configured}>
                  {p.label || name}{p.configured ? "" : " — no key yet"}
                </option>
              ))}
            </select>
          </div>
        ))}

        <div style={{ ...label, marginTop: 18, marginBottom: 8 }}>Add a paid AI (optional)</div>
        <div style={{ fontSize: 12, color: T.dim, marginBottom: 12, lineHeight: 1.5 }}>
          Paste a key and that provider becomes selectable above. Keys are stored
          on this PC and are never shown in reports — only the first and last few
          characters are ever displayed back.
        </div>
        {["deepseek", "glm", "kimi", "openrouter", "gemini", "openai"].map((p) => {
          const info = ai?.providers?.[p] || {};
          return (
            <div key={p} style={{ display: "flex", gap: 8, alignItems: "center",
                                  marginBottom: 8 }}>
              <div style={{ width: 96, fontSize: 11.5,
                            color: info.configured ? T.green : T.dim }}>
                {info.label || p}
              </div>
              <input type="password" placeholder="API key (leave blank to keep off)"
                     value={cfg[`ai_${p}_api_key`] || ""} style={{ ...input, flex: 1 }}
                     onChange={(e) => set(`ai_${p}_api_key`)(e.target.value)} />
              <input placeholder="model (optional)" value={cfg[`ai_${p}_model`] || ""}
                     style={{ ...input, width: 170 }}
                     onChange={(e) => set(`ai_${p}_model`)(e.target.value)} />
            </div>
          );
        })}

        {ai?.last_used && Object.keys(ai.last_used).length > 0 && (
          <div style={{ marginTop: 14, fontSize: 11.5, color: T.dim }}>
            Last used —{" "}
            {Object.entries(ai.last_used)
              .map(([t, u]) => `${t}: ${u.provider}`).join(" · ")}
          </div>
        )}

        <button style={{ ...btn(T.green), marginTop: 12 }} onClick={save}>Save</button>
      </section>

      {/* ── Security ───────────────────────────────────────────────────── */}
      <section style={card}>
        <div style={label}>Security</div>
        <div style={{ fontSize: 12.5, color: T.text, lineHeight: 1.55, marginBottom: 12 }}>
          {sec?.summary || "Checking…"}
        </div>
        {sec && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))",
                        gap: 12 }}>
            <Fact k="Listening on" v={sec.bound_to} />
            <Fact k="Token required" v={sec.token_required ? "yes" : "no (local only)"} />
            <Fact k="Web pages blocked" v={sec.origin_checked ? "yes" : "NO — turn this on"} />
            <Fact k="Desktop control" v={sec.desktop_control ? "on" : "off"} />
          </div>
        )}
        <div style={{ fontSize: 11.5, color: T.dim, marginTop: 14, lineHeight: 1.6 }}>
          Jarvis can type on your keyboard and use a browser already signed in to
          your accounts. Keep it on 127.0.0.1. Set DESKTOP_CONTROL_ENABLED=0 in
          backend/.env to let the freelance engine keep running while nothing
          touches your desktop.
        </div>
      </section>

      {/* ── Live values ────────────────────────────────────────────────── */}
      <section style={card}>
        <div style={label}>What's actually in effect</div>
        <div style={{ fontSize: 12, color: T.dim, marginBottom: 14, lineHeight: 1.5 }}>
          If you changed something and nothing happened, this is where you find
          out why — the source column shows whether the running system is using
          your value or overriding it.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: "6px 12px",
                      fontSize: 12 }}>
          {effective.map((s) => (
            <Row key={s.key} s={s} />
          ))}
        </div>
      </section>
    </div>
  );
}

function Fact({ k, v }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: T.dim, letterSpacing: "0.1em",
                    textTransform: "uppercase" }}>{k}</div>
      <div style={{ fontSize: 12.5, color: T.text, marginTop: 3 }}>{v}</div>
    </div>
  );
}

function Row({ s }) {
  const mine = (s.source || "").startsWith("you");
  return (
    <>
      <div style={{ color: T.dim }}>{s.key}</div>
      <div style={{ color: T.text, wordBreak: "break-all" }}>
        {s.value === "" || s.value == null
          ? <span style={{ color: T.dim }}>(empty)</span> : String(s.value)}
      </div>
      <div style={{ color: mine ? T.green : T.dim, whiteSpace: "nowrap" }}>{s.source}</div>
    </>
  );
}
