"""
test_hubstaff.py — Verify Hubstaff scraper returns REAL jobs.
- Fake/placeholder data detection
- RAM monitoring before and after scrape
- FAIL if zero jobs returned
"""
from _harness import TestRun, guard, dump_process_list, save_ram_artifact

FAKE_MARKERS = [
    "sample", "fake", "test job", "hardcoded", "placeholder",
    "example job", "lorem ipsum", "n/a", "unknown", "acme corp",
]


def _looks_fake(job: dict) -> bool:
    for field in ("title", "company", "job_title", "client"):
        val = (job.get(field) or "").lower().strip()
        if any(m in val for m in FAKE_MARKERS):
            return True
        if val in ("", "?", "-", "none"):
            return True
    return False


def run() -> dict:
    t   = TestRun("test_hubstaff")
    ram = [t.ram("start")]

    t.add_artifact(dump_process_list("before_hubstaff"))

    scrape = guard(t, "import scrape_hubstaff_jobs",
                   lambda: __import__("services.hubstaff_service",
                                      fromlist=["scrape_hubstaff_jobs"]).scrape_hubstaff_jobs)
    if scrape is None:
        return t.finish()

    t.log("Calling scrape_hubstaff_jobs(max_jobs=10) — needs Playwright + network")
    ram.append(t.ram("before_scrape"))
    jobs = guard(t, "call scrape_hubstaff_jobs", lambda: scrape(10))
    ram.append(t.ram("after_scrape"))

    if jobs is None:
        t.add_artifact(save_ram_artifact(ram, "hubstaff"))
        return t.finish()

    t.log(f"Returned {len(jobs)} job(s)")
    t.check("at least one job returned",
            len(jobs) >= 1,
            evidence={"count": len(jobs),
                      "first_raw": jobs[0] if jobs else None,
                      "ram_before_mb": ram[-2].get("used_mb"),
                      "ram_after_mb":  ram[-1].get("used_mb")},
            error=None if len(jobs) >= 1 else "zero jobs — scraper needs Playwright + login")

    if not jobs:
        t.add_artifact(save_ram_artifact(ram, "hubstaff"))
        return t.finish()

    fake = [j for j in jobs if _looks_fake(j)]
    t.check("no fake/sample/placeholder data detected",
            len(fake) == 0,
            evidence={"total": len(jobs), "fake_count": len(fake),
                      "fake_samples": [j.get("title") for j in fake[:3]]},
            error=None if not fake else f"{len(fake)} job(s) look like fake data")

    sample = []
    for j in jobs[:5]:
        title   = j.get("title") or j.get("job_title") or ""
        company = j.get("company") or j.get("client") or ""
        budget  = j.get("budget") or j.get("pay") or j.get("rate") or ""
        t.log(f"JOB: {title!r} | {company!r} | {budget!r}")
        sample.append({"title": title, "company": company, "budget": budget,
                       "title_len": len(title), "company_len": len(company)})

    all_have_titles = all(len(j["title"].strip()) > 3 for j in sample)
    t.check("all returned jobs have non-trivial titles",
            all_have_titles,
            evidence={"jobs": sample},
            error=None if all_have_titles else "some jobs have empty/trivial titles")

    t.screenshot("after_scrape")
    ram.append(t.ram("end"))
    t.add_artifact(save_ram_artifact(ram, "hubstaff"))
    return t.finish()


if __name__ == "__main__":
    run()
