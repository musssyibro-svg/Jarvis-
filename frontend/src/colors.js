/**
 * colors.js — one safe way to build a translucent version of a colour.
 *
 * This exists because of a real, repeated bug. Buttons were tinted by string
 * concatenation, `${c}18`, which only produces a valid colour when `c` happens
 * to be a 6-digit hex. Callers also passed `rgba(...)` and CSS variables, giving
 * "rgba(255,255,255,0.15)18" — the browser discards the whole declaration, the
 * button falls back to the UA default ButtonFace, and you get the WHITE BLANK
 * BUTTONS with invisible text.
 *
 * The first fix swapped in `color-mix(in srgb, ...)`, which is correct CSS but
 * only landed in Chrome 111 / Firefox 113. On an older browser it is *also*
 * invalid, so the white buttons came straight back.
 *
 * So: no CSS-level colour maths at all. Parse the colour in JS and emit a plain
 * `rgba()`, which every browser has understood for fifteen years. If a colour
 * can't be parsed, return a neutral dark tint rather than something invalid —
 * a slightly-wrong shade is always better than an unreadable control.
 */

const NEUTRAL = "rgba(120,160,190,0.10)";

/** Parse any common CSS colour into [r,g,b], or null if we can't. */
export function toRgb(color) {
  const c = String(color || "").trim();
  if (!c) return null;

  // #rgb / #rgba
  if (/^#[0-9a-f]{3,4}$/i.test(c)) {
    return [c[1], c[2], c[3]].map((h) => parseInt(h + h, 16));
  }
  // #rrggbb / #rrggbbaa
  if (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(c)) {
    return [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  }
  // rgb() / rgba(), with either comma or space separators
  const m = c.match(/^rgba?\(([^)]+)\)$/i);
  if (m) {
    const parts = m[1]
      .split(/[\s,/]+/)
      .filter(Boolean)
      .slice(0, 3)
      .map(Number);
    if (parts.length === 3 && parts.every((n) => Number.isFinite(n))) {
      return parts.map((n) => Math.max(0, Math.min(255, Math.round(n))));
    }
  }
  return null;
}

/**
 * A translucent version of `color` at alpha `a` (0-1).
 * Always returns a colour the browser will accept.
 */
export function tint(color, a = 0.1) {
  const rgb = toRgb(color);
  if (!rgb) return NEUTRAL;
  const alpha = Math.max(0, Math.min(1, a));
  return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`;
}

/** Same, but for borders — slightly stronger so the edge stays visible. */
export function edge(color, a = 0.32) {
  return tint(color, a);
}

/**
 * Standard control style. Every button in Jarvis should come from here, so the
 * white-button class of bug can only ever be fixed in one place.
 */
export function btn(color = "#00d4ff", opts = {}) {
  const { active = false, disabled = false, size = "sm" } = opts;
  const pad = size === "lg" ? "10px 20px" : "7px 16px";
  const fs = size === "lg" ? 11 : 9;
  return {
    padding: pad,
    borderRadius: 3,
    border: `1px solid ${edge(color, active ? 0.9 : 0.55)}`,
    background: tint(color, active ? 0.22 : 0.09),
    color,
    fontFamily: "monospace",
    fontSize: fs,
    letterSpacing: "0.1em",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.45 : 1,
    transition: "background 120ms ease, border-color 120ms ease",
  };
}
