/**
 * theme.js — the one visual language, in a module that imports nothing.
 *
 * These colours used to live in JarvisOS.jsx and be imported back out of it by
 * the pages. That created a cycle:
 *
 *     JarvisOS.jsx  ──imports──▶  pages/Planner.jsx
 *          ▲                             │
 *          └──────── imports T ──────────┘
 *
 * ES modules allow cycles, but the bindings are in the temporal dead zone while
 * the cycle is being resolved. Vite's dev server evaluates each module natively,
 * so Planner.jsx ran first (as a dependency of JarvisOS.jsx), reached
 * `const card = { border: T.line }` at its top level, and threw
 * "Cannot access 'T' before initialization" — killing the whole module graph
 * before React mounted. The page stayed blank and white, index.css never even
 * loaded, and every file still showed 200 in the network tab because loading
 * was never the problem; evaluation was.
 *
 * `npm run build` did NOT catch it. Rollup bundles everything into one scope and
 * hoists the declaration, so the cycle resolves at build time and the build
 * passes. Dev and prod genuinely disagree here — which is why a green build was
 * not evidence that the app runs.
 *
 * The fix is structural rather than a workaround: shared tokens live in a leaf
 * module with no imports of its own, so nothing can ever import its way back
 * into a cycle through them.
 */

export const T = {
  bg: "#080b11",
  panel: "#0d1220",
  panelSoft: "rgba(255,255,255,0.028)",
  line: "rgba(255,255,255,0.075)",
  text: "#e6edf5",
  dim: "#7d8798",
  cyan: "#54d6ff",
  green: "#3ee6a8",
  amber: "#f5b544",
  red: "#ff5f6d",
  violet: "#a98bff",
};

/* Shared surface + label styles, so every screen reads as one system. */
export const card = {
  background: T.panel,
  border: `1px solid ${T.line}`,
  borderRadius: 14,
};

export const sectionLabel = {
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: T.dim,
  marginBottom: 10,
  fontWeight: 600,
};

/* Feed/severity colours, used by the timeline, the logs console and the planner. */
export const LEVEL_COLOR = {
  info: T.cyan,
  success: T.green,
  warning: T.amber,
  error: T.red,
};
