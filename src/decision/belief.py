"""Count-constrained proposals, weighted separately by public-action evidence.

Live snapshots use observed concealed-slot counts: retained flowers occupy slots
and unknown kongs reserve four identical unseen copies. Legacy snapshots without
slot observations retain the older structural prior. Neither is human-calibrated.
"""
import random
from dataclasses import dataclass, field
from collections import Counter

from ..core.probability import count_remaining_tiles
from ..core.tiles import GameState, Tile, Meld

OPPONENTS = ("left", "opposite", "right")
MODEL = "joint-uniform-deal-v1"


@dataclass
class HiddenWorld:
    hands: dict[str, list[Tile]]
    flowers: dict[str, list[Tile]]
    wall: list[Tile]
    melds: dict[str, list[Meld]] = field(default_factory=dict)


def sample_world(state: GameState, rng: random.Random) -> HiddenWorld:
    if state.opponent_hand_counts or any(state.opponent_unknown_kongs.values()):
        return _slot_world(state, rng)
    pool = [t for t, n in count_remaining_tiles(state).items() for _ in range(n)]
    rng.shuffle(pool)
    seats = list(OPPONENTS)
    rng.shuffle(seats)
    hands, flowers = {}, {}
    for seat in seats:
        needed = 13 - 3 * len(state.melds[seat])
        if needed < 1 or len(state.melds[seat]) > 4:
            raise ValueError("对手明牌组数不合法")
        hands[seat] = []
        flowers[seat] = list(state.opponent_flowers[seat])
        skipped = []
        while len(hands[seat]) < needed:
            if not pool:
                raise ValueError("未见牌不足以分配三家暗牌，请检查记录")
            tile = pool.pop()
            if not tile.is_flower:
                hands[seat].append(tile)
            elif state.opponent_flowers_complete[seat]:
                skipped.append(tile)
            else:
                flowers[seat].append(tile)
        pool.extend(skipped)
        rng.shuffle(pool)
    return HiddenWorld(hands, flowers, pool)


def _slot_world(state, rng):
    """Live observations: flowers occupy slots; hidden kongs consume four equal copies."""
    counts = Counter(count_remaining_tiles(state))
    melds = {seat: list(state.melds[seat]) for seat in OPPONENTS}
    hidden = [seat for seat in OPPONENTS for _ in range(state.opponent_unknown_kongs.get(seat, 0))]
    rng.shuffle(hidden)
    for seat in hidden:
        eligible = [tile for tile, count in counts.items() if count == 4]
        if not eligible:
            raise ValueError("未见牌无法容纳已声明的未知暗杠")
        tile = rng.choice(eligible)
        counts[tile] -= 4
        melds[seat].append(Meld("an_gang", [tile]*4))
    pool = list(counts.elements())
    rng.shuffle(pool)
    seats = list(OPPONENTS)
    rng.shuffle(seats)
    hands, flowers = {}, {}
    for seat in seats:
        groups = len(melds[seat])
        slots = state.opponent_hand_counts.get(seat, 13 - 3*groups)
        known = list(state.opponent_flowers[seat])
        if groups > 4 or slots < len(known) or slots < 0:
            raise ValueError("对手手牌或副露数量不合法")
        hands[seat], flowers[seat], skipped = [], known, []
        for _ in range(slots-len(known)):
            while True:
                if not pool:
                    raise ValueError("未见牌不足以分配已知手牌位")
                tile = pool.pop()
                if tile.is_flower and state.opponent_flowers_complete.get(seat):
                    skipped.append(tile)
                    continue
                (flowers[seat] if tile.is_flower else hands[seat]).append(tile)
                break
        pool.extend(skipped)
        rng.shuffle(pool)
    return HiddenWorld(hands, flowers, pool, melds)
