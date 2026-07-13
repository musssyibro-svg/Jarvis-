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

function NeuralCore({ state }) {
  const ref = useRef(null), stateRef = useRef(state), shockRef = useRef(0), prev = useRef(state);
  useEffect(() => {
    if (prev.current !== state) { shockRef.current = 1; prev.current = state; }
    stateRef.current = state;
  }, [state]);
  useEffect(() => {
    const canvas = ref.current, ctx = canvas.getContext("2d");
    let raf, t = 0;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    const size = () => {
      const r = canvas.getBoundingClientRect();
      canvas.width = r.width * DPR; canvas.height = r.height * DPR;
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    };
    size();
    const ro = new ResizeObserver(size); ro.observe(canvas);

    // ambient drifting motes (survive forever; live in dead space at low opacity)
    const MOTES = 40;
    const motes = Array.from({ length: MOTES }, () => ({
      x: Math.random(), y: Math.random(),
      vx: (Math.random() - 0.5) * 0.0004, vy: (Math.random() - 0.5) * 0.0004,
      sz: 0.5 + Math.random() * 1.3,
    }));

    const PN = 64;
    const parts = Array.from({ length: PN }, (_, i) => ({
      a: (i / PN) * Math.PI * 2, r: 0, base: 0.5 + Math.random() * 0.5,
      sp: 0.0015 + Math.random() * 0.004, sz: 0.7 + Math.random() * 2.0,
    }));

    const draw = () => {
      const st = stateRef.current, s = STATES[st] || STATES.idle, col = s.color;
      const r = canvas.getBoundingClientRect(), cx = r.width / 2, cy = r.height / 2;
      const R = Math.min(cx, cy);
      // SCENE OCCUPANCY ~80%, orb +30%, orbit +20% vs 3.5
      const ORB = R * 0.21, ORBIT = R * 0.94;
      ctx.clearRect(0, 0, r.width, r.height);
      t += 0.016 * s.speed;

      // ── ambient layer: parallax scan line + drifting motes + hex mesh (3-7%) ──
      ctx.save(); ctx.globalAlpha = 0.045; ctx.strokeStyle = col; ctx.lineWidth = 0.5;
      const hx = 30;
      for (let y = 0; y < r.height + hx; y += hx * 0.86)
        for (let x = 0; x < r.width + hx; x += hx * 1.5) {
          const ox = (Math.floor(y / (hx * 0.86)) % 2) * hx * 0.75;
          drawHex(ctx, x + ox, y, hx * 0.5);
        }
      ctx.restore();
      // drifting motes
      ctx.save();
      motes.forEach((m) => {
        m.x += m.vx; m.y += m.vy;
        if (m.x < 0) m.x = 1; if (m.x > 1) m.x = 0;
        if (m.y < 0) m.y = 1; if (m.y > 1) m.y = 0;
        ctx.beginPath(); ctx.arc(m.x * r.width, m.y * r.height, m.sz, 0, Math.PI * 2);
        ctx.fillStyle = hexA(col, 0.06); ctx.fill();
      });
      ctx.restore();
      // slow vertical scan sweep
      const sweepY = ((t * 0.06) % 1) * r.height;
      const sg = ctx.createLinearGradient(0, sweepY - 60, 0, sweepY + 60);
      sg.addColorStop(0, hexA(col, 0)); sg.addColorStop(0.5, hexA(col, 0.04)); sg.addColorStop(1, hexA(col, 0));
      ctx.fillStyle = sg; ctx.fillRect(0, sweepY - 60, r.width, 120);

      // ambient core glow
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
      g.addColorStop(0, hexA(col, 0.15)); g.addColorStop(1, hexA(col, 0));
      ctx.fillStyle = g; ctx.fillRect(0, 0, r.width, r.height);

      // ── outer orbit ring with ticks ──
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(t * 0.1);
      ctx.strokeStyle = hexA(col, 0.16); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(0, 0, ORBIT, 0, Math.PI * 2); ctx.stroke();
      for (let i = 0; i < 60; i++) {
        const a = (i / 60) * Math.PI * 2, r1 = ORBIT - (i % 5 === 0 ? 9 : 4);
        ctx.beginPath(); ctx.moveTo(Math.cos(a) * ORBIT, Math.sin(a) * ORBIT);
        ctx.lineTo(Math.cos(a) * r1, Math.sin(a) * r1);
        ctx.strokeStyle = hexA(col, 0.22); ctx.stroke();
      }
      ctx.restore();

      // breathing rings
      for (let i = 0; i < 3; i++) {
        const rr = R * 0.34 + i * R * 0.16 + Math.sin(t + i) * 5;
        ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2);
        ctx.strokeStyle = hexA(col, 0.09 + i * 0.05); ctx.lineWidth = 1; ctx.stroke();
      }

      // ── STATE-DRIVEN COGNITION (deterministic, not random) ──
      if (st === "thinking") {
        // geometry lock: triangulation mesh that snaps into place
        const lock = (Math.sin(t * 1.5) + 1) / 2;
        const pts = 7, rad = R * 0.5;
        const nodes = Array.from({ length: pts }, (_, i) => {
          const a = (i / pts) * Math.PI * 2 + t * 0.2;
          return [cx + Math.cos(a) * rad, cy + Math.sin(a) * rad];
        });
        ctx.strokeStyle = hexA(col, 0.25 + lock * 0.3); ctx.lineWidth = 1;
        for (let i = 0; i < pts; i++)
          for (let j = i + 1; j < pts; j++) {
            ctx.beginPath(); ctx.moveTo(nodes[i][0], nodes[i][1]); ctx.lineTo(nodes[j][0], nodes[j][1]); ctx.stroke();
          }
        nodes.forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill(); });
      } else if (st === "scouting") {
        // inbound scan sweeps: radar arc from edge toward core
        for (let k = 0; k < 3; k++) {
          const prog = ((t * 0.4 + k / 3) % 1);
          const rr = R * (1 - prog);
          ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2);
          ctx.strokeStyle = hexA(col, prog * 0.4); ctx.lineWidth = 1.5; ctx.stroke();
        }
      } else if (st === "proposing") {
        // ring segmentation assembling into a complete ring
        const segs = 12, built = Math.floor(((t * 0.5) % 1) * segs) + 1;
        for (let i = 0; i < built; i++) {
          const a0 = (i / segs) * Math.PI * 2;
          ctx.beginPath(); ctx.arc(cx, cy, R * 0.55, a0, a0 + (Math.PI * 2 / segs) * 0.7);
          ctx.strokeStyle = hexA(col, 0.6); ctx.lineWidth = 3; ctx.stroke();
        }
      } else if (st === "executing") {
        // beam convergence: multiple lines snapping to core
        for (let i = 0; i < 8; i++) {
          const a = (i / 8) * Math.PI * 2 + t * 0.5;
          const conv = (Math.sin(t * 3 + i) + 1) / 2;
          const r0 = R * 0.85, r1 = ORB + (R * 0.5 - ORB) * (1 - conv);
          ctx.beginPath();
          ctx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
          ctx.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
          ctx.strokeStyle = hexA(col, 0.5); ctx.lineWidth = 2; ctx.stroke();
        }
      } else {
        // idle / default: minimal rotating arc accents
        for (let i = 0; i < 2; i++) {
          const a0 = t * (i % 2 ? -0.5 : 0.7) + i * 2.1;
          ctx.beginPath(); ctx.arc(cx, cy, R * 0.55 + i * 14, a0, a0 + Math.PI * 0.5);
          ctx.strokeStyle = hexA(col, 0.4); ctx.lineWidth = 2; ctx.stroke();
        }
      }

      // agent beams (directional energy entering core)
      if (s.beam) {
        const beamCol = s.beam === "left" ? C.emerald : s.beam === "right" ? C.amber : C.cyan;
        const from = s.beam === "left" ? [0, cy] : s.beam === "right" ? [r.width, cy] : [cx, r.height];
        const pulse = (Math.sin(t * 4) + 1) / 2;
        const lg = ctx.createLinearGradient(from[0], from[1], cx, cy);
        lg.addColorStop(0, hexA(beamCol, 0)); lg.addColorStop(1, hexA(beamCol, 0.5 * pulse + 0.2));
        ctx.strokeStyle = lg; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.moveTo(from[0], from[1]); ctx.lineTo(cx, cy); ctx.stroke();
        const tp = (t * 0.5) % 1;
        ctx.beginPath(); ctx.arc(from[0] + (cx - from[0]) * tp, from[1] + (cy - from[1]) * tp, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = beamCol; ctx.fill();
      }

      // shockwave on state change
      if (shockRef.current > 0) {
        const sw = shockRef.current;
        ctx.beginPath(); ctx.arc(cx, cy, (1 - sw) * R, 0, Math.PI * 2);
        ctx.strokeStyle = hexA(col, sw * 0.6); ctx.lineWidth = 2; ctx.stroke();
        shockRef.current = Math.max(0, sw - 0.02);
      }

      // approval crimson lock ring (freeze feel)
      if (st === "approval") {
        ctx.save(); ctx.translate(cx, cy); ctx.rotate(-t * 0.25);
        for (let i = 0; i < 6; i++) {
          const a = (i / 6) * Math.PI * 2;
          ctx.beginPath(); ctx.arc(0, 0, R * 0.46, a, a + Math.PI / 6);
          ctx.strokeStyle = hexA(C.crimson, 0.75); ctx.lineWidth = 3.5; ctx.stroke();
        }
        ctx.restore();
      }

      // orbiting particles (slow in approval, fast in executing)
      parts.forEach((p) => {
        p.a += p.sp * (1 + s.speed);
        const rr = (R * 0.5 + R * 0.45 * p.base);
        const x = cx + Math.cos(p.a) * rr, y = cy + Math.sin(p.a) * rr * 0.82;
        ctx.beginPath(); ctx.arc(x, y, p.sz, 0, Math.PI * 2);
        ctx.fillStyle = hexA(col, 0.65); ctx.fill();
      });

      // ── metallic core orb (bigger) ──
      const pulse = 1 + Math.sin(t * 2) * 0.07, orbR = ORB * pulse;
      const cg = ctx.createRadialGradient(cx - orbR * 0.3, cy - orbR * 0.3, 0, cx, cy, orbR);
      cg.addColorStop(0, "#ffffff"); cg.addColorStop(0.25, hexA(col, 0.95));
      cg.addColorStop(0.65, hexA(col, 0.4)); cg.addColorStop(1, hexA(col, 0));
      ctx.fillStyle = cg; ctx.beginPath(); ctx.arc(cx, cy, orbR, 0, Math.PI * 2); ctx.fill();
      // inner core ring detail
      ctx.beginPath(); ctx.arc(cx, cy, orbR * 0.6, 0, Math.PI * 2);
      ctx.strokeStyle = hexA("#ffffff", 0.25); ctx.lineWidth = 1; ctx.stroke();

      // waveform sync when speaking
      if (st === "speaking") {
        ctx.beginPath();
        for (let i = -26; i <= 26; i++) {
          const x = cx + i * 5, y = cy + Math.sin(t * 6 + i * 0.5) * 14 * Math.exp(-Math.abs(i) / 16);
          i === -26 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = hexA(col, 0.9); ctx.lineWidth = 2; ctx.stroke();
      }

      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);
  return <canvas ref={ref} style={{ width: "100%", height: "100%", display: "block" }} />;
}

