"""Small JSON-file state store.

Kept deliberately simple (no database) since this runs once an hour. When
run in GitHub Actions, the workflow commits this file back to the repo after
each run so state survives between ephemeral runner instances.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Streak:
    count: int
    last_change_id: int
    last_profit_pct: float
    alerted: bool = False
    last_hops: list = field(default_factory=list)


@dataclass
class State:
    next_fetch_id: Optional[int] = None
    history: List[dict] = field(default_factory=list)
    streaks: Dict[str, Streak] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> "State":
        if not path.exists():
            return State()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return State()
        streaks = {
            k: Streak(**v) for k, v in raw.get("streaks", {}).items()
        }
        return State(
            next_fetch_id=raw.get("next_fetch_id"),
            history=raw.get("history", []),
            streaks=streaks,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "next_fetch_id": self.next_fetch_id,
            "history": self.history,
            "streaks": {k: vars(v) for k, v in self.streaks.items()},
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)


def cycle_key(nodes) -> str:
    return "|".join(nodes)
