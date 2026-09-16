"""Alert delivery. Always logs locally; optionally pushes to ntfy.sh and/or
a Discord webhook if configured. This tool never touches the game - you
execute every trade by hand in Faustus after seeing an alert here.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from . import names
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


def _format_hops(hops: list) -> str:
    """Turn stored hop dicts into a plain-text worked example starting from
    100 units, so the alert itself shows roughly what to expect at the
    Currency Exchange panel without needing to open the dashboard."""
    if not hops:
        return ""
    lines = []
    amount = 100.0
    for h in hops:
        from_name = names.humanize(h["from"])
        to_name = names.humanize(h["to"])
        next_amount = amount * h["rate"]
        lines.append(
            f"  {amount:.2f} {from_name} -> {next_amount:.2f} {to_name}  "
            f"(rate {h['rate']:.6g}, leg volume ~{min(h['volume_from'], h['volume_to']):.0f})"
        )
        amount = next_amount
    return "Worked example (starting from 100 units, ignores Faustus gold fee):\n" + "\n".join(lines)


def send_alert(cfg: Config, alert: dict) -> None:
    """alert keys: cycle_display, profit_pct, timestamp, persistence_hours, min_volume, hops."""
    title = f"Faustus arbitrage: {alert['profit_pct']:.2f}% profit"
    hop_block = _format_hops(alert.get("hops") or [])
    body = (
        f"{alert['cycle_display']}\n"
        f"Expected profit: {alert['profit_pct']:.2f}%\n"
        f"Confirmed over {alert['persistence_hours']} consecutive hourly pulls\n"
        f"Min leg volume this hour: {alert['min_volume']:.0f}\n"
        f"As of: {alert['timestamp']} UTC\n"
        f"League: {alert['league']}\n"
        + (f"{hop_block}\n" if hop_block else "")
        + "Execute manually in the in-game Currency Exchange panel - check current rates before trading."
    )
    print("=" * 60)
    print(title)
    print(body)
    print("=" * 60)

    log_alert(cfg, alert)
    _send_ntfy(cfg, title, body)
    _send_discord(cfg, f"**{title}**\n```\n{body}\n```")
