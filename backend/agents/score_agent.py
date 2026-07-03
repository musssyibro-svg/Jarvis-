"""
agents/score_agent.py
ScoreAgent — scores and filters opportunities.
Uses keyword matching + historical win patterns from MemoryEngine.
No external AI calls (fast, synchronous).
"""
from agents.base_agent import BaseAgent

SKILL_KEYWORDS = [
    "python", "automation", "scraping", "fastapi", "flask", "django",
    "playwright", "selenium", "api", "rest", "data", "ai", "ml",
    "bot", "script", "crawl", "parse", "web", "backend",
]

NEGATIVE_KEYWORDS = [
    "design", "photoshop", "illustrator", "figma", "video editing",
    "3d model", "animation", "blender", "unity", "unreal",
    "mobile app", "ios", "android", "swift", "kotlin",
    "sales call", "cold calling", "phone", "on-site", "onsite",
]


class ScoreAgent(BaseAgent):
    name = "score"

    def run(self, context: dict) -> dict:
        jobs    = context.get("jobs", [])
        min_score = context.get("min_score", 30)
        your_skills = context.get("your_skills", "python automation scraping").lower()
        feed    = []

        # Load win patterns from memory
        win_patterns = self._load_win_patterns()

        scored = []
        for job in jobs:
            score, reasons = self._score(job, your_skills, win_patterns)
            job["score"]          = score
            job["score_reasons"]  = reasons
            job["qualified"]      = score >= min_score
            scored.append(job)

        qualified = [j for j in scored if j["qualified"]]
        scored_sorted = sorted(scored, key=lambda x: x["score"], reverse=True)

        feed.append(self.log(f"Scored {len(jobs)} opportunities"))
        feed.append(self.log(f"{len(qualified)} qualified (score >= {min_score})"))

        return {"jobs": scored_sorted, "qualified": qualified, "feed": feed}

    def _score(self, job: dict, your_skills: str, win_patterns: list) -> tuple:
        score   = 40  # base
        reasons = []

        title = (job.get("title") or "").lower()
        desc  = (job.get("description") or "").lower()
        text  = title + " " + desc

        # Skill match boost
        matched = [k for k in SKILL_KEYWORDS if k in text]
        if matched:
            boost = min(len(matched) * 8, 40)
            score += boost
            reasons.append(f"+{boost} skill match: {', '.join(matched[:4])}")

        # Skill match from user's own skills
        user_skills = [s.strip().lower() for s in your_skills.split(",")]
        user_matched = [s for s in user_skills if s and s in text]
        if user_matched:
            boost = min(len(user_matched) * 6, 20)
            score += boost
            reasons.append(f"+{boost} your skills match: {', '.join(user_matched[:3])}")

        # Negative keywords penalty
        neg_matched = [k for k in NEGATIVE_KEYWORDS if k in text]
        if neg_matched:
            penalty = min(len(neg_matched) * 15, 50)
            score  -= penalty
            reasons.append(f"-{penalty} out-of-scope: {', '.join(neg_matched[:2])}")

        # Description quality
        desc_len = len(job.get("description") or "")
        if desc_len < 30:
            score -= 20
            reasons.append("-20 thin description")
        elif desc_len > 200:
            score += 10
            reasons.append("+10 detailed description")

        # Win pattern boost
        for pattern in win_patterns:
            if pattern.lower() in text:
                score += 15
                reasons.append(f"+15 historical win pattern: {pattern}")
                break

        return max(0, min(100, score)), reasons

    def _load_win_patterns(self) -> list:
        try:
            from models.db import conn
            with conn() as db:
                rows = db.execute(
                    "SELECT title FROM proposals WHERE won=1 ORDER BY id DESC LIMIT 20"
                ).fetchall()
            patterns = []
            for r in rows:
                words = (r["title"] or "").lower().split()
                patterns.extend([w for w in words if len(w) > 4])
            return list(set(patterns))
        except Exception:
            return []
