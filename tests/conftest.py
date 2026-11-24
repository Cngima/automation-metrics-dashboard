import pytest

from automation_metrics.classify import Classifier
from automation_metrics.store import Store


def rec(key, status, notes="", platforms="", date=None, pillar=""):
    return {
        "key": key,
        "data": {
            "date": date or key[-10:],
            "status": status,
            "notes": notes,
            "platforms_ok": platforms,
            "pillar": pillar,
        },
    }


@pytest.fixture
def classifier():
    return Classifier()


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture
def week_records():
    """One week (Mon 2 Nov to Sun 8 Nov 2026) with every kind of outcome and incident."""
    return [
        {"key": "config", "data": {"status": "Active", "notes": "settings"}},
        {"key": "story-ABC", "data": {"date": "story", "status": "Use"}},
        rec(
            "2026-11-02",
            "Posted",
            "graphic checked; generate-design failed twice, so built by copying the checked layout",
            "facebook,instagram",
        ),
        rec("2026-11-04", "Partial", "Instagram post failed; connection expired, reauthorize in Make", "facebook"),
        rec("2026-11-06", "Skipped", "owner chose to skip"),
        rec("reel-2026-11-03", "Failed", "Generation failed twice; nothing published", "none"),
        rec("wa-2026-11-02", "Sent to Carol", "scenarios_run returned 'Bad Gateway' but finished SUCCESS"),
        rec("wa-2026-11-03", "Sent to Carol", "graphic checked"),
        rec("wa-2026-11-04", "Sent to Carol", "quota_exceeded, so built by copying the checked layout"),
        # wa 5th, 6th and 7th missing: the scheduler did not fire
        rec("wa-2026-11-08", "Sent to Carol", "graphic checked"),
        rec("2026-11-09", "Planned"),
    ]
