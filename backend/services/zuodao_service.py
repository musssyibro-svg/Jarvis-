"""
services/zuodao_service.py
Zuodao (做道) task discovery and tracking.
Zuodao is a Chinese freelance/task platform. Integration via HTTP scraping.
AI assists with task understanding and completion where appropriate.
"""

import re, traceback
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

ZUODAO_URL = "https://www.zuodao.com"
TASK_URL   = "https://www.zuodao.com/task/"


def fetch_tasks(max_tasks: int = 20) -> list[dict]:
    """Scrape available tasks from Zuodao."""
    tasks = _scrape_zuodao(max_tasks)
    if not tasks:
        # V8: sample fallback REMOVED per directive. Real scraping only.
        print("[Zuodao] Live scrape returned 0 tasks (no sample fallback).")
        return []
    return tasks[:max_tasks]


def _scrape_zuodao(max_tasks: int) -> list[dict]:
    try:
        r = requests.get(TASK_URL, headers=HEADERS, timeout=20)
        print(f"[Zuodao] GET {TASK_URL} -> HTTP {r.status_code}, {len(r.text)} bytes")
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select(".task-item, .job-item, [class*='task'], article, li[class*='item']")
        print(f"[Zuodao] card selector matched {len(cards)} element(s)")
        tasks = []
        for i, card in enumerate(cards[:max_tasks]):
            title_el = card.select_one("h2, h3, .title, a")
            title    = title_el.get_text(strip=True) if title_el else f"Task #{i+1}"
            a_el     = card.select_one("a[href]")
            link     = a_el["href"] if a_el else ""
            if link and not link.startswith("http"):
                link = ZUODAO_URL + link
            desc_el  = card.select_one("p, .desc, .summary")
            desc     = desc_el.get_text(strip=True)[:400] if desc_el else ""
            reward_el = card.select_one("[class*='price'], [class*='pay'], [class*='reward'], .money")
            reward   = reward_el.get_text(strip=True) if reward_el else ""
            deadline_el = card.select_one("[class*='deadline'], [class*='time'], time")
            deadline = deadline_el.get_text(strip=True) if deadline_el else ""
            cat_el   = card.select_one("[class*='category'], [class*='type'], .tag")
            category = cat_el.get_text(strip=True) if cat_el else _guess_category(title)
            tasks.append({
                "task_id":  f"zd_{abs(hash(title + link)) % 999999}",
                "title":    title,
                "category": category,
                "description": desc,
                "reward":   reward,
                "deadline": deadline,
                "status":   "available",
                "link":     link,
            })
        print(f"[Zuodao] Scraped {len(tasks)} tasks")
        return tasks
    except Exception as e:
        print(f"[Zuodao] Scrape error: {e}")
        return []


def _known_categories() -> list[dict]:
    return [
        {"task_id": "zd_cat_data",    "title": "数据录入 (Data Entry)",
         "category": "Data",           "description": "Enter and organize data into spreadsheets or systems.",
         "reward": "¥5-20/task",       "deadline": "", "status": "available", "link": TASK_URL},
        {"task_id": "zd_cat_translate","title": "翻译任务 (Translation)",
         "category": "Translation",    "description": "Translate documents between Chinese and English.",
         "reward": "¥10-50/task",      "deadline": "", "status": "available", "link": TASK_URL},
        {"task_id": "zd_cat_label",   "title": "数据标注 (Data Labeling)",
         "category": "AI Training",   "description": "Label images and text for AI training.",
         "reward": "¥3-15/task",       "deadline": "", "status": "available", "link": TASK_URL},
        {"task_id": "zd_cat_code",    "title": "编程任务 (Coding Tasks)",
         "category": "Development",    "description": "Small coding and scripting tasks.",
         "reward": "¥20-200/task",     "deadline": "", "status": "available", "link": TASK_URL},
        {"task_id": "zd_cat_write",   "title": "文案写作 (Copywriting)",
         "category": "Writing",        "description": "Write product descriptions, ads, articles.",
         "reward": "¥10-80/task",      "deadline": "", "status": "available", "link": TASK_URL},
    ]


def _guess_category(title: str) -> str:
    t = title.lower()
    if any(w in t for w in ["数据", "data", "录入"]): return "Data"
    if any(w in t for w in ["翻译", "translate", "translation"]): return "Translation"
    if any(w in t for w in ["标注", "label", "annotate"]): return "AI Training"
    if any(w in t for w in ["代码", "code", "程序", "开发"]): return "Development"
    if any(w in t for w in ["写", "write", "文案", "article"]): return "Writing"
    return "General"


def ai_assist_task(title: str, description: str) -> str:
    from services.deepseek_service import call_model
    prompt = f"""Help complete this Zuodao task:

Task: {title}
Description: {description}

Provide a high-quality response suitable for submission.
Output ONLY the task response."""
    return call_model(prompt, fast=True)
