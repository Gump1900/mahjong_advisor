"""Scoring tests.

The full 花数 table for this variant is not yet specified; these tests pin
the rules the design doc DOES list (4明刻=5花 / 4暗刻=10花 / 杠开=8花) plus
the agreed default of 1 花 per flower tile. Everything else is an explicit
extension point (see SCORING_TABLE in src/core/scoring.py).
"""
import pytest

from src.core.tiles import create_tile, GameState, Meld
from src.core.scoring import score_hand, ScoringResult

_SUIT = {"m": "万", "p": "饼", "s": "条"}


def H(spec):
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


class TestFlowers:
    def test_each_flower_one_hua(self):
        # agreed default: every flower tile (held or konged) is 1 花
        hand = H("m123 p456 s789 南南南 西西")   # standard shape: no pattern 花
        result = score_hand(hand, flowers=["中", "春"], konged_flowers=[])
        assert result.flowers == 2
        assert result.hua == 2

    def test_konged_flowers_count_too(self):
        hand = H("m123 p456 s789 南南南 西西")
        result = score_hand(hand, flowers=["中"], konged_flowers=["夏", "菊"])
        assert result.flowers == 3
        assert result.hua == 3


class TestAllTripletHands:
    def test_four_concealed_triplets_is_ten_hua(self):
        # 4暗刻 + pair, fully concealed -> 10 花 (design doc)
        hand = H("m111 p222 s333 南南南 西西")
        result = score_hand(hand)
        assert result.hua == 10
        assert any("暗刻" in r for r in result.breakdown)

    def test_four_exposed_triplets_is_five_hua(self):
        # 4明刻 (all four triplets called) + pair -> 5 花 (design doc)
        hand = H("m11")      # just the pair, everything else called
        melds = [
            Meld(type="peng", tiles=[create_tile("万", 3)] * 3),
            Meld(type="peng", tiles=[create_tile("万", 7)] * 3),
            Meld(type="peng", tiles=[create_tile("饼", 5)] * 3),
            Meld(type="peng", tiles=[create_tile("条", 9)] * 3),
        ]
        result = score_hand(hand, my_melds=melds)
        assert result.hua == 5
        assert any("明刻" in r for r in result.breakdown)

    def test_mixed_triplets_default(self):
        # 2 concealed + 2 exposed triplets: not one of the doc's whole-hand
        # rules; falls to the extensible per-pattern table (currently 0)
        hand = H("m111 p22 s999 西西")
        melds = [
            Meld(type="peng", tiles=[create_tile("饼", 5)] * 3),
            Meld(type="peng", tiles=[create_tile("条", 3)] * 3),
        ]
        result = score_hand(hand, my_melds=melds)
        assert result.hua == 0   # TODO: fill in with the variant's table


class TestGangkai:
    def test_gangkai_eight_hua(self):
        hand = H("m111 p222 s333 南南南 西西")
        result = score_hand(hand, win_method="gangkai")
        assert "杠开" in result.breakdown[0]
        # doc: 杠开 = 8花 上不封顶 -> patterns stack on top (this hand is also 4暗刻)
        assert result.hua == 8 + 10

    def test_gangkai_plus_flowers(self):
        hand = H("m111 p222 s333 南南南 西西")
        result = score_hand(hand, flowers=["中"], win_method="gangkai")
        assert result.hua == 8 + 10 + 1   # 杠开 + 4暗刻 + 1 flower, uncapped


class TestResultShape:
    def test_breakdown_lists_every_component(self):
        hand = H("m111 p222 s333 南南南 西西")
        result = score_hand(hand, flowers=["春", "夏"], win_method="gangkai")
        assert isinstance(result, ScoringResult)
        assert result.hua == 8 + 10 + 2     # 杠开 + 4暗刻 + flowers
        assert len(result.breakdown) == 3

    def test_invalid_win_method(self):
        hand = H("m111 p222 s333 南南南 西西")
        with pytest.raises(ValueError):
            score_hand(hand, win_method="bogus")
