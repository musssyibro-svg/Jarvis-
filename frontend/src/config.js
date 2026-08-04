// src/config.js — central API config (V8)
// Override with VITE_API_URL env variable in production
export const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
export const SID = "default";

export async function apiFetch(url, opts = {}) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let d = null;
  try {
    d = text ? JSON.parse(text) : null;
  } catch {
    d = text;
  }
  if (!res.ok) throw new Error(d?.detail || d?.message || `HTTP ${res.status}`);
  return d;
}
export const apiPost = (url, body) =>
  apiFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const apiPatch = (url, body) =>
  apiFetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
