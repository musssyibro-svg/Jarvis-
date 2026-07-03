"""
test_clickworker.py — Verify Clickworker returns REAL tasks, no sample data.
- Detects hardcoded task_ids from the removed fallback
- RAM monitoring
"""
from _harness import TestRun, guard, save_ram_artifact

FAKE_TASK_IDS = {
    "cw_cat_survey", "cw_cat_text", "cw_cat_annotation",
    "cw_cat_audio", "cw_cat_search", "cw_cat_classify",
    "cw_cat_translate", "cw_cat_mystery",
}
FAKE_MARKERS = ["sample", "fake", "hardcoded", "placeholder", "lorem"]


def _is_fake(task: dict) -> tuple:
    tid = task.get("task_id", "")
    if tid in FAKE_TASK_IDS:
        return True, f"hardcoded sample task_id: {tid}"
    if task.get("is_sample") or task.get("source") == "sample_fallback":
        return True, "is_sample flag present"
    title = (task.get("title") or "").lower()
    if any(m in title for m in FAKE_MARKERS):
        return True, f"fake marker in title: {title}"
    return False, ""


def run() -> dict:
    t   = TestRun("test_clickworker")
    ram = [t.ram("start")]

    fetch = guard(t, "import fetch_public_tasks",
                  lambda: __import__("services.clickworker_service",
                                     fromlist=["fetch_public_tasks"]).fetch_public_tasks)
    if fetch is None:
        t.add_artifact(save_ram_artifact(ram, "clickworker"))
        return t.finish()

    t.log("Calling fetch_public_tasks(max_tasks=10)")
    ram.append(t.ram("before_fetch"))
    tasks = guard(t, "call fetch_public_tasks", lambda: fetch(10))
    ram.append(t.ram("after_fetch"))

    if tasks is None:
        t.add_artifact(save_ram_artifact(ram, "clickworker"))
        return t.finish()

    t.log(f"Returned {len(tasks)} task(s)")

    fake_results = [(i, task, reason)
                    for i, task in enumerate(tasks)
                    for is_f, reason in [_is_fake(task)] if is_f]
    t.check("no hardcoded sample data detected",
            len(fake_results) == 0,
            evidence={"total": len(tasks), "fake_count": len(fake_results),
                      "fake_details": [{"idx": i, "id": task.get("task_id"),
                                        "reason": r} for i, task, r in fake_results[:3]]},
            error=None if not fake_results else f"{len(fake_results)} fake items found")

    t.check("at least one real task returned",
            len(tasks) >= 1,
            evidence={"count": len(tasks),
                      "sample": [{k: x.get(k) for k in ("task_id","title","reward")}
                                 for x in tasks[:5]],
                      "ram_before_mb": ram[-2].get("used_mb"),
                      "ram_after_mb":  ram[-1].get("used_mb")},
            error=None if tasks else "zero tasks — site needs login or is unavailable")

    for x in tasks[:5]:
        t.log(f"TASK: id={x.get('task_id')!r} title={x.get('title')!r} reward={x.get('reward')!r}")

    ram.append(t.ram("end"))
    t.add_artifact(save_ram_artifact(ram, "clickworker"))
    return t.finish()


if __name__ == "__main__":
    run()
