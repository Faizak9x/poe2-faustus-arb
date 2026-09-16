"""Entry point: one run = one hourly poll + arbitrage check.

Usage:
    python -m src.main

Intended to be run once per hour (locally via Task Scheduler/cron, or via
the included GitHub Actions workflow). Safe to run more often than hourly -
it will just report "no new data yet" until GGG closes the next hour.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from . import graph, names, notify, price_cycles, state as state_mod
from .config import load_config
from .ggg_client import GGGApiError, bootstrap_id, fetch_digest


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour_label(change_id: int) -> str:
    return datetime.fromtimestamp(change_id, tz=timezone.utc).strftime("%Y-%m-%d %H:00 UTC")


def _matching_league(markets, league_name: str):
    league_lower = league_name.lower().strip()
    matched = [m for m in markets if league_lower in (m.get("league") or "").lower()]
    if matched:
        return matched, None
    seen_leagues = sorted({m.get("league") for m in markets if m.get("league")})
    return [], seen_leagues


def run() -> int:
    cfg = load_config()
    st = state_mod.State.load(cfg.state_dir / "history.json")
    price_store = price_cycles.load(cfg.state_dir / "price_cycles.json")

    fetch_id = st.next_fetch_id if st.next_fetch_id is not None else bootstrap_id()

    print(f"[{_iso_now()}] Fetching Currency Exchange digest for id={fetch_id} "
          f"({_hour_label(fetch_id)}), realm={cfg.realm} ...")

    try:
        digest = fetch_digest(cfg, fetch_id)
    except GGGApiError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if digest.next_change_id == fetch_id:
        print(f"[{_iso_now()}] Hour {_hour_label(fetch_id)} hasn't closed/aggregated yet. "
              "Nothing to do - try again after the next hourly boundary.")
        return 0

    all_markets = digest.markets
    matched, seen_leagues = _matching_league(all_markets, cfg.league_name)

    if not all_markets:
        print(f"[{_iso_now()}] Hour {_hour_label(fetch_id)} closed with zero trades recorded "
              "across all leagues (unusual, but not an error).")
    elif seen_leagues is not None:
        print(f"[warn] No markets matched LEAGUE_NAME={cfg.league_name!r} for "
              f"{_hour_label(fetch_id)}. Leagues seen this hour: {seen_leagues}")

    hour_of_day = datetime.fromtimestamp(fetch_id, tz=timezone.utc).hour
    price_cycles.update(price_store, matched, hour_of_day, _hour_label(fetch_id))

    volume_floor = graph.compute_volume_floor(
        matched, cfg.min_volume_abs_floor, cfg.min_volume_percentile
    )
    cycles = graph.find_arbitrage_cycles(
        matched,
        min_volume=volume_floor,
        min_profit_pct=cfg.min_profit_pct,
        max_cycles=cfg.max_cycles_per_run,
    )

    print(f"[{_iso_now()}] {_hour_label(fetch_id)}: {len(matched)} market pairs seen, "
          f"volume floor this hour = {volume_floor:.0f} units "
          f"(p{cfg.min_volume_percentile*100:.0f} of this hour's activity), "
          f"{len(cycles)} candidate cycle(s) at/above {cfg.min_profit_pct}% profit.")

    # --- persistence tracking across consecutive hours ---
    current_keys = set()
    to_alert = []

    for c in cycles:
        key = state_mod.cycle_key(c.nodes)
        current_keys.add(key)
        prev = st.streaks.get(key)

        if prev and prev.last_change_id == fetch_id - 3600:
            count = prev.count + 1
            alerted = prev.alerted
        else:
            count = 1
            alerted = False

        st.streaks[key] = state_mod.Streak(
            count=count,
            last_change_id=fetch_id,
            last_profit_pct=c.profit_pct,
            alerted=alerted,
            last_hops=[
                {
                    "from": h.from_id,
                    "to": h.to_id,
                    "rate": h.rate,
                    "volume_from": h.volume_from,
                    "volume_to": h.volume_to,
                }
                for h in c.hops
            ],
        )

        if count >= cfg.persistence_hours and not alerted:
            st.streaks[key].alerted = True
            to_alert.append(c)

    # drop streaks for cycles that didn't show up this hour (a gap resets persistence)
    for key in list(st.streaks.keys()):
        if key not in current_keys:
            del st.streaks[key]

    for c in to_alert:
        notify.send_alert(cfg, {
            "cycle_display": names.format_cycle(c.nodes),
            "cycle_ids": list(c.nodes),
            "profit_pct": c.profit_pct,
            "min_volume": c.min_volume,
            "persistence_hours": cfg.persistence_hours,
            "league": cfg.league_name,
            "timestamp": _iso_now(),
            "hour": _hour_label(fetch_id),
            "hops": [
                {
                    "from": h.from_id,
                    "to": h.to_id,
                    "rate": h.rate,
                    "volume_from": h.volume_from,
                    "volume_to": h.volume_to,
                }
                for h in c.hops
            ],
        })

    if cycles and not to_alert:
        print(f"[{_iso_now()}] {len(cycles)} candidate(s) found but none have yet persisted "
              f"{cfg.persistence_hours} consecutive hours - not alerting yet.")

    # --- persist history ---
    st.history.append({
        "change_id": fetch_id,
        "hour": _hour_label(fetch_id),
        "fetched_at": _iso_now(),
        "league": cfg.league_name,
        "market_count": len(matched),
        "volume_floor": round(volume_floor, 2),
        "candidates": [
            {
                "cycle": list(c.nodes),
                "profit_pct": round(c.profit_pct, 4),
                "hops": [
                    {
                        "from": h.from_id,
                        "to": h.to_id,
                        "rate": h.rate,
                        "volume_from": h.volume_from,
                        "volume_to": h.volume_to,
                    }
                    for h in c.hops
                ],
            }
            for c in cycles
        ],
    })
    st.history = st.history[-cfg.history_keep:]
    st.next_fetch_id = digest.next_change_id
    st.save(cfg.state_dir / "history.json")
    price_cycles.save(price_store, cfg.state_dir / "price_cycles.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
