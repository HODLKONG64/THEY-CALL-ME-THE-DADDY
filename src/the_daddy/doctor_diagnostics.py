"""Read-only operational metrics. No raw diagnostics or credentials in the report."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from statistics import median

from .doctor_history import terms
from .swarmsy_doctor import FINAL_STATUSES


def duration(item):
    try:
        start, end = datetime.fromisoformat(item.created_at), datetime.fromisoformat(item.updated_at)
        seconds = (end - start).total_seconds()
        return seconds if seconds >= 0 else None
    except (ValueError, TypeError):
        return None


def report(archive, index, target, repos):
    rows = [r for r in archive.all_requests() if r.repo_target.casefold() == target.casefold()]
    terminal = [r for r in rows if r.status in FINAL_STATUSES]
    merged = [r for r in terminal if r.status == "merged"]
    times = [d for r in terminal if (d := duration(r)) is not None]
    # Counts are by case, never by R2 versions or repeated synchronization pages.
    patterns = Counter()
    for r in rows:
        key = " ".join(sorted(terms(r.problem_summary)))
        if key:
            patterns[key] += 1
    # Only counts, not diagnostic text (which can contain personal information).
    repeated = sorted((n for n in patterns.values() if n > 1), reverse=True)
    db = index.connect()
    try:
        coverage = []
        for repo in repos:
            count = db.execute("SELECT count(*) FROM history WHERE repo=?", (repo,)).fetchone()[0]
            checkpoint = db.execute("SELECT page,since,started,full_scan FROM checkpoint WHERE repo=?", (repo,)).fetchone()
            coverage.append({"repo": repo, "unique_records": count,
                             "next_page": checkpoint[0] if checkpoint else None,
                             "initial_scan_checkpointed": bool(checkpoint and checkpoint[1]),
                             "cycle_started": checkpoint[2] if checkpoint else None})
    finally:
        db.close()
    return {"target": target, "requests": len(rows), "outcomes": dict(Counter(r.status for r in rows)),
            "merged_cases": len(merged), "terminal_cases": len(terminal),
            "merge_fraction_of_terminal_cases": round(len(merged)/len(terminal), 4) if terminal else None,
            "post_merge_ci": dict(Counter(r.post_merge_ci for r in merged)),
            "deployment_jobs": dict(Counter(r.deployment_status for r in merged)),
            "median_case_age_at_last_update_seconds": round(median(times), 1) if times else None,
            "repeated_normalized_problem_groups": len(repeated),
            "cases_per_repeated_group": repeated[:20],
            "history_coverage": coverage,
            "limitations": ["Merge fraction is not a production success rate.",
                            "Case age includes queue/review time and later status updates.",
                            "Repeat groups are lexical, not proven common root causes.",
                            "API cost and live production health are not measured."]}
