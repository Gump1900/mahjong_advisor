"""Sampling EV tests: P_deal / V_deal with eligibility & interlock gates."""
import pytest

from src.decision.belief import HiddenWorld
from src.decision.ev import DealRisk, deal_risks, evaluate_world
from src.core.round_rules import locked_pairs
from src.core.tiles import GameState, Tile, create_tile, parse_tile

T = parse_tile
WAITING_13 = "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条"   # 单吊 5条
MY_13 = "2条 4条 6条 8条 1万 3万 5万 7万 9万 2饼 4饼 6饼 8饼"


def _world(hands: dict, flowers: dict) -> HiddenWorld:
    return HiddenWorld(hands=hands, flowers=flowers, wall=[])


def _state(**kw) -> GameState:
    state = GameState(my_hand=[T(t) for t in MY_13.split()])
    for key, value in kw.items():
        setattr(state, key, value)
    return state


class TestEvaluateWorld:
    def test_eligible_opponent_rons_on_wait(self):
        world = _world(
            hands={"left": [T(t) for t in WAITING_13.split()], "opposite": [T(t) for t in MY_13.split()], "right": [T(t) for t in MY_13.split()]},
            flowers={"left": [T("中")], "opposite": [], "right": []},
        )
        result = evaluate_world(world, _state(), [T("5条"), T("9条")])
        assert set(result["ronners"][T("5条")]) == {"left"}
        assert result["ronners"][T("9条")] == set()

    def test_no_flower_opponent_cannot_ron(self):
        world = _world(
            hands={"left": [T(t) for t in WAITING_13.split()], "opposite": [T(t) for t in MY_13.split()], "right": [T(t) for t in MY_13.split()]},
            flowers={"left": [], "opposite": [], "right": []},
        )
        result = evaluate_world(world, _state(), [T("5条")])
        assert result["ronners"][T("5条")] == set()          # 无资格
        assert result["structural"][T("5条")] == {"left"}    # 结构上在听

    def test_interlocked_opponent_excluded_even_structural(self):
        state = _state(chi_peng_source_counts={"left": {"me": 3}})
        world = _world(
            hands={"left": [T(t) for t in WAITING_13.split()], "opposite": [T(t) for t in MY_13.split()], "right": [T(t) for t in MY_13.split()]},
            flowers={"left": [T("中")], "opposite": [], "right": []},
        )
        result = evaluate_world(world, state, [T("5条")])
        assert result["ronners"][T("5条")] == set()
        assert result["structural"][T("5条")] == set()       # 互锁连结构层都排除

    def test_multi_ron_sums_payments(self):
        world = _world(
            hands={"left": [T(t) for t in WAITING_13.split()],
                   "opposite": [T(t) for t in WAITING_13.split()],
                   "right": [T(t) for t in MY_13.split()]},
            flowers={"left": [T("中")], "opposite": [T("发")], "right": []},
        )
        result = evaluate_world(world, _state(), [T("5条")])
        assert result["ronners"][T("5条")] == {"left", "opposite"}
        # 两家各自 settle("dianpao", hua, source=me) 之和
        assert result["my_payment"][T("5条")] < 0
        assert result["my_payment"][T("5条")] == result["hua_sum"][T("5条")] * -1

    def test_flower_candidate_never_rons(self):
        world = _world(
            hands={"left": [T(t) for t in WAITING_13.split()], "opposite": [T(t) for t in MY_13.split()], "right": [T(t) for t in MY_13.split()]},
            flowers={"left": [T("中")], "opposite": [], "right": []},
        )
        result = evaluate_world(world, _state(), [T("中")])
        assert result["ronners"][T("中")] == set()
        assert result["structural"][T("中")] == set()


