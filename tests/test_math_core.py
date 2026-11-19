"""Closed-form math core tests: n_eff / wall model / efficiency / hypergeometric."""
import random

import pytest

from src.core.hand_analyzer import get_ukeire
from src.core.math_core import (
    e_efficiency,
    expected_neff_1ply,
    hypergeom_pmf,
    n_eff,
    n_eff_kinds,
    opp_structural_total,
    p_hit,
    wall_adjusted,
)
from src.core.tiles import GameState, Meld, Tile, create_tile, parse_tile


def _full_unseen() -> dict:
    counts = {}
    for suit in ("万", "饼", "条"):
        for v in range(1, 10):
            counts[create_tile(suit, v)] = 4
    return counts


class TestNEff:
    def test_n_eff_matches_ukeire_live_count(self):
        hand = [parse_tile(t) for t in
                "1万 1万 2万 3万 5万 5万 7万 8万 9万 2饼 3饼 4饼 9条".split()]
        unseen = _full_unseen()
        expected = sum(unseen[u] for u in get_ukeire(hand, 0))
        assert n_eff(hand, 0, unseen) == expected

    def test_n_eff_kinds_equals_ukeire(self):
        hand = [parse_tile(t) for t in
                "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 1饼 2饼 3饼".split()]
        assert n_eff_kinds(hand, 0) == get_ukeire(hand, 0)

    def test_n_eff_flowers_contribute_zero(self):
        hand = [parse_tile(t) for t in
                "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 1饼 2饼 3饼".split()]
        unseen = _full_unseen()
        unseen[create_tile("三元", "中")] = 4
        assert n_eff(hand, 0, unseen) == sum(unseen[u] for u in get_ukeire(hand, 0))
        assert all(not u.is_flower for u in get_ukeire(hand, 0))

    def test_n_eff_rejects_bad_hand_length(self):
        with pytest.raises(ValueError, match="手牌张数"):
            n_eff([parse_tile("1万")], 0, {})


class TestWallAdjusted:
    def test_uniform_share_is_constant_ratio(self):
        unseen = {create_tile("万", v): 4 for v in range(1, 10)}
        wall = wall_adjusted(unseen, opp_structural_total=18)
        # unseen_total=36, wall_total=36-18=18 -> ratio 0.5 for every tile
        assert sum(wall.values()) == 18
        for tile, n_wall in wall.items():
            assert n_wall == unseen[tile] * 0.5

    def test_zero_opponents_returns_unseen(self):
        unseen = {create_tile("万", 1): 3, create_tile("饼", 9): 1}
        assert wall_adjusted(unseen, 0) == unseen

    def test_exhausted_wall_returns_zero(self):
        unseen = {create_tile("万", 1): 3, create_tile("饼", 9): 1}
        assert all(v == 0 for v in wall_adjusted(unseen, 4).values())

    def test_empty_unseen_is_empty(self):
        assert wall_adjusted({}, 12) == {}

    def test_opp_structural_total_counts_three_seats(self):
        state = GameState()
        state.melds = {
            "left": [Meld(type="peng", tiles=[create_tile("万", 1)] * 3)],
            "opposite": [],
            "right": [],
        }
        # 13-3 + 13 + 13 = 36
        assert opp_structural_total(state) == 36

    def test_opp_structural_total_floors_at_zero(self):
        state = GameState()
        state.melds = {
            "left": [Meld(type="peng", tiles=[create_tile("万", 1)] * 3)] * 4,
            "opposite": [Meld(type="chi", tiles=[create_tile("万", 2), create_tile("万", 3), create_tile("万", 4)])],
            "right": [],
        }
        assert opp_structural_total(state) == 1 + 10 + 13


