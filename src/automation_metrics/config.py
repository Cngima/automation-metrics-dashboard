"""Settings: secrets from the environment (or a .env file), behaviour from YAML in config/."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("AMD_CONFIG_DIR", ROOT / "config"))


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader: KEY=value lines; existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    make_base_url: str = "https://eu1.make.com/api/v2"
    make_token: str | None = None
    make_data_store_id: int | None = None
    db_path: Path = ROOT / "data" / "private" / "metrics.db"
    alert_email_to: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    ai_provider: str = "off"
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        env = os.environ.get
        store_id = env("MAKE_DATA_STORE_ID")
        return cls(
            make_base_url=env("MAKE_BASE_URL", "https://eu1.make.com/api/v2"),
            make_token=env("MAKE_API_TOKEN"),
            make_data_store_id=int(store_id) if store_id else None,
            db_path=Path(env("AMD_DB_PATH", str(ROOT / "data" / "private" / "metrics.db"))),
            alert_email_to=env("ALERT_EMAIL_TO"),
            smtp_host=env("SMTP_HOST"),
            smtp_port=int(env("SMTP_PORT", "587")),
            smtp_user=env("SMTP_USER"),
            smtp_password=env("SMTP_PASSWORD"),
            ai_provider=env("AI_PROVIDER", "off"),
        )


def load_yaml(name: str, config_dir: Path | None = None) -> dict:
    return yaml.safe_load(((config_dir or CONFIG_DIR) / name).read_text(encoding="utf-8"))