class TestDealRisks:
    def test_deterministic_given_seed(self):
        state = _state()
        cands = [T("5条"), T("9条")]
        first = deal_risks(state, cands, samples=32, seed=3)
        second = deal_risks(state, cands, samples=32, seed=3)
        assert first == second

    def test_bounds_order(self):
        state = _state()
        risks = deal_risks(state, [T("5条")], samples=32, seed=1)
        risk = risks[T("5条")]
        assert risk.p_lo <= risk.p_point <= risk.p_hi <= 1.0

    def test_bounds_collapse_when_flowers_complete(self):
        state = _state()
        state.opponent_flowers = {"left": [T("中")], "opposite": [], "right": []}
        state.opponent_flowers_complete = {"left": True, "opposite": True, "right": True}
        risks = deal_risks(state, [T("5条")], samples=32, seed=5)
        risk = risks[T("5条")]
        assert risk.p_lo == risk.p_point == risk.p_hi

    def test_deal_risk_shape(self):
        state = _state()
        risks = deal_risks(state, [T("5条")], samples=16, seed=0)
        risk = risks[T("5条")]
        assert isinstance(risk, DealRisk)
        assert risk.v_deal >= 0


# --- V_win / EV 排序 ----------------------------------------------------------------
from src.decision.ev import CandidateEV, rank_candidates, sort_candidates
from src.core.tiles import Meld


class TestRankCandidates:
    def test_deterministic_ordering(self):
        state = _state()
        first = rank_candidates(state, samples=16, seed=2)
        second = rank_candidates(state, samples=16, seed=2)
        assert [(str(c.tile), round(c.ev, 9)) for c in first] == \
               [(str(c.tile), round(c.ev, 9)) for c in second]

    def test_tenpai_candidate_carries_attack_term(self):
        # 14张：打9条=单吊5条（听牌），打5条=单吊9条（听牌）
        state = GameState(my_hand=[T(t) for t in
            "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条 9条".split()],
            flowers_in_hand=[T("中")])
        ranked = rank_candidates(state, samples=16, seed=0)
        by_tile = {c.tile: c for c in ranked}
        keep5 = by_tile[T("9条")]   # 打9条 → 听5条
        assert keep5.p_win_next > 0
        assert keep5.v_win > 0
        assert keep5.ev == pytest.approx(
            keep5.p_win_next * keep5.v_win - keep5.p_point * keep5.v_deal)

    def test_non_tenpai_ev_is_defense_only(self):
        state = _state()   # MY_13 杂牌一向听/更远
        ranked = rank_candidates(state, samples=16, seed=1)
        for cand in ranked:
            if cand.p_win_next == 0:
                assert cand.ev == pytest.approx(-cand.p_point * cand.v_deal)
                break

    def test_ev_rank_exhausted_wall(self):
        # 把未见牌压到恰好等于对手暗牌数：墙空，不得抛异常
        state = GameState(my_hand=[T("1万")])
        state.my_melds = [Meld("peng", [T("2万")] * 3), Meld("chi", [T("3万"), T("4万"), T("5万")]),
                          Meld("peng", [T("6万")] * 3), Meld("chi", [T("7万"), T("8万"), T("9万")])]
        state.melds["left"] = [Meld("peng", [T("1饼")] * 3), Meld("chi", [T("2饼"), T("3饼"), T("4饼")]),
                               Meld("peng", [T("5饼")] * 3), Meld("chi", [T("6饼"), T("7饼"), T("8饼")])]
        state.melds["opposite"] = [Meld("peng", [T("1条")] * 3), Meld("chi", [T("2条"), T("3条"), T("4条")]),
                                   Meld("peng", [T("5条")] * 3), Meld("chi", [T("6条"), T("7条"), T("8条")])]
        state.melds["right"] = [Meld("peng", [T("南")] * 3), Meld("peng", [T("西")] * 3),
                                Meld("peng", [T("北")] * 3), Meld("chi", [T("3万"), T("4万"), T("5万")])]
        # 用弃牌河吞掉全部未见牌，只留 3 张 9条（对手暗牌恰好分完，墙=0）
        from src.core.probability import count_remaining_tiles
        remaining = count_remaining_tiles(state)
        for tile, n in remaining.items():
            keep = 3 if str(tile) == "9条" else 0
            state.discards["left"].extend([tile] * (n - keep))
        ranked = rank_candidates(state, samples=8, seed=0)
        assert all(c.p_win_next == 0.0 for c in ranked)
        assert all(c.ev == pytest.approx(-c.p_point * c.v_deal) for c in ranked)

    def test_zimo_pays_locked_triple(self):
        hand = [T(t) for t in
                "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条 9条".split()]
        unlocked = rank_candidates(
            GameState(my_hand=hand, flowers_in_hand=[T("中")]), samples=16, seed=0)
        locked_state = GameState(my_hand=hand, flowers_in_hand=[T("中")],
                                 chi_peng_source_counts={"left": {"me": 3}})
        locked = rank_candidates(locked_state, samples=16, seed=0)
        u = {c.tile: c for c in unlocked}[T("9条")].v_win
        l = {c.tile: c for c in locked}[T("9条")].v_win
        # 直接互锁者(left)付3倍：总赔付 3+1+1=5 份 vs 3 份
        assert l == pytest.approx(u * 5 / 3)


