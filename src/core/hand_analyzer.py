"""Hand analysis: shanten, ukeire, waiting tiles, discard ranking.

Two winning forms are supported, and the overall shanten is their minimum:
  1. Standard form: 4 melds (sequence or triplet) + 1 pair.
  2. Seven pairs (chiitoitsu): 7 distinct pairs, concealed only.

Flower tiles (东风 / 中发白 / 季节) are excluded from the structure.
Shanten convention: a complete winning hand is -1, tenpai (waiting) is 0.
"""
from collections import Counter
from typing import List, Tuple

from .tiles import PLAYABLE_TILES, Tile, tile_index

# Playable index layout (length-30 counts array):
#   0-8   万 1-9     9-17  饼 1-9     18-26  条 1-9     27-29  南/西/北
# Segments for per-suit decomposition: (start, end, allow_shuntsu).
_SEGMENTS = [(0, 9, True), (9, 18, True), (18, 27, True), (27, 30, False)]


def _hand_to_counts(hand: List[Tile]) -> List[int]:
    """Pack a hand into a length-30 counts array, dropping flower tiles."""
    counts = [0] * 30
    for t in hand:
        if t.is_flower:
            continue
        counts[tile_index(t)] += 1
    return counts


# --- Standard-form shanten via decomposition counting ----------------------
def _decompose_suit(seg, allow_shuntsu):
    """Enumerate this suit's decompositions; return Pareto (sets, taatsu, toitsu).

    sets   = complete melds (triplet or sequence)
    taatsu = 2-tile partials toward a meld (two-sided / edge / middle-gap)
    toitsu = pairs (can serve as the head or toward a triplet)
    """
    counts = list(seg)
    results = []
    _recurse_suit(counts, 0, 0, 0, 0, allow_shuntsu, results)
    return _pareto(results)


def _recurse_suit(c, i, sets, taatsu, toitsu, allow_shuntsu, results):
    while i < len(c) and c[i] == 0:
        i += 1
    if i >= len(c):
        results.append((sets, taatsu, toitsu))
        return

    # Triplet (刻子)
    if c[i] >= 3:
        c[i] -= 3
        _recurse_suit(c, i, sets + 1, taatsu, toitsu, allow_shuntsu, results)
        c[i] += 3
    # Sequence (顺子)
    if allow_shuntsu and i + 2 < len(c) and c[i + 1] >= 1 and c[i + 2] >= 1:
        c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
        _recurse_suit(c, i, sets + 1, taatsu, toitsu, allow_shuntsu, results)
        c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
    # Pair (对子)
    if c[i] >= 2:
        c[i] -= 2
        _recurse_suit(c, i, sets, taatsu, toitsu + 1, allow_shuntsu, results)
        c[i] += 2
    # Two-sided / edge partial (i, i+1)
    if allow_shuntsu and i + 1 < len(c) and c[i + 1] >= 1:
        c[i] -= 1; c[i + 1] -= 1
        _recurse_suit(c, i, sets, taatsu + 1, toitsu, allow_shuntsu, results)
        c[i] += 1; c[i + 1] += 1
    # Middle-gap partial (i, i+2)
    if allow_shuntsu and i + 2 < len(c) and c[i + 2] >= 1:
        c[i] -= 1; c[i + 2] -= 1
        _recurse_suit(c, i, sets, taatsu + 1, toitsu, allow_shuntsu, results)
        c[i] += 1; c[i + 2] += 1
    # Isolated tile (孤张): leave one and continue
    c[i] -= 1
    _recurse_suit(c, i, sets, taatsu, toitsu, allow_shuntsu, results)
    c[i] += 1


def _pareto(states):
    """Keep states not dominated by any other (more sets/taatsu/toitsu is better)."""
    uniq = set(states)
    kept = []
    for s in uniq:
        dominated = False
        for o in uniq:
            if o is s:
                continue
            if o[0] >= s[0] and o[1] >= s[1] and o[2] >= s[2] and o != s:
                dominated = True
                break
        if not dominated:
            kept.append(s)
    return kept


def _combine(front_lists):
    """Sum per-suit Pareto fronts, pruning the combined front at each step."""
    combined = [(0, 0, 0)]
    for front in front_lists:
        merged = [
            (a[0] + b[0], a[1] + b[1], a[2] + b[2])
            for a in combined
            for b in front
        ]
        combined = _pareto(merged)
    return combined


def _standard_shanten(counts, fuuro=0) -> int:
    fronts = [_decompose_suit(counts[s:e], shuntsu) for s, e, shuntsu in _SEGMENTS]
    best = 8 - 2 * fuuro   # each called meld is a complete mentsu already
    mentsu_needed = 4 - fuuro
    for sets, taatsu, toitsu in _combine(fronts):
        head_bonus = 1 if toitsu >= 1 else 0
        partial_slots = taatsu + max(0, toitsu - 1)  # reserve one pair as head
        usable = max(0, min(partial_slots, mentsu_needed - sets))
        shanten = 8 - 2 * fuuro - 2 * sets - usable - head_bonus
        if shanten < best:
            best = shanten
    return best


def _chiitoitsu_shanten(counts) -> int:
    pairs = sum(1 for c in counts if c >= 2)   # distinct pair types
    kinds = sum(1 for c in counts if c >= 1)   # distinct tile types
    return 6 - pairs + max(0, 7 - kinds)


# --- Public API ------------------------------------------------------------
def calculate_shanten(hand: List[Tile], fuuro: int = 0) -> int:
    """Minimum shanten over both winning forms (lower is closer to winning)."""
    counts = _hand_to_counts(hand)
    best = _standard_shanten(counts, fuuro)
    if fuuro == 0:  # seven pairs is only possible fully concealed
        best = min(best, _chiitoitsu_shanten(counts))
    return best


def is_agari(hand: List[Tile], fuuro: int = 0) -> bool:
    """True if the hand is a complete winning hand (shanten -1)."""
    return calculate_shanten(hand, fuuro) == -1


def is_tenpai(hand: List[Tile], fuuro: int = 0) -> bool:
    """True if the hand is waiting (shanten 0)."""
    return calculate_shanten(hand, fuuro) == 0


def get_ukeire(hand: List[Tile], fuuro: int = 0) -> List[Tile]:
    """Playable tile types that advance the hand by one step (reduce shanten by 1)."""
    base = calculate_shanten(hand, fuuro)
    return [
        t for t in PLAYABLE_TILES
        if calculate_shanten(hand + [t], fuuro) == base - 1
    ]


def get_waiting_tiles(hand: List[Tile], fuuro: int = 0) -> List[Tile]:
    """Winning tiles for a tenpai hand (empty if not tenpai)."""
    if not is_tenpai(hand, fuuro):
        return []
    return [
        t for t in PLAYABLE_TILES
        if calculate_shanten(hand + [t], fuuro) == -1
    ]


def rank_discards(hand: List[Tile], fuuro: int = 0) -> List[Tuple[Tile, int]]:
    """Rank each distinct playable tile by the shanten after discarding it.

    Returns (tile, resulting_shanten) sorted by shanten ascending (best first).
    """
    present = Counter(t for t in hand if not t.is_flower)
    ranked = []
    for tile in present:
        remaining = list(hand)
        remaining.remove(tile)
        ranked.append((tile, calculate_shanten(remaining, fuuro)))
    ranked.sort(key=lambda x: (x[1], str(x[0])))
    return ranked
