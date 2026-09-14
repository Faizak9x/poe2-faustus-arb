"""Client for GGG's public Currency Exchange history endpoint.

Endpoint (confirmed public, no OAuth app/registration required as of the
Forbidden Rites league - see README "Data access" section for how this was
verified against https://www.pathofexile.com/developer/docs):

    GET https://web.poecdn.com/api/currency-exchange[/<realm>][/<id>]

- Data is hourly aggregate digests across all leagues. There is no way to
  get the still-open current hour; you can only fetch already-closed hours.
- `id` is a unix timestamp truncated to the hour. Omitting it starts from
  the very first hour of recorded history (not useful for us).
- The response's `next_change_id` is the id to pass in on your NEXT call to
  get the following hour. If `next_change_id` comes back equal to the `id`
  you requested, that hour hasn't closed/aggregated yet - wait and retry
  later (this is expected, not an error).

GGG's docs require every request - including this public one - to send an
identifying User-Agent: "OAuth {clientId}/{version} (contact: {contact})".
No real OAuth client registration is needed to use this public endpoint,
but we still follow the required header format in good faith.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

from .config import Config

BASE_URL = "https://web.poecdn.com/api/currency-exchange"


class GGGApiError(RuntimeError):
    pass


@dataclass
class Digest:
    requested_id: Optional[int]
    next_change_id: int
    markets: list


def _user_agent(cfg: Config) -> str:
    return f"OAuth {cfg.app_name}/{cfg.app_version} (contact: {cfg.contact_email})"


def current_hour_start(now: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    epoch = int(now)
    return epoch - (epoch % 3600)


def bootstrap_id(now: Optional[float] = None) -> int:
    """Pick a starting id for a first-ever run: the most recently closed hour."""
    return current_hour_start(now) - 3600


def fetch_digest(cfg: Config, fetch_id: Optional[int], session: Optional[requests.Session] = None) -> Digest:
    sess = session or requests.Session()
    url = f"{BASE_URL}/{cfg.realm}"
    if fetch_id is not None:
        url = f"{url}/{fetch_id}"

    headers = {
        "User-Agent": _user_agent(cfg),
        "Accept": "application/json",
    }

    attempts = 0
    while True:
        attempts += 1
        resp = sess.get(url, headers=headers, timeout=cfg.request_timeout)

        if resp.status_code == 429 or resp.status_code == 503:
            retry_after = resp.headers.get("Retry-After")
            wait_s = float(retry_after) if retry_after else min(30, 2 ** attempts)
            if attempts >= 4:
                raise GGGApiError(
                    f"Rate limited / unavailable after {attempts} attempts "
                    f"(status {resp.status_code})."
                )
            time.sleep(wait_s)
            continue

        if resp.status_code != 200:
            raise GGGApiError(
                f"Unexpected status {resp.status_code} from {url}: {resp.text[:300]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise GGGApiError(f"Non-JSON response from {url}: {exc}") from exc

        if "next_change_id" not in data or "markets" not in data:
            raise GGGApiError(f"Unexpected response shape from {url}: keys={list(data.keys())}")

        return Digest(
            requested_id=fetch_id,
            next_change_id=int(data["next_change_id"]),
            markets=data["markets"],
        )