// constellation with moving packets + radar sweep
function Constellation({ state }) {
  const ref = useRef(null), stateRef = useRef(state);
  stateRef.current = state;
  useEffect(() => {
    const canvas = ref.current, ctx = canvas.getContext("2d");
    let raf, t = 0;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    const size = () => { const r = canvas.getBoundingClientRect();
      canvas.width = r.width * DPR; canvas.height = r.height * DPR; ctx.setTransform(DPR,0,0,DPR,0,0); };
    size(); const ro = new ResizeObserver(size); ro.observe(canvas);
    const nodes = {
      scout: [0.2,0.25,C.emerald,"Scout"], planner:[0.8,0.25,C.cyan,"Planner"],
      core:[0.5,0.52,C.amber,"Core"], memory:[0.2,0.82,C.cyan,"Memory"],
      executor:[0.8,0.82,C.amber,"Executor"], proposal:[0.5,0.14,C.amber,"Proposal"],
    };
    const links = [["scout","core"],["planner","core"],["memory","core"],["executor","core"],["proposal","core"],["scout","planner"],["memory","executor"]];
    const activeFor = { scouting:"scout", proposing:"proposal", executing:"executor" };
    const draw = () => {
      const r = canvas.getBoundingClientRect(); ctx.clearRect(0,0,r.width,r.height);
      t += 0.016;
      const active = activeFor[stateRef.current];
      // faint radar sweep
      const cx2 = nodes.core[0]*r.width, cy2 = nodes.core[1]*r.height;
      ctx.save(); ctx.translate(cx2,cy2); ctx.rotate(t*0.6);
      const rg = ctx.createConicGradient ? ctx.createConicGradient(0,0,0) : null;
      ctx.globalAlpha = 0.05;
      ctx.beginPath(); ctx.moveTo(0,0); ctx.arc(0,0,r.width*0.5,0,Math.PI*0.25); ctx.closePath();
      ctx.fillStyle = C.amber; ctx.fill(); ctx.restore();
      // links
      links.forEach(([a,b]) => {
        const on = active && (a===active||b===active);
        const [ax,ay]=nodes[a],[bx,by]=nodes[b];
        ctx.beginPath(); ctx.moveTo(ax*r.width,ay*r.height); ctx.lineTo(bx*r.width,by*r.height);
        ctx.strokeStyle = on ? hexA(nodes[active][2],0.6) : "rgba(255,255,255,0.07)";
        ctx.lineWidth = on?1.4:0.7; ctx.stroke();
        // moving packet along active edges (and a slow ambient one everywhere)
        const speed = on?0.6:0.15, tp=((t*speed)%1);
        if (on || Math.random()<0.5) {
          ctx.beginPath();
          ctx.arc((ax+(bx-ax)*tp)*r.width,(ay+(by-ay)*tp)*r.height, on?2.4:1.2,0,Math.PI*2);
          ctx.fillStyle = on?nodes[active][2]:"rgba(255,255,255,0.2)"; ctx.fill();
        }
      });
      // nodes
      Object.entries(nodes).forEach(([k,[x,y,c,label]]) => {
        const on = k===active||k==="core";
        const pr = (k==="core"?5:3.2) + (on?Math.sin(t*3)*0.8:0);
        ctx.beginPath(); ctx.arc(x*r.width,y*r.height,pr,0,Math.PI*2);
        ctx.fillStyle = on?c:"#2a2e38"; ctx.fill();
        ctx.strokeStyle = hexA(c,0.5); ctx.lineWidth=0.6; ctx.stroke();
        ctx.fillStyle = on?c:C.dim; ctx.font="7px Inter, sans-serif"; ctx.textAlign="center";
        ctx.fillText(label, x*r.width, y*r.height-8);
      });
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);
  return <canvas ref={ref} style={{ width:"100%", height:"100%", display:"block" }} />;
}

const matDeep  = { background: C.surfaceDeep, border: "1px solid rgba(255,255,255,0.05)", borderRadius: 18 };
const matFrost = { background: "rgba(28,32,40,0.5)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 16, backdropFilter: "blur(24px)", WebkitBackdropFilter: "blur(24px)" };
const matMetal = (c) => ({ background: `linear-gradient(135deg, ${hexA(c,0.16)}, ${hexA(c,0.04)})`, border: `1px solid ${hexA(c,0.35)}`, borderRadius: 16, boxShadow: `inset 0 1px 0 ${hexA("#ffffff",0.08)}, 0 0 24px ${hexA(c,0.12)}` });
const btn = (c, filled) => ({ padding: "12px 20px", borderRadius: 12, border: filled?"none":`1px solid ${hexA(c,0.4)}`, background: filled?c:"transparent", color: filled?"#0a0a0a":c, fontSize: 13, fontWeight: 700, cursor: "pointer", letterSpacing: 0.3 });
const now = () => new Date().toLocaleTimeString("en-GB", { hour12: false });

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
  const [agents, setAgents] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [brainStatus, setBrainStatus] = useState(null);
  const [brainDocs, setBrainDocs] = useState([]);
  const [brainQuery, setBrainQuery] = useState("");
  const [brainResults, setBrainResults] = useState(null);
  const [noteText, setNoteText] = useState("");
  const [noteProject, setNoteProject] = useState("");
  const [noteKind, setNoteKind] = useState("note");
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
  const loadDoctor = () => {
    fetch(API + "/system/doctor").then(r => r.json()).then(setDoctor).catch(() => setDoctor(null));
  };
  useEffect(() => {
    if (panel === "Brain") loadBrain();
    if (panel === "Plans") loadPlans();
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
  const [feed, setFeed] = useState([
    { t: "09:42:12", a: "SCOUT", c: C.emerald, m: "Found 12 opportunities" },
    { t: "09:42:18", a: "EXEC", c: C.amber, m: "Browser session ready" },
  ]);
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
  const send = async () => {
    if (!input.trim()) return;
    const msg = input;
    setFeed((f) => [{ t: now(), a: "YOU", c: C.cyan, m: msg }, ...f].slice(0, 50));
    setState("thinking"); setInput("");
    try {
      const res = await fetch(API + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: "core" }),
      });
      const data = await res.json();
      const reply = data.response || data.reply || "";
      if (reply) setFeed((f) => [{ t: now(), a: "JARVIS", c: C.amber, m: reply }, ...f].slice(0, 50));
    } catch (err) {
      setFeed((f) => [{ t: now(), a: "ERROR", c: C.crimson, m: "Backend unreachable" }, ...f].slice(0, 50));
    }
  };
  const s = STATES[state];
  return (
    <div style={{ height: "100vh", display: "flex", background: C.bg, color: C.text, fontFamily: "Inter, system-ui, sans-serif", overflow: "hidden" }}>
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
        {["Command","Agents","Tasks","Brain","Plans","Settings"].map((x) => (
          <div key={x} onClick={() => setPanel(x)} style={{ padding: "11px 12px", borderRadius: 10, fontSize: 13, cursor: "pointer", color: panel===x?C.amber:C.dim, background: panel===x?hexA(C.amber,0.07):"transparent", borderLeft: panel===x?`2px solid ${C.amber}`:"2px solid transparent" }}>{x}</div>
        ))}
        <div style={{ marginTop: "auto", ...matFrost, padding: 12, fontSize: 11, color: C.dim }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}><span>RAM</span><span style={{ color: C.emerald }}>9.9 / 16 GB</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}><span>Model</span><span style={{ color: C.amber }}>qwen2 · fast</span></div>
        </div>
      </aside>
      <main style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
          <NeuralCore state={state} />
          <div style={{ position: "absolute", top: 24, left: 0, right: 0, textAlign: "center", pointerEvents: "none" }}>
            <div style={{ fontSize: 12, color: C.dim, letterSpacing: 1 }}>Good morning</div>
            <div style={{ fontSize: 27, fontWeight: 600, marginTop: 4 }}>How can I <span style={{ color: C.amber, fontStyle: "italic" }}>assist</span>?</div>
          </div>
          <div style={{ position: "absolute", bottom: 14, left: 0, right: 0, textAlign: "center", pointerEvents: "none" }}>
            <span style={{ fontSize: 11, letterSpacing: 3, textTransform: "uppercase", color: s.color }}>◦ {s.label}</span>
          </div>
          {panel !== "Command" && (
            <div style={{ position: "absolute", top: 90, left: 24, right: 24, bottom: 24, ...matFrost, padding: 22, overflowY: "auto" }}>
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
                            </div>
                          );
                        })}
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
            placeholder="Command Jarvis…  scan RemoteOK · open chrome · draft proposals"
            style={{ flex: 1, background: "transparent", border: "none", color: C.text, fontSize: 14, outline: "none" }} />
          <button onClick={send} style={btn(C.amber, true)}>Send</button>
        </div>
      </main>
      <aside style={{ width: "25%", minWidth: 250, padding: 20, display: "flex", flexDirection: "column", gap: 14, borderLeft: "1px solid rgba(255,255,255,0.04)" }}>
        <div style={{ ...matFrost, padding: 14, height: 240, display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 10, color: C.dim, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 4 }}>Agent Network</div>
          <div style={{ flex: 1 }}><Constellation state={state} /></div>
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
