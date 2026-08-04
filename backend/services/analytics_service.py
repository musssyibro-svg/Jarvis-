"""
services/analytics_service.py — Unified analytics across ALL platforms
"""
from datetime import datetime, timedelta, timezone

from models.db import conn


def _period_stats(days=None) -> dict:
    with conn() as db:
        if days:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            proposals = [dict(r) for r in db.execute(
                "SELECT * FROM proposals WHERE created_at >= ?", (since,)).fetchall()]
            hs_apps = [dict(r) for r in db.execute(
                "SELECT * FROM hubstaff_applications WHERE created_at >= ?", (since,)).fetchall()]
            cw_done = [dict(r) for r in db.execute(
                "SELECT * FROM clickworker_completed WHERE completed_at >= ?", (since,)).fetchall()]
            zd_subs = [dict(r) for r in db.execute(
                "SELECT * FROM zuodao_submissions WHERE created_at >= ?", (since,)).fetchall()]
        else:
            proposals = [dict(r) for r in db.execute("SELECT * FROM proposals").fetchall()]
            hs_apps   = [dict(r) for r in db.execute("SELECT * FROM hubstaff_applications").fetchall()]
            cw_done   = [dict(r) for r in db.execute("SELECT * FROM clickworker_completed").fetchall()]
            zd_subs   = [dict(r) for r in db.execute("SELECT * FROM zuodao_submissions").fetchall()]

    sent      = sum(1 for p in proposals if p["status"] not in ("draft",))
    replies   = sum(1 for p in proposals if p.get("got_reply"))
    won       = sum(1 for p in proposals if p.get("won"))
    hs_sent   = sum(1 for a in hs_apps if a["status"] != "draft")
    hs_replied= sum(1 for a in hs_apps if a.get("got_reply"))
    hs_hired  = sum(1 for a in hs_apps if a["status"] == "hired")
    cw_earned = sum(r.get("reward", 0) for r in cw_done)
    all_apps  = sent + hs_sent

    total_replies = replies + hs_replied
    total_won     = won + hs_hired

    status_counts: dict = {}
    for p in proposals:
        s = p.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "total_proposals":     len(proposals),
        "proposals_sent":      sent,
        "replies_received":    replies,
        "projects_won":        won,
        "response_rate":       round((replies / sent * 100) if sent else 0, 1),
        "win_rate":            round((won / sent * 100) if sent else 0, 1),
        "reply_to_win_rate":   round((won / replies * 100) if replies else 0, 1),
        "status_breakdown":    status_counts,
        # Hubstaff
        "hs_applications":     len(hs_apps),
        "hs_sent":             hs_sent,
        "hs_replied":          hs_replied,
        "hs_hired":            hs_hired,
        # Clickworker
        "cw_tasks_done":       len(cw_done),
        "cw_earned":           round(cw_earned, 2),
        # Zuodao
        "zd_submissions":      len(zd_subs),
        # Combined
        "all_applications":    all_apps,
        "all_replies":         total_replies,
        "all_won":             total_won,
        "overall_response_rate": round((total_replies / all_apps * 100) if all_apps else 0, 1),
    }


def _recommendations(a: dict) -> list[str]:
    tips = []
    if a["all_applications"] == 0:
        tips.append("No applications sent yet. Use the Job Scanner or Auto Mode to get started.")
        return tips
    if a["overall_response_rate"] < 5:
        tips.append("Very low response rate. Personalise your applications more — show you read the job description.")
    if a["overall_response_rate"] >= 5 and a["overall_response_rate"] < 15:
        tips.append("Response rate is improving. Try adding a portfolio link and a specific result you achieved.")
    if a["win_rate"] == 0 and a["proposals_sent"] >= 5:
        tips.append("Getting replies but not winning. Follow up within 24 hours and offer a lower-risk trial.")
    if a["cw_earned"] > 0:
        tips.append(f"Clickworker earned ${a['cw_earned']}. Keep completing tasks to build consistent micro-income.")
    if a["hs_hired"] > 0:
        tips.append(f"Won {a['hs_hired']} Hubstaff job(s). Ask for a review and repeat similar job applications.")
    if a["all_applications"] >= 20 and a["overall_response_rate"] >= 15:
        tips.append("Strong pipeline. Scale up by enabling Auto Mode to scan more platforms daily.")
    return tips or ["Keep scanning and applying consistently. Volume + quality = results."]


def get_analytics() -> dict:
    return {
        "all_time":       _period_stats(days=None),
        "last_7_days":    _period_stats(days=7),
        "last_30_days":   _period_stats(days=30),
        "recommendations": _recommendations(_period_stats(days=None)),
    }