class TestSortCandidates:
    def _c(self, tile, ev, p, neff):
        return CandidateEV(tile=T(tile), ev=ev, p_win_next=0, v_win=0,
                           p_point=p, p_lo=p, p_hi=p, v_deal=0,
                           exp_neff_1ply=neff, exp_neff_exact=True, labels=[])

    def test_tiebreak_stability(self):
        # 规则 v2：EV 桶内先比结构（进张/改善概率），噪声级点炮差不算信号
        cands = [self._c("9条", 1.0, 0.2, 4), self._c("5条", 1.0, 0.1, 2),
                 self._c("1万", 1.0, 0.1, 8), self._c("3万", 2.0, 0.9, 0)]
        ordered = sort_candidates(cands, tol=0.3)
        assert [str(c.tile) for c in ordered] == ["3万", "1万", "9条", "5条"]
        assert sort_candidates(list(reversed(cands)), tol=0.3) == ordered


class TestPairedCandidate:
    def test_discard_from_pair_keeps_attack_term(self):
        # 手握 9饼9饼 对子：打 9饼 应留下单吊 9饼 的听牌结构
        state = GameState(my_hand=[T(t) for t in
            "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 9饼 9饼".split()])
        ranked = rank_candidates(state, samples=8, seed=0)
        cand = {c.tile: c for c in ranked}[T("9饼")]
        assert cand.p_win_next > 0
        assert cand.exp_neff_1ply > 0


class TestBoundsCollapseComplete:
    def test_complete_seat_structural_collapses_to_eligible(self):
        # 花观测完整 + 有花：结构层 == 资格层（hi 收敛）
        world = _world(
            hands={"left": [T(t) for t in WAITING_13.split()],
                   "opposite": [T(t) for t in MY_13.split()],
                   "right": [T(t) for t in MY_13.split()]},
            flowers={"left": [T("中")], "opposite": [], "right": []},
        )
        state = _state()
        state.opponent_flowers = {"left": [T("中")], "opposite": [], "right": []}
        state.opponent_flowers_complete = {"left": True, "opposite": True, "right": True}
        result = evaluate_world(world, state, [T("5条")])
        assert result["structural"][T("5条")] == result["ronners"][T("5条")] == {"left"}

    def test_complete_seat_without_flowers_never_structural(self):
        # 花观测完整 + 无花：该家确定无资格，结构层也必须为空（否则 p_hi 虚高）
        world = _world(
            hands={"left": [T(t) for t in WAITING_13.split()],
                   "opposite": [T(t) for t in MY_13.split()],
                   "right": [T(t) for t in MY_13.split()]},
            flowers={"left": [], "opposite": [], "right": []},
        )
        state = _state()
        state.opponent_flowers_complete = {"left": True, "opposite": True, "right": True}
        result = evaluate_world(world, state, [T("5条")])
        assert result["structural"][T("5条")] == set()
        assert result["ronners"][T("5条")] == set()

    def test_incomplete_seat_keeps_structural_bound(self):
        # 花观测不完整：资格不确定，结构上界必须保留
        world = _world(
            hands={"left": [T(t) for t in WAITING_13.split()],
                   "opposite": [T(t) for t in MY_13.split()],
                   "right": [T(t) for t in MY_13.split()]},
            flowers={"left": [], "opposite": [], "right": []},
        )
        state = _state()
        result = evaluate_world(world, state, [T("5条")])
        assert result["structural"][T("5条")] == {"left"}


