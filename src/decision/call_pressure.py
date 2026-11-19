"""Counterfactual structural acceleration from feeding public calls.

Compare pass-standing with claim+best-discard on the SAME sampled hand.
No assumption that the opponent actually calls; no conversion to score EV.
"""
from functools import lru_cache

from ..core.hand_analyzer import calculate_shanten, can_chi
from ..core.tiles import tile_sort_key


@lru_cache(maxsize=32768)
def _after_call_shanten(hand, groups, needed):
    remaining = list(hand)
    for tile in needed:
        remaining.remove(tile)
    return min(calculate_shanten(remaining[:i]+remaining[i+1:], groups+1)
               for i, tile in enumerate(remaining)
               if i == 0 or tile != remaining[i-1])


def advances_on_claim(hand, groups, tile, *, allow_chi):
    if groups >= 4 or len(hand) != 13 - 3*groups:
        return False
    needed = list(can_chi(hand, tile)) if allow_chi else []
    if hand.count(tile) >= 2:
        needed.append([tile, tile])
    if not needed:
        return False
    packed = tuple(sorted(hand, key=tile_sort_key))
    baseline = calculate_shanten(hand, groups)
    return any(_after_call_shanten(packed, groups, tuple(pair)) < baseline
               for pair in needed)
