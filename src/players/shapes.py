"""Bounded, non-overlapping hand decompositions, including flower occupancy."""
from collections import Counter
from functools import lru_cache

from ..core.tiles import PLAYABLE_TILES, parse_tile, tile_sort_key


@lru_cache(maxsize=4096)
def _partitions(counts):
    if not any(counts):
        return ((),), False
    i = next(i for i,n in enumerate(counts) if n)
    options = [("single", (i,))]
    if counts[i] >= 2:
        options.append(("pair", (i,i)))
    if counts[i] >= 3:
        options.append(("triplet", (i,i,i)))
    if i < 27:
        for gap in (1,2):
            if i//9 == (i+gap)//9 and counts[i+gap]:
                options.append(("taatsu", (i,i+gap)))
        if i % 9 <= 6 and counts[i+1] and counts[i+2]:
            options.append(("sequence", (i,i+1,i+2)))
    result, truncated = [], False
    for kind, indices in options:
        rest = list(counts)
        for j in indices:
            rest[j] -= 1
        tail, limited = _partitions(tuple(rest))
        truncated |= limited
        result.extend(((kind, indices),)+p for p in tail)
    def rank(parts):
        return (-sum(k in ("sequence","triplet") for k,_ in parts),
                -sum(k in ("pair","taatsu") for k,_ in parts),
                sum(k == "single" for k,_ in parts), parts)
    result = sorted(set(result), key=rank)
    if len(result) > 64:
        result, truncated = result[:64], True
    return tuple(result), truncated


def describe_hand(hand, meld_count=0, *, alternatives=3):
    hand = [parse_tile(t) if isinstance(t,str) else t for t in hand]
    counts = Counter(hand)
    parts, truncated = _partitions(tuple(counts[t] for t in PLAYABLE_TILES))
    isolated = []
    for t,n in counts.items():
        if t.is_flower or n != 1:
            continue
        if t.suit in ("万","饼","条") and any(
                u.suit == t.suit and u != t and abs(int(u.value)-int(t.value)) <= 2 for u in counts):
            continue
        isolated.append(str(t))
    return {"groups_still_needed": 4-meld_count,
        "held_flowers": [str(t) for t in sorted(hand,key=tile_sort_key) if t.is_flower],
        "isolated_playable": sorted(isolated),
        "decompositions": [[{"kind": kind, "tiles": [str(PLAYABLE_TILES[i]) for i in indices]}
                             for kind,indices in p] for p in parts[:alternatives]],
        "seven_pairs_pair_slots": sum(n//2 for t,n in counts.items() if not t.is_flower),
        "seven_pairs_available": meld_count == 0,
        "truncated": truncated or len(parts) > alternatives,
        "scope": "每个分解内部不复用牌；不同分解是替代方案。仅展示有限分解，不是最优打法；花占位但不入结构。"}
