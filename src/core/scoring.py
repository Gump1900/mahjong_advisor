"""花数 scoring — full table (user-confirmed rules).

Total = 底分 + Σ番型分 + 花牌数.

底分 (exactly one):
  自摸 +4 / 放炮 +2; 杠开 +8 — the 杠开 value REPLACES the 2/4 base
  (杠开已有8，不额外加底分). 杠开是自摸胡，番型按自摸档计.

番型 (stack on top of the base; (自摸, 放炮)):
  碰碰胡    10 / 5   — 4组刻子（暗刻/碰/杠）+ 1对，无吃
  小吊车    10 / 5   — 1张手牌 + 明牌里有吃
  大吊车    20 / 10  — 1张手牌 + 4组全是碰/杠（独立算，不再叠碰碰胡）
  清一色    10 / 5   — 全部同一门数牌（无字牌）
  七对      10 / 5   — 7个对子（门清）
  豪华七对  20 / 10  — 七对里有一组4张一样的当两对
  双豪华    40 / 20  — 七对里有两组4张一样的
  七对/豪华/双豪华互斥，按最高档计；清一色等其余番型照常叠加.

花牌: 每张 1 花（手里 + 已杠）.
"""
from dataclasses import dataclass, field
from typing import Dict, List

from .tiles import Meld, Tile

VALID_WIN_METHODS = ("zimo", "dianpao", "gangkai")

# pattern name -> (自摸花, 放炮花)
PATTERN_VALUES: Dict[str, tuple] = {
    "碰碰胡": (10, 5),
    "小吊车": (10, 5),
    "大吊车": (20, 10),
    "清一色": (10, 5),
    "七对": (10, 5),
    "豪华七对": (20, 10),
    "双豪华": (40, 20),
}

_TRIPLET_MELDS = ("peng", "ming_gang", "an_gang")
_NUMBER_SUITS = ("万", "饼", "条")


@dataclass
class ScoringResult:
    hua: int                                   # total 花
    flowers: int = 0                           # 花 contribution from flower tiles
    breakdown: List[str] = field(default_factory=list)   # human-readable parts


def _counts(hand: List[Tile]) -> Dict[Tile, int]:
    c: Dict[Tile, int] = {}
    for t in hand:
        if not t.is_flower:
            c[t] = c.get(t, 0) + 1
    return c


def _diao_che(hand: List[Tile], melds: List[Meld]):
    """大吊车 (all 4 melds are peng/gang) / 小吊车 (melds include chi)."""
    if len(hand) != 1 or len(melds) != 4:
        return None
    if all(m.type in _TRIPLET_MELDS for m in melds):
        return "大吊车"
    return "小吊车"


def _is_pengpeng(hand: List[Tile], melds: List[Meld]) -> bool:
    """碰碰胡: all-triplet standard form. 吊车 hands count their own way."""
    if any(m.type == "chi" for m in melds):
        return False
    if _diao_che(hand, melds) is not None:
        return False   # 大吊车独立算，不再叠碰碰胡
    c = _counts(hand)
    if any(v == 1 or v > 3 for v in c.values()):
        return False
    if sum(1 for v in c.values() if v == 2) != 1:
        return False   # exactly one pair
    return sum(c.values()) == 3 * (4 - len(melds)) + 2


def _seven_pairs_level(hand: List[Tile], melds: List[Meld]):
    """七对 / 豪华七对 / 双豪华 — mutually exclusive levels (None if not 七对)."""
    if melds or len(hand) != 14:
        return None
    c = _counts(hand)
    if sum(c.values()) != 14 or any(v not in (2, 4) for v in c.values()):
        return None
    quads = sum(1 for v in c.values() if v == 4)
    if quads == 0:
        return "七对"
    if quads == 1:
        return "豪华七对"
    return "双豪华"


def _is_qing_yi_se(hand: List[Tile], melds: List[Meld]) -> bool:
    """清一色: every tile (hand + melds) from one number suit, no honors."""
    tiles = [t for t in hand if not t.is_flower]
    for m in melds:
        tiles += [t for t in m.tiles if not t.is_flower]
    if not tiles:
        return False
    suits = {t.suit for t in tiles}
    return len(suits) == 1 and suits.issubset(set(_NUMBER_SUITS))


def score_hand(
    hand: List[Tile],
    my_melds: List[Meld] = None,
    flowers: list = None,
    konged_flowers: list = None,
    win_method: str = "zimo",
) -> ScoringResult:
    """Score a winning hand in 花.

    hand: concealed tiles (winning form: (4 - #melds) melds + 1 pair).
    flowers / konged_flowers: flower tile names (or Tiles) held / konged.
    win_method: "zimo" | "dianpao" | "gangkai".
    """
    if win_method not in VALID_WIN_METHODS:
        raise ValueError(f"未知胡法 {win_method!r}（可用：{'/'.join(VALID_WIN_METHODS)}）")
    melds = my_melds or []

    is_zimo_level = win_method in ("zimo", "gangkai")   # 杠开按自摸档计番型
    base = 8 if win_method == "gangkai" else (4 if is_zimo_level else 2)
    base_name = {"zimo": "自摸", "dianpao": "放炮", "gangkai": "杠开"}[win_method]
    breakdown = [f"{base_name} {base}花"]
    hua = base

    patterns: List[str] = []
    seven = _seven_pairs_level(hand, melds)
    if seven:
        patterns.append(seven)
    if _is_pengpeng(hand, melds):
        patterns.append("碰碰胡")
    diao = _diao_che(hand, melds)
    if diao:
        patterns.append(diao)
    if _is_qing_yi_se(hand, melds):
        patterns.append("清一色")

    for name in patterns:
        value = PATTERN_VALUES[name][0 if is_zimo_level else 1]
        hua += value
        breakdown.append(f"{name} {value}花")

    flower_count = len(flowers or []) + len(konged_flowers or [])
    if flower_count:
        hua += flower_count
        breakdown.append(f"花牌 {flower_count}花（每张1花）")

    return ScoringResult(hua=hua, flowers=flower_count, breakdown=breakdown)
