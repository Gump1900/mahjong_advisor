"""Scoring tests — the user-confirmed full 花数 table.

Model: 总分 = 底分(自摸4/放炮2，杠开8替代) + Σ番型(杠开按自摸档) + 花牌数.
大吊车独立算（不叠碰碰胡）；七对/豪华/双豪华互斥按最高档。
"""
import pytest

from src.core.tiles import create_tile, Meld
from src.core.scoring import score_hand, ScoringResult, PATTERN_VALUES

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


def _peng(tile):
    return Meld(type="peng", tiles=[tile] * 3)


def _chi(a, b, c):
    return Meld(type="chi", tiles=[a, b, c])


# --- base -------------------------------------------------------------------
class TestBase:
    def test_plain_zimo(self):
        assert score_hand(H("m123 p456 s789 南南南 西西"), win_method="zimo").hua == 4

    def test_plain_dianpao(self):
        assert score_hand(H("m123 p456 s789 南南南 西西"), win_method="dianpao").hua == 2

    def test_gangkai_replaces_base(self):
        # 杠开已有8花，不额外加自摸4
        r = score_hand(H("m123 p456 s789 南南南 西西"), win_method="gangkai")
        assert r.hua == 8
        assert r.breakdown[0] == "杠开 8花"

    def test_invalid_win_method(self):
        with pytest.raises(ValueError):
            score_hand(H("m123 p456 s789 南南南 西西"), win_method="bogus")


# --- patterns ----------------------------------------------------------------
class TestPengPeng:
    def test_concealed_zimo(self):
        r = score_hand(H("m111 p222 s333 南南南 西西"), win_method="zimo")
        assert r.hua == 4 + 10
        assert "碰碰胡 10花" in r.breakdown

    def test_concealed_dianpao(self):
        assert score_hand(H("m111 p222 s333 南南南 西西"), win_method="dianpao").hua == 2 + 5

    def test_with_called_pengs(self):
        hand = H("m111 p222 南南")   # 2 concealed triplets + pair, 2 pengs called
        melds = [_peng(create_tile("饼", 5)), _peng(create_tile("条", 9))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert r.hua == 4 + 10

    def test_chi_meld_breaks_it(self):
        # 2 concealed triplets + pair, but one meld is a chi -> no 碰碰胡
        hand = H("m111 p222 南南")
        melds = [_peng(create_tile("饼", 5)),
                 _chi(create_tile("条", 3), create_tile("条", 4), create_tile("条", 5))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert "碰碰胡" not in r.breakdown
        assert r.hua == 4   # base only


class TestDiaoChe:
    def test_da_diao_che_standalone(self):
        # 1 hand tile + 4 pengs: 大吊车 only (独立算，不叠碰碰胡)
        hand = [create_tile("风", "西")]
        melds = [_peng(create_tile("万", 3)), _peng(create_tile("万", 7)),
                 _peng(create_tile("饼", 5)), _peng(create_tile("条", 9))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert "大吊车 20花" in r.breakdown
        assert "碰碰胡" not in r.breakdown
        assert r.hua == 4 + 20

    def test_da_diao_che_dianpao(self):
        hand = [create_tile("风", "西")]
        melds = [_peng(create_tile("万", 3)), _peng(create_tile("万", 7)),
                 _peng(create_tile("饼", 5)), _peng(create_tile("条", 9))]
        assert score_hand(hand, my_melds=melds, win_method="dianpao").hua == 2 + 10

    def test_xiao_diao_che(self):
        # 1 hand tile + melds containing chi -> 小吊车
        hand = [create_tile("风", "西")]
        melds = [_peng(create_tile("万", 3)), _peng(create_tile("万", 7)),
                 _chi(create_tile("饼", 5), create_tile("饼", 6), create_tile("饼", 7)),
                 _chi(create_tile("条", 1), create_tile("条", 2), create_tile("条", 3))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert "小吊车 10花" in r.breakdown
        assert r.hua == 4 + 10


class TestQingYiSe:
    def test_flush_with_runs(self):
        r = score_hand(H("m111 m222 m345 m678 m99"), win_method="zimo")
        assert "清一色 10花" in r.breakdown
        assert r.hua == 4 + 10

    def test_flush_dianpao(self):
        assert score_hand(H("m111 m222 m345 m678 m99"), win_method="dianpao").hua == 2 + 5

    def test_flush_plus_pengpeng_stacks(self):
        r = score_hand(H("m111 m222 m333 m444 m99"), win_method="zimo")
        assert r.hua == 4 + 10 + 10   # 清一色 + 碰碰胡 叠加

    def test_honors_break_flush(self):
        r = score_hand(H("m111 m222 m333 m444 南南"), win_method="zimo")
        assert "清一色" not in r.breakdown   # 南 is an honor


class TestSevenPairs:
    def test_plain(self):
        r = score_hand(H("m11 m22 p33 p44 s55 s66 南南"), win_method="zimo")
        assert r.hua == 4 + 10
        assert "七对 10花" in r.breakdown

    def test_luxury(self):
        # one quad (4张一样的) as two pairs + five pairs
        r = score_hand(H("m1111 m22 p33 p44 s55 s66"), win_method="dianpao")
        assert "豪华七对 10花" in r.breakdown
        assert "七对" not in [b.split()[0] for b in r.breakdown]   # 互斥
        assert r.hua == 2 + 10

    def test_double_luxury(self):
        r = score_hand(H("m1111 p2222 s33 s55 南南"), win_method="zimo")
        assert "双豪华 40花" in r.breakdown
        assert r.hua == 4 + 40

    def test_melds_block_seven_pairs(self):
        hand = H("m11 m22 p33 p44 s55 s66")
        r = score_hand(hand, my_melds=[_peng(create_tile("条", 9))], win_method="zimo")
        assert all("七对" not in b and "豪华" not in b for b in r.breakdown)


# --- combinations -------------------------------------------------------------
class TestCombinations:
    def test_gangkai_plus_pengpeng(self):
        # 杠开按自摸档计番型: 8 + 10
        r = score_hand(H("m111 p222 s333 南南南 西西"), win_method="gangkai")
        assert r.hua == 8 + 10
        assert r.breakdown[0] == "杠开 8花"

    def test_qingyise_seven_pairs_stacks(self):
        r = score_hand(H("m11 m22 m33 m44 m55 m66 m77"), win_method="zimo")
        assert r.hua == 4 + 10 + 10   # 清一色 + 七对

    def test_flowers_add(self):
        r = score_hand(H("m123 p456 s789 南南南 西西"),
                       flowers=["中", "春"], konged_flowers=["夏"], win_method="zimo")
        assert r.hua == 4 + 3
        assert r.flowers == 3


class TestResultShape:
    def test_breakdown_complete(self):
        r = score_hand(H("m1111 p2222 s33 s55 南南"), flowers=["中"], win_method="gangkai")
        assert isinstance(r, ScoringResult)
        assert r.hua == 8 + 40 + 1
        assert len(r.breakdown) == 3

    def test_pattern_table_has_both_levels(self):
        for name, (zimo, dianpao) in PATTERN_VALUES.items():
            assert zimo > dianpao, name
