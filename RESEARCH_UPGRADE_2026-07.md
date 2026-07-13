# Deep Research: How to Make Jarvis 100% Better (2026-07)

Research question: among everything free in 2026, should Jarvis be replaced by
an existing open-source assistant ("rename it Jarvis"), or upgraded in place?
Constraints that ruled the decision: **16GB RAM Windows 10**, **China network**
(cloud AI unreliable, some registries blocked), **zero budget**, and the
existing **freelance income pipeline must survive**.

## Alternatives evaluated

| Project | What it is | Verdict for this machine |
|---|---|---|
| **OpenClaw** | Self-hosted autonomous assistant, chat via WhatsApp/Telegram/etc. | **No.** Wants 4–8GB RAM for itself (before Ollama + Chromium), Docker, a static IP, and had a high-severity one-click RCE (CVE-2026-25253, CVSS 8.8) this year. No freelance pipeline. Security is "entirely your responsibility." |
| **Open Interpreter** | Natural-language code execution in a terminal | **Partial idea source.** Great at "do things on my PC" but no UI, no memory, no freelance pipeline, no agent registry. Jarvis's executor already covers the same ground with an approval gate. |
| **Khoj** | Self-hosted "second brain" with local LLMs | **Idea source.** The best second-brain UX, but it's a full Django+Postgres stack — heavy for 16GB alongside Ollama — and does nothing for desktop control or freelancing. |
| **OpenAgent** | LLM + RAG knowledge base + agent loops, self-hosted | **Closest overall**, but replacing Jarvis with it means porting the entire freelance pipeline and Iron-Man UI for roughly zero capability gain. |
| **PyGPT** | Desktop AI app with 12 modes incl. computer use | Good reference, but a monolithic desktop app — can't serve the phone-as-remote-interface goal (Jarvis's web UI can). |
| **Obsidian + Smart Connections + Ollama** | Notes vault with local RAG chat | The pattern everyone converges on for "brain": local embeddings + retrieval. **This pattern is what got implemented inside Jarvis.** |

**Verdict: upgrade in place.** Every alternative either (a) can't fit next to
Ollama in 16GB, (b) has no freelance pipeline (the actual income feature), or
(c) would trade a working, audited codebase for a migration project. What the
alternatives DO have that Jarvis lacked — a personal knowledge brain — is a
pattern, not a product, and it fits in ~400 lines on the existing stack.

## What was implemented from this research

### The Brain (new)
A local personal knowledge base built directly into Jarvis:

- **Feed it anything** — Brain panel in the UI (paste text, upload .txt/.md/.pdf),
  or say `remember <fact>` in chat. Stored in the existing `jarvis.db` SQLite.
- **Semantic search** via Ollama `nomic-embed-text` (274MB, CPU-friendly, beats
  OpenAI ada-002 on retrieval benchmarks — the standard local pick in 2026).
- **Zero-download fallback**: pure-Python BM25 keyword search (with CJK
  tokenization, so Chinese text works) — the brain functions on day one,
  offline, with **no models installed at all**.
- **Lazy backfill**: text saved while Ollama was down gets embedded
  automatically the next time it's up.
- **Chat grounding**: every plain-chat message retrieves the top brain matches
  and injects them into the prompt; if no LLM is installed, Jarvis answers
  with the retrieved knowledge directly instead of an error.
- Endpoints: `POST /brain/ingest`, `POST /brain/upload`, `GET /brain/search`,
  `GET /brain/documents`, `DELETE /brain/document/{id}`, `GET /brain/status`.

### China/16GB hardening (launcher)
- `START_JARVIS.bat` now auto-pulls `nomic-embed-text` once (non-fatal,
  minimized window) and retries `npm install` through the
  `registry.npmmirror.com` China mirror, matching the existing Tsinghua pip
  mirror fallback.

### Model policy confirmed by research (no change needed)
The existing routing — `qwen2.5:0.5b` fast / `deepseek-r1:1.5b` reasoning /
`llava:7b` lazy-loaded vision — matches 2026 best practice for 16GB. The one
addition is `nomic-embed-text` (274MB); total resident footprint stays under
~2.5GB with vision unloaded.

## Roadmap the research supports (not yet built)

1. **Voice** (fits Phase 2+): `faster-whisper` tiny/base for STT (~150MB,
   CPU-real-time) + Windows built-in SAPI or `piper` for TTS — both free,
   both local. Add as an optional agent, never in the hot path.
2. **Phone remote**: the existing web UI over LAN (`--host 0.0.0.0` + phone
   browser) is the free path; Tailscale (free tier, works in China better
   than most) if off-LAN access is wanted.
3. **Browser autonomy**: keep Playwright direct (already in the stack);
   avoid `browser-use` (the dependency conflict that previously broke
   Starlette is documented in the legacy reports).
4. **Chat-history-as-memory**: auto-ingest daily chat summaries into the
   Brain so Jarvis remembers conversations across sessions.

## Sources
- [Vellum: Best open-source personal AI assistants 2026](https://www.vellum.ai/blog/best-open-source-personal-ai-assistants)
- [OpenClaw hardware requirements (Macaron)](https://macaron.im/blog/openclaw-hardware-requirements)
- [OpenClaw server requirements + CVE-2026-25253 (ClawTrust)](https://clawtrust.ai/blog/openclaw-server-requirements)
- [Cherry Servers: OpenClaw hardware guide](https://www.cherryservers.com/blog/openclaw-hardware-requirements)
- [Ollama embedding models benchmarked (morphllm)](https://www.morphllm.com/ollama-embedding-models)
- [nomic-embed-text on Ollama](https://ollama.com/library/nomic-embed-text)
- [bge-m3 on Ollama](https://ollama.com/library/bge-m3)
- [InsiderLLM: embedding models for local RAG](https://insiderllm.com/guides/embedding-models-rag/)
- [OpenAgent (GitHub)](https://github.com/the-open-agent/openagent)
- [Build a local AI second brain with Obsidian & Ollama](https://vucense.com/ai-intelligence/local-llms/how-to-build-a-second-brain-powered-by-local-ai/)
- [DEV: RAG-powered knowledge tools that never leave your machine](https://dev.to/kennedyraju55/build-your-own-second-brain-rag-powered-knowledge-tools-that-never-leave-your-machine-21cn)
