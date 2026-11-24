"""Optional AI suggestions for notes the incident rules could not classify. Off by default.

Providers (set AI_PROVIDER in .env):
  off          default: no AI calls at all
  claude_code  the Claude Code CLI in non-interactive mode (`claude -p`), using your existing Claude
               plan login; no API key
  ollama       a local model through Ollama on localhost:11434; free and private

The AI only suggests a category for a person to review. It never changes stored data or rules.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import requests


def _prompt(notes: str, categories: list[dict]) -> str:
    options = "\n".join(f"- {c['id']}: {c['label']}" for c in categories)
    return (
        "Classify this automation run note into one incident category, or 'none' if no category fits.\n"
        f"Categories:\n{options}\n\nNote:\n{notes}\n\n"
        'Answer with JSON only: {"category": "<id or none>", "reason": "<one short sentence>"}'
    )


def _parse(text: str, categories: list[dict]) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    valid = {c["id"] for c in categories} | {"none"}
    return data if data.get("category") in valid else None


def suggest(notes: str, categories: list[dict], provider: str = "off", timeout: int = 90) -> dict | None:
    if provider == "off":
        return None
    prompt = _prompt(notes, categories)
    if provider == "claude_code":
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("Claude Code CLI not found. Install Claude Code or set AI_PROVIDER=off.")
        out = subprocess.run(
            [exe, "-p", prompt, "--output-format", "json"], capture_output=True, text=True, timeout=timeout, check=False
        )
        if out.returncode != 0:
            raise RuntimeError(f"Claude Code exited with {out.returncode}: {out.stderr[:200]}")
        try:
            text = json.loads(out.stdout).get("result", "")
        except json.JSONDecodeError:
            text = out.stdout
        return _parse(text, categories)
    if provider == "ollama":
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "qwen2.5:7b", "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        return _parse(resp.json().get("response", ""), categories)
    raise ValueError(f"Unknown AI provider: {provider}")
