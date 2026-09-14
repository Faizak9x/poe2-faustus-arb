"""Alert delivery. Always logs locally; optionally pushes to ntfy.sh and/or
a Discord webhook if configured. This tool never touches the game - you
execute every trade by hand in Faustus after seeing an alert here.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .config import Config

DISCLAIMER = "This product isn't affiliated with or endorsed by Grinding Gear Games in any way."


def log_alert(cfg: Config, alert: dict) -> None:
    log_path = cfg.state_dir / "alerts.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(alert) + "\n")


def _send_ntfy(cfg: Config, title: str, body: str) -> None:
    if not cfg.ntfy_topic:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{cfg.ntfy_topic}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "default", "Tags": "moneybag"},
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"[warn] ntfy notification failed: {exc}")


def _send_discord(cfg: Config, content: str) -> None:
    if not cfg.discord_webhook_url:
        return
    try:
        requests.post(cfg.discord_webhook_url, json={"content": content}, timeout=10)
    except requests.RequestException as exc:
        print(f"[warn] discord notification failed: {exc}")


def send_alert(cfg: Config, alert: dict) -> None:
    """alert keys: cycle_display, profit_pct, timestamp, persistence_hours, min_volume."""
    title = f"Faustus arbitrage: {alert['profit_pct']:.2f}% profit"
    body = (
        f"{alert['cycle_display']}\n"
        f"Expected profit: {alert['profit_pct']:.2f}%\n"
        f"Confirmed over {alert['persistence_hours']} consecutive hourly pulls\n"
        f"Min leg volume this hour: {alert['min_volume']:.0f}\n"
        f"As of: {alert['timestamp']} UTC\n"
        f"League: {alert['league']}\n"
        "Execute manually in the in-game Currency Exchange panel."
    )
    print("=" * 60)
    print(title)
    print(body)
    print("=" * 60)

    log_alert(cfg, alert)
    _send_ntfy(cfg, title, body)
    _send_discord(cfg, f"**{title}**\n```\n{body}\n```")
