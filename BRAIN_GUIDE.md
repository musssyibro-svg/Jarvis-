# Jarvis Brain — Quick Guide

Your personal knowledge base. Feed it information; Jarvis uses it to answer
questions and ground every chat. 100% local — nothing leaves your PC.

## Feeding it

1. **UI**: click **Brain** in the sidebar → paste text → *Save to Brain*,
   or *upload a .txt / .md file* (.pdf works after `pip install pypdf`).
2. **Chat**: type `remember my WeChat backup phone is ...` — anything after
   "remember" is saved.
3. **API**: `POST /brain/ingest {"title": "...", "text": "..."}`.

Good things to feed it: your project notes, research summaries, client info,
account usernames, your CV, the JARVIS master context document, EV/PINN paper
notes — anything you'd want an assistant to already know.

## Using it

- Just chat. If the brain has something relevant, Jarvis answers with it
  (the live feed shows "Found relevant knowledge in your brain").
- Ask directly: `what did I say about ...` / `recall ...`.
- Or search visually in the Brain panel.

## Modes

| Mode | Needs | Quality |
|---|---|---|
| `keyword` | Nothing. Works offline, day one. | Good for exact words/names (English + Chinese). |
| `vector` | `ollama pull nomic-embed-text` (274MB, once — the launcher does this automatically) | Understands meaning, not just words. |

Check current mode: `GET /brain/status` or the top line of the Brain panel.
Anything saved while Ollama was off gets embedded automatically later.

## Forgetting

Brain panel → ✕ next to a document, or `DELETE /brain/document/{id}`.
