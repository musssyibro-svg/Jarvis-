"""
services/deepseek_service.py
Unified AI service — Ollama (DeepSeek-R1 + Qwen) with Anthropic fallback.
Thread-safe. Handles timeouts and missing models gracefully.
"""

import os
import re
import json
import traceback
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "ollama").lower()
OLLAMA_MODEL       = os.getenv("OLLAMA_REASONING_MODEL", "deepseek-r1:latest")
OLLAMA_FAST_MODEL  = os.getenv("OLLAMA_FAST_MODEL", "qwen2:1.5b")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = (
    "You are Jarvis, the user's personal AI assistant, running locally on their own PC. "
    "You are their assistant for EVERYTHING: daily life, university, their MiStore phone "
    "business, research, files, and controlling their computer — you can open and close "
    "apps, type, take screenshots, read the screen, and browse. Freelancing is just one "
    "of your modules, never your identity. Speak as Jarvis: direct, capable, loyal, "
    "concise. Never describe yourself as a platform, a website, or 'a virtual assistant "
    "designed to assist freelancers'."
)

try:
    import ollama as _ollama
except ImportError:
    _ollama = None

try:
    from anthropic import Anthropic as _Anthropic
except ImportError:
    _Anthropic = None


def _resolve_chat_model(fast: bool, task: str | None = None) -> str:
    """
    Ask the model router for the best INSTALLED model that fits in free RAM.

    Previously this trusted the configured name, which is how a 0.5B model ended
    up doing everything — it was "resolved" successfully and nothing complained.
    The router ranks by real quality and memory headroom instead.
    """
    try:
        from services import model_router
        chosen = model_router.pick_model(task or ("chat" if fast else "reasoning"))
        if chosen:
            return chosen
    except Exception:
        pass
    # Fallbacks: role resolution, then whatever is configured.
    preferred = OLLAMA_FAST_MODEL if fast else OLLAMA_MODEL
    try:
        from services.ollama_manager import resolve_models
        info = resolve_models()
        resolved = info["resolved"].get("fast" if fast else "reasoning")
        if resolved:
            return resolved
        if info["installed"]:
            return info["installed"][0]
    except Exception:
        pass
    return preferred


def call_model(prompt: str, history: list | None = None, fast: bool = False,
               task: str | None = None) -> str:
    """
    Call the AI model. fast=True prefers the lighter model.
    Auto-detects installed Ollama models; never hardcodes an unpulled name.
    Returns string response. Never raises — returns error message on failure.
    """
    history = history or []
    model   = _resolve_chat_model(fast, task)

    # ── Ollama ────────────────────────────────────────────────────────────────
    if _ollama:
        try:
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
            msgs += [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
            msgs.append({"role": "user", "content": prompt})
            print(f"[deepseek_service] using model: {model}")
            # Bound the work. Without num_predict a small model can ramble for
            # thousands of tokens; on a RAM-pressured machine that turned single
            # requests into multi-minute stalls. num_ctx keeps the prompt window
            # sane, and keep_alive frees the model instead of pinning RAM.
            resp = _ollama.chat(model=model, messages=msgs, keep_alive="5m",
                                options={"num_predict": 400, "num_ctx": 4096,
                                         "temperature": 0.7})
            text = resp["message"]["content"]
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return text
        except Exception as exc:
            traceback.print_exc()
            # Fallback: try ANY installed model before giving up
            try:
                from services.ollama_manager import _list_installed
                for alt in _list_installed():
                    if alt == model:
                        continue
                    try:
                        resp = _ollama.chat(model=alt,
                                            messages=[{"role":"user","content":prompt}])
                        print(f"[deepseek_service] fell back to: {alt}")
                        return re.sub(r"<think>.*?</think>", "",
                                      resp["message"]["content"], flags=re.DOTALL).strip()
                    except Exception:
                        continue
            except Exception:
                pass
            return (f"[Ollama error: {exc}. Models installed but none responded. "
                    f"Try: ollama pull qwen2.5:0.5b]")

    # ── Anthropic fallback ────────────────────────────────────────────────────
    if ANTHROPIC_API_KEY and _Anthropic:
        try:
            client   = _Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=history + [{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        except Exception as exc:
            return f"[Claude error: {exc}]"

    return "[No AI available. Run: ollama serve && ollama pull deepseek-r1:latest]"


def generate_proposal(
    job_title: str, job_desc: str, budget: str,
    skills: list, platform: str,
    your_name: str = "Ibrahim",
    your_skills: str = "Python, automation, web scraping, AI integration, FastAPI",
    tone: str = "professional",
) -> dict:
    prompt = f"""You are writing a freelance proposal on behalf of {your_name}.

Job Title: {job_title}
Platform: {platform}
Budget: {budget}
Required Skills: {', '.join(skills) if skills else 'Not listed'}
Job Description: {job_desc}
Your skills: {your_skills}

Respond ONLY with a JSON object (no markdown, no preamble):
{{
  "proposal_text": "<proposal under 220 words, tone={tone}, sign off as {your_name}>",
  "confidence": <integer 0-100>,
  "can_auto_work": <true if AI can complete this entirely>,
  "work_type": "<writing|code|research|report|other>",
  "work_reason": "<one sentence>"
}}"""

    raw = call_model(prompt)
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return {
        "proposal_text": raw,
        "confidence":    50,
        "can_auto_work": False,
        "work_type":     "other",
        "work_reason":   "Could not parse AI response.",
    }


def generate_reply_draft(sender: str, message: str) -> str:
    prompt = f"""A client named "{sender}" sent:
---
{message}
---
Write a professional, friendly reply. Under 120 words. Output ONLY the reply text."""
    return call_model(prompt, fast=True)


def auto_work_job(job_title: str, job_desc: str) -> dict:
    assess = call_model(
        f"""Job: {job_title}\nDescription: {job_desc}
Can AI complete this? Reply ONLY with JSON:
{{"workable": true/false, "reason": "...", "job_type": "writing|code|research|other"}}""",
        fast=True,
    )
    workable, job_type = False, "other"
    try:
        m = re.search(r"\{.*\}", assess, re.DOTALL)
        if m:
            d = json.loads(m.group())
            workable  = bool(d.get("workable"))
            job_type  = d.get("job_type", "other")
    except Exception:
        pass

    if not workable:
        return {"workable": False, "output": "Manual work required.", "status": "manual_required"}

    output = call_model(
        f"Complete this job professionally.\nTitle: {job_title}\nDescription: {job_desc}\n"
        "Produce the full deliverable. Output ONLY the deliverable."
    )
    return {"workable": True, "output": output, "status": "done"}
