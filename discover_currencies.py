"""Helper: print the raw currency ids actually trading right now, sorted by
volume, so you can identify them in-game and add friendly names to
currency_names.json (see src/names.py for how that file is used).

Usage:
    python discover_currencies.py [league_name]

If league_name is omitted, uses LEAGUE_NAME from your .env / environment.
"""
from __future__ import annotations

import sys
from collections import defaultdict

from src.config import load_config
from src.ggg_client import bootstrap_id, fetch_digest
from src.names import humanize


def main() -> int:
    cfg = load_config()
    league_name = sys.argv[1] if len(sys.argv) > 1 else cfg.league_name

    digest = fetch_digest(cfg, bootstrap_id())
    matched = [m for m in digest.markets if league_name.lower() in (m.get("league") or "").lower()]

    if not matched:
        leagues = sorted({m.get("league") for m in digest.markets if m.get("league")})
        print(f"No markets matched league {league_name!r}. Leagues seen: {leagues}")
        return 1

    volume_by_id = defaultdict(int)
    for m in matched:
        for cid, vol in (m.get("volume_traded") or {}).items():
            volume_by_id[cid] += vol

    print(f"{'raw id':70} {'auto-guess name':25} volume")
    print("-" * 105)
    for cid, vol in sorted(volume_by_id.items(), key=lambda kv: kv[1], reverse=True):
        print(f"{cid:70} {humanize(cid):25} {vol}")

    print(
        "\nTo override any of these display names, create currency_names.json "
        "in the project root, e.g.:\n"
        '  { "Metadata/Items/Currency/CurrencyModValues": "Exalted Orb" }\n'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