class TestLabelsAndPerf:
    def test_consult_mode_labeled(self):
        state = _state()   # 13 张（摸牌前咨询）
        ranked = rank_candidates(state, samples=8, seed=0)
        assert ranked and all("咨询:摸牌前" in c.labels for c in ranked)
        state14 = GameState(my_hand=[T(t) for t in MY_13.split()] + [T("9条")])
        ranked14 = rank_candidates(state14, samples=8, seed=0)
        assert all("咨询:摸牌前" not in c.labels for c in ranked14)

    def test_bounds_labels_present(self):
        state = _state()
        risks = deal_risks(state, [T("5条")], samples=16, seed=0)
        labels = risks[T("5条")].labels
        assert "上界:p_hi(结构)" in labels
        assert "下界:p_lo(资格确证)" in labels

    def test_perf_contract_under_1s_at_128_samples(self):
        import time
        state = GameState(my_hand=[T(t) for t in MY_13.split()] + [T("9条")])
        start = time.monotonic()
        rank_candidates(state, samples=128, seed=0)
        assert time.monotonic() - start < 1.0


class TestConsultModeStructure:
    def test_consult_mode_discriminates_isolated_vs_taatsu(self):
        # 用户实测手牌（13张咨询态）：打孤张9万 必须优于 拆35万嵌张
        state = GameState(my_hand=[T(t) for t in
            "3万 5万 9万 2饼 3饼 2条 3条 6条 7条 8条 9条 南风 南风".split()])
        ranked = rank_candidates(state, samples=8, seed=0)
        tiles = [str(c.tile) for c in ranked]
        assert tiles.index("9万") < tiles.index("5万")
        assert tiles.index("9万") < tiles.index("3万")
        assert ranked[0].exp_neff_1ply != ranked[-1].exp_neff_1ply

    def test_noise_level_p_does_not_outrank_structure(self):
        # EV 全零 + 点炮差异在采样噪声内：结构（进张）先决
        from src.decision.ev import sort_candidates
        a = CandidateEV(tile=T("9万"), ev=0.0, p_win_next=0, v_win=0,
                        p_point=0.09, p_lo=0.09, p_hi=0.09, v_deal=0,
                        exp_neff_1ply=20.0, exp_neff_exact=True, labels=[])
        b = CandidateEV(tile=T("5万"), ev=0.0, p_win_next=0, v_win=0,
                        p_point=0.01, p_lo=0.01, p_hi=0.01, v_deal=0,
                        exp_neff_1ply=12.0, exp_neff_exact=True, labels=[])
        assert sort_candidates([a, b], tol=0.3)[0].tile == T("9万")

    def test_real_ev_gap_still_dominates(self):
        from src.decision.ev import sort_candidates
        a = CandidateEV(tile=T("9万"), ev=0.0, p_win_next=0, v_win=0,
                        p_point=0.0, p_lo=0, p_hi=0, v_deal=0,
                        exp_neff_1ply=20.0, exp_neff_exact=True, labels=[])
        b = CandidateEV(tile=T("5万"), ev=2.0, p_win_next=0.1, v_win=20,
                        p_point=0.0, p_lo=0, p_hi=0, v_deal=0,
                        exp_neff_1ply=1.0, exp_neff_exact=True, labels=[])
        assert sort_candidates([a, b], tol=0.3)[0].tile == T("5万")


