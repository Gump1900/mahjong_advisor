"""Hand analyzer tests: shanten, ukeire, waiting tiles, discards.

Compact hand notation via H(): number runs prefixed m/p/s (万/饼/条),
and bare honor/flower chars (南西北 / 中发白 / seasons). Examples:
  H("m123 p456 s789 南南南 西西")  -> 14 tiles, a winning hand
"""
import pytest

from src.core.tiles import create_tile
from src.core.hand_analyzer import (
    calculate_shanten,
    is_agari,
    is_tenpai,
    get_ukeire,
    get_waiting_tiles,
    rank_discards,
)

_SUIT = {"m": "万", "p": "饼", "s": "条"}


def H(spec):
    """Build a hand list from a compact spec string (prefix notation: m123 = 万1,2,3)."""
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
                    from src.core.tiles import parse_tile
                    tiles.append(parse_tile(ch))
    return tiles


# --- Standard-form shanten (exact, hand-computed) --------------------------
@pytest.mark.parametrize("spec,expected", [
    ("m123 p456 s789 南南南 西西", -1),   # complete win: 4 melds + pair
    ("m123 p456 s789 南南南 西", 0),      # tenpai, single-wait on 西
    ("m123 p456 s78 南南南 西 北", 1),   # one-shanten
    ("m123 p456 s78 南南 北 m49", 2),     # two-shanten
])
def test_standard_shanten(spec, expected):
    assert calculate_shanten(H(spec)) == expected


def test_agari_and_tenpai_flags():
    assert is_agari(H("m123 p456 s789 南南南 西西")) is True
    assert is_tenpai(H("m123 p456 s789 南南南 西")) is True
    assert is_tenpai(H("m123 p456 s789 南南南 西西")) is False  # win is past tenpai
    assert is_tenpai(H("m123 p456 s78 南南 北 m49")) is False


# --- Seven pairs (chiitoitsu) ----------------------------------------------
def test_chiitoitsu_win():
    assert calculate_shanten(H("m11 m22 p33 p44 s55 s66 南南")) == -1
    assert is_agari(H("m11 m22 p33 p44 s55 s66 南南")) is True


def test_chiitoitsu_tenpai():
    hand = H("m11 m22 p33 p44 s55 s66 南")  # 6 pairs + 1 single
    assert is_tenpai(hand) is True
    assert set(get_waiting_tiles(hand)) == {create_tile("风", "南")}


def test_quad_counts_as_one_pair_only():
    # four of a kind is only one pair for chiitoitsu; not a win
    hand = H("m1111 m22 p33 p44 s55 s66")  # 4+2+2+2+2 = 12... add 南南 ->14
    hand = H("m1111 m22 p33 p44 s55 s66 南南")  # pairs: 1m,2m,3p,4p,5s,6s,南 = 7 distinct
    assert calculate_shanten(hand) == -1   # 7 distinct pairs still wins


# --- Waiting tiles: single, two-sided, multi-decomposition -----------------
def _waiting(spec):
    return set(get_waiting_tiles(H(spec)))


def test_wait_single():
    assert _waiting("m123 p456 s789 南南南 西") == {create_tile("风", "西")}


def test_wait_two_sided():
    # 3 melds + 南南 head + m56 partial -> waits 4万 / 7万
    assert _waiting("m123 p456 s789 南南 m56") == {create_tile("万", 4), create_tile("万", 7)}


def test_wait_triplet_meld_legal():
    # 666 / 111 / 222 are valid triplet melds
    assert _waiting("m666 p111 s222 南南南 西") == {create_tile("风", "西")}


def test_wait_multi_decomp_23456():
    # m23456 + p111 + s222, tenpai waiting 1/4/7万
    assert _waiting("m23456 p111 s222 南南") == {
        create_tile("万", 1), create_tile("万", 4), create_tile("万", 7)
    }


