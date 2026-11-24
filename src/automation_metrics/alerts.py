"""Alerts: two failed runs in a row for an agent, or a scheduled run that was never logged."""

from __future__ import annotations

import smtplib
from datetime import date, timedelta
from email.message import EmailMessage

import pandas as pd

from .config import Settings
from .metrics import expected_runs


def find_alerts(agents_cfg: dict, runs: pd.DataFrame, today: date, lookback_days: int = 7) -> list[str]:
    alerts = []
    for name, a in agents_cfg["agents"].items():
        mine = runs[(runs["agent"] == name) & (runs["outcome"] != "skipped")].sort_values("run_date")
        last_two = mine.tail(2)
        if len(last_two) == 2 and (last_two["outcome"] == "failed").all():
            alerts.append(f"{a['label']}: the last two runs failed ({', '.join(last_two['key'])}).")
    yesterday = today - timedelta(days=1)
    slots = expected_runs(agents_cfg, runs, today - timedelta(days=lookback_days), yesterday)
    for _, s in slots[~slots["covered"]].iterrows():
        label = agents_cfg["agents"][s["agent"]]["label"]
        alerts.append(f"{label}: no run logged for the slot due {s['due'].isoformat()}.")
    return alerts


def send_alerts(alerts: list[str], settings: Settings, dry_run: bool = True) -> str:
    """Email the alerts (or just return the text when dry_run is True or SMTP is not configured)."""
    body = "Automation alerts:\n\n" + "\n".join(f"- {a}" for a in alerts) + "\n"
    configured = all([settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.alert_email_to])
    if dry_run or not configured or not alerts:
        return body
    msg = EmailMessage()
    msg["Subject"] = f"Automation alerts: {len(alerts)} item(s)"
    msg["From"], msg["To"] = settings.smtp_user, settings.alert_email_to
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
    return body
