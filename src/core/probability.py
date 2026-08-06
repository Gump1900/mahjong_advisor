"""Tile counting and remaining-tile probability.

TileCounter starts from the full 144-tile wall and lets us subtract every
tile that is visible to us (our hand, our flowers, all discards, all melds)
to estimate how many of each tile type are still live.
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
        self._counts[tile] = max(0, self._counts.get(tile, 0) - count)

    def all_counts(self) -> Dict[Tile, int]:
        return dict(self._counts)


def count_remaining_tiles(state: GameState) -> Dict[Tile, int]:
    """Count remaining tiles given everything visible in the game state."""
    counter = TileCounter()

    for tile in state.my_hand:
        counter.remove(tile)
    for tile in state.flowers_in_hand:
        counter.remove(tile)
    for tile in state.konged_flowers:
        counter.remove(tile)

    for player_discards in state.discards.values():
        for tile in player_discards:
            counter.remove(tile)

    for player_melds in state.melds.values():
        for meld in player_melds:
            for tile in meld.tiles:
                counter.remove(tile)

    return counter.all_counts()
