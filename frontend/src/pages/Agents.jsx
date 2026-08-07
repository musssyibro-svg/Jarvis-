import { useEffect, useRef, useState } from "react";
import { btn, tint } from "../colors";
import { API, apiFetch, apiPost } from "../config";

const C = {
  accent: "#00d4ff",
  green: "#00ff88",
  orange: "#ff9500",
  red: "#ff4444",
  purple: "#a78bfa",
};
const card = {
  border: "1px solid rgba(0,212,255,0.15)",
  borderRadius: 4,
  padding: 18,
  background: "rgba(0,8,16,0.8)",
  marginBottom: 12,
};
const label = {
  fontSize: 9,
  color: "rgba(0,212,255,0.45)",
  letterSpacing: "0.2em",
  marginBottom: 10,
  textTransform: "uppercase",
};
const inp = {
  width: "100%",
  background: "rgba(0,10,20,0.9)",
  border: "1px solid rgba(0,212,255,0.2)",
  outline: "none",
  color: "#c8e8f0",
  padding: "8px 11px",
  fontSize: 11,
  fontFamily: "monospace",
  borderRadius: 3,
  boxSizing: "border-box",
};
// tint/edge/btn live in ../colors — they emit plain rgba() rather than doing
// colour maths in CSS, because both earlier attempts here (hex concatenation,
// then color-mix) produced invalid values on some inputs/browsers and the
// buttons rendered as white blanks.
const Dot = ({ on }) => (
  <span
    style={{
      width: 7,
      height: 7,
      borderRadius: "50%",
      background: on ? C.green : "rgba(255,255,255,0.15)",
      boxShadow: on ? `0 0 6px ${C.green}` : "none",
      display: "inline-block",
      marginRight: 6,
    }}
  />
);

const LEVEL_COLOR = { info: C.accent, success: C.green, warning: C.orange, error: C.red };

