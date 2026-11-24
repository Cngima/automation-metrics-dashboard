from datetime import date

import pytest
from conftest import rec

from automation_metrics import alerts, metrics
from automation_metrics.config import Settings, load_yaml

START, END = date(2026, 11, 2), date(2026, 11, 8)


@pytest.fixture
def loaded(store, classifier, week_records):
    store.upsert_records(week_records, classifier)
    return load_yaml("agents.yaml"), metrics.runs_frame(store), metrics.incidents_frame(store)


def test_kpis(loaded):
    cfg, runs, inc = loaded
    k = metrics.kpis(cfg, runs, inc, START, END)
    assert (k.runs, k.success, k.partial, k.failed, k.skipped) == (8, 5, 1, 1, 1)
    assert k.success_rate == round(100 * 5 / 7, 1)
    # slots: social Mon/Wed/Fri = 3 covered; reel 1 covered; WhatsApp 7 with 4 covered
    assert k.missed_slots == 3 and k.on_schedule_rate == round(100 * 8 / 11, 1)
    # hours saved: 1 social x 60 + 4 WhatsApp x 40 = 220 minutes
    assert k.hours_saved == round(220 / 60, 1)


def test_expected_runs_marks_missing_days(loaded):
    cfg, runs, _ = loaded
    slots = metrics.expected_runs(cfg, runs, START, END)
    missing = slots[~slots["covered"]]
    assert set(missing["agent"]) == {"whatsapp_pack"}
    assert [d.day for d in missing["due"]] == [5, 6, 7]


def test_weekly_agent_covered_by_late_run(classifier, store):
    store.upsert_records([rec("reel-2026-11-05", "Posted", platforms="facebook,instagram")], classifier)
    slots = metrics.expected_runs(load_yaml("agents.yaml"), metrics.runs_frame(store), START, END)
    assert slots["covered"].all() and len(slots) == 1


def test_weekly_outcomes(loaded):
    _, runs, _ = loaded
    table = metrics.weekly_outcomes(runs, START, END)
    row = table.loc[START]
    assert (row["success"], row["partial"], row["failed"], row["skipped"]) == (5, 1, 1, 1)


def test_incident_breakdown_counts_runs(loaded):
    _, _, inc = loaded
    b = metrics.incident_breakdown(inc, START, END).set_index("label")["runs"]
    assert b["Fallback layout used"] == 2 and b["Connection expired"] == 1


def test_platform_reliability(loaded):
    _, runs, _ = loaded
    p = metrics.platform_reliability(runs, START, END).set_index("platform")
    # publishing runs attempted: social Mon (fb+ig), social Wed (fb), reel (none) -> 3
    assert p.loc["facebook", "posted"] == 2 and p.loc["instagram", "posted"] == 1
    assert p.loc["facebook", "attempted"] == 3


def test_empty_period(loaded):
    cfg, runs, inc = loaded
    k = metrics.kpis(cfg, runs, inc, date(2025, 1, 1), date(2025, 1, 7))
    assert k.runs == 0 and k.success_rate == 0.0


def test_alert_for_two_failures_in_a_row(classifier, store):
    store.upsert_records([rec("reel-2026-11-03", "Failed"), rec("reel-2026-11-10", "Failed")], classifier)
    found = alerts.find_alerts(load_yaml("agents.yaml"), metrics.runs_frame(store), date(2026, 11, 11))
    assert any("last two runs failed" in a for a in found)


def test_alert_for_missed_slot(loaded):
    cfg, runs, _ = loaded
    found = alerts.find_alerts(cfg, runs, date(2026, 11, 8))
    assert any("2026-11-07" in a for a in found)


def test_send_alerts_dry_run_returns_text():
    body = alerts.send_alerts(["x failed"], Settings(), dry_run=True)
    assert "- x failed" in body
