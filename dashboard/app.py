"""Streamlit dashboard for scheduled AI automations.

Run with:  streamlit run dashboard/app.py            (your private database if one exists, else the demo)
           streamlit run dashboard/app.py -- --demo  (always the fictional demo data)
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_metrics import demo, metrics  # noqa: E402
from automation_metrics.classify import Classifier  # noqa: E402
from automation_metrics.config import ROOT, Settings, load_yaml  # noqa: E402
from automation_metrics.store import Store  # noqa: E402

OUTCOME_COLORS = {"success": "#2E7D5B", "partial": "#E0A526", "failed": "#C2413A", "skipped": "#A7A9AC"}
SEVERITY_COLORS = {"failure": "#C2413A", "recovered": "#3A78C2", "warning": "#E0A526"}

st.set_page_config(page_title="Automation metrics", layout="wide")


@st.cache_resource
def demo_store() -> Store:
    path = ROOT / "data" / "demo.db"
    path.unlink(missing_ok=True)
    store = Store(path)
    store.upsert_records(demo.sample_records(), Classifier())
    return store


def pick_store() -> tuple[Store, bool]:
    private = Settings.from_env().db_path
    if "--demo" in sys.argv or not private.exists():
        return demo_store(), True
    return Store(private), False


store, is_demo = pick_store()
cfg = load_yaml("agents.yaml")
runs, incidents = metrics.runs_frame(store), metrics.incidents_frame(store)

# ---------- sidebar ----------
st.sidebar.header("Period")
latest = max(runs["run_date"]) if not runs.empty else date.today()
weeks = st.sidebar.selectbox("Show the last", [4, 8, 12], index=1, format_func=lambda w: f"{w} weeks")
end = st.sidebar.date_input("Ending on", value=latest)
start = end - timedelta(weeks=weeks) + timedelta(days=1)
agent_labels = {k: a["label"] for k, a in cfg["agents"].items()}
chosen = st.sidebar.multiselect(
    "Automations", list(agent_labels), default=list(agent_labels), format_func=agent_labels.get
)
runs_f = runs[runs["agent"].isin(chosen)]
incidents_f = incidents[incidents["agent"].isin(chosen)]
cfg_f = {**cfg, "agents": {k: v for k, v in cfg["agents"].items() if k in chosen}}

# ---------- header ----------
st.title("Automation metrics")
source = "fictional demo data" if is_demo else "live data synced from Make"
st.caption(f"{start:%d %b %Y} to {end:%d %b %Y} · {source}")

k = metrics.kpis(cfg_f, runs_f, incidents_f, start, end)
c = st.columns(5)
c[0].metric("Runs", k.runs, help="Logged runs in the period, including skipped ones")
c[1].metric("Success rate", f"{k.success_rate}%", help="Successful runs as a share of runs attempted (skips excluded)")
c[2].metric("On schedule", f"{k.on_schedule_rate}%", help="Scheduled slots that have a logged run")
c[3].metric(
    "Recovered incidents",
    k.recovered_incidents,
    help="Problems the agent handled itself, e.g. a fallback layout or a gateway error confirmed without re-running",
)
c[4].metric("Est. hours saved", k.hours_saved, help="Successful runs x the manual-minutes assumption per automation")

# ---------- charts ----------
left, right = st.columns([1, 1])
with left:
    st.subheader("Runs per week by outcome")
    weekly = metrics.weekly_outcomes(runs_f, start, end).reset_index()
    if weekly.empty:
        st.info("No runs in this period.")
    else:
        long = weekly.melt(id_vars="week", var_name="outcome", value_name="runs")
        long["week_label"] = pd.to_datetime(long["week"]).dt.strftime("%d %b")
        week_order = list(dict.fromkeys(long.sort_values("week")["week_label"]))
        chart = (
            alt.Chart(long)
            .mark_bar()
            .encode(
                x=alt.X("week_label:O", title="Week starting", sort=week_order, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("runs:Q", title="Runs", stack="zero"),
                color=alt.Color(
                    "outcome:N",
                    scale=alt.Scale(domain=list(OUTCOME_COLORS), range=list(OUTCOME_COLORS.values())),
                    legend=alt.Legend(orient="bottom", title=None, labelLimit=0, direction="horizontal", offset=10),
                ),
                order=alt.Order("outcome_order:Q"),
                tooltip=[alt.Tooltip("week_label:O", title="Week starting"), "outcome:N", "runs:Q"],
            )
            .transform_calculate(outcome_order="indexof(['success','partial','failed','skipped'], datum.outcome)")
            .properties(height=300, autosize=alt.AutoSizeParams(type="fit", contains="padding"))
        )
        st.altair_chart(chart, use_container_width=True)
with right:
    st.subheader("Incidents by type")
    breakdown = metrics.incident_breakdown(incidents_f, start, end)
    if breakdown.empty:
        st.info("No incidents in this period.")
    else:
        chart = (
            alt.Chart(breakdown)
            .mark_bar()
            .encode(
                y=alt.Y("label:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
                x=alt.X("runs:Q", title="Runs affected"),
                color=alt.Color(
                    "severity:N",
                    scale=alt.Scale(domain=list(SEVERITY_COLORS), range=list(SEVERITY_COLORS.values())),
                    legend=None,
                ),
                tooltip=["label:N", "severity:N", "runs:Q"],
            )
            .properties(height=300, autosize=alt.AutoSizeParams(type="fit", contains="padding"))
        )
        st.altair_chart(chart, use_container_width=True)
        st.caption("Red: failure, nothing delivered. Blue: recovered by the agent. Amber: delivered but not confirmed.")

# ---------- tables ----------
st.subheader("By automation")
st.dataframe(metrics.agent_summary(cfg_f, runs_f, start, end), hide_index=True, use_container_width=True)

col_a, col_b = st.columns([1, 1])
with col_a:
    st.subheader("Platform reliability")
    st.dataframe(metrics.platform_reliability(runs_f, start, end), hide_index=True, use_container_width=True)
    st.caption("Share of publishing runs reported as posted on each platform.")
with col_b:
    st.subheader("Missed scheduled runs")
    slots = metrics.expected_runs(cfg_f, runs_f, start, end)
    missed = slots[~slots["covered"]] if not slots.empty else slots
    if missed.empty:
        st.info("None in this period.")
    else:
        st.dataframe(
            missed.assign(agent=missed["agent"].map(agent_labels))[["agent", "due"]],
            hide_index=True,
            use_container_width=True,
        )

st.subheader("Run log")
period = metrics.in_period(runs_f, start, end).sort_values("run_date", ascending=False)
outcomes = st.multiselect("Outcome", list(OUTCOME_COLORS), default=list(OUTCOME_COLORS))
log = period[period["outcome"].isin(outcomes)].assign(agent=lambda d: d["agent"].map(agent_labels))
st.dataframe(
    log[["run_date", "agent", "outcome", "status", "pillar", "topic", "platforms_ok", "notes"]],
    hide_index=True,
    use_container_width=True,
)

with st.expander("Assumptions and definitions"):
    st.markdown(
        "\n".join(
            f"- **{a['label']}**: {a['manual_minutes']} minutes by hand per run; scheduled {', '.join(a['schedule'])}"
            for a in cfg_f["agents"].values()
        )
        + "\n\n- **Hours saved** is an estimate: successful runs x the manual minutes above. Edit "
        "`config/agents.yaml` to change the assumptions.\n"
        "- **On schedule** counts a slot as covered when any run (including a skip) is logged for it. Weekly "
        "automations are covered by a run anywhere in that week.\n"
        "- **Incidents** come from rules in `config/incident_rules.yaml` matched against each run's notes."
    )
last = store.last_sync()
if last:
    st.caption(f"Last sync: {last['finished'] or last['started']} ({last['source']})")
