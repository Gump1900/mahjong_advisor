"""Confirmed local rules: multi-ron, claim priority and final-only payments."""
from itertools import permutations

import pytest

from src.core.round_rules import Claim, can_win_on_discard, resolve_claims, settle_round
from src.core.tiles import parse_tile


def test_all_ron_winners_survive_regardless_of_arrival_order():
    declarations = [Claim("me", "ron"), Claim("right", "ron"), Claim("opposite", "ron")]
    for order in permutations(declarations):
        assert resolve_claims("left", order) == tuple(declarations)


def test_ron_beats_gang_and_peng_beats_chi():
    assert resolve_claims("left", [Claim("me", "chi"), Claim("right", "peng")]) == (Claim("right", "peng"),)
    assert resolve_claims("left", [Claim("me", "ron"), Claim("right", "gang")]) == (Claim("me", "ron"),)


def test_chi_requires_the_upstream_seat_and_cannot_claim_own_discard():
    with pytest.raises(ValueError, match="上家"):
        resolve_claims("left", [Claim("right", "chi")])
    with pytest.raises(ValueError, match="以外"):
        resolve_claims("left", [Claim("left", "ron")])


def test_multi_ron_charges_only_the_discarder_for_each_winner():
    settlement = settle_round("dianpao", {"me": 7, "opposite": 12}, "left")
    assert settlement.net == {"me": 7, "left": -19, "opposite": 12, "right": 0}
    assert sum(settlement.net.values()) == 0


@pytest.mark.parametrize("method", ["zimo", "gangkai"])
def test_self_draw_charges_all_three_separately(method):
    settlement = settle_round(method, {"me": 6})
    assert settlement.net == {"me": 18, "left": -6, "opposite": -6, "right": -6}


def test_draw_has_no_kong_payment_or_penalty():
    settlement = settle_round("draw", {})
    assert not settlement.payments
    assert set(settlement.net.values()) == {0}


def test_invalid_or_inconsistent_settlement_rejected():
    for method, amounts, source in [
        ("draw", {"me": 10}, None), ("dianpao", {"me": 10}, "me"),
        ("zimo", {"me": 6, "left": 6}, None), ("zimo", {"me": -1}, None),
    ]:
        with pytest.raises(ValueError):
            settle_round(method, amounts, source)


def test_ron_requires_qualifying_hua_not_just_a_winning_structure():
    hand = [parse_tile(t) for t in "1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 1条 2条 3条 9条".split()]
    assert not can_win_on_discard(hand, parse_tile("9条"))
    assert can_win_on_discard(hand, parse_tile("9条"), flowers=["春"])