class TestEfficiencyAndHypergeometric:
    def test_e_efficiency_ratio_and_bounds(self):
        assert e_efficiency(4, 20) == pytest.approx(0.2)
        assert e_efficiency(0, 20) == 0.0

    def test_p_hit_hand_computed_case(self):
        # 1 - C(7,2)/C(10,2) = 1 - 21/45 = 8/15
        assert p_hit(2, 10, 3) == pytest.approx(8 / 15)

    def test_p_hit_monotonic_in_k(self):
        prev = -1.0
        for k in range(0, 8):
            value = p_hit(k, 10, 3)
            assert value >= prev
            prev = value

    def test_p_hit_boundaries(self):
        assert p_hit(0, 10, 3) == 0.0
        assert p_hit(2, 10, 10) == 1.0   # hits >= n_wall
        assert p_hit(11, 10, 3) == 1.0   # k > n_wall

    def test_p_hit_empty_wall(self):
        assert p_hit(3, 0, 0) == 0.0
        assert e_efficiency(3, 0) == 0.0

    def test_p_hit_matches_sampling(self):
        rng = random.Random(7)
        n_wall, hits, k = 30, 6, 4
        trials = 4000
        hit_set = set(range(hits))
        made = 0
        pool = list(range(n_wall))
        for _ in range(trials):
            drawn = rng.sample(pool, k)
            if hit_set.intersection(drawn):
                made += 1
        assert abs(made / trials - p_hit(k, n_wall, hits)) < 0.02

    def test_hypergeom_pmf_sums_to_one(self):
        n_wall, hits, k = 20, 5, 6
        total = sum(hypergeom_pmf(x, n_wall, hits, k) for x in range(k + 1))
        assert total == pytest.approx(1.0)

    def test_hypergeom_pmf_value(self):
        # P(X=1): C(5,1)*C(15,2)/C(20,3)
        assert hypergeom_pmf(1, 20, 5, 3) == pytest.approx(5 * 105 / 1140)


class TestExpectedNeff1ply:
    def _wall(self):
        return {create_tile(s, v): 4
                for s in ("万", "饼", "条") for v in range(1, 10)}

    def test_expected_neff_matches_direct_summation(self):
        hand = [parse_tile(t) for t in
                "1万 2万 3万 4万 5万 6万 7万 8万 9万 2饼 3饼 5饼 9条".split()]
        wall = self._wall()
        n_wall = sum(wall.values())
        discard = parse_tile("9条")
        rest = [t for t in hand if t != discard]
        expected = 0.0
        for y, w in wall.items():
            if w <= 0:
                continue
            expected += w / n_wall * n_eff(rest + [y], 0, wall)
        value, exact = expected_neff_1ply(hand, 0, discard, wall)
        assert exact is True
        assert value == pytest.approx(expected)

    def test_expected_neff_prefers_keeping_both_taatsu_same_shanten(self):
        # 打9条保留 23饼+56饼 两搭 vs 打5饼只剩 23饼 一搭（同为一向听）
        hand = [parse_tile(t) for t in
                "1万 2万 3万 4万 5万 6万 7万 8万 9万 2饼 3饼 5饼 9条".split()]
        wall = self._wall()
        keep_both, _ = expected_neff_1ply(hand, 0, parse_tile("9条"), wall)
        keep_one, _ = expected_neff_1ply(hand, 0, parse_tile("5饼"), wall)
        assert keep_both > keep_one

    def test_expected_neff_deadline_zero_is_approximate(self):
        hand = [parse_tile(t) for t in
                "1万 2万 3万 4万 5万 6万 7万 8万 9万 2饼 3饼 5饼 9条".split()]
        value, exact = expected_neff_1ply(hand, 0, parse_tile("9条"), self._wall(),
                                          deadline_s=0)
        assert exact is False
        assert value >= 0.0

    def test_expected_neff_empty_wall_returns_zero(self):
        hand = [parse_tile(t) for t in
                "1万 2万 3万 4万 5万 6万 7万 8万 9万 2饼 3饼 5饼 9条".split()]
        value, exact = expected_neff_1ply(hand, 0, parse_tile("9条"), {})
        assert value == 0.0 and exact is True
