"""
services/custom_platforms.py — add ANY freelance site yourself.

The ask: "make a place where I can add other new freelancer sites + login and it
adds them to my freelance section for full automation."

So a platform is now data, not code. You give it a name, its jobs URL and login
URL, optionally CSS selectors, and (optionally) credentials — which go straight
into the encrypted vault, never into this table. From then on it:

  * appears in Platform Logins (so you can log in once and reuse the session),
  * is scanned by the income engine like any built-in platform,
  * is classified bid/board so submission behaves correctly.

Scraping a user-added site uses generic selectors, so results vary by site. That
is stated plainly in the UI rather than pretended away.
"""
import json
from datetime import datetime, timezone

from models.db import conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS custom_platforms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT UNIQUE NOT NULL,
    label       TEXT NOT NULL,
    jobs_url    TEXT NOT NULL,
    login_url   TEXT,
    check_url   TEXT,
    kind        TEXT DEFAULT 'board',       -- bid | board | talent | micro
    selectors   TEXT,                        -- optional JSON {card,title,link,desc}
    enabled     INTEGER DEFAULT 1,
    created_at  TEXT
);
"""

DEFAULT_SELECTORS = {
    # deliberately generic — most job boards match at least one of these
    "card":  "article, li.job, div.job, div[class*='job'], div[class*='card']",
    "title": "h1, h2, h3, a[class*='title'], span[class*='title']",
    "link":  "a",
    "desc":  "p, div[class*='desc'], div[class*='summary']",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_custom_platforms() -> None:
    with conn() as db:
        db.executescript(SCHEMA)


def _slugify(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())[:32]


def add_platform(label: str, jobs_url: str, login_url: str = "", kind: str = "board",
                 check_url: str = "", selectors: dict | None = None,
                 username: str = "", password: str = "") -> dict:
    init_custom_platforms()
    slug = _slugify(label)
    if not slug or not jobs_url:
        return {"ok": False, "error": "name and jobs URL are required"}
    if kind not in ("bid", "board", "talent", "micro"):
        kind = "board"
    with conn() as db:
        db.execute(
            "INSERT INTO custom_platforms(slug,label,jobs_url,login_url,check_url,kind,"
            "selectors,enabled,created_at) VALUES(?,?,?,?,?,?,?,1,?) "
            "ON CONFLICT(slug) DO UPDATE SET label=excluded.label, jobs_url=excluded.jobs_url,"
            " login_url=excluded.login_url, check_url=excluded.check_url, kind=excluded.kind,"
            " selectors=excluded.selectors",
            (slug, label.strip(), jobs_url.strip(), (login_url or "").strip(),
             (check_url or login_url or jobs_url).strip(), kind,
             json.dumps(selectors or DEFAULT_SELECTORS), _now()))

    # Credentials never live here — straight into the encrypted vault.
    stored = False
    if username and password:
        try:
            from services.vault import store_credential
            stored = store_credential(slug, username, password).get("ok", False)
        except Exception:
            stored = False

    _register_with_session_manager()
    return {"ok": True, "slug": slug, "label": label, "kind": kind,
            "credentials_saved": stored}


def list_platforms(enabled_only: bool = False) -> list[dict]:
    init_custom_platforms()
    q = "SELECT * FROM custom_platforms"
    if enabled_only:
        q += " WHERE enabled=1"
    q += " ORDER BY label"
    with conn() as db:
        rows = db.execute(q).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["selectors"] = json.loads(d.get("selectors") or "{}")
        except Exception:
            d["selectors"] = {}
        out.append(d)
    return out


def delete_platform(slug: str) -> dict:
    init_custom_platforms()
    with conn() as db:
        cur = db.execute("DELETE FROM custom_platforms WHERE slug=?", (slug,))
    try:
        from services.vault import delete_credential
        delete_credential(slug)
    except Exception:
        pass
    _register_with_session_manager()
    return {"ok": cur.rowcount > 0}


def set_enabled(slug: str, on: bool) -> dict:
    init_custom_platforms()
    with conn() as db:
        db.execute("UPDATE custom_platforms SET enabled=? WHERE slug=?", (1 if on else 0, slug))
    return {"ok": True, "slug": slug, "enabled": on}


def _register_with_session_manager() -> None:
    """Make user-added sites first-class in login status + platform kind lookups."""
    try:
        from services import session_manager, platform_meta
        for p in list_platforms():
            session_manager.PLATFORMS[p["slug"]] = {
                "label": p["label"],
                "login_url": p["login_url"] or p["jobs_url"],
                "check_url": p["check_url"] or p["jobs_url"],
            }
            platform_meta.PLATFORM_KIND[p["slug"]] = p["kind"]
    except Exception:
        pass


# ── Generic scraping for user-added sites ─────────────────────────────────────

def scan(slug: str, max_jobs: int = 15) -> list[dict]:
    """
    Best-effort scrape of a user-added site using its (or the default) selectors.
    Returns the same job shape as the built-in platforms.
    """
    plat = next((p for p in list_platforms() if p["slug"] == slug), None)
    if not plat:
        return []
    sel = {**DEFAULT_SELECTORS, **(plat.get("selectors") or {})}
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(plat["jobs_url"], timeout=20,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; JarvisBot/14)"})
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select(sel["card"])[:max_jobs]
        jobs = []
        for _i, c in enumerate(cards):
            t = c.select_one(sel["title"])
            title = (t.get_text(strip=True) if t else "")[:160]
            if not title:
                continue
            a = c.select_one(sel["link"])
            href = a.get("href") if a else ""
            if href and href.startswith("/"):
                from urllib.parse import urljoin
                href = urljoin(plat["jobs_url"], href)
            d = c.select_one(sel["desc"])
            jobs.append({
                "job_id": f"{slug}_{abs(hash(title)) % 10**9}",
                "title": title,
                "description": (d.get_text(" ", strip=True) if d else "")[:600],
                "skills": [], "company": plat["label"],
                "link": href or plat["jobs_url"],
                "date_posted": "", "platform": slug,
            })
        print(f"[{plat['label']}] {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"[{plat.get('label', slug)}] scrape failed: {e}")
        return []
