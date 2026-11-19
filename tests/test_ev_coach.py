"""EV coach: same explain() contract as LLMCoach, output fits the table page."""
from src.decision.ev_coach import EVCoach
from src.players.base import DecisionError

OBS = {
    "seat": 0, "wall_count": 60, "locked_pairs": [], "events": [], "pending": None,
    "self": {"hand": "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条 9条".split(),
             "ron_blocked": False, "peng_blocked": [], "locked_with": [],
             "held_flower_count": 0, "structural_shanten": 0},
    "players": [{"seat": i, "river": [], "melds": [], "flowers": []} for i in range(4)],
    "legal_actions": [],
}


def test_live_result_shape_and_version():
    result = EVCoach().explain({"observation": OBS})
    assert result["verification_version"] == "strategy-v2"
    assert "建议打" in result["summary"]
    assert "EV" not in result["summary"]              # 用户要求：门口不再摆EV术语
    assert "三家推测" in result["explanation"]         # 三家推测一等公民
    assert "对手已听牌的可能" in result["explanation"]
    assert "还差" in result["explanation"] and "能接" in result["explanation"]
    assert "越来越准" in result["explanation"]         # 推测随牌局进化的明示
    assert "LLM" in result["verification_note"] and "不参与" in result["verification_note"]


def test_flower_placeholder_gives_note_not_error():
    obs = {"observation": {**OBS, "self": {**OBS["self"],
            "hand": "1万 2万 中".split(), "held_flower_count": 1}}}
    result = EVCoach().explain(obs)
    assert result["verification_version"] == "strategy-v2"
    assert "换花" in result["summary"]


def test_review_mode_is_honest_about_scope():
    payload = {"review": {"seat": 0, "decisions": [{"step": 1}]}}
    result = EVCoach().explain(payload)
    assert result["verification_version"] == "strategy-v2"
    assert "复盘" in result["summary"]
    assert "EV" not in result["summary"] + result["explanation"]  # 复盘也说人话


NEAR_TIE_HAND = "1万 2万 5万 7万 7万 9万 1饼 6饼 7饼 7饼 5条 6条 8条 南风".split()


class TestNearTieDisplay:
    """后劲差<2 的候选基本等价：军师必须说"先打哪张都行"，
    而不是把小数点决胜摆成唯一答案（用户三次被此困惑：五万/9饼/6饼）。"""

    def test_near_tie_summary_names_equivalent_options(self):
        obs = {"observation": {**OBS, "self": {**OBS["self"],
                                               "hand": NEAR_TIE_HAND}}}
        result = EVCoach().explain(obs)
        assert "先打哪张都行" in result["summary"]
        assert "南" in result["summary"]          # 点名等价替代（打南=孤字先走）

    def test_convention_winner_shows_its_reason(self):
        """教学决胜的行内要亮出理由，否则后劲数字不降序会显得乱排。"""
        obs = {"observation": {**OBS, "self": {**OBS["self"],
                                               "hand": NEAR_TIE_HAND}}}
        result = EVCoach().explain(obs)
        assert "孤字先走" in result["explanation"]

    def test_retreating_candidate_hides_inflated_count(self):
        """退向听候选的静态进张是跨向听虚数（如90张），不得显示为"能接90张"。"""
        hand = "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 1饼 1饼 2条 南风".split()
        obs = {"observation": {**OBS, "self": {**OBS["self"], "hand": hand}}}
        result = EVCoach().explain(obs)
        assert "能接90" not in result["explanation"]
        assert "更慢" in result["explanation"]    # 退向听行如实标注


class TestCoachReceipts:
    def test_live_advice_saves_receipt(self, tmp_path, monkeypatch):
        import src.decision.ev_coach as evc
        from src.decision.receipts import load_receipts
        saved = []
        monkeypatch.setattr(evc, "save_receipt",
                            lambda gid, ver, cands: saved.append((gid, ver, len(cands))))
        coach = EVCoach()
        result = coach.explain({"observation": OBS})
        assert result["verification_version"] == "strategy-v2"
        assert saved and saved[0][2] > 0      # 建议已落盘候选数


class TestCallAdvice:
    def _response(self, hand, tile, call_counts=None):
        return {
            "seat": 0, "stage": "responses", "wall_count": 60,
            "locked_pairs": [], "events": [],
            "pending": {"source": 3, "tile": tile},
            "call_counts": call_counts or [[0]*4 for _ in range(4)],
            "self": {"hand": hand, "ron_blocked": False, "peng_blocked": [],
                     "locked_with": [], "held_flower_count": 0,
                     "structural_shanten": 1},
            "players": [{"seat": i, "river": [], "melds": [], "flowers": []}
                        for i in range(4)],
            "legal_actions": [
                {"id": "p1", "kind": "peng", "tiles": [tile]},
                {"id": "pass1", "kind": "pass", "tiles": []},
            ],
        }

    def test_recommends_beneficial_peng_with_numbers(self):
        obs = self._response("1万 2万 3万 4万 5万 6万 7万 8万 9万 5饼 5饼 2条 9条".split(), "5饼")
        result = EVCoach().explain({"observation": obs})
        assert "碰" in result["summary"]
        assert "1→0" in result["explanation"]          # 向听对比
        assert "过" not in result["summary"].split("：")[0]

    def test_recommends_pass_when_call_regresses(self):
        obs = self._response(
            "1万 2万 3万 4万 5万 6万 7条 8条 9条 2饼 4饼 7饼 7饼".split(), "7饼")
        result = EVCoach().explain({"observation": obs})
        assert "过" in result["summary"]

    def test_third_bite_lock_warning(self):
        counts = [[0]*4 for _ in range(4)]
        counts[0][3] = 2                                  # 我已吃/碰上家两口
        obs = self._response(
            "1万 2万 3万 4万 5万 6万 7万 8万 9万 5饼 5饼 2条 9条".split(), "5饼",
            call_counts=counts)
        result = EVCoach().explain({"observation": obs})
        assert "互锁" in result["explanation"] or "第三口" in result["explanation"]
