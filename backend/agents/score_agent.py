"""
agents/score_agent.py
ScoreAgent — scores and filters opportunities.
Uses keyword matching + revenue signals + job-type matching + historical win
patterns from MemoryEngine. No external AI calls (fast, synchronous).

Two upgrades over the original keyword scorer, both driven by the screenshots:
  * Revenue-first: parse the budget/rate and boost higher-paying work, so the
    money-making jobs float to the top instead of every job being equal.
  * Job-type matching: classify each job (dev / data / admin / writing / …) and
    penalise a hard mismatch with the user's skills. This is what stops a Python
    automation proposal being sent to an "Entry Level Administrative Assistant".
The detected job_type and est_pay are written onto the job so the ProposalAgent
can tailor (or the pipeline can skip) accordingly.
"""
import re
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

# Coarse job-type classification (first match wins). Used for tailoring proposals
# and for penalising mismatches with a technical skill set.
JOB_TYPES = [
    ("dev",     ["python", "developer", "engineer", "automation", "script",
                 "api", "backend", "scraping", "software", "code", "bot",
                 "django", "flask", "fastapi", "selenium", "playwright"]),
    ("data",    ["data entry", "data analyst", "excel", "spreadsheet", "analytics",
                 "sql", "database", "reporting", "dashboard"]),
    ("writing", ["content", "copywriter", "blog", "article", "writer", "seo writing",
                 "ghostwrit", "proofread", "editing"]),
    ("admin",   ["administrative", "admin assistant", "virtual assistant", "clerical",
                 "receptionist", "scheduling", "customer support", "customer service",
                 "sales director", "sales", "recruit", "hr "]),
    ("design",  ["designer", "graphic", "logo", "figma", "photoshop", "illustrator", "ui/ux"]),
]

# Which job types a Python/automation dev should actually apply to.
TECHNICAL_TYPES = {"dev", "data"}


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
            score, reasons, job_type, est_pay = self._score(job, your_skills, win_patterns)
            job["score"]          = score
            job["score_reasons"]  = reasons
            job["job_type"]       = job_type
            job["est_pay"]        = est_pay
            job["qualified"]      = score >= min_score
            scored.append(job)

        qualified = [j for j in scored if j["qualified"]]
        # Revenue-first ordering: higher score, then higher estimated pay.
        scored_sorted = sorted(scored, key=lambda x: (x["score"], x.get("est_pay") or 0),
                               reverse=True)
        qualified = sorted(qualified, key=lambda x: (x["score"], x.get("est_pay") or 0),
                           reverse=True)

        feed.append(self.log(f"Scored {len(jobs)} opportunities"))
        feed.append(self.log(f"{len(qualified)} qualified (score >= {min_score}), "
                             f"ranked by fit + pay"))

        return {"jobs": scored_sorted, "qualified": qualified, "feed": feed}

    def _classify(self, text: str) -> str:
        for jtype, kws in JOB_TYPES:
            if any(kw in text for kw in kws):
                return jtype
        return "other"

    def _parse_pay(self, job: dict) -> float:
        """Best-effort hourly/budget figure from budget or description text."""
        blob = f"{job.get('budget','')} {job.get('description','')}"
        nums = []
        # comma-grouped branch first (requires a comma), else plain digits, so
        # "$2000" reads as 2000 not 200 and "$2,000" reads as 2000 too.
        for m in re.finditer(r"\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(k)?", blob):
            try:
                val = float(m.group(1).replace(",", ""))
                if m.group(2):   # "5k"
                    val *= 1000
                if 3 <= val <= 100000:
                    nums.append(val)
            except Exception:
                continue
        return max(nums) if nums else 0.0

    def _score(self, job: dict, your_skills: str, win_patterns: list) -> tuple:
        score   = 40  # base
        reasons = []

        title = (job.get("title") or "").lower()
        desc  = (job.get("description") or "").lower()
        text  = title + " " + desc
        job_type = self._classify(text)
        est_pay  = self._parse_pay(job)

        user_skills = [s.strip().lower() for s in your_skills.split(",")]
        technical_user = any(s in ("python", "automation", "scraping", "fastapi",
                                   "backend", "api", "ai", "web scraping")
                             for s in user_skills)

        # Skill match boost
        matched = [k for k in SKILL_KEYWORDS if k in text]
        if matched:
            boost = min(len(matched) * 8, 40)
            score += boost
            reasons.append(f"+{boost} skill match: {', '.join(matched[:4])}")

        # Skill match from user's own skills
        user_matched = [s for s in user_skills if s and s in text]
        if user_matched:
            boost = min(len(user_matched) * 6, 20)
            score += boost
            reasons.append(f"+{boost} your skills match: {', '.join(user_matched[:3])}")

        # Job-type mismatch: a technical user bidding on a clearly non-technical
        # role is the "Python copy on an admin job" bug. Penalise hard so it
        # drops out of the qualified set instead of getting a mismatched proposal.
        if technical_user and job_type in ("admin", "design"):
            score -= 45
            reasons.append(f"-45 job type '{job_type}' doesn't match your dev skills")
        elif technical_user and job_type in TECHNICAL_TYPES:
            score += 12
            reasons.append(f"+12 '{job_type}' role matches your skills")

        # Negative keywords penalty
        neg_matched = [k for k in NEGATIVE_KEYWORDS if k in text]
        if neg_matched:
            penalty = min(len(neg_matched) * 15, 50)
            score  -= penalty
            reasons.append(f"-{penalty} out-of-scope: {', '.join(neg_matched[:2])}")

        # Revenue signal: reward higher pay so money-making leads rank first.
        if est_pay >= 1000:
            score += 18; reasons.append(f"+18 high budget (~${int(est_pay)})")
        elif est_pay >= 300:
            score += 10; reasons.append(f"+10 solid budget (~${int(est_pay)})")
        elif est_pay >= 50:
            score += 4;  reasons.append(f"+4 budget ~${int(est_pay)}")

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

        return max(0, min(100, score)), reasons, job_type, est_pay

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
