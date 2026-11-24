"""Command line: amd demo | sync | rebuild | summary | alerts | unclassified | dashboard."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from . import ai, alerts, demo, metrics
from .classify import Classifier
from .config import ROOT, Settings, load_yaml
from .make_client import MakeAPIError, MakeClient
from .store import Store

DEMO_DB = ROOT / "data" / "demo.db"


def _store(args, settings: Settings) -> Store:
    return Store(DEMO_DB if args.demo else (args.db or settings.db_path))


def cmd_demo(args, settings):
    DEMO_DB.unlink(missing_ok=True)
    store = Store(DEMO_DB)
    sid = store.start_sync("demo")
    counts = store.upsert_records(demo.sample_records(), Classifier())
    store.finish_sync(sid, counts)
    print(f"Demo data loaded into {DEMO_DB}: {counts['inserted']} records, {len(store.runs())} runs.")


def cmd_sync(args, settings):
    if not settings.make_data_store_id:
        raise SystemExit("Set MAKE_DATA_STORE_ID in .env")
    store = _store(args, settings)
    sid = store.start_sync("make")
    try:
        client = MakeClient(settings.make_base_url, settings.make_token or "")
        records = client.data_store_records(settings.make_data_store_id)
        counts = store.upsert_records(records, Classifier())
    except MakeAPIError as e:
        store.finish_sync(sid, {}, error=str(e))
        raise SystemExit(f"Sync failed: {e}") from e
    store.finish_sync(sid, counts)
    print(
        f"Synced {counts['fetched']} records: {counts['inserted']} new, {counts['updated']} changed, "
        f"{counts['unchanged']} unchanged."
    )


def cmd_rebuild(args, settings):
    store = _store(args, settings)
    store.rebuild(Classifier())
    print(f"Re-classified {len(store.runs())} runs with the current rules.")


def _period(args) -> tuple[date, date]:
    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
    return end - timedelta(days=args.days - 1), end


def cmd_summary(args, settings):
    store = _store(args, settings)
    cfg = load_yaml("agents.yaml")
    runs, inc = metrics.runs_frame(store), metrics.incidents_frame(store)
    start, end = _period(args)
    k = metrics.kpis(cfg, runs, inc, start, end)
    print(f"Period {start} to {end}")
    print(f"Runs: {k.runs} (success {k.success}, partial {k.partial}, failed {k.failed}, skipped {k.skipped})")
    print(f"Success rate: {k.success_rate}% | On schedule: {k.on_schedule_rate}% ({k.missed_slots} missed slots)")
    print(f"Recovered incidents: {k.recovered_incidents} | Estimated hours saved: {k.hours_saved}")
    print()
    print(metrics.agent_summary(cfg, runs, start, end).to_string(index=False))
    print()
    print(metrics.incident_breakdown(inc, start, end).to_string(index=False))


def cmd_alerts(args, settings):
    store = _store(args, settings)
    found = alerts.find_alerts(
        load_yaml("agents.yaml"),
        metrics.runs_frame(store),
        date.fromisoformat(args.today) if args.today else date.today(),
    )
    if not found:
        print("No alerts.")
        return
    print(alerts.send_alerts(found, settings, dry_run=not args.send))
    if args.send:
        print("Email sent." if settings.smtp_host else "SMTP not configured; nothing sent.")


def cmd_unclassified(args, settings):
    store = _store(args, settings)
    categories = load_yaml("incident_rules.yaml")["categories"]
    classified = {r["run_key"] for r in store.incident_rows()}
    pending = [r for r in store.runs() if r["notes"] and r["key"] not in classified]
    if not pending:
        print("Every run note matched at least one rule.")
        return
    provider = args.ai or settings.ai_provider
    for r in pending:
        print(f"{r['key']}: {r['notes'][:120]}")
        if provider != "off":
            s = ai.suggest(r["notes"], categories, provider)
            print(f"   suggestion: {s['category']} ({s.get('reason', '')})" if s else "   suggestion: none")


def cmd_dashboard(args, settings):
    app = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"
    extra = ["--", "--demo"] if args.demo else []
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app), *extra], check=False)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="amd", description="Automation metrics: sync, measure and alert.")
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--demo", action="store_true", help="use the fictional demo database")
        p.add_argument("--db", help="path to a SQLite database (default from .env)")
        p.set_defaults(func=func)
        return p

    add("demo", cmd_demo, "load the fictional sample dataset")
    add("sync", cmd_sync, "pull run records from the Make data store (read-only)")
    add("rebuild", cmd_rebuild, "re-classify stored runs after changing the rules")
    s = add("summary", cmd_summary, "print KPIs for a period")
    s.add_argument("--days", type=int, default=28)
    s.add_argument("--end", help="YYYY-MM-DD (default yesterday)")
    a = add("alerts", cmd_alerts, "check for consecutive failures and missed runs")
    a.add_argument("--send", action="store_true", help="email the alerts (otherwise just print)")
    a.add_argument("--today", help="YYYY-MM-DD, for testing")
    u = add("unclassified", cmd_unclassified, "list run notes no incident rule matched")
    u.add_argument("--ai", choices=["off", "claude_code", "ollama"], help="suggest categories with AI")
    add("dashboard", cmd_dashboard, "open the Streamlit dashboard")

    args = ap.parse_args(argv)
    args.func(args, Settings.from_env())


if __name__ == "__main__":
    main()
