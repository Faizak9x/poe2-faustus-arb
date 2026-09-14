"""Build the exchange-rate graph and find negative-weight (= arbitrage) cycles.

Rate direction, derived directly from the API's own field names (verified
against a live pull of the endpoint):

    market_pair: [A, B]
    lowest_ratio:  {A: a1, B: b1}   # the ratio at the cheapest trade this hour
    highest_ratio: {A: a2, B: b2}   # the ratio at the priciest trade this hour

Both dicts describe the SAME equivalence ("a1 units of A were traded for b1
units of B") just keyed by currency id, so the direction is unambiguous and
doesn't depend on which currency GGG happened to list first in market_pair:

    rate(X -> Y) using one snapshot = ratio[Y] / ratio[X]   (units of Y per 1 X)

Because a single hourly digest gives a RANGE (lowest/highest), not one fixed
rate, we always take the *worse* of the two snapshot-implied rates for a
given direction. This is deliberately conservative: it approximates the
real bid/ask-style spread you'd actually face using Faustus, on top of
which the caller still applies a minimum-profit threshold.

Triangular arbitrage = a negative-weight cycle in the graph where each edge
weight is -log(rate). Found via Bellman-Ford (with an implicit zero-weight
virtual source connected to every node), which handles cycles of any length
(not just length 3) despite the project's shorthand name "triangular
arbitrage".
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

EPS = 1e-9


@dataclass
class Edge:
    u: str
    v: str
    weight: float  # -log(rate)
    rate: float  # units of v received per 1 unit of u
    volume_u: float
    volume_v: float


@dataclass
class Cycle:
    nodes: Tuple[str, ...]  # trade order, NOT repeating the closing node
    profit_pct: float
    min_volume: float


def _conservative_rate(lowest_ratio: dict, highest_ratio: dict, x: str, y: str) -> Optional[float]:
    try:
        lx, ly = lowest_ratio[x], lowest_ratio[y]
        hx, hy = highest_ratio[x], highest_ratio[y]
    except KeyError:
        return None
    if lx <= 0 or hx <= 0 or ly <= 0 or hy <= 0:
        return None
    rate_from_low = ly / lx
    rate_from_high = hy / hx
    return min(rate_from_low, rate_from_high)


def compute_volume_floor(markets: List[dict], abs_floor: float, percentile: float) -> float:
    """A fixed absolute MIN_VOLUME doesn't generalize: a "busy" pair in a
    quiet league/hour and a "busy" pair in a booming one are very different
    in scale. Verified on live data - a flat floor of 20 left obvious false
    "arbitrage" (1000%+ profit from 1-2 real trades) uncaught on a
    high-activity league where most real pairs trade in the thousands.

    Instead, the floor scales to THIS hour's own activity: take the
    per-market volume (the smaller of its two sides - the binding
    constraint) and require the `percentile`-th percentile of that
    distribution, floored by `abs_floor` so a very quiet hour still filters
    out truly dead pairs.
    """
    pair_volumes = []
    for m in markets:
        vt = m.get("volume_traded") or {}
        if len(vt) >= 2:
            pair_volumes.append(min(vt.values()))
    if not pair_volumes:
        return abs_floor
    pair_volumes.sort()
    idx = min(int(len(pair_volumes) * percentile), len(pair_volumes) - 1)
    return max(abs_floor, pair_volumes[idx])


def build_edges(markets: List[dict], min_volume: float) -> List[Edge]:
    edges: List[Edge] = []
    for m in markets:
        pair = m.get("market_pair") or []
        if len(pair) != 2:
            continue
        a, b = pair
        volume_traded = m.get("volume_traded", {})
        vol_a = volume_traded.get(a, 0)
        vol_b = volume_traded.get(b, 0)
        if vol_a < min_volume or vol_b < min_volume:
            continue

        lowest_ratio = m.get("lowest_ratio", {})
        highest_ratio = m.get("highest_ratio", {})

        rate_ab = _conservative_rate(lowest_ratio, highest_ratio, a, b)
        rate_ba = _conservative_rate(lowest_ratio, highest_ratio, b, a)

        if rate_ab and rate_ab > 0:
            edges.append(Edge(a, b, -math.log(rate_ab), rate_ab, vol_a, vol_b))
        if rate_ba and rate_ba > 0:
            edges.append(Edge(b, a, -math.log(rate_ba), rate_ba, vol_b, vol_a))
    return edges


def _bellman_ford_find_cycle(nodes: List[str], edges: List[Edge]) -> Optional[List[str]]:
    dist: Dict[str, float] = {n: 0.0 for n in nodes}
    pred: Dict[str, Optional[str]] = {n: None for n in nodes}

    x: Optional[str] = None
    for _ in range(len(nodes)):
        x = None
        for e in edges:
            if dist[e.u] + e.weight < dist[e.v] - EPS:
                dist[e.v] = dist[e.u] + e.weight
                pred[e.v] = e.u
                x = e.v
        if x is None:
            return None  # no negative cycle

    # x is guaranteed reachable from within a negative cycle now; walk back
    # len(nodes) more times to land ON the cycle itself.
    for _ in range(len(nodes)):
        x = pred[x]

    cycle = [x]
    y = pred[x]
    while y != x:
        cycle.append(y)
        y = pred[y]
    cycle.append(x)
    cycle.reverse()
    return cycle


def _edge_lookup(edges: List[Edge]) -> Dict[Tuple[str, str], Edge]:
    lookup: Dict[Tuple[str, str], Edge] = {}
    for e in edges:
        # keep the more favorable (less positive weight) parallel edge, if duplicates exist
        key = (e.u, e.v)
        if key not in lookup or e.weight < lookup[key].weight:
            lookup[key] = e
    return lookup


def _cycle_profit_pct(cycle_nodes: List[str], lookup: Dict[Tuple[str, str], Edge]) -> Tuple[float, float]:
    """Returns (profit_pct, min_volume_along_cycle). cycle_nodes repeats the closing node."""
    log_sum = 0.0
    min_vol = math.inf
    for i in range(len(cycle_nodes) - 1):
        e = lookup[(cycle_nodes[i], cycle_nodes[i + 1])]
        log_sum += -e.weight  # = log(rate)
        min_vol = min(min_vol, e.volume_u, e.volume_v)
    multiplier = math.exp(log_sum)
    return (multiplier - 1.0) * 100.0, min_vol


def normalize_cycle(nodes: Tuple[str, ...]) -> Tuple[str, ...]:
    """Rotate (not reverse - direction matters) so comparisons/dedup are stable."""
    if not nodes:
        return nodes
    min_i = min(range(len(nodes)), key=lambda i: nodes[i])
    return tuple(nodes[min_i:] + nodes[:min_i])


def find_arbitrage_cycles(
    markets: List[dict],
    min_volume: float,
    min_profit_pct: float,
    max_cycles: int,
) -> List[Cycle]:
    edges = build_edges(markets, min_volume)
    if not edges:
        return []

    nodes = sorted({e.u for e in edges} | {e.v for e in edges})
    working_edges = list(edges)
    found: Dict[Tuple[str, ...], Cycle] = {}

    for _ in range(max_cycles):
        cycle_path = _bellman_ford_find_cycle(nodes, working_edges)
        if cycle_path is None:
            break

        lookup = _edge_lookup(working_edges)
        profit_pct, min_vol = _cycle_profit_pct(cycle_path, lookup)
        cycle_nodes = tuple(cycle_path[:-1])
        norm = normalize_cycle(cycle_nodes)

        if profit_pct >= min_profit_pct and norm not in found:
            found[norm] = Cycle(nodes=norm, profit_pct=profit_pct, min_volume=min_vol)

        # Remove this cycle's edges so the next Bellman-Ford pass can surface
        # a different negative cycle instead of re-finding the same one.
        cycle_edge_keys = {
            (cycle_path[i], cycle_path[i + 1]) for i in range(len(cycle_path) - 1)
        }
        working_edges = [e for e in working_edges if (e.u, e.v) not in cycle_edge_keys]
        if not working_edges:
            break

    return sorted(found.values(), key=lambda c: c.profit_pct, reverse=True)

