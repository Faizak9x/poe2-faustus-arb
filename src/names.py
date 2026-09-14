"""Best-effort human-readable names for GGG's internal currency item ids.

GGG's Currency Exchange API only ever gives us internal metadata paths like
"Metadata/Items/Currency/CurrencyModValues" - it does not include the
in-game display name ("Exalted Orb", "Chaos Orb", etc). There is no public,
always-current mapping for this, and it changes as new currency items are
added each league, so we deliberately do NOT ship a hardcoded id->name
table that pretends to be authoritative (a wrong guess in a tool used for
real trades is worse than an honest raw id).

Instead:
  1. We auto-"humanize" the raw id into something readable (strip the
     "Metadata/Items/Currency/Currency" prefix, split CamelCase).
  2. You can override any of these by adding entries to currency_names.json
     in the project root (raw_id -> display name). Run discover_currencies.py
     to print the raw ids actually trading right now, so you can identify
     them in-game and add the ones you care about.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES_PATH = ROOT / "currency_names.json"

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _load_overrides() -> Dict[str, str]:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


_OVERRIDES = _load_overrides()


def humanize(raw_id: str) -> str:
    if raw_id in _OVERRIDES:
        return _OVERRIDES[raw_id]

    base = raw_id.rsplit("/", 1)[-1]
    if base.startswith("Currency"):
        base = base[len("Currency"):]
    spaced = _CAMEL_RE.sub(" ", base).strip()
    return spaced or raw_id


def format_cycle(cycle_ids) -> str:
    """cycle_ids: node ids WITHOUT the repeated closing node, in trade order."""
    names = [humanize(c) for c in cycle_ids]
    names.append(names[0])
    return " → ".join(names)
