# JARVIS OS V4 — Autonomous Freelance Agent

## What it does
1. **Scans** job platforms (Hubstaff, RemoteOK, WWR, PeoplePerHour, Wellfound, Contra)
2. **Scores** each job using AI (DeepSeek-R1 via Ollama)
3. **Drafts proposals** and queues them for your review
4. **You approve** each proposal in the Queue tab (one click)
5. **Playwright auto-submits** the bid on Freelancer/platform after your approval
6. **Tracks results** (won/lost/replied) in SQLite memory

Nothing is ever submitted without your explicit approval.

---

## Quick Start

### Backend
```
start.bat
```
Or manually:
```
pip install -r requirements.txt
python -m playwright install msedge
python -m uvicorn main:app --reload --port 8000
```

### Frontend
```
start_frontend.bat
```
Or manually:
```
cd frontend
npm install
npm run dev
```
Open: http://localhost:5173

---

## First-Time Setup

1. **Install Ollama**: https://ollama.ai
2. **Pull models**:
   ```
   ollama pull qwen
   ollama pull deepseek-r1
   ```
3. **Log into Freelancer** in your Edge browser (the edge-profile folder stores the session)
4. **Start Jarvis** via start.bat

---

## Project Structure

```
jarvis_v3/
├── main.py                    # FastAPI app entry point
├── requirements.txt
├── start.bat / start_frontend.bat
│
├── agents/
│   ├── orchestrator.py        # Pipeline coordinator + SSE feed
│   ├── browser_agent.py       # Playwright persistent context
│   ├── memory_agent.py        # SQLite win/loss memory
│   ├── proposal_agent.py      # AI proposal generation
│   ├── score_agent.py         # Job scoring
│   └── scout_agent.py         # Platform scraping
│
├── services/
│   ├── bid_executor.py        # ← NEW: Playwright bid submission after approval
│   ├── automation_engine.py   # Queue management
│   ├── deepseek_service.py    # AI service wrapper
│   └── ...
│
├── routes/
│   ├── orchestrator.py        # /orchestrator/* + SSE /feed endpoint
│   ├── automation.py          # /automation/queue/* + /execute-approved
│   ├── proposals.py
│   ├── messages.py
│   ├── analytics.py
│   └── scraper.py
│
├── models/
│   └── db.py                  # SQLite schema + connection
│
└── frontend/src/
    ├── App.jsx
    ├── pages/
    │   ├── AutoMode.jsx       # ← NEW: Live feed + Queue + Executor controls
    │   ├── Workspace.jsx      # Unified Jobs/Queue/Applications/Earnings
    │   ├── Dashboard.jsx
    │   ├── Proposals.jsx
    │   ├── Messages.jsx
    │   ├── Analytics.jsx
    │   ├── Chat.jsx
    │   └── ...
    └── components/
        ├── Sidebar.jsx
        └── UI.jsx
```

---

## Autonomous Mode Flow

```
[START SCAN] → Scout platforms → Score jobs → Generate proposals
      ↓
[QUEUE TAB] → Review each proposal
      ↓
[APPROVE + SUBMIT] → Playwright opens job page → fills bid form → clicks Place Bid
      ↓
[TRACKING] → Memory records win/loss → improves future proposals
```

---

## Environment Variables (.env)

```
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen:latest
DEEPSEEK_MODEL=deepseek-r1:latest
ANTHROPIC_API_KEY=         # optional, for Claude
JARVIS_DB=jarvis.db
CORS_ORIGINS=*
```

