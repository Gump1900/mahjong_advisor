"""Tile data structures and basic operations.

Rule baseline (see docs/plans/2026-02-27-mahjong-advisor-design.md):
- Playable tiles (form the 4-melds + 1-pair winning structure): 万/饼/条 1-9,
  plus the wind tiles 南/西/北 (honors: pairs/triplets only, no sequences).
- Flower tiles (set aside, never part of the structure, may be held for 杠开):
  东风, 三元 (中/发/白), and seasonal flowers (春夏秋冬梅兰竹菊).
"""
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Union

Suit = Literal["万", "饼", "条", "风", "三元", "季节"]

_NUMBER_SUITS = ("万", "饼", "条")


@dataclass(frozen=True)
class Tile:
    """A single mahjong tile."""

    suit: Suit
    value: Union[int, str]
    is_flower: bool = False

    def __str__(self) -> str:
        if self.suit in _NUMBER_SUITS:
            return f"{self.value}{self.suit}"
        if self.suit == "风":
            return f"{self.value}风"
        # 三元 / 季节: suit name is redundant, value alone is the clean name
        return str(self.value)


def create_tile(suit: Suit, value: Union[int, str]) -> Tile:
    """Create a tile, coercing number values to int and auto-detecting flowers."""
    if suit in _NUMBER_SUITS:
        value = int(value)
        if not 1 <= value <= 9:
            raise ValueError(f"Invalid number tile value: {value}{suit}")

    is_flower = (
        (suit == "风" and value == "东")  # 东风 is a flower; 南西北 are not
        or suit == "三元"
        or suit == "季节"
    )
    return Tile(suit=suit, value=value, is_flower=is_flower)


def parse_tile(s: str) -> Tile:
    """Parse a tile from text.

    Accepted forms: '3万'/'9条'/'1饼', '东风'/'南风'/'西风'/'北风',
    '中'/'发'/'白', and season names '春'..'菊'.
    """
    s = s.strip()
    if len(s) == 2 and s[1] in _NUMBER_SUITS:
        return create_tile(s[1], int(s[0]))
    if len(s) == 2 and s[1] == "风":
        return create_tile("风", s[0])
    if s in ("中", "发", "白"):
        return create_tile("三元", s)
    if s in ("春", "夏", "秋", "冬", "梅", "兰", "竹", "菊"):
        return create_tile("季节", s)
    raise ValueError(f"Cannot parse tile: {s!r}")


# --- Engine indexing over the 30 playable tile types -----------------------
# Order: 万 1-9 (0-8), 饼 1-9 (9-17), 条 1-9 (18-26), 南/西/北 (27-29).
_PLAYABLE_LIST: List[Tile] = (
    [create_tile("万", v) for v in range(1, 10)]
    + [create_tile("饼", v) for v in range(1, 10)]
    + [create_tile("条", v) for v in range(1, 10)]
    + [create_tile("风", "南"), create_tile("风", "西"), create_tile("风", "北")]
)
_PLAYABLE_INDEX: Dict[Tile, int] = {t: i for i, t in enumerate(_PLAYABLE_LIST)}

PLAYABLE_TILES: tuple = tuple(_PLAYABLE_LIST)


def is_playable(tile: Tile) -> bool:
    """True if the tile can be part of the winning hand structure."""
    return tile in _PLAYABLE_INDEX


def tile_index(tile: Tile) -> int:
    """Integer index (0-29) of a playable tile. Raises for flower tiles."""
    try:
        return _PLAYABLE_INDEX[tile]
    except KeyError:
        raise ValueError(f"{tile} is not a playable tile") from None


def index_to_tile(index: int) -> Tile:
    """Inverse of tile_index."""
    return _PLAYABLE_LIST[index]


# --- Game-state structures --------------------------------------------------
MeldType = Literal["chi", "peng", "ming_gang", "an_gang"]


@dataclass
class Meld:
    """An exposed meld (call): chi / peng / ming_gang / an_gang."""

    type: MeldType
    tiles: List[Tile]


def _three_player_dict() -> Dict[str, List]:
    return {"left": [], "right": [], "opposite": []}


@dataclass
class GameState:
    """Snapshot of the table from my perspective.

    left = 上家 (the player whose discards I may chi), right = 下家,
    opposite = 对家.
    """

    my_hand: List[Tile] = field(default_factory=list)
    discards: Dict[str, List[Tile]] = field(default_factory=_three_player_dict)
    melds: Dict[str, List[Meld]] = field(default_factory=_three_player_dict)
    flowers_in_hand: List[Tile] = field(default_factory=list)
    konged_flowers: List[Tile] = field(default_factory=list)
    current_turn: Literal["me", "left", "right", "opposite"] = "me"
