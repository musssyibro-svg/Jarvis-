# Jarvis Brain — Quick Guide

Your personal knowledge base. Feed it information; Jarvis uses it to answer
questions and ground every chat. 100% local — nothing leaves your PC.

## Feeding it

1. **UI**: click **Brain** in the sidebar → pick a kind (*Knowledge* / *Fact
   about me* / *Decision*), optionally a project, paste text → *Save to Brain*,
   or *upload a .txt / .md file* (.pdf works after `pip install pypdf`).
2. **Chat**:
   - `remember my WeChat backup phone is ...` → **fact about you**. Facts are
     always in Jarvis's context — it knows you without being asked.
   - `remember decision: we use SQLite because ...` → **why** you chose
     something, retrievable months later ("why did we ...?").
   - `remember for mistore: shipping is 18k flat` → scoped to a **project
     workspace** (mistore, ev, jarvis — any name you like).
3. **API**: `POST /brain/ingest {"title","text","project","source"}`.

## It also learns by itself

Every ~24 chat messages, Jarvis summarizes the conversation in the background
(needs an Ollama chat model) and stores the durable facts, decisions and open
tasks as a `chat_summary` — so it remembers past sessions without you doing
anything. You can see (and delete) these in the Brain panel like any document.

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
