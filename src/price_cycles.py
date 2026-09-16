"""Long-running per-currency, per-hour-of-day price tracking.

Builds a cheap/expensive-hour profile for every currency that trades
directly against Chaos Orb or Divine Orb, without ever growing unbounded:
each currency keeps a running average per UTC hour-of-day bucket (an
incremental mean, not a raw log) plus its all-time observed high/low, so
this file stays a small, constant size no matter how many hours the tool
has been running.

This is purely informational for the dashboard - arbitrage detection in
graph.py does not read or depend on this data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

CHAOS_ID = "Metadata/Items/Currency/CurrencyRerollRare"
DIVINE_ID = "Metadata/Items/Currency/CurrencyModValues"
ANCHORS = {"chaos": CHAOS_ID, "divine": DIVINE_ID}


def _typical_rate(lowest_ratio: dict, highest_ratio: dict, x: str, y: str) -> Optional[float]:
    """Average of the two snapshot-implied rates for x -> y (units of y per 1 x).

    Unlike graph.py's _conservative_rate (deliberately worst-case, for
    arbitrage safety margins), this is a plain typical-price estimate for
    tracking, not a trade-safety bound.
    """
    try:
        lx, ly = lowest_ratio[x], lowest_ratio[y]
        hx, hy = highest_ratio[x], highest_ratio[y]
    except KeyError:
        return None
    if lx <= 0 or hx <= 0 or ly <= 0 or hy <= 0:
        return None
    return ((ly / lx) + (hy / hx)) / 2.0


def _empty_currency_entry() -> dict:
    return {
        anchor: {
            "buckets": [{"count": 0, "mean": 0.0} for _ in range(24)],
            "all_time_high": None,
            "all_time_low": None,
            "last_price": None,
            "last_hour": None,
        }
        for anchor in ANCHORS
    }


def load(path: Path) -> dict:
    if not path.exists():
        return {"currencies": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"currencies": {}}
    if "currencies" not in data:
        return {"currencies": {}}
    return data


def save(store: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    tmp.replace(path)


def _record(entry: dict, price: float, hour_of_day: int, hour_label: str) -> None:
    bucket = entry["buckets"][hour_of_day]
    bucket["count"] += 1
    bucket["mean"] += (price - bucket["mean"]) / bucket["count"]

    if entry["all_time_high"] is None or price > entry["all_time_high"]["value"]:
        entry["all_time_high"] = {"value": price, "hour": hour_label}
    if entry["all_time_low"] is None or price < entry["all_time_low"]["value"]:
        entry["all_time_low"] = {"value": price, "hour": hour_label}

    entry["last_price"] = price
    entry["last_hour"] = hour_label


def update(store: dict, markets: List[dict], hour_of_day: int, hour_label: str) -> dict:
    currencies = store.setdefault("currencies", {})

    for m in markets:
        pair = m.get("market_pair") or []
        if len(pair) != 2:
            continue
        a, b = pair
        lowest_ratio = m.get("lowest_ratio", {})
        highest_ratio = m.get("highest_ratio", {})

        for anchor_name, anchor_id in ANCHORS.items():
            if a == anchor_id and b != anchor_id:
                other = b
            elif b == anchor_id and a != anchor_id:
                other = a
            else:
                continue

            price = _typical_rate(lowest_ratio, highest_ratio, other, anchor_id)
            if price is None or price <= 0:
                continue

            entry = currencies.setdefault(other, _empty_currency_entry())
            _record(entry[anchor_name], price, hour_of_day, hour_label)

    return store