export default function Agents() {
  const [tab, setTab] = useState("commander");
  const [cmdStatus, setCmdStatus] = useState(null);
  const [feed, setFeed] = useState([]);
  const [cmdInput, setCmdInput] = useState("");
  const [cmdResult, setCmdResult] = useState(null);
  const [cmdBusy, setCmdBusy] = useState(false);
  const [deskStatus, setDeskStatus] = useState(null);
  const [visStatus, setVisStatus] = useState(null);
  const [screenshot, setScreenshot] = useState(null);
  const [ocrResult, setOcrResult] = useState(null);
  const [plans, setPlans] = useState([]);
  const [planGoal, setPlanGoal] = useState("");
  const [planResult, setPlanResult] = useState(null);
  const [memory, setMemory] = useState(null);
  const [insights, setInsights] = useState(null);
  const [appName, setAppName] = useState("chrome");
  const [fmDir, setFmDir] = useState("");
  const [fmQuery, setFmQuery] = useState("");
  const [fmResults, setFmResults] = useState(null);
  const [typeText, setTypeText] = useState("");
  const [analyzeQ, setAnalyzeQ] = useState("What is on the screen?");
  const [findText, setFindText] = useState("");
  const feedRef = useRef(null);
  const sseRef = useRef(null);

  useEffect(() => {
    const connect = () => {
      const es = new EventSource(`${API}/orchestrator/feed`);
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (!d.ping) setFeed((f) => [...f.slice(-149), d]);
        } catch {}
      };
      es.onerror = () => {
        es.close();
        setTimeout(connect, 3000);
      };
      sseRef.current = es;
    };
    connect();
    loadStatus();
    return () => sseRef.current?.close();
  }, []);

  useEffect(() => {
    feedRef.current?.scrollTo(0, feedRef.current.scrollHeight);
  }, [feed]);
  useEffect(() => {
    if (tab === "desktop") loadDesktop();
    if (tab === "memory") loadMemory();
    if (tab === "planner") loadPlans();
  }, [tab]);

  const loadStatus = async () => {
    try {
      setCmdStatus(await apiFetch(`${API}/agents/status`));
    } catch {}
  };
  const loadDesktop = async () => {
    try {
      setDeskStatus(await apiFetch(`${API}/agents/desktop/status`));
      setVisStatus(await apiFetch(`${API}/agents/vision/status`));
    } catch {}
  };
  const loadMemory = async () => {
    try {
      setMemory(await apiFetch(`${API}/agents/memory/status`));
    } catch {}
  };
  const loadPlans = async () => {
    try {
      setPlans((await apiFetch(`${API}/agents/planner/plans`)).plans || []);
    } catch {}
  };

  const sendCommand = async () => {
    if (!cmdInput.trim()) return;
    setCmdBusy(true);
    setCmdResult(null);
    try {
      const r = await apiPost(`${API}/agents/command`, {
        message: cmdInput,
        session_id: "default",
      });
      setCmdResult(r);
    } catch (e) {
      setCmdResult({ response: `Error: ${e.message}`, intent: "error" });
    } finally {
      setCmdBusy(false);
    }
  };

  const takeScreenshot = async () => {
    try {
      const r = await apiPost(`${API}/agents/vision/screenshot`, {});
      setScreenshot(r);
    } catch (e) {
      setScreenshot({ error: e.message });
    }
  };

  const runOcr = async () => {
    try {
      const r = await apiPost(`${API}/agents/vision/ocr`, {});
      setOcrResult(r);
    } catch (e) {
      setOcrResult({ error: e.message });
    }
  };

  const analyzeScreen = async () => {
    try {
      const r = await apiPost(`${API}/agents/vision/analyze`, { question: analyzeQ });
      setOcrResult(r);
    } catch (e) {
      setOcrResult({ error: e.message });
    }
  };

  const findOnScreen = async () => {
    if (!findText.trim()) return;
    try {
      const r = await apiPost(`${API}/agents/vision/find-text`, { text: findText });
      setOcrResult(r);
    } catch (e) {
      setOcrResult({ error: e.message });
    }
  };

  const openApp = async () => {
    try {
      await apiPost(`${API}/agents/desktop/open-app`, { action: "open_app", app: appName });
      setFeed((f) => [
        ...f,
        {
          agent: "desktop",
          msg: `Opened ${appName}`,
          level: "success",
          ts: new Date().toISOString().slice(11, 19),
        },
      ]);
    } catch (e) {
      alert(e.message);
    }
  };

  const openFolder = async () => {
    if (!fmDir.trim()) return;
    try {
      await apiPost(`${API}/agents/desktop/open-folder`, { path: fmDir });
    } catch (e) {
      alert(e.message);
    }
  };

  const searchFiles = async () => {
    if (!fmDir.trim() || !fmQuery.trim()) {
      alert("Enter folder path and search query");
      return;
    }
    try {
      setFmResults(
        await apiPost(`${API}/agents/desktop/search-files`, { directory: fmDir, query: fmQuery })
      );
    } catch (e) {
      setFmResults({ error: e.message });
    }
  };

  const typeOnScreen = async () => {
    if (!typeText.trim()) return;
    try {
      await apiPost(`${API}/agents/desktop/type`, { action: "type", text: typeText });
      setFeed((f) => [
        ...f,
        {
          agent: "desktop",
          msg: `Typed text`,
          level: "success",
          ts: new Date().toISOString().slice(11, 19),
        },
      ]);
    } catch (e) {
      alert(e.message);
    }
  };

  const createPlan = async (exec = false) => {
    if (!planGoal.trim()) return;
    try {
      const r = await apiPost(`${API}/agents/planner/create`, { goal: planGoal, execute: exec });
      setPlanResult(r);
      loadPlans();
    } catch (e) {
      setPlanResult({ error: e.message });
    }
  };

  const executePlan = async (id) => {
    try {
      await apiPost(`${API}/agents/planner/${id}/execute`, {});
      loadPlans();
    } catch (e) {
      alert(e.message);
    }
  };

  const loadInsights = async () => {
    try {
      setInsights(await apiFetch(`${API}/agents/memory/insights`));
    } catch (e) {
      setInsights({ error: e.message });
    }
  };

  const TABS = ["commander", "desktop", "vision", "planner", "registry", "memory", "feed"];

  return (
    <div style={{ padding: 20, overflowY: "auto", height: "100%", boxSizing: "border-box" }}>
      {/* Header */}
      <div style={{ marginBottom: 18 }}>
        <div
          style={{
            fontSize: 9,
            color: "rgba(0,212,255,0.35)",
            letterSpacing: "0.2em",
            marginBottom: 4,
          }}
        >
          AGENT CONTROL
        </div>
        <div style={{ fontSize: 17, fontWeight: 700, color: C.accent, letterSpacing: "0.05em" }}>
          ⬡ AGENT CONTROL
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 6, marginBottom: 18, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              ...btn(tab === t ? C.accent : "#8aa0b4", { active: tab === t }),
              background: tab === t ? tint(C.accent, 0.14) : "transparent",
            }}
          >
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {/* ── COMMANDER ── */}
      {tab === "commander" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div>
            <div style={card}>
              <div style={label}>AGENT STATUS</div>
              {cmdStatus ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {[
                    ["Commander", true],
                    ["Desktop", cmdStatus.desktop?.pyautogui],
                    ["Vision", cmdStatus.vision?.mss || cmdStatus.vision?.pillow],
                    ["Browser", true],
                    ["Memory", true],
                    ["Planner", true],
                  ].map(([name, ok]) => (
                    <div
                      key={name}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "5px 0",
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                      }}
                    >
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontSize: 10,
                          color: "rgba(255,255,255,0.5)",
                        }}
                      >
                        <Dot on={ok} />
                        {name}Agent
                      </span>
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontSize: 9,
                          color: ok ? C.green : "rgba(255,255,255,0.2)",
                        }}
                      >
                        {ok ? "ONLINE" : "OFFLINE"}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: "rgba(255,255,255,0.2)", fontSize: 11 }}>Loading…</div>
              )}
            </div>

            <div style={card}>
              <div style={label}>SEND COMMAND</div>
              <p
                style={{
                  fontSize: 11,
                  color: "rgba(255,255,255,0.35)",
                  lineHeight: 1.6,
                  marginBottom: 12,
                }}
              >
                Natural language → Commander routes to correct agent automatically.
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <textarea
                  value={cmdInput}
                  onChange={(e) => setCmdInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      sendCommand();
                    }
                  }}
                  placeholder="Take a screenshot&#10;Open notepad&#10;What's on my screen?&#10;Plan: how to apply for jobs"
                  rows={4}
                  style={{ ...inp, resize: "vertical" }}
                />
                <button onClick={sendCommand} disabled={cmdBusy} style={btn(C.green)}>
                  {cmdBusy ? "⟳ PROCESSING…" : "▶ SEND TO COMMANDER"}
                </button>
              </div>
              {[
                "Take a screenshot",
                "Open notepad",
                "What's on my screen?",
                "Plan: apply for 3 jobs today",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => {
                    setCmdInput(q);
                  }}
                  style={{ ...btn("#8aa0b4"), marginTop: 5, marginRight: 5, fontSize: 8 }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>

          <div>
            {cmdResult && (
              <div style={card}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <div style={label}>RESPONSE</div>
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontSize: 8,
                      padding: "2px 7px",
                      borderRadius: 2,
                      border: `1px solid ${C.accent}44`,
                      color: C.accent,
                    }}
                  >
                    {cmdResult.intent?.toUpperCase()}
                  </span>
                </div>
                <div
                  style={{
                    background: "rgba(0,4,8,0.9)",
                    padding: 12,
                    borderRadius: 3,
                    fontSize: 11,
                    color: "rgba(200,230,240,0.8)",
                    lineHeight: 1.7,
                    whiteSpace: "pre-wrap",
                    maxHeight: 250,
                    overflowY: "auto",
                  }}
                >
                  {cmdResult.response || JSON.stringify(cmdResult, null, 2)}
                </div>
                {cmdResult.plan && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 9, color: C.orange, marginBottom: 6 }}>
                      PLAN ({cmdResult.plan.steps?.length} steps)
                    </div>
                    {cmdResult.plan.steps?.map((s) => (
                      <div
                        key={s.step}
                        style={{
                          fontSize: 10,
                          color: "rgba(255,255,255,0.4)",
                          padding: "3px 0",
                          borderBottom: "1px solid rgba(255,255,255,0.04)",
                        }}
                      >
                        <span style={{ color: C.accent, marginRight: 8 }}>{s.step}.</span>
                        {s.description}
                      </div>
                    ))}
                    {cmdResult.plan_id && (
                      <button
                        onClick={() => executePlan(cmdResult.plan_id)}
                        style={{ ...btn(C.green), marginTop: 10 }}
                      >
                        ▶ EXECUTE PLAN
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
            {/* Mini feed */}
            <div style={card}>
              <div style={label}>LIVE FEED</div>
              <div
                ref={feedRef}
                style={{
                  background: "rgba(0,4,8,0.9)",
                  borderRadius: 3,
                  padding: 10,
                  height: 200,
                  overflowY: "auto",
                  fontFamily: "monospace",
                  fontSize: 9,
                }}
              >
                {feed.length === 0 && (
                  <span style={{ color: "rgba(255,255,255,0.15)" }}>Waiting…</span>
                )}
                {feed.map((e, i) => (
                  <div key={i} style={{ lineHeight: 1.9, color: LEVEL_COLOR[e.level] || C.accent }}>
                    <span style={{ color: "rgba(255,255,255,0.2)", marginRight: 6 }}>{e.ts}</span>
                    <span style={{ color: "rgba(255,255,255,0.3)", marginRight: 6 }}>
                      [{e.agent}]
                    </span>
                    {e.msg}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── DESKTOP ── */}
      {tab === "desktop" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div>
            <div style={card}>
              <div style={label}>DESKTOP CONTROL STATUS</div>
              {deskStatus ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  {Object.entries(deskStatus.capabilities || {}).map(([k, v]) => (
                    <div
                      key={k}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: 10,
                        padding: "4px 0",
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                      }}
                    >
                      <span style={{ color: "rgba(255,255,255,0.4)", fontFamily: "monospace" }}>
                        {k}
                      </span>
                      <span style={{ color: v ? C.green : C.red, fontFamily: "monospace" }}>
                        {v ? "✓" : "✗"}
                      </span>
                    </div>
                  ))}
                  {deskStatus.screen && (
                    <div
                      style={{
                        fontSize: 9,
                        color: "rgba(255,255,255,0.25)",
                        fontFamily: "monospace",
                        marginTop: 8,
                      }}
                    >
                      Screen: {deskStatus.screen.width}×{deskStatus.screen.height} | Mouse:{" "}
                      {deskStatus.screen.mouse_x},{deskStatus.screen.mouse_y}
                    </div>
                  )}
                </div>
              ) : (
                <button onClick={loadDesktop} style={btn()}>
                  Load Status
                </button>
              )}
              {!deskStatus?.pyautogui && (
                <div
                  style={{
                    marginTop: 10,
                    padding: "8px 10px",
                    background: "rgba(255,149,0,0.08)",
                    border: "1px solid rgba(255,149,0,0.25)",
                    borderRadius: 3,
                    fontSize: 10,
                    color: C.orange,
                  }}
                >
                  Install: pip install pyautogui pygetwindow
                </div>
              )}
            </div>

            <div style={card}>
              <div style={label}>OPEN APPLICATION</div>
              <div style={{ display: "flex", gap: 7, marginBottom: 8 }}>
                <input
                  value={appName}
                  onChange={(e) => setAppName(e.target.value)}
                  style={{ ...inp, flex: 1 }}
                  placeholder="notepad, chrome, edge…"
                />
                <button onClick={openApp} style={btn(C.green)}>
                  OPEN
                </button>
              </div>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {[
                  "chrome",
                  "edge",
                  "vscode",
                  "discord",
                  "telegram",
                  "steam",
                  "explorer",
                  "notepad",
                  "calculator",
                  "spotify",
                  "cmd",
                ].map((a) => (
                  <button
                    key={a}
                    onClick={() => {
                      setAppName(a);
                    }}
                    style={{ ...btn("#8aa0b4"), fontSize: 8 }}
                  >
                    {a}
                  </button>
                ))}
              </div>
            </div>

            <div style={card}>
              <div style={label}>TYPE TEXT</div>
              <textarea
                value={typeText}
                onChange={(e) => setTypeText(e.target.value)}
                rows={3}
                style={{ ...inp, marginBottom: 8 }}
                placeholder="Text to type on screen…"
              />
              <button onClick={typeOnScreen} style={btn(C.green)}>
                TYPE ON SCREEN
              </button>
            </div>
          </div>

          <div>
            <div style={card}>
              <div style={label}>QUICK ACTIONS</div>
              {[
                [
                  "Take Screenshot",
                  () =>
                    apiPost(`${API}/agents/desktop/screenshot`, {}).then((r) => setScreenshot(r)),
                  "#00d4ff",
                ],
                [
                  "Copy (Ctrl+C)",
                  () =>
                    apiPost(`${API}/agents/execute`, {
                      action: "hotkey",
                      params: { keys: ["ctrl", "c"] },
                    }),
                  "#00ff88",
                ],
                [
                  "Paste (Ctrl+V)",
                  () =>
                    apiPost(`${API}/agents/execute`, {
                      action: "hotkey",
                      params: { keys: ["ctrl", "v"] },
                    }),
                  "#00ff88",
                ],
                [
                  "Select All",
                  () =>
                    apiPost(`${API}/agents/execute`, {
                      action: "hotkey",
                      params: { keys: ["ctrl", "a"] },
                    }),
                  "#ff9500",
                ],
                [
                  "Press Escape",
                  () =>
                    apiPost(`${API}/agents/execute`, {
                      action: "press",
                      params: { key: "escape" },
                    }),
                  "#ff4444",
                ],
                [
                  "Press Enter",
                  () =>
                    apiPost(`${API}/agents/execute`, { action: "press", params: { key: "enter" } }),
                  "#a78bfa",
                ],
              ].map(([label, fn, c]) => (
                <button
                  key={label}
                  onClick={fn}
                  style={{
                    ...btn(c),
                    marginBottom: 6,
                    marginRight: 6,
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            <div style={card}>
              <div style={label}>CLOSE APP</div>
              <div style={{ display: "flex", gap: 7 }}>
                <input
                  id="closeApp"
                  style={{ ...inp, flex: 1 }}
                  placeholder="chrome, notepad, discord…"
                />
                <button
                  onClick={() => {
                    const v = document.getElementById("closeApp").value;
                    if (v) apiPost(`${API}/agents/desktop/close-app`, { app: v });
                  }}
                  style={btn(C.red)}
                >
                  CLOSE
                </button>
              </div>
            </div>

            <div style={card}>
              <div style={label}>FILE MANAGER</div>
              <div style={{ display: "flex", gap: 7, marginBottom: 8 }}>
                <input
                  value={fmDir}
                  onChange={(e) => setFmDir(e.target.value)}
                  style={{ ...inp, flex: 1 }}
                  placeholder="Folder path (e.g. C:\\Users\\You\\Documents)"
                />
                <button onClick={openFolder} style={btn(C.accent)}>
                  OPEN
                </button>
              </div>
              <div style={{ display: "flex", gap: 7, marginBottom: 8 }}>
                <input
                  value={fmQuery}
                  onChange={(e) => setFmQuery(e.target.value)}
                  style={{ ...inp, flex: 1 }}
                  placeholder="Search filename…"
                />
                <button onClick={searchFiles} style={btn(C.green)}>
                  SEARCH
                </button>
              </div>
              {fmResults && (
                <div
                  style={{
                    background: "rgba(0,4,8,0.8)",
                    borderRadius: 3,
                    padding: 10,
                    maxHeight: 200,
                    overflowY: "auto",
                    marginTop: 6,
                  }}
                >
                  {fmResults.error && (
                    <div style={{ color: C.red, fontSize: 11 }}>{fmResults.error}</div>
                  )}
                  {fmResults.matches?.length === 0 && (
                    <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 11 }}>No matches</div>
                  )}
                  {fmResults.matches?.map((m, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        padding: "4px 0",
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                        fontSize: 10,
                      }}
                    >
                      <span
                        style={{
                          color: m.is_dir ? C.orange : "rgba(255,255,255,0.6)",
                          fontFamily: "monospace",
                        }}
                      >
                        {m.is_dir ? "📁" : "📄"} {m.name}
                      </span>
                      <button
                        onClick={() => {
                          if (confirm(`Delete ${m.name}?`))
                            apiPost(`${API}/agents/desktop/delete-file`, {
                              path: m.path,
                              confirm: true,
                            }).then(() => searchFiles());
                        }}
                        style={{
                          background: "none",
                          border: "none",
                          color: C.red,
                          cursor: "pointer",
                          fontSize: 9,
                        }}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── VISION ── */}
      {tab === "vision" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div>
            <div style={card}>
              <div style={label}>VISION STATUS</div>
              {visStatus ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  {Object.entries(visStatus.capabilities || {}).map(([k, v]) => (
                    <div
                      key={k}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: 10,
                        padding: "4px 0",
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                      }}
                    >
                      <span style={{ color: "rgba(255,255,255,0.4)", fontFamily: "monospace" }}>
                        {k}
                      </span>
                      <span style={{ color: v ? C.green : C.red, fontFamily: "monospace" }}>
                        {v ? "✓" : "✗"}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <button onClick={loadDesktop} style={btn()}>
                  Load Status
                </button>
              )}
              {!visStatus?.mss && (
                <div
                  style={{
                    marginTop: 10,
                    padding: "8px 10px",
                    background: "rgba(255,149,0,0.08)",
                    border: "1px solid rgba(255,149,0,0.25)",
                    borderRadius: 3,
                    fontSize: 10,
                    color: C.orange,
                  }}
                >
                  Install: pip install mss Pillow pytesseract opencv-python
                </div>
              )}
            </div>

            <div style={card}>
              <div style={label}>SCREEN ACTIONS</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <button onClick={takeScreenshot} style={btn(C.accent)}>
                  📷 TAKE SCREENSHOT
                </button>
                <button onClick={runOcr} style={btn(C.green)}>
                  🔍 READ TEXT (OCR)
                </button>
                <div style={{ height: 1, background: "rgba(255,255,255,0.06)", margin: "2px 0" }} />
                <input
                  value={analyzeQ}
                  onChange={(e) => setAnalyzeQ(e.target.value)}
                  style={inp}
                  placeholder="Ask about the screen…"
                />
                <button onClick={analyzeScreen} style={btn(C.purple)}>
                  🤖 AI ANALYZE SCREEN
                </button>
                <div style={{ height: 1, background: "rgba(255,255,255,0.06)", margin: "2px 0" }} />
                <input
                  value={findText}
                  onChange={(e) => setFindText(e.target.value)}
                  style={inp}
                  placeholder="Text to find on screen…"
                />
                <div style={{ display: "flex", gap: 7 }}>
                  <button onClick={findOnScreen} style={{ ...btn(C.orange), flex: 1 }}>
                    🔎 FIND TEXT
                  </button>
                  <button
                    onClick={async () => {
                      if (!findText.trim()) return;
                      try {
                        setOcrResult(
                          await apiPost(`${API}/agents/vision/click-text`, { text: findText })
                        );
                      } catch (e) {
                        setOcrResult({ error: e.message });
                      }
                    }}
                    style={{ ...btn(C.green), flex: 1 }}
                  >
                    🎯 FIND + CLICK IT
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div>
            {screenshot && (
              <div style={card}>
                <div style={label}>SCREENSHOT</div>
                <div
                  style={{
                    fontSize: 10,
                    color: "rgba(255,255,255,0.3)",
                    fontFamily: "monospace",
                    marginBottom: 6,
                  }}
                >
                  {screenshot.width}×{screenshot.height} — {screenshot.path}
                </div>
                {screenshot.error && (
                  <div style={{ color: C.red, fontSize: 11 }}>{screenshot.error}</div>
                )}
              </div>
            )}
            {ocrResult && (
              <div style={card}>
                <div style={label}>RESULT</div>
                {ocrResult.found !== undefined && (
                  <div
                    style={{
                      fontFamily: "monospace",
                      fontSize: 11,
                      color: ocrResult.found ? C.green : C.red,
                      marginBottom: 8,
                    }}
                  >
                    {ocrResult.found ? "✓ FOUND" : "✗ NOT FOUND"}: "{ocrResult.search}"
                  </div>
                )}
                {(ocrResult.ai_answer || ocrResult.answer) && (
                  <div
                    style={{
                      background: "rgba(0,4,8,0.8)",
                      padding: 10,
                      borderRadius: 3,
                      fontSize: 11,
                      color: "rgba(200,230,240,0.8)",
                      lineHeight: 1.7,
                      marginBottom: 8,
                      borderLeft: `2px solid ${C.purple}`,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 8,
                        color: C.purple,
                        letterSpacing: "0.15em",
                        marginBottom: 5,
                        fontFamily: "monospace",
                      }}
                    >
                      AI ANALYSIS {ocrResult.method ? `(${ocrResult.method})` : ""}
                    </div>
                    {ocrResult.ai_answer || ocrResult.answer}
                  </div>
                )}
                {ocrResult.target && ocrResult.success && (
                  <div
                    style={{
                      fontFamily: "monospace",
                      fontSize: 11,
                      color: C.green,
                      marginBottom: 8,
                    }}
                  >
                    ✓ Clicked "{ocrResult.matched || ocrResult.target}" at ({ocrResult.x},
                    {ocrResult.y})
                  </div>
                )}
                {ocrResult.text && (
                  <div
                    style={{
                      background: "rgba(0,4,8,0.8)",
                      padding: 10,
                      borderRadius: 3,
                      fontFamily: "monospace",
                      fontSize: 9,
                      color: "rgba(200,230,240,0.5)",
                      maxHeight: 200,
                      overflowY: "auto",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {ocrResult.text.slice(0, 1500)}
                  </div>
                )}
                {ocrResult.error && (
                  <div style={{ color: C.red, fontSize: 11 }}>{ocrResult.error}</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── PLANNER ── */}
      {tab === "planner" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div>
            <div style={card}>
              <div style={label}>CREATE PLAN (Observe→Plan→Execute→Learn)</div>
              <textarea
                value={planGoal}
                onChange={(e) => setPlanGoal(e.target.value)}
                rows={3}
                style={{ ...inp, marginBottom: 10 }}
                placeholder="Goal: Apply for 3 Python automation jobs today&#10;Goal: Check my Freelancer messages and draft replies&#10;Goal: Open Chrome and search for remote Python jobs"
              />
              <div style={{ display: "flex", gap: 7 }}>
                <button onClick={() => createPlan(false)} style={btn(C.accent)}>
                  CREATE PLAN
                </button>
                <button onClick={() => createPlan(true)} style={btn(C.green)}>
                  CREATE + EXECUTE
                </button>
              </div>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 8 }}>
                {[
                  "Apply for 3 Python jobs today",
                  "Check Freelancer inbox and draft replies",
                  "Screenshot and analyze my screen",
                ].map((g) => (
                  <button
                    key={g}
                    onClick={() => setPlanGoal(g)}
                    style={{ ...btn("#8aa0b4"), fontSize: 8 }}
                  >
                    {g}
                  </button>
                ))}
              </div>
            </div>
            {planResult && (
              <div style={card}>
                <div style={label}>PLAN CREATED</div>
                {planResult.error && (
                  <div style={{ color: C.red, fontSize: 11 }}>{planResult.error}</div>
                )}
                {planResult.plan && (
                  <>
                    <div style={{ fontSize: 11, color: "rgba(255,255,255,0.5)", marginBottom: 10 }}>
                      {planResult.plan.goal}
                    </div>
                    {planResult.plan.steps?.map((s) => (
                      <div
                        key={s.step}
                        style={{
                          display: "flex",
                          gap: 10,
                          padding: "6px 0",
                          borderBottom: "1px solid rgba(255,255,255,0.04)",
                        }}
                      >
                        <span
                          style={{
                            fontFamily: "monospace",
                            fontSize: 10,
                            color: C.accent,
                            minWidth: 20,
                          }}
                        >
                          {s.step}.
                        </span>
                        <div>
                          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.6)" }}>
                            {s.description}
                          </div>
                          <div
                            style={{
                              fontSize: 9,
                              color: "rgba(255,255,255,0.25)",
                              fontFamily: "monospace",
                            }}
                          >
                            {s.action}({JSON.stringify(s.params)})
                          </div>
                        </div>
                      </div>
                    ))}
                    {planResult.plan_id && !planResult.executing && (
                      <button
                        onClick={() => executePlan(planResult.plan_id)}
                        style={{ ...btn(C.green), marginTop: 10 }}
                      >
                        ▶ EXECUTE THIS PLAN
                      </button>
                    )}
                    {planResult.executing && (
                      <div
                        style={{
                          fontSize: 10,
                          color: C.green,
                          fontFamily: "monospace",
                          marginTop: 8,
                        }}
                      >
                        ● Executing in background — watch the feed
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
          <div>
            <div style={card}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 10,
                }}
              >
                <div style={label}>SAVED PLANS</div>
                <button
                  onClick={loadPlans}
                  style={{ ...btn("#8aa0b4"), padding: "3px 8px", fontSize: 8 }}
                >
                  ↺
                </button>
              </div>
              {plans.length === 0 && (
                <div style={{ color: "rgba(255,255,255,0.2)", fontSize: 11 }}>No plans yet</div>
              )}
              {plans.map((p) => (
                <div
                  key={p.id}
                  style={{ padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.05)" }}
                >
                  <div
                    style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}
                  >
                    <span style={{ fontSize: 11, color: "rgba(255,255,255,0.6)" }}>
                      {p.goal?.slice(0, 50)}
                    </span>
                    <span
                      style={{
                        fontFamily: "monospace",
                        fontSize: 8,
                        color:
                          p.status === "done"
                            ? C.green
                            : p.status === "running"
                              ? C.orange
                              : C.accent,
                      }}
                    >
                      {p.status?.toUpperCase()}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      onClick={() => executePlan(p.id)}
                      style={{ ...btn(C.green), fontSize: 8, padding: "3px 10px" }}
                    >
                      ▶ RUN
                    </button>
                    <span
                      style={{
                        fontSize: 9,
                        color: "rgba(255,255,255,0.2)",
                        fontFamily: "monospace",
                        alignSelf: "center",
                      }}
                    >
                      {p.created_at?.slice(0, 16)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── REGISTRY (add / manage custom agents) ── */}
      {tab === "registry" && <RegistryPanel />}

      {/* ── MEMORY ── */}
      {tab === "memory" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div>
            <div style={card}>
              <div style={label}>MEMORY STATUS</div>
              {memory ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  {[
                    ["Win Patterns", memory.win_patterns],
                    ["Fail Patterns", memory.fail_patterns],
                    ["KV Records", memory.kv_count],
                  ].map(([k, v]) => (
                    <div
                      key={k}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: 11,
                        padding: "5px 0",
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                      }}
                    >
                      <span style={{ color: "rgba(255,255,255,0.4)" }}>{k}</span>
                      <span style={{ fontFamily: "monospace", color: C.accent }}>{v}</span>
                    </div>
                  ))}
                  {memory.platforms?.map((p) => (
                    <div
                      key={p.platform}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: 11,
                        padding: "5px 0",
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                      }}
                    >
                      <span style={{ color: "rgba(255,255,255,0.4)" }}>{p.platform}</span>
                      <span
                        style={{
                          fontFamily: "monospace",
                          color: p.win_rate > 30 ? C.green : C.orange,
                        }}
                      >
                        {p.win_rate}% win ({p.total_won}/{p.total_sent})
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <button onClick={loadMemory} style={btn()}>
                  Load Memory
                </button>
              )}
            </div>

            <div style={card}>
              <div style={label}>AI INSIGHTS</div>
              <button onClick={loadInsights} style={{ ...btn(C.purple), marginBottom: 12 }}>
                🧠 GENERATE INSIGHTS
              </button>
              {insights && (
                <>
                  {insights.error && (
                    <div style={{ color: C.red, fontSize: 11 }}>{insights.error}</div>
                  )}
                  {insights.insights?.map((ins, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        gap: 8,
                        padding: "6px 0",
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                      }}
                    >
                      <span style={{ color: C.purple, fontFamily: "monospace", fontSize: 10 }}>
                        →
                      </span>
                      <span
                        style={{ fontSize: 11, color: "rgba(200,230,240,0.7)", lineHeight: 1.6 }}
                      >
                        {ins}
                      </span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
          <div>
            <div style={card}>
              <div style={label}>RECORD OUTCOME (LEARNING)</div>
              <OutcomeForm
                onSave={async (data) => {
                  await apiPost(`${API}/agents/memory/outcome`, data);
                  loadMemory();
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* ── FEED ── */}
      {tab === "feed" && (
        <div style={card}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <div style={label}>LIVE AGENT FEED</div>
            <button
              onClick={() => setFeed([])}
              style={{ ...btn("#8aa0b4"), padding: "3px 10px", fontSize: 8 }}
            >
              CLEAR
            </button>
          </div>
          <div
            style={{
              background: "rgba(0,4,8,0.95)",
              borderRadius: 3,
              padding: 14,
              height: "calc(100vh - 220px)",
              overflowY: "auto",
              fontFamily: "monospace",
              fontSize: 10,
            }}
          >
            {feed.length === 0 && (
              <div style={{ color: "rgba(255,255,255,0.15)" }}>
                No events yet. Interact with any agent to see live activity.
              </div>
            )}
            {feed.map((e, i) => (
              <div
                key={i}
                style={{ lineHeight: 2, borderBottom: "1px solid rgba(255,255,255,0.03)" }}
              >
                <span style={{ color: "rgba(255,255,255,0.18)", marginRight: 8, fontSize: 9 }}>
                  {e.ts}
                </span>
                <span
                  style={{
                    marginRight: 8,
                    padding: "1px 6px",
                    borderRadius: 2,
                    fontSize: 8,
                    background: `${LEVEL_COLOR[e.level] || C.accent}18`,
                    color: LEVEL_COLOR[e.level] || C.accent,
                    border: `1px solid ${LEVEL_COLOR[e.level] || C.accent}33`,
                  }}
                >
                  {e.agent}
                </span>
                <span style={{ color: LEVEL_COLOR[e.level] || "rgba(200,230,240,0.7)" }}>
                  {e.msg}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RegistryPanel() {
  const [agents, setAgents] = useState([]);
  const [template, setTemplate] = useState("");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState(null);
  const [runOut, setRunOut] = useState(null);

  const load = async () => {
    try {
      const r = await apiFetch(`${API}/agents/registry`);
      setAgents(r.agents || []);
      if (r.template && !code) setTemplate(r.template);
    } catch {}
  };
  useEffect(() => {
    load();
  }, []);

  const install = async () => {
    if (!name.trim() || !code.trim()) {
      setMsg({ err: "Name and code required" });
      return;
    }
    try {
      const r = await apiPost(`${API}/agents/registry/install`, { name, code, description: desc });
      setMsg({ ok: `Installed '${r.name}' (${r.kind}) ✓ — it's live now` });
      setName("");
      setCode("");
      setDesc("");
      load();
    } catch (e) {
      setMsg({ err: e.message });
    }
  };

  const toggle = async (n) => {
    try {
      await apiPost(`${API}/agents/registry/${n}/toggle`, {});
      load();
    } catch (e) {
      alert(e.message);
    }
  };
  const remove = async (n) => {
    if (!confirm(`Remove custom agent '${n}'?`)) return;
    try {
      await fetch(`${API}/agents/registry/${n}`, { method: "DELETE" });
      load();
    } catch (e) {
      alert(e.message);
    }
  };
  const runAgent = async (n) => {
    try {
      setRunOut({
        agent: n,
        ...(await apiPost(`${API}/agents/registry/${n}/run`, { context: {} })),
      });
    } catch (e) {
      setRunOut({ agent: n, error: e.message });
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
      <div>
        <div style={card}>
          <div style={label}>ADD AGENT — PASTE PYTHON, IT GOES LIVE</div>
          <p
            style={{
              fontSize: 11,
              color: "rgba(255,255,255,0.35)",
              lineHeight: 1.6,
              marginBottom: 10,
            }}
          >
            Any class with a <code style={{ color: C.green }}>run(context)</code> method (or a plain
            <code style={{ color: C.green }}> run(context)</code> function) becomes a Jarvis agent:
            saved to <code style={{ color: C.accent }}>agents/custom/</code>, registered instantly,
            reloaded on every restart, callable by the orchestrator and from this panel.
          </p>
          <div style={{ display: "flex", gap: 7, marginBottom: 8 }}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ ...inp, flex: 1 }}
              placeholder="agent_name (letters/underscores)"
            />
            <input
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              style={{ ...inp, flex: 2 }}
              placeholder="what it does (optional)"
            />
          </div>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            rows={12}
            style={{
              ...inp,
              fontFamily: "monospace",
              fontSize: 10,
              resize: "vertical",
              marginBottom: 8,
            }}
            placeholder={
              template || 'class MyAgent:\n    def run(self, context):\n        return {"ok": True}'
            }
          />
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={install} style={btn(C.green)}>
              ⬢ INSTALL AGENT
            </button>
            <button onClick={() => setCode(template)} style={btn("#8aa0b4")}>
              USE TEMPLATE
            </button>
          </div>
          {msg?.ok && (
            <div style={{ marginTop: 8, fontSize: 10, color: C.green, fontFamily: "monospace" }}>
              {msg.ok}
            </div>
          )}
          {msg?.err && (
            <div style={{ marginTop: 8, fontSize: 10, color: C.red, fontFamily: "monospace" }}>
              {msg.err}
            </div>
          )}
        </div>
        {runOut && (
          <div style={card}>
            <div style={label}>RUN OUTPUT — {runOut.agent}</div>
            <pre
              style={{
                background: "rgba(0,4,8,0.9)",
                padding: 10,
                borderRadius: 3,
                fontSize: 10,
                color: "rgba(200,230,240,0.7)",
                maxHeight: 220,
                overflowY: "auto",
                whiteSpace: "pre-wrap",
              }}
            >
              {JSON.stringify(runOut, null, 2)}
            </pre>
          </div>
        )}
      </div>
      <div>
        <div style={card}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <div style={label}>REGISTERED AGENTS ({agents.length})</div>
            <button onClick={load} style={{ ...btn("#8aa0b4"), padding: "3px 8px", fontSize: 8 }}>
              ↺
            </button>
          </div>
          {agents.map((a) => (
            <div
              key={a.name}
              style={{ padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.05)" }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                <Dot on={a.enabled} />
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: "#c4e4ef",
                    fontFamily: "monospace",
                  }}
                >
                  {a.name}
                </span>
                <span
                  style={{
                    fontSize: 8,
                    padding: "1px 6px",
                    borderRadius: 2,
                    fontFamily: "monospace",
                    background:
                      a.source === "custom" ? "rgba(167,139,250,0.15)" : "rgba(0,212,255,0.1)",
                    color: a.source === "custom" ? C.purple : C.accent,
                    border: `1px solid ${a.source === "custom" ? C.purple : C.accent}33`,
                  }}
                >
                  {a.source.toUpperCase()}
                </span>
                <span style={{ flex: 1 }} />
                <button
                  onClick={() => runAgent(a.name)}
                  style={{ ...btn(C.green), fontSize: 8, padding: "3px 9px" }}
                >
                  ▶ RUN
                </button>
                <button
                  onClick={() => toggle(a.name)}
                  style={{ ...btn(C.orange), fontSize: 8, padding: "3px 9px" }}
                >
                  {a.enabled ? "DISABLE" : "ENABLE"}
                </button>
                {a.source === "custom" && (
                  <button
                    onClick={() => remove(a.name)}
                    style={{ ...btn(C.red), fontSize: 8, padding: "3px 9px" }}
                  >
                    ✕
                  </button>
                )}
              </div>
              {(a.description || a.kind) && (
                <div
                  style={{
                    fontSize: 9,
                    color: "rgba(255,255,255,0.3)",
                    fontFamily: "monospace",
                    paddingLeft: 15,
                  }}
                >
                  {a.kind}
                  {a.kind && a.description ? " — " : ""}
                  {a.description}
                </div>
              )}
            </div>
          ))}
          {agents.length === 0 && (
            <div style={{ color: "rgba(255,255,255,0.2)", fontSize: 11 }}>Loading registry…</div>
          )}
        </div>
      </div>
    </div>
  );
}

function OutcomeForm({ onSave }) {
  const [platform, setPlatform] = useState("freelancer");
  const [jobType, setJobType] = useState("code");
  const [snippet, setSnippet] = useState("");
  const [won, setWon] = useState(true);
  const [response, setResponse] = useState("");
  const submit = async () => {
    await onSave({
      platform,
      job_type: jobType,
      proposal_snippet: snippet,
      won,
      client_response: response,
    });
    setSnippet("");
    setResponse("");
  };
  const inp = {
    width: "100%",
    background: "rgba(0,10,20,0.9)",
    border: "1px solid rgba(0,212,255,0.2)",
    outline: "none",
    color: "#c8e8f0",
    padding: "7px 10px",
    fontSize: 11,
    fontFamily: "monospace",
    borderRadius: 3,
    boxSizing: "border-box",
    marginBottom: 8,
  };
  const sel = { ...inp, cursor: "pointer" };
  return (
    <div>
      <select value={platform} onChange={(e) => setPlatform(e.target.value)} style={sel}>
        {["freelancer", "hubstaff", "remoteok", "weworkremotely", "peopleperhour", "contra"].map(
          (p) => (
            <option key={p} value={p}>
              {p}
            </option>
          )
        )}
      </select>
      <select value={jobType} onChange={(e) => setJobType(e.target.value)} style={sel}>
        {["code", "writing", "research", "data", "email", "seo", "automation", "other"].map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <textarea
        value={snippet}
        onChange={(e) => setSnippet(e.target.value)}
        rows={3}
        style={inp}
        placeholder="Proposal snippet (first 100 words)…"
      />
      <textarea
        value={response}
        onChange={(e) => setResponse(e.target.value)}
        rows={2}
        style={inp}
        placeholder="Client response (optional)…"
      />
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
        <label
          style={{
            fontSize: 11,
            color: "rgba(255,255,255,0.5)",
            display: "flex",
            alignItems: "center",
            gap: 6,
            cursor: "pointer",
          }}
        >
          <input
            type="checkbox"
            checked={won}
            onChange={(e) => setWon(e.target.checked)}
            style={{ accentColor: "#00ff88" }}
          />
          Won this project
        </label>
      </div>
      <button
        onClick={submit}
        style={{
          padding: "7px 16px",
          borderRadius: 3,
          border: "1px solid #00ff88",
          background: "rgba(0,255,136,0.1)",
          color: "#00ff88",
          fontFamily: "monospace",
          fontSize: 9,
          cursor: "pointer",
        }}
      >
        💾 SAVE OUTCOME
      </button>
    </div>
  );
}
