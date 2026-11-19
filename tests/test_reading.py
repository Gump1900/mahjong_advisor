"""Reading layer v1: discard-weighted world prior tests."""
import math

from src.core.tiles import GameState, Tile, create_tile, parse_tile
from src.decision.belief import HiddenWorld
from src.decision.reading import suit_reads, world_weight

T = parse_tile
SUITS = ("万", "饼", "条")
WINDS = ("南", "西", "北")
ALPHA = 0.35
FLOOR = 0.01


def _world(hands: dict, flowers: dict) -> HiddenWorld:
    return HiddenWorld(
        hands={seat: [T(t) for t in h] for seat, h in hands.items()},
        flowers={seat: [T(t) for t in f] for seat, f in flowers.items()},
        wall=[])


def _state_with_rivers(rivers: dict) -> GameState:
    state = GameState(my_hand=[T(t) for t in
        "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条 9条".split()])
    for seat, river in rivers.items():
        state.discards[seat] = [T(t) for t in river]
    return state


class TestWorldWeight:
    def test_dumping_suit_downweights_holding_it(self):
        state = _state_with_rivers({"left": ["2条", "5条", "8条", "9条", "4条"]})
        # 两个候选世界：left 囤 6 张条 vs 囤 1 张条
        hand_many_tiao = (
            "1条 2条 3条 4条 5条 6条 7万 8万 9万 1饼 2饼 3饼 4万"
        ).split()
        hand_few_tiao = (
            "1万 2万 3万 5万 6万 7万 8万 9万 1饼 2饼 3饼 4饼 4万"
        ).split()
        base = {s: "2条 4条 6条 8条 1万 3万 5万 7万 9万 2饼 4饼 6饼 8饼".split()
                for s in ("opposite", "right")}
        w_many = world_weight(_world({"left": hand_many_tiao, **base},
                                     {"left": [], "opposite": [], "right": []}), state)
        w_few = world_weight(_world({"left": hand_few_tiao, **base},
                                    {"left": [], "opposite": [], "right": []}), state)
        assert w_few / w_many > 1.5

    def test_no_discards_is_flat(self):
        state = _state_with_rivers({})
        hand_a = "1条 2条 3条 4条 5条 6条 7万 8万 9万 1饼 2饼 3饼 4万".split()
        hand_b = "1万 2万 3万 5万 6万 7万 8万 9万 1饼 2饼 3饼 4饼 4万".split()
        base = {s: "2条 4条 6条 8条 1万 3万 5万 7万 9万 2饼 4饼 6饼 8饼".split()
                for s in ("opposite", "right")}
        w_a = world_weight(_world({"left": hand_a, **base},
                                  {"left": [], "opposite": [], "right": []}), state)
        w_b = world_weight(_world({"left": hand_b, **base},
                                  {"left": [], "opposite": [], "right": []}), state)
        assert math.isclose(w_a, w_b, rel_tol=1e-9)

    def test_wind_dumps_downweight_wind_pair(self):
        state = _state_with_rivers({"left": ["南", "南"]})
        pair_hand = "1万 2万 3万 4万 5万 6万 7万 8万 9万 南 南 1饼 2饼".split()
        none_hand = "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 4饼".split()
        base = {s: "2条 4条 6条 8条 1万 3万 5万 7万 9万 2饼 4饼 6饼 8饼".split()
                for s in ("opposite", "right")}
        w_pair = world_weight(_world({"left": pair_hand, **base},
                                     {"left": [], "opposite": [], "right": []}), state)
        w_none = world_weight(_world({"left": none_hand, **base},
                                     {"left": [], "opposite": [], "right": []}), state)
        assert w_none > w_pair

    def test_weight_floored_positive(self):
        state = _state_with_rivers({"left": ["2条"] * 4 + ["5条"] * 4})
        hand = "1条 2条 3条 4条 5条 6条 7条 8条 9条 1万 2万 3万 4万".split()
        base = {s: "2条 4条 6条 8条 1万 3万 5万 7万 9万 2饼 4饼 6饼 8饼".split()
                for s in ("opposite", "right")}
        w = world_weight(_world({"left": hand, **base},
                                {"left": [], "opposite": [], "right": []}), state)
        assert w >= FLOOR


