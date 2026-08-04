"""
services/clickworker_service.py
Clickworker task discovery via public API + web scraping.
Clickworker exposes tasks to registered users; we provide:
  - Public task page scraping (no auth required for listings)
  - Manual task entry support
  - Earnings tracking
  - AI assistance for task completion
"""

import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
}
BASE = "https://www.clickworker.com"
MARKETPLACE_URL = "https://www.clickworker.com/en/clickworker/tasks/"
APP_URL = "https://marketplace.clickworker.com"


def fetch_public_tasks(max_tasks: int = 20) -> list[dict]:
    """Scrape publicly visible task categories from Clickworker site."""
    tasks = []
    try:
        r = requests.get(MARKETPLACE_URL, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        # Clickworker lists task types publicly
        cards = soup.select(".task-type, .job-type, [class*='task'], article, .card")
        for i, card in enumerate(cards[:max_tasks]):
            title_el = card.select_one("h2, h3, h4, .title, [class*='title']")
            title = title_el.get_text(strip=True) if title_el else f"Task #{i+1}"
            desc_el = card.select_one("p, .description, [class*='desc']")
            desc = desc_el.get_text(strip=True)[:400] if desc_el else ""
            reward_el = card.select_one("[class*='reward'], [class*='earn'], [class*='pay'], [class*='price']")
            reward_text = reward_el.get_text(strip=True) if reward_el else "0.00"
            reward = _parse_reward(reward_text)
            category_el = card.select_one("[class*='category'], [class*='type']")
            category = category_el.get_text(strip=True) if category_el else _guess_category(title)
            tasks.append({
                "task_id":        f"cw_{abs(hash(title + str(i))) % 999999}",
                "title":          title,
                "category":       category,
                "description":    desc,
                "reward":         reward,
                "estimated_time": _estimate_time(category),
                "status":         "available",
            })
        print(f"[Clickworker] Scraped {len(tasks)} task types from site")
    except Exception as e:
        print(f"[Clickworker] Scrape failed: {e}")

    # Always return built-in known task types as fallback
    if not tasks:
        # V8: sample fallback REMOVED per directive. Real scraping only.
        # Return empty with a clear reason instead of fake categories.
        print("[Clickworker] Live scrape returned 0 tasks (no sample fallback).")
        return []

    return tasks[:max_tasks]


def _known_task_types() -> list[dict]:
    """Clickworker's well-known task categories with realistic rewards."""
    return [
        {"task_id": "cw_cat_survey",     "title": "Online Surveys",
         "category": "Survey",           "description": "Complete surveys and questionnaires for market research.",
         "reward": 0.50,                 "estimated_time": 10, "status": "available"},
        {"task_id": "cw_cat_text",       "title": "Text Creation",
         "category": "Writing",          "description": "Write product descriptions, articles, and short texts.",
         "reward": 2.00,                 "estimated_time": 20, "status": "available"},
        {"task_id": "cw_cat_annotation", "title": "Data Annotation",
         "category": "AI Training",     "description": "Label images, text, audio for AI/ML training datasets.",
         "reward": 1.00,                 "estimated_time": 15, "status": "available"},
        {"task_id": "cw_cat_audio",      "title": "Audio Recording",
         "category": "Audio",            "description": "Record voice samples for speech recognition training.",
         "reward": 1.50,                 "estimated_time": 15, "status": "available"},
        {"task_id": "cw_cat_search",     "title": "Web Research",
         "category": "Research",         "description": "Find and verify information on specific topics.",
         "reward": 0.75,                 "estimated_time": 12, "status": "available"},
        {"task_id": "cw_cat_classify",   "title": "Image Classification",
         "category": "AI Training",     "description": "Categorize and tag images for training datasets.",
         "reward": 0.30,                 "estimated_time": 5,  "status": "available"},
        {"task_id": "cw_cat_translate",  "title": "Translation Tasks",
         "category": "Translation",      "description": "Translate short texts between languages.",
         "reward": 3.00,                 "estimated_time": 30, "status": "available"},
        {"task_id": "cw_cat_mystery",    "title": "Mystery Shopping",
         "category": "Research",         "description": "Visit websites or apps and report on user experience.",
         "reward": 5.00,                 "estimated_time": 25, "status": "available"},
    ]


def _parse_reward(text: str) -> float:
    m = re.search(r"[\d]+\.?[\d]*", text.replace(",", "."))
    return float(m.group()) if m else 0.0


def _estimate_time(category: str) -> int:
    estimates = {
        "Survey": 10, "Writing": 20, "AI Training": 15, "Audio": 15,
        "Research": 12, "Translation": 30, "Review": 8,
    }
    return estimates.get(category, 15)


def _guess_category(title: str) -> str:
    t = title.lower()
    if any(w in t for w in ["survey", "questionnaire"]): return "Survey"
    if any(w in t for w in ["write", "text", "article", "description"]): return "Writing"
    if any(w in t for w in ["label", "annotate", "classify", "tag"]): return "AI Training"
    if any(w in t for w in ["audio", "voice", "record", "speech"]): return "Audio"
    if any(w in t for w in ["translate", "translation"]): return "Translation"
    if any(w in t for w in ["research", "find", "search"]): return "Research"
    return "General"


def estimate_earnings(tasks: list[dict]) -> dict:
    total_reward = sum(t.get("reward", 0) for t in tasks)
    total_time   = sum(t.get("estimated_time", 15) for t in tasks)
    hourly = (total_reward / total_time * 60) if total_time else 0
    return {
        "tasks_count":   len(tasks),
        "total_reward":  round(total_reward, 2),
        "total_minutes": total_time,
        "hourly_rate":   round(hourly, 2),
    }


def ai_assist_task(title: str, description: str) -> str:
    """Generate AI assistance output for a Clickworker task."""
    from services.deepseek_service import call_model
    prompt = f"""You are helping complete a Clickworker microtask.

Task: {title}
Instructions: {description}

Provide a high-quality, accurate response suitable for submission.
Be concise and follow the task instructions exactly.
Output ONLY the task response."""
    return call_model(prompt, fast=True)
