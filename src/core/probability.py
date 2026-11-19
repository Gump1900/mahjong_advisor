"""Tile counting and remaining-tile probability.

TileCounter starts from the full 144-tile wall and lets us subtract every
tile that is visible to us (our hand, our flowers, all discards, all melds)
to count unseen copies (opponents' concealed tiles PLUS the wall, not live outs).
"""
from typing import Dict

from .tiles import GameState, Tile, create_tile


class TileCounter:
    """Tracks the remaining count of every tile type (full 144-tile deck)."""

    def __init__(self):
        self._counts: Dict[Tile, int] = {}
        self._initialize()

    def _initialize(self):
        # 万 / 饼 / 条: 1-9, four copies each (108)
        for suit in ("万", "饼", "条"):
            for value in range(1, 10):
                self._counts[create_tile(suit, value)] = 4
        # 风: 东南西北, four copies each (16)
        for value in ("东", "南", "西", "北"):
            self._counts[create_tile("风", value)] = 4
        # 三元: 中发白, four copies each (12)
        for value in ("中", "发", "白"):
            self._counts[create_tile("三元", value)] = 4
        # 季节: one copy each (8)
        for value in ("春", "夏", "秋", "冬", "梅", "兰", "竹", "菊"):
            self._counts[create_tile("季节", value)] = 1

    def get_count(self, tile: Tile) -> int:
        return self._counts.get(tile, 0)

    def remove(self, tile: Tile, count: int = 1) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("扣除张数必须是非负整数")
        if tile not in self._counts or count > self._counts[tile]:
            raise ValueError(f"{tile} 的可见数量超过实体副本上限")
        self._counts[tile] -= count

    def all_counts(self) -> Dict[Tile, int]:
        return dict(self._counts)


def count_remaining_tiles(state: GameState) -> Dict[Tile, int]:
    """Count remaining tiles given everything visible in the game state."""
    counter = TileCounter()

    for tile in state.my_hand:
        counter.remove(tile)
    for tile in state.my_discards:
        counter.remove(tile)
    for tile in state.flowers_in_hand:
        counter.remove(tile)
    for tile in state.konged_flowers:
        counter.remove(tile)

    for flowers in state.opponent_flowers.values():
        for tile in flowers:
            counter.remove(tile)
    for flowers in state.opponent_konged_flowers.values():
        for tile in flowers:
            counter.remove(tile)

    for player_discards in state.discards.values():
        for tile in player_discards:
            counter.remove(tile)

    for player_melds in state.melds.values():
        for meld in player_melds:
            for tile in meld.tiles:
                counter.remove(tile)

    for meld in state.my_melds:
        for tile in meld.tiles:
            counter.remove(tile)

    return counter.all_counts()


# Note: risk labels are a human-style heuristic, not a computed probability.
_SAFE, _MEDIUM, _DANGER = "安全", "中", "危险"


def discard_risk(tile: Tile, state: GameState) -> str:
    """Coarse structural heuristic, without any discarded-tile immunity."""
    return estimate_discard_risks(tile, state)["label"]



# --- richer (still heuristic) discard-risk estimates -------------------------
def _sequence_shapes(tile: Tile) -> int:
    """How many runs this tile can complete in its suit (centrality proxy).

    5 participates in 3 runs (345/456/567); 1 and 9 in only 1. Honors: 0.
    """
    if tile.suit not in ("万", "饼", "条"):
        return 0
    v = tile.value
    return sum(
        1 for start in range(v - 2, v + 1) if 1 <= start and start + 2 <= 9
    )


def estimate_discard_risks(tile: Tile, state: GameState) -> Dict[str, float]:
    """Uncalibrated heuristic scores, not inferred opponent probabilities.

    There is no furiten rule: a past discard never proves ron impossible.
    No unseen copies of the target also does not exclude sequence waits;
    the opponents may hold its two neighbors. Chi concerns the downstream
    player (right), not the upstream player whose discards *we* can chi.
    """
    if tile.is_flower:
        return {"chi": 0.0, "peng": 0.0, "ron": 0.0, "label": _SAFE}

    remaining = count_remaining_tiles(state)
    hidden = remaining.get(tile, 0)
    shapes = 0
    if tile.suit in ("万", "饼", "条"):
        value = int(tile.value)
        for start in range(max(1, value - 2), min(value, 7) + 1):
            others = [create_tile(tile.suit, v) for v in range(start, start + 3) if v != value]
            if all(remaining.get(t, 0) > 0 for t in others):
                shapes += 1
    is_honor = tile.suit == "风"

    # --- chi: only the downstream player can chi my discard ---
    if is_honor or not shapes:
        chi = 0.0
    else:
        downstream_discards = state.discards.get("right", [])
        suit_bias = (
            sum(1 for t in downstream_discards if t.suit == tile.suit) / len(downstream_discards)
            if downstream_discards else 0.25
        )
        chi = round(0.12 * suit_bias + 0.08 * shapes / 3, 4)

    # --- peng: any of the three; scales with hidden copies & attractiveness
    if is_honor:
        attract = 0.7
    else:
        attract = {5: 1.0, 4: 1.0, 6: 1.0, 3: 0.8, 7: 0.8,
                   2: 0.6, 8: 0.6, 1: 0.5, 9: 0.5}[tile.value]
    peng = round(0.35 * min(1.0, hidden / 3) * attract, 4) if hidden >= 2 else 0.0

    # A sequence wait needs no additional hidden copy of the discarded tile.
    if shapes == 0 and hidden == 0:
        ron = 0.0
    else:
        ron = round(0.4 * max(shapes / 3, 0.4 if hidden else 0.0), 4)

    # --- label: same coarse buckets as discard_risk ---
    if ron == 0.0:
        label = _SAFE
    elif not is_honor and tile.value in (4, 5, 6) and ron > 0.2:
        label = _DANGER
    else:
        label = _MEDIUM

    return {"chi": chi, "peng": peng, "ron": ron, "label": label}
