# JARVIS — Quick Start

## Easiest way (Windows)
1. Unzip this folder anywhere (e.g. D:\jarvis_v9)
2. Make sure Ollama is installed and you have a model:  `ollama pull qwen2:1.5b`
3. Double-click **START_JARVIS.bat**
   - First run installs dependencies (a few minutes). Later runs are fast.
   - Two windows open: backend + frontend.
4. Open the UI URL the frontend window prints (usually http://localhost:5173)

## Manual way (if you prefer the terminal)
```
ollama serve
cd backend
python -m uvicorn main:app --reload --port 8000      (one level up: backend.main:app)
```
New terminal:
```
cd frontend
npm install        (first time only)
npm run dev
```

## Check it's alive
- Backend health:  http://127.0.0.1:8000/health   -> {"status":"online"}
- Live feed (SSE): http://127.0.0.1:8000/orchestrator/sse  -> data: {"ping": true}

## First four tests (in the UI chat / command box)
1. `screenshot`      -> should save an image (works without Tesseract now)
2. `open edge`       -> should open Edge
3. `hello jarvis`    -> should reply quickly (uses qwen2:1.5b)
4. Click **Agents** in the left sidebar -> panel should open and list agents

## What's fixed in this build
See START_HERE.md for the full list. Highlights:
- Screenshot points at the right module (no Tesseract needed for the capture itself)
- Edge/Chrome launch via Windows 'start' (fixes "cannot find edge")
- Fast model defaults to qwen2:1.5b; chat no longer uses the slow 5GB reasoning model
- Left sidebar buttons work; Agents panel lists agents (foundation for adding custom agents)
- /orchestrator/sse renamed to avoid a route collision that silently broke the live feed

## Optional: read text from screenshots (OCR)
Screenshots already work. If you also want Jarvis to READ on-screen text:
`pip install pytesseract pillow` then install the Tesseract binary:
https://github.com/UB-Mannheim/tesseract/wiki  (check "Add to PATH").

## If something breaks
Copy the FULL red error from the backend window and send it back. That exact
traceback is what pins down the fix.
