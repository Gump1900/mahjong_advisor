"""Scoring tests — the user-confirmed full 花数 table.

Model: 总分 = 底分(自摸4/放炮2，杠开8替代) + Σ番型(杠开按自摸档) + 花牌数.
大吊车独立算（不叠碰碰胡）；七对/豪华/双豪华互斥按最高档。
"""
import pytest

from src.core.tiles import create_tile, Meld
from src.core.scoring import score_hand, ScoringResult, PATTERN_VALUES, flower_hua

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
    def test_zero_flower_compensation_is_better_than_one_flower(self):
        hand = H("m123 m456 p789 s123 s99")
        assert score_hand(hand).hua == 6
        assert score_hand(hand, flowers=["春"]).hua == 5
        assert score_hand(hand, flowers=["春", "夏"]).hua == 6

    def test_patterns_do_not_grant_ron_but_wind_triplets_do(self):
        with pytest.raises(ValueError, match="无花不能接炮"):
            score_hand(H("m111 m222 m333 m444 m99"), win_method="dianpao")
        result = score_hand(H("m123 p456 s789 南南南 西西"), win_method="dianpao")
        assert result.qualifying_hua == 1 and result.hua == 3

    def test_no_flower_self_draw_still_adds_pattern_points(self):
        result = score_hand(H("m111 m222 m333 m444 m99"))
        assert result.base_hua == 6 and result.pattern_hua == 20
        assert result.qualifying_hua == 0 and result.hua == 26

    def test_plain_zimo(self):
        assert score_hand(H("m123 m456 p789 s123 s99"), win_method="zimo").hua == 6

    def test_plain_dianpao(self):
        with pytest.raises(ValueError, match="无花不能接炮"):
            score_hand(H("m123 m456 p789 s123 s99"), win_method="dianpao")

    def test_gangkai_replaces_base(self):
        # 杠开已有8花，不额外加自摸4
        r = score_hand(H("m123 m456 p789 s123 s99"), win_method="gangkai")
        assert r.hua == 8
        assert r.breakdown[0] == "杠开 8花"

    def test_invalid_win_method(self):
        with pytest.raises(ValueError):
            score_hand(H("m123 m456 p789 s123 s99"), win_method="bogus")


