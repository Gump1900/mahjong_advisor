"""Physical-count constrained v4 prior. No access to referee state or replay.

Unrevealed hands include retained flowers. Unknown ankans consume four identical
copies, never a type held/seen by us. This uniform prior is NOT a learned posterior.
"""
from collections import Counter
from dataclasses import dataclass

from ..core.tiles import Meld, parse_tile
from .state import full_deck


@dataclass
class SampledWorld:
    hands: dict
    melds: dict
    wall: list


def unseen_counts(obs):
    counts = Counter(full_deck())
    known = Counter(parse_tile(t) for t in obs["self"]["hand"])
    for p in obs["players"]:
        known.update(parse_tile(t) for t in p["river"]+p["flowers"])
        for m in p["melds"]:
            if m["tiles"] is not None:
                known.update(parse_tile(t) for t in m["tiles"])
    if known-counts:
        raise ValueError("已见牌超过物理副本上限")
    counts.subtract(known)
    return +counts


def sample_world(obs, rng):
    pool = unseen_counts(obs)
    me = obs["seat"]
    melds = {p["seat"]: [None]*len(p["melds"]) for p in obs["players"]}
    hidden = []
    for p in obs["players"]:
        for index,m in enumerate(p["melds"]):
            if m["tiles"] is None:
                if m["type"] != "an_gang" or m["size"] != 4 or p["seat"] == me:
                    raise ValueError("未知成组必须是对手四张暗杠")
                hidden.append((p["seat"], index))
            else:
                melds[p["seat"]][index] = Meld(m["type"], [parse_tile(t) for t in m["tiles"]])
    rng.shuffle(hidden)
    for seat,index in hidden:
        types = [t for t,n in pool.items() if n == 4]
        if not types:
            raise ValueError("已见信息无法容纳未知暗杠")
        tile = rng.choice(types)
        pool[tile] -= 4
        melds[seat][index] = Meld("an_gang", [tile]*4)
    tiles = list(pool.elements())
    opponents = [p for p in obs["players"] if p["seat"] != me]
    expected = sum(p["hand_count"] for p in opponents)+obs["wall_count"]
    if len(tiles) != expected:
        raise ValueError("手牌、明牌与牌墙张数不守恒，拒绝采样")
    rng.shuffle(tiles)
    rng.shuffle(opponents)
    hands = {me: [parse_tile(t) for t in obs["self"]["hand"]]}
    for p in opponents:
        size = p["hand_count"]
        hands[p["seat"]], tiles = tiles[:size], tiles[size:]
    return SampledWorld(hands, melds, tiles)
