"""Tile counter / remaining-tile probability tests."""
import pytest

from src.core.tiles import create_tile, GameState, Meld
from src.core.probability import (
    TileCounter,
    count_remaining_tiles,
    discard_risk,
    estimate_discard_risks,
)


class TestTileCounter:
    def test_initial_number_count(self):
        c = TileCounter()
        assert c.get_count(create_tile("万", 3)) == 4
        assert c.get_count(create_tile("条", 9)) == 4

    def test_initial_honor_count(self):
        c = TileCounter()
        assert c.get_count(create_tile("风", "南")) == 4
        assert c.get_count(create_tile("风", "东")) == 4   # 东风: 4 copies
        assert c.get_count(create_tile("三元", "中")) == 4  # 中发白: 4 each

    def test_initial_season_count(self):
        c = TileCounter()
        for v in ("春", "夏", "秋", "冬", "梅", "兰", "竹", "菊"):
            assert c.get_count(create_tile("季节", v)) == 1

    def test_total_is_144(self):
        c = TileCounter()
        assert sum(c.all_counts().values()) == 144

    def test_remove(self):
        c = TileCounter()
        c.remove(create_tile("万", 3), 2)
        assert c.get_count(create_tile("万", 3)) == 2
        c.remove(create_tile("万", 3))
        assert c.get_count(create_tile("万", 3)) == 1

    def test_remove_clamps_at_zero(self):
        c = TileCounter()
        c.remove(create_tile("万", 3), 99)
        assert c.get_count(create_tile("万", 3)) == 0


class TestCountRemaining:
    def test_subtracts_hand(self):
        hand = [create_tile("万", i) for i in (1, 2, 3, 4)]
        state = GameState(my_hand=hand)
        rem = count_remaining_tiles(state)
        assert rem[create_tile("万", 1)] == 3   # 4 - 1 in hand
        assert rem[create_tile("万", 5)] == 4   # untouched

    def test_subtracts_discards(self):
        state = GameState()
        state.discards["left"] = [create_tile("万", 5), create_tile("万", 5)]
        state.discards["opposite"] = [create_tile("万", 5)]
        rem = count_remaining_tiles(state)
        assert rem[create_tile("万", 5)] == 1   # 4 - 3 discarded

    def test_subtracts_flowers_in_hand(self):
        state = GameState(flowers_in_hand=[create_tile("三元", "中")])
        rem = count_remaining_tiles(state)
        assert rem[create_tile("三元", "中")] == 3

    def test_subtracts_konged_flowers(self):
        state = GameState(konged_flowers=[create_tile("季节", "春")])
        rem = count_remaining_tiles(state)
        assert rem[create_tile("季节", "春")] == 0

    def test_subtracts_melds(self):
        meld = Meld(type="peng", tiles=[create_tile("万", 3)] * 3)
        state = GameState(melds={"left": [meld], "right": [], "opposite": []})
        rem = count_remaining_tiles(state)
        assert rem[create_tile("万", 3)] == 1   # 4 - 3 in the peng

    def test_subtracts_my_melds(self):
        meld = Meld(type="peng", tiles=[create_tile("万", 3)] * 3)
        state = GameState(my_melds=[meld])
        rem = count_remaining_tiles(state)
        assert rem[create_tile("万", 3)] == 1   # 4 - 3 in my peng

    def test_full_state(self):
        state = GameState(
            my_hand=[create_tile("万", 1)],
            flowers_in_hand=[create_tile("三元", "中")],
        )
        state.discards["right"] = [create_tile("万", 1)]
        rem = count_remaining_tiles(state)
        assert rem[create_tile("万", 1)] == 2   # 4 - 1 hand - 1 discard
        assert rem[create_tile("三元", "中")] == 3