class TestDecisionModeShantenFirst:
    def test_breaking_structure_never_outranks_float(self):
        # 用户实测：6778条形 + 浮牌；拆结构(打7条→3向听)不得排在浮牌(保持2向听)前
        state = GameState(my_hand=[T(t) for t in
            "6万 6万 8万 2饼 4饼 4饼 6饼 7饼 6条 7条 7条 8条 8条 3万".split()])
        ranked = rank_candidates(state, samples=8, seed=0)
        tiles = [str(c.tile) for c in ranked]
        assert tiles.index("2饼") < tiles.index("7条")
        assert tiles.index("8万") < tiles.index("8条")
        assert ranked[0].stand_shanten <= min(c.stand_shanten for c in ranked)


class TestOnePlyTiebreak:
    def test_isolated_honor_loses_to_evolvable_float_on_tie(self):
        # 用户实测：六个候选静态全同分(2向听/15活张)，1-ply 应分出
        # 北风(纯孤张只能等对)劣于 5饼(可进化成搭子)→ 打北风排前
        state = GameState(my_hand=[T(t) for t in
            "3万 3万 2饼 2饼 5饼 7饼 9饼 3条 3条 4条 8条 9条 9条 北风".split()])
        ranked = rank_candidates(state, samples=64, seed=0)
        tiles = [str(c.tile) for c in ranked[:6]]
        assert "北风" == tiles[0]
        assert tiles.index("北风") < tiles.index("5饼")


class TestConventionTiebreak:
    """教学决胜（用户 2026-11-15 实局指正）：后劲差<2 视为平局，
    平局内孤张字牌先走——数牌有邻张可进化成搭子，字牌只能等对。
    实局：6饼/南 后劲 74.0/73.7，模型原选 6饼，正确答案是先打南。"""

    def test_isolated_honor_wins_near_tie_over_number_float(self):
        state = GameState(my_hand=[T(t) for t in
            "1万 2万 5万 7万 7万 9万 1饼 6饼 7饼 7饼 5条 6条 8条 南".split()])
        ranked = rank_candidates(state, samples=64, seed=0)
        assert str(ranked[0].tile) == "南风"
        assert any("孤字" in l for l in ranked[0].labels)

    def test_terminal_isolate_ranks_between_honor_and_central(self):
        state = GameState(my_hand=[T(t) for t in
            "1万 2万 5万 7万 7万 9万 1饼 6饼 7饼 7饼 5条 6条 8条 南".split()])
        ranked = rank_candidates(state, samples=64, seed=0)
        tiles = [str(c.tile) for c in ranked[:5]]
        assert tiles.index("南风") < tiles.index("1饼") < tiles.index("6饼")

    def test_convention_only_for_isolates(self):
        from src.decision.ev import _convention_key
        pair_hand = [T(t) for t in "南 南 6饼 1饼".split()]
        assert _convention_key(T("南"), pair_hand) == 2    # 对子拆张不享教学优先
        iso_hand = [T(t) for t in "南 6饼 1饼".split()]
        assert _convention_key(T("南"), iso_hand) == 0     # 孤字最先进弃牌
        assert _convention_key(T("1饼"), iso_hand) == 1    # 幺九孤张次之
        assert _convention_key(T("6饼"), iso_hand) == 2    # 中张垫底


class TestRefineTiesFlag:
    def test_refine_ties_false_skips_one_ply(self):
        state = GameState(my_hand=[T(t) for t in
            "3万 3万 2饼 2饼 5饼 7饼 9饼 3条 3条 4条 8条 9条 9条 北风".split()])
        ranked = rank_candidates(state, samples=32, seed=0, refine_ties=False)
        assert not any("1-ply" in l for c in ranked for l in c.labels)
        ranked_default = rank_candidates(state, samples=32, seed=0)
        assert any("1-ply" in l for c in ranked_default for l in c.labels)


