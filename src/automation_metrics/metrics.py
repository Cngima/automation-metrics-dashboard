"""Metrics computed from the stored runs: volume, outcomes, incidents, reliability, missed runs and time saved."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .store import Store

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def runs_frame(store: Store) -> pd.DataFrame:
    rows = [dict(r) for r in store.runs()]
    cols = ["key", "agent", "run_date", "status", "outcome", "pillar", "topic", "platforms_ok", "notes"]
    df = pd.DataFrame(rows, columns=cols)
    df["run_date"] = pd.to_datetime(df["run_date"]).dt.date
    df["week"] = [d - timedelta(days=d.weekday()) for d in df["run_date"]]
    return df


def incidents_frame(store: Store) -> pd.DataFrame:
    rows = [dict(r) for r in store.incident_rows()]
    df = pd.DataFrame(rows, columns=["run_key", "category", "label", "severity", "agent", "run_date"])
    df["run_date"] = pd.to_datetime(df["run_date"]).dt.date
    return df


def in_period(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    return df[(df["run_date"] >= start) & (df["run_date"] <= end)]


def expected_runs(agents_cfg: dict, runs: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Scheduled slots per agent between its first logged run (or `start`, if later) and `end`, and whether
    each slot was covered. Weekly agents have one slot per week, covered by any run in that week."""
    slots = []
    for name, a in agents_cfg["agents"].items():
        mine = runs[runs["agent"] == name]
        if mine.empty:
            continue
        first = max(start, min(mine["run_date"]))
        days = {d for d in mine["run_date"]}
        if a.get("weekly"):
            weeks = {d - timedelta(days=d.weekday()) for d in days}
            wk = first - timedelta(days=first.weekday())
            while wk <= end:
                due = wk + timedelta(days=WEEKDAYS.index(a["schedule"][0]))
                if first <= due <= end or (wk in weeks and wk <= end):
                    slots.append({"agent": name, "due": due, "covered": wk in weeks})
                wk += timedelta(days=7)
        else:
            d = first
            while d <= end:
                if WEEKDAYS[d.weekday()] in a["schedule"]:
                    slots.append({"agent": name, "due": d, "covered": d in days})
                d += timedelta(days=1)
    return pd.DataFrame(slots, columns=["agent", "due", "covered"])


@dataclass
class KPIs:
    runs: int
    success: int
    partial: int
    failed: int
    skipped: int
    success_rate: float  # successful runs as % of runs attempted (skips excluded)
    on_schedule_rate: float  # scheduled slots covered by a logged run
    missed_slots: int
    recovered_incidents: int
    hours_saved: float  # estimate: successful runs x manual minutes per agent


def kpis(agents_cfg: dict, runs: pd.DataFrame, incidents: pd.DataFrame, start: date, end: date) -> KPIs:
    period = in_period(runs, start, end)
    counts = period["outcome"].value_counts()
    attempted = int(len(period) - counts.get("skipped", 0))
    success = int(counts.get("success", 0))
    slots = expected_runs(agents_cfg, runs, start, end)
    covered = int(slots["covered"].sum()) if not slots.empty else 0
    minutes = sum(
        agents_cfg["agents"][agent]["manual_minutes"] * n
        for agent, n in period[period["outcome"] == "success"]["agent"].value_counts().items()
    )
    inc = in_period(incidents, start, end)
    return KPIs(
        runs=int(len(period)),
        success=success,
        partial=int(counts.get("partial", 0)),
        failed=int(counts.get("failed", 0)),
        skipped=int(counts.get("skipped", 0)),
        success_rate=round(100 * success / attempted, 1) if attempted else 0.0,
        on_schedule_rate=round(100 * covered / len(slots), 1) if len(slots) else 0.0,
        missed_slots=int(len(slots) - covered),
        recovered_incidents=int((inc["severity"] == "recovered").sum()),
        hours_saved=round(minutes / 60, 1),
    )


def weekly_outcomes(runs: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Runs per week by outcome (rows: week starting Monday)."""
    period = in_period(runs, start, end)
    table = period.pivot_table(index="week", columns="outcome", values="key", aggfunc="count", fill_value=0)
    for col in ["success", "partial", "failed", "skipped"]:
        if col not in table:
            table[col] = 0
    return table[["success", "partial", "failed", "skipped"]].sort_index()


def incident_breakdown(incidents: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    inc = in_period(incidents, start, end)
    if inc.empty:
        return pd.DataFrame(columns=["label", "severity", "runs"])
    out = inc.groupby(["label", "severity"])["run_key"].nunique().reset_index(name="runs")
    return out.sort_values("runs", ascending=False).reset_index(drop=True)


def platform_reliability(
    runs: pd.DataFrame, start: date, end: date, platforms=("facebook", "instagram")
) -> pd.DataFrame:
    """For runs that publish, the share where each platform is reported as posted."""
    period = in_period(runs, start, end)
    publishing = period[period["agent"].isin(["social_post", "weekly_reel"]) & (period["outcome"] != "skipped")]
    rows = []
    for p in platforms:
        ok = publishing["platforms_ok"].fillna("").str.contains(p).sum()
        rows.append(
            {
                "platform": p,
                "posted": int(ok),
                "attempted": int(len(publishing)),
                "rate": round(100 * ok / len(publishing), 1) if len(publishing) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def agent_summary(agents_cfg: dict, runs: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    period = in_period(runs, start, end)
    slots = expected_runs(agents_cfg, runs, start, end)
    rows = []
    for name, a in agents_cfg["agents"].items():
        mine = period[period["agent"] == name]
        s = slots[slots["agent"] == name]
        attempted = len(mine[mine["outcome"] != "skipped"])
        ok = int((mine["outcome"] == "success").sum())
        rows.append(
            {
                "agent": a["label"],
                "runs": int(len(mine)),
                "success rate %": round(100 * ok / attempted, 1) if attempted else 0.0,
                "missed slots": int((~s["covered"]).sum()) if not s.empty else 0,
                "est. hours saved": round(ok * a["manual_minutes"] / 60, 1),
            }
        )
    return pd.DataFrame(rows)