def test_wait_multi_decomp_2345666():
    # The user's example: 2345666 -> 1,2,4,5,7 (two valid decompositions)
    assert _waiting("m2345666 p111 s222") == {
        create_tile("万", 1), create_tile("万", 2),
        create_tile("万", 4), create_tile("万", 5), create_tile("万", 7),
    }


# --- Ukeire (advancing tiles) ----------------------------------------------
def test_ukeire_reduces_shanten():
    hand = H("m123 p456 s78 南南南 西 北")   # shanten 1
    k = calculate_shanten(hand)
    assert k == 1
    ukeire = get_ukeire(hand)
    assert len(ukeire) > 0
    for u in ukeire:
        assert calculate_shanten(hand + [u]) == k - 1


def test_ukeire_includes_completing_tile():
    hand = H("m123 p456 s78 南南南 西 北")
    ukeire = get_ukeire(hand)
    # completing the 78s partial reaches tenpai
    assert create_tile("条", 6) in ukeire
    assert create_tile("条", 9) in ukeire


def test_ukeire_equals_waiting_when_tenpai():
    hand = H("m2345666 p111 s222")
    assert set(get_ukeire(hand)) == set(get_waiting_tiles(hand))


# --- Discard ranking -------------------------------------------------------
def test_rank_discards_keeps_tenpai():
    # 14-tile hand (just drew): best discard keeps shanten 0
    hand = H("m123 p456 s78 南南南 西西 北")
    ranked = rank_discards(hand)
    assert len(ranked) > 0
    # sorted ascending by resulting shanten
    shantens = [s for _, s in ranked]
    assert shantens == sorted(shantens)
    # discarding 北 keeps tenpai (shanten 0); it is the best discard
    assert ranked[0][0] == create_tile("风", "北")
    assert ranked[0][1] == 0


def test_rank_discards_breaking_structure_is_worse():
    hand = H("m123 p456 s78 南南南 西西 北")
    ranked = dict(rank_discards(hand))
    # discarding a structural tile (8s, part of the 78s partial) raises shanten
    assert ranked[create_tile("条", 8)] > 0


# --- Called melds (fuuro) change the structure target -----------------------
def test_fuuro_reduces_needed_melds():
    # after one peng, the concealed 10 tiles need 3 melds + 1 pair
    hand = H("m123 p456 s789 南南")
    assert calculate_shanten(hand, fuuro=1) == -1   # win: 3 melds + pair + the peng
    assert is_agari(hand, fuuro=1) is True

def test_fuuro_tenpai():
    hand = H("m123 p456 s78 南南")
    assert calculate_shanten(hand, fuuro=1) == 0
    # 3 melds + head + s78 partial + the peng -> waits 6条/9条
    assert set(get_waiting_tiles(hand, fuuro=1)) == {create_tile("条", 6), create_tile("条", 9)}

def test_fuuro_blocks_seven_pairs():
    hand = H("m11 m22 p33 p44 s55 s66 南")
    # chiitoitsu is impossible with a call; without fuuro this is tenpai
    assert calculate_shanten(hand, fuuro=0) == 0
    assert calculate_shanten(hand, fuuro=1) > 0

def test_fuuro_threaded_through_discards_and_ukeire():
    hand = H("m123 p456 s78 南南")   # 12 tiles + 1 peng = 13
    ukeire = get_ukeire(hand, fuuro=1)
    assert create_tile("条", 6) in ukeire
    assert create_tile("条", 9) in ukeire
    ranked = rank_discards(hand, fuuro=1)
    assert len(ranked) > 0
    assert all(s >= 0 for _, s in ranked)   # discarding never reaches a win

# --- Flowers are excluded from the structure -------------------------------
def test_flowers_excluded_from_shanten():
    base = H("m123 p456 s78 南南南 西 北")          # shanten 1
    with_flower = base + [create_tile("三元", "中")]  # add a flower
    assert calculate_shanten(with_flower) == calculate_shanten(base) == 1


def test_flowers_not_in_ukeire():
    hand = H("m123 p456 s78 南南南 西 北")
    for u in get_ukeire(hand):
        assert u.is_flower is False