class TestBlockDiscipline:
    """教学原则：三对必拆一对；五搭纪律（块数超标白亏一手）。"""

    def test_four_pairs_prefers_breaking_a_pair(self):
        # 4个对子 + 完整搭子：同等向听/进张下，拆对子的候选应排在拆顺子边前
        state = GameState(my_hand=[T(t) for t in
            "1万 1万 3万 3万 5万 5万 9万 9万 3条 4条 5条 7条 8条 9条".split()])
        ranked = rank_candidates(state, samples=8, seed=0)
        tiles = [str(c.tile) for c in ranked]
        assert tiles.index("9万") < tiles.index("3条")   # 拆第四对 优于 拆成牌边


class TestPairDiscipline:
    """G1（题库挖掘 2026-11-17）：对子价值边际递减 + 碰期权。
    0-2对=宝贵（将位+三家供牌的碰机会，n_eff只算自摸看不见）；
    块超标时过剩对/过剩块受罚（两对半/五搭纪律）。"""

    def test_two_pairs_kept_when_taatsu_redundant(self):
        # CC-07-early 教学实题：两对六搭，前期拆弱搭保对（打6万），不拆对（非2万）
        state = GameState(my_hand=[T(t) for t in
            "3条 4条 5条 8条 8条 7饼 8饼 2万 2万 4万 5万 6万 6万 7万".split()])
        ranked = rank_candidates(state, samples=64, seed=0)
        assert str(ranked[0].tile) == "6万", str(ranked[0].tile)

    @pytest.mark.xfail(reason="G1b 已知缺口（2026-11-17 拆账定性）：两站姿进张39vs33"
                         "的差距主项是搭进15vs3(万区密度厚张)，非对进薄张——"
                         "角色加权翻不动；'两对半'是多巡架构价值，属路线层(P-B)，"
                         "静态分不可表达。见题库文档拆账记录", strict=True)
    def test_surplus_pairs_broken_over_good_taatsu(self):
        # LDB-01 教学实题：四对+双面搭六搭，应拆弱对（6/7条），不得拆23条双面搭
        state = GameState(my_hand=[T(t) for t in
            "2条 3条 6条 6条 7条 7条 9条 9条 3万 3万 4万 5万 6万 7万".split()])
        ranked = rank_candidates(state, samples=64, seed=0)
        assert str(ranked[0].tile) in ("6条", "7条"), str(ranked[0].tile)

    def test_marginal_curve_capped_then_flat(self, monkeypatch):
        """纯对子曲线：第1-2对各+碰期权，之后封顶不加不减（保护北风型四对架构）。"""
        from src.decision import ev as evmod
        from src.core import hand_analyzer as ha
        dummy = [T("南风")] * 2

        def fake_best(hand_, fuuro):
            return fake_best.state
        monkeypatch.setattr(ha, "best_decomposition", fake_best)
        vals = []
        for n in (1, 2, 3, 4):
            fake_best.state = (0, 0, n)
            vals.append(evmod._pair_discipline(dummy, 0))
        assert vals[1] - vals[0] == pytest.approx(3.5)
        assert vals[2] == pytest.approx(vals[1])      # 封顶
        assert vals[3] == pytest.approx(vals[1])

    def test_no_false_penalty_at_two_pairs(self):
        # 正常两对（雀头+一组）：拆对不应被系统性惩罚到孤立张之下
        state = GameState(my_hand=[T(t) for t in
            "1万 1万 3万 3条 4条 5条 6条 7条 8条 2饼 4饼 6饼 8饼 9饼".split()])
        ranked = rank_candidates(state, samples=8, seed=0)
        tiles = [str(c.tile) for c in ranked]
        assert tiles.index("9饼") < tiles.index("1万")   # 打孤张仍优于拆雀头对
