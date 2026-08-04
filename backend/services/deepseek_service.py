"""
services/deepseek_service.py
Unified AI service — Ollama (DeepSeek-R1 + Qwen) with Anthropic fallback.
Thread-safe. Handles timeouts and missing models gracefully.
"""

import os
import re
import json
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


# How a caller's (fast, task) pair maps to a router task. `fast` is a legacy
# way of saying "this doesn't need deep thought", which is what "chat" means.
_ROUTER_TASK = {
    "planning": "planner", "planner": "planner",
    "reasoning": "reasoning", "coding": "coding",
    "proposal": "proposal", "summary": "memory", "memory": "memory",
    "vision": "vision", "chat": "chat", "routing": "chat",
}


def call_model(prompt: str, history: list | None = None, fast: bool = False,
               task: str | None = None) -> str:
    """
    Ask the AI. Kept as the name ~30 modules already import.

    THE BODY NOW DELEGATES to services/ai_router.ask(). It used to call
    ollama.chat() directly, which made this file a provider as well as a
    service — and made "which provider does Jarvis use?" a question with thirty
    possible answers.

    Rewriting all thirty call sites at once was the alternative. This is better:
    one change routes every existing caller through the gate immediately, with
    no chance of missing one and no thirty-file diff to review. Callers can move
    to ai_router.ask() at their own pace; nothing forces a flag day.

    Still never raises. Errors come back as readable '[...]' text, because
    callers all over Jarvis show this string to the user directly.
    """
    routed = _ROUTER_TASK.get((task or "").lower(), "chat" if fast else "reasoning")
    try:
        from services.ai_router import ask
    except Exception as e:
        return f"[AI router unavailable: {e}]"

    text = ask(task=routed, prompt=prompt, history=(history or [])[-10:],
               fast=fast, system_prompt=SYSTEM_PROMPT)
    # Reasoning models emit their scratchpad in <think> tags. Showing that to
    # the user is noise, and pasting it into a client proposal would be worse.
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


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
    # KNOWN GAP — the model also returns job_type, and it is parsed and then
    # thrown away. Nothing downstream receives it, so the classification is
    # paid for on every call and never used. Tracked in docs/CODE_HEALTH.md.
    workable = False
    try:
        m = re.search(r"\{.*\}", assess, re.DOTALL)
        if m:
            d = json.loads(m.group())
            workable = bool(d.get("workable"))
    except Exception:
        pass

    if not workable:
        return {"workable": False, "output": "Manual work required.", "status": "manual_required"}

    output = call_model(
        f"Complete this job professionally.\nTitle: {job_title}\nDescription: {job_desc}\n"
        "Produce the full deliverable. Output ONLY the deliverable."
    )
    return {"workable": True, "output": output, "status": "done"}
