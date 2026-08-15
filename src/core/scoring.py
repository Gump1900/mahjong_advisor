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

杠分 (each kong adds its own 花):
  明杠 万饼条 +5 / 南西北 +6;  暗杠 万饼条 +10 / 中发白东南西北 +12.
  花牌（中发白东）没人打得出来，只能自杠 -> 按暗杠 +12.

花牌分:
  中发白东（未杠，拿手里，按同款张数）: 1张=1花, 2张=2花, 3张=4花, 4张=6花
  （暗杠后牌面朝下没翻出来，不算花，只拿暗杠 12花——"留花还是杠花"的博弈）
  春夏秋冬梅兰竹菊: 每张 1 花.

西南北风刻: 南/西/北 有 3 个一样的（碰的或手上的都行）另 +1 花；
杠了的不另加（明杠南=6、暗杠南=12 已含）.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .tiles import Meld, Tile, create_tile

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

# held 中发白东 by identical-copies count -> 花
HELD_FLOWER_TIERS = {1: 1, 2: 2, 3: 4, 4: 6}
FLOWER_KONG_HUA = 12              # konged 中发白东 (4张同, 自杠) -> 12花, replaces the tier
_MULTI_FLOWERS = ("中", "发", "白", "东风")   # by str(tile); 东 normalizes to 东风

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


def _flower_name(f) -> str:
    """Normalize a flower entry (name string or Tile) to its display name."""
    name = f if isinstance(f, str) else str(f)
    return "东风" if name == "东" else name


def _held_flower_hua(flowers: list) -> int:
    """花 from un-konged flowers: 中发白东 by tier (1/2/4/6), seasons 1 each."""
    counts: Dict[str, int] = {}
    for f in flowers or []:
        name = _flower_name(f)
        counts[name] = counts.get(name, 0) + 1
    hua = 0
    for name, n in counts.items():
        if name in _MULTI_FLOWERS:
            hua += HELD_FLOWER_TIERS[min(n, 4)]
        else:
            hua += n   # season flowers exist once each -> 1花 per tile
    return hua


def _konged_flower_hua(konged_flowers: list) -> int:
    """花 from konged flowers: each 中发白东 type konged = 12花 (replaces the
    held tier); season flowers count 1花 each even when set aside."""
    counts: Dict[str, int] = {}
    for f in konged_flowers or []:
        name = _flower_name(f)
        counts[name] = counts.get(name, 0) + 1
    hua = 0
    for name, n in counts.items():
        if name in _MULTI_FLOWERS:
            hua += FLOWER_KONG_HUA
        else:
            hua += n
    return hua


def _wind_triplet_hua(hand: List[Tile], melds: List[Meld]) -> Tuple[int, List[str]]:
    """南/西/北 each: 3 identical copies (peng or concealed) -> +1花.

    Konged winds do NOT get the extra 花 (the kong value 6/12 already covers
    it, per user rule). A concealed quad (4 in hand, not konged) counts.
    """
    hua = 0
    parts: List[str] = []
    for wind in ("南", "西", "北"):
        tile = create_tile("风", wind)
        copies = sum(1 for t in hand if t == tile)
        copies += sum(
            len(m.tiles) for m in melds
            if m.type == "peng" and m.tiles and m.tiles[0] == tile
        )
        if copies >= 3:
            hua += 1
            parts.append(f"{wind}风刻 1花")
    return hua, parts


def _kong_hua(melds: List[Meld]) -> Tuple[int, List[str]]:
    """花 from kongs among my_melds: 明杠 5 (南西北 6) / 暗杠 10 (中发白东南西北 12)."""
    total = 0
    parts: List[str] = []
    for m in melds:
        if m.type not in ("ming_gang", "an_gang"):
            continue
        tile = m.tiles[0]
        if m.type == "ming_gang":
            value = 6 if tile.suit == "风" else 5
            label = "明杠"
        else:   # an_gang: 南西北(风) and 中发白(三元) all count 12
            value = 12 if tile.suit in ("风", "三元") else 10
            label = "暗杠"
        total += value
        parts.append(f"{label}{tile} {value}花")
    return total, parts


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

    kong_hua, kong_parts = _kong_hua(melds)
    if kong_hua:
        hua += kong_hua
        breakdown.extend(kong_parts)

    wind_hua, wind_parts = _wind_triplet_hua(hand, melds)
    if wind_hua:
        hua += wind_hua
        breakdown.extend(wind_parts)

    flower_hua = _held_flower_hua(flowers) + _konged_flower_hua(konged_flowers)
    if flower_hua:
        hua += flower_hua
        breakdown.append(f"花牌 {flower_hua}花")

    return ScoringResult(hua=hua, flowers=flower_hua, breakdown=breakdown)
