"""End-to-end integration: game state -> analysis -> consistency checks."""
from src.core.tiles import create_tile, parse_tile, GameState, Meld
from src.core.hand_analyzer import (
    calculate_shanten,
    is_tenpai,
    get_ukeire,
    get_waiting_tiles,
    rank_discards,
)
from src.core.probability import count_remaining_tiles

_SUIT = {"m": "万", "p": "饼", "s": "条"}


def H(spec):
    """Compact hand builder (prefix notation: m123 = 万1,2,3)."""
    tiles = []
    for tok in spec.split():
        if tok and tok[0] in _SUIT:
            for ch in tok[1:]:
                tiles.append(create_tile(_SUIT[tok[0]], int(ch)))
        else:
            for ch in tok:
                if ch in "南西北东":
                    tiles.append(create_tile("风", ch))
                else:
                    tiles.append(parse_tile(ch))
    return tiles


def test_tenpai_scenario_with_live_waits():
    hand = H("m123 p456 s789 南南南 西")          # tenpai, waiting on 西
    state = GameState(my_hand=hand)
    state.discards["left"] = [create_tile("风", "西"), create_tile("万", 9)]

    assert is_tenpai(hand)
    waiting = get_waiting_tiles(hand)
    assert set(waiting) == {create_tile("风", "西")}

    remaining = count_remaining_tiles(state)
    # 西: 4 total - 1 in hand - 1 discarded by left = 2 still live
    assert remaining[create_tile("风", "西")] == 2
    # every wait still has live copies
    for t in waiting:
        assert remaining[t] > 0

    # ukeire and waiting agree for a tenpai hand
    assert set(get_ukeire(hand)) == set(waiting)


def test_discard_decision_uses_remaining_context():
    # 14-tile hand: best discard keeps tenpai
    hand = H("m123 p456 s78 南南南 西西 北")
    ranked = rank_discards(hand)
    best_tile, best_shanten = ranked[0]
    assert best_tile == create_tile("风", "北")
    assert best_shanten == 0

    # the resulting 13-tile hand (m123 p456 s78 南南南 西西) is tenpai,
    # using 西西 as the head and 78条 as the waiting partial -> waits 6条/9条
    kept = list(hand)
    kept.remove(best_tile)
    assert set(get_waiting_tiles(kept)) == {create_tile("条", 6), create_tile("条", 9)}


def test_flowers_integrated_across_modules():
    playable = H("m123 p456 s789 南南南 西")       # tenpai hand (no flowers)
    state = GameState(
        my_hand=playable,
        flowers_in_hand=[create_tile("三元", "中")],   # holding one flower
    )
    # shanten ignores the flower
    assert calculate_shanten(state.my_hand) == 0
    # remaining subtracts the held flower from the live pool (4 - 1 = 3)
    remaining = count_remaining_tiles(state)
    assert remaining[create_tile("三元", "中")] == 3


def test_meld_affects_remaining():
    meld = Meld(type="peng", tiles=[create_tile("饼", 1)] * 3)  # 饼1 not in hand
    state = GameState(
        my_hand=H("m123 p456 s789 南南南 西"),
        melds={"left": [meld], "right": [], "opposite": []},
    )
    remaining = count_remaining_tiles(state)
    assert remaining[create_tile("饼", 1)] == 1   # 4 - 3 in left's peng
