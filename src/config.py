"""Configuration loading.

All settings come from environment variables, with a local ".env" file
(if present) loaded first as a convenience for running on your own machine.
In GitHub Actions, these are instead supplied via repo Secrets/Variables
(see the workflow file and README).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Don't clobber a real environment variable someone already set.
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    contact_email: str
    app_name: str
    app_version: str
    league_name: str
    realm: str
    min_volume_abs_floor: int
    min_volume_percentile: float
    min_profit_pct: float
    persistence_hours: int
    max_cycles_per_run: int
    ntfy_topic: str
    discord_webhook_url: str
    state_dir: Path
    history_keep: int
    request_timeout: int


def load_config() -> Config:
    contact_email = os.environ.get("CONTACT_EMAIL", "").strip()
    if not contact_email or "@" not in contact_email:
        raise SystemExit(
            "CONTACT_EMAIL is not set (or looks invalid).\n"
            "GGG's API rules require a contact email in every request's "
            "User-Agent header, even for this public endpoint.\n"
            "Copy .env.example to .env and fill in CONTACT_EMAIL, "
            "or set it as a GitHub Actions secret."
        )

    return Config(
        contact_email=contact_email,
        app_name=os.environ.get("APP_NAME", "poe2-faustus-arb").strip() or "poe2-faustus-arb",
        app_version=os.environ.get("APP_VERSION", "1.0.0").strip() or "1.0.0",
        league_name=os.environ.get("LEAGUE_NAME", "Forbidden Rites").strip(),
        realm=os.environ.get("REALM", "poe2").strip() or "poe2",
        min_volume_abs_floor=_get_int("MIN_VOLUME_ABS_FLOOR", 20),
        min_volume_percentile=_get_float("MIN_VOLUME_PERCENTILE", 0.90),
        min_profit_pct=_get_float("MIN_PROFIT_PCT", 2.0),
        persistence_hours=max(1, _get_int("PERSISTENCE_HOURS", 2)),
        max_cycles_per_run=max(1, _get_int("MAX_CYCLES_PER_RUN", 8)),
        ntfy_topic=os.environ.get("NTFY_TOPIC", "").strip(),
        discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
        state_dir=ROOT / "state",
        history_keep=_get_int("HISTORY_KEEP", 6),
        request_timeout=_get_int("REQUEST_TIMEOUT", 20),
    )
