"""A fictional sample dataset in the same shape as real Make data store records.

The demo brand, topics and notes are invented. The incident patterns (a flaky design step
recovered with a fallback layout, gateway errors confirmed without re-running, a few days
where the scheduler did not fire) mirror the kinds of problems real agent runs hit.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

TOPICS = [
    "How to turn duties into achievements",
    "What ATS screening really checks",
    "Five interview follow-up habits",
    "Writing a summary that gets read",
    "How to tailor a CV in 20 minutes",
    "Spotting a fake job advert",
    "Cover letters that add to your CV",
    "Getting ready for the January hiring rush",
]
PILLARS = {0: "Educational", 2: "Client story", 4: "Offer"}


def _notes(rng: random.Random, outcome: str) -> str:
    parts = ["graphic checked, header added"]
    if rng.random() < 0.35:
        parts.append(
            "design generation failed ('Generation failed'), so the graphic was built by copying the "
            "checked layout and rewriting the text"
        )
    if rng.random() < 0.15:
        parts.append("design tool returned quota_exceeded; built by copying the checked layout")
    if rng.random() < 0.2:
        parts.append("fixed a headline that wrapped onto three lines")
    if outcome == "Failed":
        return "graphic failed quality check after 4 candidates; not published, owner emailed"
    if rng.random() < 0.15:
        parts.append("scenario call returned 'Bad Gateway' but the execution finished SUCCESS, so it was NOT re-run")
    parts.append("per-platform post IDs not readable on the free plan, so the result is unconfirmed")
    return "; ".join(parts)


def sample_records(end: date | None = None, weeks: int = 10, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    end = end or date(2026, 11, 23)
    start = end - timedelta(weeks=weeks) + timedelta(days=1)
    missed = {start + timedelta(days=d) for d in rng.sample(range(weeks * 7), 4)}
    records: list[dict] = [{"key": "config", "data": {"status": "Active", "notes": "demo settings"}}]
    d = start
    while d <= end:
        wd = d.weekday()
        # WhatsApp pack, daily
        if d not in missed:
            records.append(
                {
                    "key": f"wa-{d}",
                    "data": {
                        "date": str(d),
                        "pillar": "WHATSAPP",
                        "topic": rng.choice(TOPICS),
                        "status": "Sent",
                        "notes": _notes(rng, "Sent"),
                    },
                }
            )
        # Social post, Mon/Wed/Fri
        if wd in PILLARS and d not in missed:
            roll = rng.random()
            status = (
                "Failed" if roll < 0.06 else ("Partial" if roll < 0.12 else ("Skipped" if roll < 0.15 else "Posted"))
            )
            platforms = {"Posted": "facebook,instagram", "Partial": "facebook", "Failed": "none", "Skipped": ""}[status]
            records.append(
                {
                    "key": str(d),
                    "data": {
                        "date": str(d),
                        "pillar": PILLARS[wd],
                        "topic": rng.choice(TOPICS),
                        "status": status,
                        "platforms_ok": platforms,
                        "notes": _notes(rng, status) if status != "Skipped" else "owner chose to skip",
                    },
                }
            )
        # Weekly reel, Tuesday (one in ten fails and is carried to Thursday)
        if wd == 1:
            if rng.random() < 0.1:
                records.append(
                    {
                        "key": f"reel-{d}",
                        "data": {
                            "date": str(d),
                            "pillar": "REEL",
                            "topic": rng.choice(TOPICS),
                            "status": "Failed",
                            "platforms_ok": "none",
                            "notes": "design generation failed twice; nothing published",
                        },
                    }
                )
            else:
                records.append(
                    {
                        "key": f"reel-{d}",
                        "data": {
                            "date": str(d),
                            "pillar": "REEL",
                            "topic": rng.choice(TOPICS),
                            "status": "Posted",
                            "platforms_ok": "facebook,instagram",
                            "notes": _notes(rng, "Posted"),
                        },
                    }
                )
        d += timedelta(days=1)
    # planned future posts are in the store too, and must not count as runs
    records.append(
        {
            "key": str(end + timedelta(days=2)),
            "data": {"date": str(end + timedelta(days=2)), "status": "Planned", "topic": "upcoming"},
        }
    )
    return records
