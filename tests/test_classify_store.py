from datetime import date

from conftest import rec

from automation_metrics.classify import Classifier


def test_agent_detection(classifier):
    assert classifier.agent_for("2026-11-04") == "social_post"
    assert classifier.agent_for("reel-2026-11-04") == "weekly_reel"
    assert classifier.agent_for("wa-2026-11-04") == "whatsapp_pack"
    assert classifier.agent_for("story-MAHZ2") is None
    assert classifier.agent_for("config") is None


def test_outcomes(classifier):
    assert classifier.outcome("social_post", "Posted") == "success"
    assert classifier.outcome("social_post", "Partial") == "partial"
    assert classifier.outcome("social_post", "Failed") == "failed"
    assert classifier.outcome("social_post", "Skipped") == "skipped"
    assert classifier.outcome("social_post", "Planned") is None
    assert classifier.outcome("whatsapp_pack", "Sent to Carol") == "success"


def test_unknown_status_counts_as_failed(classifier):
    assert classifier.outcome("weekly_reel", "Something odd") == "failed"


def test_incident_rules_match_real_style_notes(classifier):
    notes = (
        "generate-design failed twice ('Generation failed'), so the graphic was built by copying the checked "
        "layout; scenarios_run returned 'Bad Gateway' but finished SUCCESS, so it was NOT re-run; per-module "
        "post IDs are not readable via the API, so platforms_ok is unconfirmed"
    )
    ids = {i.category for i in classifier.incidents(notes)}
    assert ids == {"design_generation_failed", "fallback_layout_used", "gateway_error_no_rerun", "result_unconfirmed"}


def test_clean_notes_have_no_incidents(classifier):
    assert classifier.incidents("graphic checked, header added") == []


def test_to_run_skips_non_runs(classifier):
    assert classifier.to_run(rec("2026-11-09", "Planned")) is None
    assert classifier.to_run({"key": "config", "data": {"status": "Active"}}) is None


def test_to_run_parses_fields(classifier):
    run = classifier.to_run(rec("2026-11-04", "Partial", "connection expired", "facebook"))
    assert run.run_date == date(2026, 11, 4) and run.outcome == "partial"
    assert run.platforms_ok == ["facebook"]
    assert [i.category for i in run.incidents] == ["connection_expired"]


def test_platforms_none_means_empty(classifier):
    assert classifier.to_run(rec("reel-2026-11-03", "Failed", platforms="none")).platforms_ok == []


def test_custom_rules_are_used():
    rules = {"categories": [{"id": "x", "label": "X", "severity": "warning", "patterns": ["banana"]}]}
    assert Classifier(rules_cfg=rules).incidents("Banana split")[0].category == "x"


def test_sync_is_incremental(store, classifier, week_records):
    first = store.upsert_records(week_records, classifier)
    assert first["inserted"] == len(week_records) and first["unchanged"] == 0
    again = store.upsert_records(week_records, classifier)
    assert again == {"fetched": len(week_records), "inserted": 0, "updated": 0, "unchanged": len(week_records)}


def test_changed_record_replaces_run_and_incidents(store, classifier):
    store.upsert_records([rec("2026-11-02", "Failed", "graphic failed quality check")], classifier)
    assert [r["category"] for r in store.incident_rows()] == ["quality_check_failed"]
    counts = store.upsert_records([rec("2026-11-02", "Posted", "graphic checked", "facebook,instagram")], classifier)
    assert counts["updated"] == 1
    assert store.runs()[0]["outcome"] == "success" and store.incident_rows() == []


def test_runs_exclude_reference_and_planned_records(store, classifier, week_records):
    store.upsert_records(week_records, classifier)
    keys = {r["key"] for r in store.runs()}
    assert "config" not in keys and "story-ABC" not in keys and "2026-11-09" not in keys
    assert len(keys) == 8


def test_rebuild_applies_new_rules(store, week_records):
    store.upsert_records(week_records, Classifier())
    rules = {
        "categories": [{"id": "any_check", "label": "Checked", "severity": "warning", "patterns": ["graphic checked"]}]
    }
    store.rebuild(Classifier(rules_cfg=rules))
    assert {r["category"] for r in store.incident_rows()} == {"any_check"}


def test_sync_log(store):
    sid = store.start_sync("test")
    store.finish_sync(sid, {"fetched": 3, "inserted": 3}, error=None)
    last = store.last_sync()
    assert last["source"] == "test" and last["fetched"] == 3 and last["finished"]