class TestDiscardRisk:
    """discard_risk is a heuristic (安全/中/危险), not an exact probability."""

    def test_flower_is_safe(self):
        # flowers can't be part of a winning structure, so never deal into one
        assert discard_risk(create_tile("三元", "中"), GameState()) == "安全"

    def test_exhausted_tile_is_safe(self):
        # all four copies visible -> no hidden copies -> safe
        state = GameState(
            my_hand=[create_tile("万", 5)],
            discards={"left": [create_tile("万", 5)] * 3, "right": [], "opposite": []},
        )
        assert discard_risk(create_tile("万", 5), state) == "安全"

    def test_genbutu_seen_in_discard_is_safe(self):
        # an opponent already discarded it -> low ron risk (现物 heuristic)
        state = GameState(discards={"left": [create_tile("万", 5)], "right": [], "opposite": []})
        assert discard_risk(create_tile("万", 5), state) == "安全"

    def test_unseen_middle_tile_is_dangerous(self):
        # 4/5/6 are the most-wanted tiles; unseen and live -> dangerous
        state = GameState()
        assert discard_risk(create_tile("万", 5), state) == "危险"

    def test_unseen_honor_is_medium(self):
        state = GameState()
        assert discard_risk(create_tile("风", "南"), state) == "中"

    def test_unseen_terminal_is_medium(self):
        state = GameState()
        assert discard_risk(create_tile("万", 1), state) == "中"



class TestEstimateDiscardRisks:
    """estimate_discard_risks is a transparent heuristic (0..1 estimates + label)."""

    def test_structure(self):
        r = estimate_discard_risks(create_tile("万", 5), GameState())
        assert set(r) == {"chi", "peng", "ron", "label"}
        for key in ("chi", "peng", "ron"):
            assert 0.0 <= r[key] <= 1.0
        assert r["label"] in ("安全", "中", "危险")

    def test_flower_never_risks(self):
        r = estimate_discard_risks(create_tile("三元", "中"), GameState())
        assert (r["chi"], r["peng"], r["ron"]) == (0.0, 0.0, 0.0)
        assert r["label"] == "安全"

    def test_genbutu_ron_near_zero(self):
        # a tile already discarded by an opponent: ron risk drops toward 0
        state = GameState(discards={"left": [create_tile("万", 5)], "right": [], "opposite": []})
        safe = estimate_discard_risks(create_tile("万", 5), state)
        unseen = estimate_discard_risks(create_tile("万", 5), GameState())
        assert safe["ron"] < unseen["ron"]
        assert safe["ron"] < 0.05
        assert safe["label"] == "安全"

    def test_exhausted_ron_zero(self):
        state = GameState(
            my_hand=[create_tile("万", 5)],
            discards={"left": [create_tile("万", 5)] * 3, "right": [], "opposite": []},
        )
        r = estimate_discard_risks(create_tile("万", 5), state)
        assert r["ron"] == 0.0

    def test_honor_cannot_be_chied(self):
        r = estimate_discard_risks(create_tile("风", "南"), GameState())
        assert r["chi"] == 0.0

    def test_chi_only_from_left(self):
        # left throwing lots of 万 -> discarding 万 is likelier to be chied
        base = estimate_discard_risks(create_tile("万", 5), GameState())
        left_throws_wan = GameState(discards={
            "left": [create_tile("万", v) for v in (1, 2, 4, 9)],
            "right": [create_tile("饼", v) for v in (1, 2, 3)],
            "opposite": [],
        })
        biased = estimate_discard_risks(create_tile("万", 5), left_throws_wan)
        assert biased["chi"] > base["chi"]

    def test_peng_scales_with_hidden_copies(self):
        # fewer hidden copies -> lower peng chance
        full = estimate_discard_risks(create_tile("万", 5), GameState())
        drained = GameState(discards={
            "left": [create_tile("万", 5)], "right": [create_tile("万", 5)], "opposite": [],
        })
        thin = estimate_discard_risks(create_tile("万", 5), drained)
        assert thin["peng"] < full["peng"]

    def test_middle_tile_more_dangerous_than_terminal(self):
        mid = estimate_discard_risks(create_tile("万", 5), GameState())
        edge = estimate_discard_risks(create_tile("万", 1), GameState())
        assert mid["ron"] > edge["ron"]

    def test_matches_legacy_label(self):
        # the old coarse label and the new estimate agree on the label
        state = GameState()
        for tile in (create_tile("万", 5), create_tile("风", "南"), create_tile("万", 1)):
            assert estimate_discard_risks(tile, state)["label"] == discard_risk(tile, state)