# --- patterns ----------------------------------------------------------------
class TestPengPeng:
    def test_concealed_zimo(self):
        r = score_hand(H("m111 p222 s333 南南南 西西"), win_method="zimo")
        assert r.hua == 4 + 10 + 1   # 碰碰胡 + 南风刻
        assert "碰碰胡 10花" in r.breakdown
        assert "南风刻 1花" in r.breakdown

    def test_concealed_dianpao(self):
        assert score_hand(H("m111 p222 s333 南南南 西西"), win_method="dianpao").hua == 2 + 5 + 1   # +南风刻

    def test_with_called_pengs(self):
        hand = H("m111 p222 南南")   # 2 concealed triplets + pair, 2 pengs called
        melds = [_peng(create_tile("饼", 5)), _peng(create_tile("条", 9))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert r.hua == 6 + 10

    def test_chi_meld_breaks_it(self):
        # 2 concealed triplets + pair, but one meld is a chi -> no 碰碰胡
        hand = H("m111 p222 南南")
        melds = [_peng(create_tile("饼", 5)),
                 _chi(create_tile("条", 3), create_tile("条", 4), create_tile("条", 5))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert "碰碰胡" not in r.breakdown
        assert r.hua == 6   # no-flower self-draw compensation


class TestDiaoChe:
    def test_da_diao_che_standalone(self):
        # One-tile wait has become a pair on winning; no 碰碰胡 stacking.
        hand = [create_tile("风", "西")] * 2
        melds = [_peng(create_tile("万", 3)), _peng(create_tile("万", 7)),
                 _peng(create_tile("饼", 5)), _peng(create_tile("条", 9))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert "大吊车 20花" in r.breakdown
        assert "碰碰胡" not in r.breakdown
        assert r.hua == 6 + 20

    def test_da_diao_che_dianpao(self):
        hand = [create_tile("风", "西")] * 2
        melds = [_peng(create_tile("万", 3)), _peng(create_tile("万", 7)),
                 _peng(create_tile("饼", 5)), _peng(create_tile("条", 9))]
        assert score_hand(hand, my_melds=melds, flowers=["春"], win_method="dianpao").hua == 2 + 10 + 1

    def test_xiao_diao_che(self):
        # Completed one-tile wait plus a chi meld -> 小吊车.
        hand = [create_tile("风", "西")] * 2
        melds = [_peng(create_tile("万", 3)), _peng(create_tile("万", 7)),
                 _chi(create_tile("饼", 5), create_tile("饼", 6), create_tile("饼", 7)),
                 _chi(create_tile("条", 1), create_tile("条", 2), create_tile("条", 3))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert "小吊车 10花" in r.breakdown
        assert r.hua == 6 + 10


class TestQingYiSe:
    def test_flush_with_runs(self):
        r = score_hand(H("m111 m222 m345 m678 m99"), win_method="zimo")
        assert "清一色 10花" in r.breakdown
        assert r.hua == 6 + 10

    def test_flush_dianpao(self):
        assert score_hand(H("m111 m222 m345 m678 m99"), flowers=["春"], win_method="dianpao").hua == 2 + 5 + 1

    def test_flush_plus_pengpeng_stacks(self):
        r = score_hand(H("m111 m222 m333 m444 m99"), win_method="zimo")
        assert r.hua == 6 + 10 + 10   # 无花自摸 + 清一色 + 碰碰胡

    def test_honors_break_flush(self):
        r = score_hand(H("m111 m222 m333 m444 南南"), win_method="zimo")
        assert "清一色" not in r.breakdown   # 南 is an honor


class TestSevenPairs:
    @pytest.mark.parametrize("method,pattern,total", [("zimo", 60, 65),
                                                      ("gangkai", 60, 69),
                                                      ("dianpao", 30, 33)])
    def test_triple_luxury(self, method, pattern, total):
        hand = H("m1111 p2222 s3333 北北")
        r = score_hand(hand, konged_flowers=["春"], flower_kong_groups=[["春"]], win_method=method)
        assert r.hua == total and r.pattern_hua == pattern
        assert f"三豪华 {pattern}花" in r.breakdown
        assert not any(b.startswith(("七对 ", "豪华七对 ", "双豪华 ", "暗杠", "明杠")) for b in r.breakdown)

    def test_triple_luxury_without_flower_is_self_draw_only(self):
        hand = H("m1111 p2222 s3333 北北")
        assert score_hand(hand, win_method="zimo").hua == 66
        with pytest.raises(ValueError, match="无花不能接炮"):
            score_hand(hand, win_method="dianpao")

    def test_triple_luxury_can_stack_with_flush(self):
        assert score_hand(H("m11112222333344"), win_method="zimo").hua == 6+60+10

    def test_plain(self):
        r = score_hand(H("m11 m22 p33 p44 s55 s66 南南"), win_method="zimo")
        assert r.hua == 6 + 10
        assert "七对 10花" in r.breakdown

    def test_luxury(self):
        # one quad (4张一样的) as two pairs + five pairs
        r = score_hand(H("m1111 m22 p33 p44 s55 s66"), flowers=["春"], win_method="dianpao")
        assert "豪华七对 10花" in r.breakdown
        assert "七对" not in [b.split()[0] for b in r.breakdown]   # 互斥
        assert r.hua == 2 + 10 + 1

    def test_double_luxury(self):
        r = score_hand(H("m1111 p2222 s33 s55 南南"), win_method="zimo")
        assert "双豪华 40花" in r.breakdown
        assert r.hua == 6 + 40

    def test_melds_block_seven_pairs(self):
        hand = H("m11 m22 p33 p44 s55 s66")
        r = score_hand(hand, my_melds=[_peng(create_tile("条", 9))], win_method="zimo")
        assert all("七对" not in b and "豪华" not in b for b in r.breakdown)


# --- combinations -------------------------------------------------------------
class TestCombinations:
    def test_gangkai_plus_pengpeng(self):
        # 杠开按自摸档计番型: 8 + 10
        r = score_hand(H("m111 p222 s333 南南南 西西"), win_method="gangkai")
        assert r.hua == 8 + 10 + 1   # +南风刻
        assert r.breakdown[0] == "杠开 8花"

    def test_qingyise_seven_pairs_stacks(self):
        r = score_hand(H("m11 m22 m33 m44 m55 m66 m77"), win_method="zimo")
        assert r.hua == 6 + 10 + 10   # 无花自摸 + 清一色 + 七对

    def test_flowers_add(self):
        r = score_hand(H("m123 m456 p789 s123 s99"),
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


# --- kong & flower-tile 花 (user-confirmed second table) ----------------------
class TestKongHua:
    def _win_with_kong(self, kong):
        # 2 concealed triplets + pair + 1 kong + 1 peng = valid win
        hand = H("m111 p222 南南")
        melds = [kong, _peng(create_tile("饼", 5))]
        return score_hand(hand, my_melds=melds, win_method="zimo")

    def test_ming_gang_number_is_five(self):
        r = self._win_with_kong(Meld("ming_gang", [create_tile("条", 9)] * 4))
        assert "明杠9条 5花" in r.breakdown
        assert r.hua == 4 + 10 + 5   # 自摸 + 碰碰胡 + 明杠

    def test_ming_gang_wind_is_six(self):
        r = self._win_with_kong(Meld("ming_gang", [create_tile("风", "南")] * 4))
        assert "明杠南风 6花" in r.breakdown
        assert r.hua == 4 + 10 + 6

    def test_an_gang_number_is_ten(self):
        r = self._win_with_kong(Meld("an_gang", [create_tile("条", 9)] * 4))
        assert "暗杠9条 10花" in r.breakdown
        assert r.hua == 4 + 10 + 10

    def test_an_gang_wind_is_twelve(self):
        r = self._win_with_kong(Meld("an_gang", [create_tile("风", "南")] * 4))
        assert r.hua == 4 + 10 + 12

    def test_multiple_kongs_stack(self):
        hand = [create_tile("风", "西")] * 2
        melds = [Meld("ming_gang", [create_tile("条", 9)] * 4),
                 Meld("an_gang", [create_tile("万", 3)] * 4),
                 _peng(create_tile("饼", 5)), _peng(create_tile("条", 1))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        # 大吊车 + 明杠5 + 暗杠10
        assert r.hua == 4 + 20 + 5 + 10


class TestHeldFlowerTiers:
    def _plain(self, flowers):
        return score_hand(H("m123 m456 p789 s123 s99"), flowers=flowers, win_method="zimo")

    def test_tier_one_two(self):
        assert self._plain(["中"]).hua == 4 + 1
        assert self._plain(["中", "中"]).hua == 4 + 2

    def test_tier_three_four(self):
        assert self._plain(["中"] * 3).hua == 4 + 4
        assert self._plain(["中"] * 4).hua == 4 + 6

    def test_seasons_one_each(self):
        assert self._plain(["春", "夏", "菊"]).hua == 4 + 3

    def test_mixed_multi_flowers(self):
        # 3个中(4花) + 2个发(2花) + 春(1花)
        assert self._plain(["中"] * 3 + ["发", "发"] + ["春"]).hua == 4 + 4 + 2 + 1


class TestKongedFlowers:
    def test_four_single_kongs_differ_from_one_concealed_kong(self):
        tiles = ["中"] * 4
        assert flower_hua([], tiles, [["中"]] * 4) == 6
        assert flower_hua([], tiles, [tiles]) == 12

    def test_held_and_individually_konged_flowers_share_one_tier(self):
        assert flower_hua(["中", "中"], ["中"], [["中"]]) == 4
        assert flower_hua(["中", "中", "中"], ["中"], [["中"]]) == 6

    def test_flower_replacement_win_uses_eight_base(self):
        result = score_hand(H("m123 m456 p789 s123 s99"),
                            konged_flowers=["中"], flower_kong_groups=[["中"]],
                            win_method="gangkai")
        assert result.base_hua == 8 and result.hua == 9

    def test_group_mismatch_rejected(self):
        with pytest.raises(ValueError, match="不一致"):
            flower_hua([], ["中"], [["中"] * 4])

    def test_konged_flower_replaces_tier(self):
        # 4个中杠掉 = 12花（不再叠手持4张档的6花）
        r = score_hand(H("m123 m456 p789 s123 s99"),
                       konged_flowers=["中"] * 4, win_method="zimo")
        assert "花牌 12花" in r.breakdown
        assert r.hua == 4 + 12

    def test_two_konged_flower_types(self):
        r = score_hand(H("m123 m456 p789 s123 s99"),
                       konged_flowers=["中"] * 4 + ["东风"] * 4, win_method="zimo")
        assert r.hua == 4 + 24

    def test_konged_seasons_still_one_each(self):
        r = score_hand(H("m123 m456 p789 s123 s99"),
                       konged_flowers=["夏", "菊"], win_method="zimo")
        assert r.hua == 4 + 2

    def test_dong_normalization(self):
        # both 东 and 东风 spell the multi-flower type
        assert score_hand(H("m123 m456 p789 s123 s99"),
                          flowers=["东", "东", "东"], win_method="zimo").hua == 4 + 4


class TestWindTripletHua:
    """南/西/北 3个一样（碰的或手上的）= +1花；杠了不另加。"""

    def test_concealed_triplet(self):
        r = score_hand(H("m123 p456 s789 南南南 西西"), win_method="zimo")
        assert "南风刻 1花" in r.breakdown
        assert r.hua == 4 + 1

    def test_peng_counts(self):
        # peng 南 (3 copies, none left in hand) + 西西 pair; 3 runs concealed
        hand = H("m123 p456 s789 西西")           # 11 tiles + 1 peng = win
        r = score_hand(hand, my_melds=[_peng(create_tile("风", "南"))], win_method="zimo")
        assert "南风刻 1花" in r.breakdown
        assert r.hua == 4 + 1

    def test_concealed_quad_is_nothing(self):
        # 4 held without konging can't fit the win shape -> scores nothing
        r = score_hand(H("m123 p456 s789 南南南 南"), win_method="zimo")
        assert all("南风刻" not in b for b in r.breakdown)

    def test_drawn_fourth_after_peng_is_konged_or_discarded(self):
        # 碰3南后摸回第4张：胡牌时不可能"拿在手里不杠"（那张配不成任何面子，
        # 不杠就胡不了）。两条真实出路各有测试：开明杠(+6替代+1) / 打掉(碰刻保持+1)。
        # 这里验证打掉第4张后的正常胡：碰刻仍 +1。
        hand = H("m123 p456 s789 西西")        # 4th 南 was discarded, pair is 西西
        r = score_hand(hand, my_melds=[_peng(create_tile("风", "南"))], win_method="zimo")
        assert "南风刻 1花" in r.breakdown
        assert r.hua == 4 + 1

    def test_peng_upgrade_to_ming_kang_replaces_one(self):
        # 碰后开明杠: +1 变 +6（替代，不是 6+1=7）
        hand = H("m111 p222 南南")
        melds = [Meld("ming_gang", [create_tile("风", "南")] * 4), _peng(create_tile("饼", 5))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert "南风刻" not in r.breakdown     # +1 replaced by the kong value
        assert r.hua == 4 + 10 + 6             # 自摸 + 碰碰胡 + 明杠南

    def test_two_wind_triplets(self):
        r = score_hand(H("m123 p456 南南南 北北北 西西"), win_method="zimo")
        assert r.hua == 4 + 1 + 1   # 南刻 + 北刻

    def test_pair_alone_is_zero(self):
        r = score_hand(H("m123 m456 p789 s123 s99"), win_method="zimo")
        assert all("风刻" not in b for b in r.breakdown)
        assert r.hua == 6

    def test_konged_wind_no_extra(self):
        # 明杠南=6、暗杠南=12 已含；不再+1
        hand = H("m111 p222 南南")
        melds = [Meld("ming_gang", [create_tile("风", "南")] * 4), _peng(create_tile("饼", 5))]
        r = score_hand(hand, my_melds=melds, win_method="zimo")
        assert all("南风刻" not in b for b in r.breakdown)
        assert r.hua == 4 + 10 + 6   # 自摸+碰碰胡+明杠南
