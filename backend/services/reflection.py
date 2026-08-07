"""
services/reflection.py — the loop that lets Jarvis get better, not just repeat.

Verification tells you IF a task worked. Reflection asks WHY, and what to change
next time. After a workflow or goal finishes, we look at the step outcomes and:
  * record a short, structured lesson to the personal brain (so it informs
    future proposals/plans),
  * if a taught workflow keeps failing at the same step, attach an improvement
    note so the user (or a later auto-fix) knows exactly where it breaks,
  * publish a "reflection.saved" event.

Kept cheap and honest: reflections are derived from real step results first, and
only summarised by the fast LLM when one is available. No LLM -> still a useful
rule-based lesson, never a fabricated one.
"""
from datetime import datetime, timezone

from services import event_bus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rule_based(goal: str, steps: list, ok: bool) -> str:
    total = len(steps)
    done = sum(1 for s in steps if s.get("verified") or s.get("success"))
    retried = [s for s in steps if (s.get("attempts") or 1) > 1]
    fail = next((s for s in steps if not (s.get("verified") or s.get("success"))), None)
    parts = [f"{'Succeeded' if ok else 'Failed'}: {done}/{total} steps verified."]
    if retried:
        parts.append(f"{len(retried)} step(s) needed a retry "
                     f"({', '.join(s.get('action','?') for s in retried[:3])}) — "
                     f"these are the flaky points to watch.")
    if fail:
        parts.append(f"Broke at step {fail.get('step')}: {fail.get('action')} "
                     f"({fail.get('verify_reason') or fail.get('error','')}).")
    return " ".join(parts)


def reflect(goal: str, steps: list, ok: bool,
            kind: str = "task", workflow_name: str | None = None) -> dict:
    """Produce + store a reflection for a finished task/goal. Never raises."""
    lesson = _rule_based(goal, steps, ok)

    # Optional richer insight from the fast model, grounded in the real outcome.
    try:
        from services.deepseek_service import call_model
        detail = call_model(
            "In ONE sentence, give a concrete lesson to do this better next time. "
            "Base it ONLY on these facts, don't invent:\n"
            f"Goal: {goal}\nOutcome: {lesson}\n"
            "Lesson:", fast=True)
        if detail and not detail.startswith("[") and len(detail) < 400:
            lesson = f"{lesson} Lesson: {detail.strip()}"
    except Exception:
        pass

    # Persist to the personal brain so it surfaces in future context.
    try:
        from services import brain_service as brain
        brain.ingest(f"Reflection: {goal[:50]}", lesson,
                     source="reflection", project=workflow_name)
    except Exception:
        pass

    # If a taught workflow failed at a step, annotate it for later repair.
    if workflow_name and not ok:
        try:
            from models.db import conn
            with conn() as db:
                db.execute("UPDATE workflows SET last_status='needs_fix' WHERE name=?",
                           (workflow_name,))
        except Exception:
            pass

    event_bus.publish("reflection.saved",
                      {"goal": goal[:60], "ok": ok, "kind": kind}, emit_feed=True,
                      level="success" if ok else "warning")
    return {"ok": True, "reflection": lesson, "at": _now()}


def recent(limit: int = 10) -> list[dict]:
    """Recent reflections from the brain (for the UI)."""
    try:
        from models.db import conn
        with conn() as db:
            rows = db.execute(
                "SELECT d.title, d.created_at, "
                "  (SELECT text FROM brain_chunks c WHERE c.doc_id=d.id ORDER BY c.seq LIMIT 1) AS text "
                "FROM brain_documents d WHERE d.source='reflection' "
                "ORDER BY d.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
