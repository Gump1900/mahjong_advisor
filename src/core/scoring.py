"""花数 scoring.

IMPORTANT — the rules implemented here are exactly what the design doc
specifies plus one agreed default:

  - 4 个暗刻（全门清对对胡）      = 10 花
  - 4 个明刻（全副露对对胡）      = 5 花
  - 杠开                        = 8 花
  - 每张花牌（手里 + 已杠）       = 1 花   (agreed default, calibrate me)

The rest of this variant's 花数 table (对对胡/清一色/字一色/七对…, 底花,
倍数) is NOT specified yet — extend PATTERN_TABLE below as the rules get
confirmed. Hands matching none of the listed patterns score their flowers
only.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .tiles import Meld, Tile, create_tile

VALID_WIN_METHODS = ("zimo", "dianpao", "gangkai")

# (pattern name, 花) — extension point: add the variant's full table here.
PATTERN_TABLE: List[Tuple[str, int]] = [
    # ("清一色", ?), ("字一色", ?), ("七对", ?), ...  TODO: fill in
]


@dataclass
class ScoringResult:
    hua: int                                   # total 花
    flowers: int = 0                           # 花 contribution from flower tiles
    breakdown: List[str] = field(default_factory=list)   # human-readable parts


def _four_concealed_triplets(hand: List[Tile], melds: List[Meld]) -> bool:
    """4 暗刻 + 1 对, fully concealed (design doc: 10 花)."""
    if melds:
        return False
    counts: Dict[Tile, int] = {}
    for t in hand:
        if not t.is_flower:
            counts[t] = counts.get(t, 0) + 1
    if len(hand) != 14 or set(counts.values()) != {3, 2}:
        return False
    return list(counts.values()).count(3) == 4


def _four_exposed_triplets(hand: List[Tile], melds: List[Meld]) -> bool:
    """4 明刻 + 1 对: all four triplets called as peng (design doc: 5 花)."""
    if len(melds) != 4 or not all(m.type == "peng" for m in melds):
        return False
    counts: Dict[Tile, int] = {}
    for t in hand:
        if not t.is_flower:
            counts[t] = counts.get(t, 0) + 1
    return len(hand) == 2 and 2 in counts.values()   # just the pair concealed


def score_hand(
    hand: List[Tile],
    my_melds: List[Meld] = None,
    flowers: List[str] = None,
    konged_flowers: List[str] = None,
    win_method: str = "zimo",
) -> ScoringResult:
    """Score a winning hand in 花.

    hand: concealed tiles (winning 14-tile form is 3n+2 minus melds).
    flowers / konged_flowers: flower tile names held / already konged.
    win_method: "zimo" | "dianpao" | "gangkai".
    """
    if win_method not in VALID_WIN_METHODS:
        raise ValueError(f"未知胡法 {win_method!r}（可用：{'/'.join(VALID_WIN_METHODS)}）")
    my_melds = my_melds or []

    breakdown: List[str] = []
    hua = 0

    if win_method == "gangkai":
        hua += 8
        breakdown.append("杠开 8花")

    if _four_concealed_triplets(hand, my_melds):
        hua += 10
        breakdown.append("4暗刻 10花")
    elif _four_exposed_triplets(hand, my_melds):
        hua += 5
        breakdown.append("4明刻 5花")

    flower_count = len(flowers or []) + len(konged_flowers or [])
    if flower_count:
        hua += flower_count
        breakdown.append(f"花牌 {flower_count}花（每张1花）")

    return ScoringResult(hua=hua, flowers=flower_count, breakdown=breakdown)