class TestSuitReads:
    def test_read_direction_from_rivers(self):
        state = _state_with_rivers({"left": ["2条", "5条", "8条", "9条"]})
        worlds = [_world({"left": "1万 2万 3万 5万 6万 7万 8万 9万 1饼 2饼 3饼 4饼 4万".split(),
                          "opposite": [], "right": []}, {"left": [], "opposite": [], "right": []})]
        reads = suit_reads(state, [("left", worlds[0].hands["left"])])
        assert reads["left"]["条"] == "↓"


class TestDealRiskDifferentiation:
    def test_dumped_suit_candidate_gets_lower_risk(self):
        """设计验收#2：同一种子下，对手弃满条 vs 弃满万，
        我打条候选的点炮先验应更低（读牌抑制'他囤条'的世界）。"""
        from src.decision.ev import deal_risks

        def state_with_river(suit_tiles):
            state = _state_with_rivers({"left": suit_tiles})
            return state

        tiao_dumped = state_with_river(["2条", "5条", "8条", "9条"])
        wan_dumped = state_with_river(["2万", "5万", "8万", "9万"])
        cand = [T("6条")]
        risk_tiao = deal_risks(tiao_dumped, cand, samples=256, seed=7)[cand[0]]
        risk_wan = deal_risks(wan_dumped, cand, samples=256, seed=7)[cand[0]]
        assert risk_tiao.p_hi <= risk_wan.p_hi + 0.02   # 结构上界受抑制


class TestAdjacencyGradedEvidence:
    """用户指正：7899 打9 正常 → 弃边张对邻张持有只有轻微证据；
    弃中张（冗余解释少）证据才重。分级由 centrality 决定。"""

    def _two_worlds(self, held_pair):
        base = {s: "2条 4条 6条 8条 1万 3万 5万 7万 9万 2饼 4饼 6饼 8饼".split()
                for s in ("opposite", "right")}
        def world(held):
            return _world(
                {"left": held, **base},
                {"left": [], "opposite": [], "right": []})
        return world, base

    def test_middle_discard_is_strong_evidence(self):
        # 弃5万：持46万 的世界明显降权
        world, base = self._two_worlds(None)
        state = _state_with_rivers({"left": ["5万"]})
        w_with = world("4万 6万 1条 2条 3条 4条 5条 7条 8条 9条 2饼 4饼 6饼".split())
        w_without = world("4条 6条 1条 2条 3条 4条 5条 7条 8条 9条 2饼 4饼 6饼".split())
        assert world_weight(w_without, state) / world_weight(w_with, state) > 1.3

    def test_terminal_discard_is_weak_evidence(self):
        # 弃9万：持78万 的世界只轻微降权（7899 也会弃9）
        world, base = self._two_worlds(None)
        state = _state_with_rivers({"left": ["9万"]})
        w_with = world("7万 8万 1条 2条 3条 4条 5条 6条 7条 8条 9条 2饼 4饼".split())
        w_without = world("1条 2条 3条 4条 5条 6条 7条 8条 9条 2饼 4饼 6饼 8饼".split())
        ratio = world_weight(w_without, state) / world_weight(w_with, state)
        assert 1.0 < ratio < 1.15   # 有信号，但很轻

    def test_middle_stronger_than_terminal(self):
        world, base = self._two_worlds(None)
        filler = "1条 2条 3条 4条 5条 7条 8条 9条 2饼 4饼 6饼".split()
        w_hold46 = world(["4万", "6万"] + filler)
        w_hold78 = world(["7万", "8万"] + filler)
        w_no = world("1条 2条 3条 4条 5条 6条 7条 8条 9条 2饼 4饼 6饼 8饼".split())
        mid = _state_with_rivers({"left": ["5万"]})
        term = _state_with_rivers({"left": ["9万"]})
        mid_ratio = world_weight(w_no, mid) / world_weight(w_hold46, mid)
        term_ratio = world_weight(w_no, term) / world_weight(w_hold78, term)
        # 对数证据比（等价于 odds 空间的强度比较）：中张显著强于边张
        assert math.log(mid_ratio) > 1.5 * math.log(term_ratio)
