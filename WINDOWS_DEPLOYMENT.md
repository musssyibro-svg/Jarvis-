# Jarvis V9 — Windows Deployment + Runtime Validation

## One-time setup
1. Install Python 3.11+, Node 18+, Ollama.
2. Pull a model:  ollama pull deepseek-r1   (and qwen2 if you want the fast model)
3. Backend deps:  cd backend && pip install -r requirements.txt
4. Playwright browser:  python -m playwright install chromium
5. (Stage 2 desktop OCR) Install Tesseract for Windows; ensure tesseract.exe is on PATH.
6. Frontend deps:  cd frontend && npm install

## Run (4 terminals)
1. ollama serve
2. cd backend && python -m uvicorn main:app --port 8000
3. cd frontend && npm run dev      (open the printed URL)
4. cd jarvis_v8 && RUN_VALIDATION.bat

## Runtime validation YOU must run (cannot be done off-machine)
A. The 4-command harness (RUN_VALIDATION.bat) -> artifacts in
   backend/runtime_validation_<timestamp>/ : results.json, sse_log.txt, *.png
B. In the Chat tab, manually try:
   - open notepad          (expect Notepad opens + "[Executor] Opening notepad")
   - open chrome           (watch for alias-resolution failure — known risk)
   - take a screenshot     (expect a PNG path)
   - start autonomous mode (expect scout->propose pipeline in the live feed)
C. Stage 2 browser perception (the new part):
   - Open a job page in the agent's browser, then in Chat:
       "click the Submit button"  (routes to click_element -> observe_browser ->
        find_element -> click). Confirm it locates and clicks the right element.
   - This is the core Stage 2 proof: structured DOM click, not blind coordinates.

## Send back
The whole runtime_validation_<timestamp> folder + any traceback from results.json.
