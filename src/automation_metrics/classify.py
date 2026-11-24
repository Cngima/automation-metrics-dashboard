"""Turn each run record into an agent run plus its incidents, using rules from config/."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .config import load_yaml


@dataclass
class Incident:
    category: str
    label: str
    severity: str


@dataclass
class AgentRun:
    key: str
    agent: str
    run_date: date
    status: str
    outcome: str  # success | partial | failed | skipped
    pillar: str = ""
    topic: str = ""
    platforms_ok: list[str] = field(default_factory=list)
    notes: str = ""
    incidents: list[Incident] = field(default_factory=list)


class Classifier:
    def __init__(self, agents_cfg: dict | None = None, rules_cfg: dict | None = None):
        self.agents_cfg = agents_cfg or load_yaml("agents.yaml")
        self.rules = (rules_cfg or load_yaml("incident_rules.yaml"))["categories"]
        self._agent_patterns = [(name, re.compile(a["key_pattern"])) for name, a in self.agents_cfg["agents"].items()]
        self._rule_patterns = [(r, [re.compile(p, re.I) for p in r["patterns"]]) for r in self.rules]

    def agent_for(self, key: str) -> str | None:
        for name, pattern in self._agent_patterns:
            if pattern.match(key):
                return name
        return None

    def incidents(self, notes: str) -> list[Incident]:
        found = []
        for rule, patterns in self._rule_patterns:
            if any(p.search(notes or "") for p in patterns):
                found.append(Incident(rule["id"], rule["label"], rule["severity"]))
        return found

    def outcome(self, agent: str, status: str) -> str | None:
        a = self.agents_cfg["agents"][agent]
        if status in self.agents_cfg.get("not_runs", []):
            return None
        if status in self.agents_cfg.get("skipped", []):
            return "skipped"
        if status in a.get("success_status", []):
            return "success"
        if status in a.get("partial_status", []):
            return "partial"
        return "failed"

    def to_run(self, record: dict) -> AgentRun | None:
        """A data store record becomes a run, or None for settings, reference and planned records."""
        key, data = record["key"], record.get("data") or {}
        agent = self.agent_for(key)
        if not agent:
            return None
        status = (data.get("status") or "").strip()
        outcome = self.outcome(agent, status)
        if outcome is None:
            return None
        try:
            run_date = date.fromisoformat(str(data.get("date") or key[-10:]))
        except ValueError:
            return None
        platforms = [p for p in (data.get("platforms_ok") or "").split(",") if p.strip() and p.strip() != "none"]
        notes = data.get("notes") or ""
        return AgentRun(
            key=key,
            agent=agent,
            run_date=run_date,
            status=status,
            outcome=outcome,
            pillar=data.get("pillar") or "",
            topic=data.get("topic") or "",
            platforms_ok=[p.strip() for p in platforms],
            notes=notes,
            incidents=self.incidents(notes),
        )
