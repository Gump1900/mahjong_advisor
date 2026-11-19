"""EV bot: personality policy over the math core, gated by rule predicates."""
import pytest

from src.decision.ev_bot import EVBot, PERSONALITIES, Personality
from src.decision.ev import CandidateEV
from src.players.base import DecisionError
from src.core.tiles import parse_tile

T = parse_tile


def _cand(tile, attack, defense):
    return CandidateEV(tile=parse_tile(tile), ev=attack - defense,
                       p_win_next=0.5, v_win=attack / 0.5,
                       p_point=0.25, p_lo=0.1, p_hi=0.5,
                       v_deal=defense / 0.25,
                       exp_neff_1ply=4.0, exp_neff_exact=True, labels=[])


def _obs(**overrides):
    obs = {
        "seat": 0,
        "wall_count": 40,
        "locked_pairs": [],
        "players": [],
        "events": [],
        "pending": None,
        "self": {
            "hand": "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条 9条".split(),
            "ron_blocked": False, "peng_blocked": [], "locked_with": [],
            "held_flower_count": 0, "structural_shanten": 0,
        },
        "legal_actions": [
            {"id": "d1", "kind": "discard", "tiles": ["5条"]},
            {"id": "d2", "kind": "discard", "tiles": ["9条"]},
        ],
    }
    obs.update(overrides)
    return obs


def _stub_ranker(cands):
    def ranker(state, *, samples=8, seed=0):
        return [_cand(**c) for c in cands]
    return ranker


class TestPersonalities:
    def test_three_personalities_defined(self):
        assert set(PERSONALITIES) == {"稳", "均衡", "凶"}
        assert PERSONALITIES["稳"] == Personality(a=1.0, d=2.0)
        assert PERSONALITIES["均衡"] == Personality(a=1.0, d=1.0)
        assert PERSONALITIES["凶"] == Personality(a=1.6, d=0.4)

    def test_aggressive_takes_risk_cautious_dodges(self):
        # 5条：高进攻(10)高危(8)；9条：低进攻(4)低危(1)
        ranker = _stub_ranker([{"tile": "5条", "attack": 10.0, "defense": 8.0},
                               {"tile": "9条", "attack": 4.0, "defense": 1.0}])
        fierce = EVBot("凶", ranker=ranker).choose(_obs())
        cautious = EVBot("稳", ranker=ranker).choose(_obs())
        assert fierce.action_id == "d1"     # 打5条搏进攻
        assert cautious.action_id == "d2"   # 打9条避风险


class TestRuleGates:
    def test_takes_win_when_offered(self):
        obs = _obs(legal_actions=[
            {"id": "w1", "kind": "win", "tiles": []},
            {"id": "d1", "kind": "discard", "tiles": ["5条"]},
        ])
        assert EVBot("均衡", ranker=_stub_ranker(
            [{"tile": "5条", "attack": 1.0, "defense": 0.0}])).choose(obs).action_id == "w1"

    def test_guoquan_skips_ron(self):
        obs = _obs(legal_actions=[
            {"id": "r1", "kind": "ron", "tiles": ["5条"]},
            {"id": "d1", "kind": "discard", "tiles": ["5条"]},
        ])
        obs["self"]["ron_blocked"] = True
        choice = EVBot("均衡", ranker=_stub_ranker(
            [{"tile": "5条", "attack": 1.0, "defense": 0.0}])).choose(obs)
        assert choice.action_id != "r1"

    def test_takes_ron_when_eligible(self):
        obs = _obs(legal_actions=[
            {"id": "r1", "kind": "ron", "tiles": ["5条"]},
            {"id": "d1", "kind": "discard", "tiles": ["5条"]},
        ])
        assert EVBot("均衡", ranker=_stub_ranker(
            [{"tile": "5条", "attack": 1.0, "defense": 0.0}])).choose(obs).action_id == "r1"

    def test_flower_kong_taken_only_when_tenpai(self):
        tenpai_obs = _obs(legal_actions=[
            {"id": "f1", "kind": "flower_kong", "tiles": ["中"]},
            {"id": "p1", "kind": "pass", "tiles": []},
        ])
        assert EVBot("均衡", ranker=_stub_ranker(
            [{"tile": "5条", "attack": 1.0, "defense": 0.0}])).choose(
            tenpai_obs).action_id == "f1"
        notenpai_obs = _obs(legal_actions=[
            {"id": "f1", "kind": "flower_kong", "tiles": ["中"]},
            {"id": "p1", "kind": "pass", "tiles": []},
        ])
        notenpai_obs["self"]["structural_shanten"] = 2
        assert EVBot("均衡", ranker=_stub_ranker(
            [{"tile": "5条", "attack": 1.0, "defense": 0.0}])).choose(
            notenpai_obs).action_id == "p1"


class TestDeterminism:
    def test_same_observation_same_choice(self):
        ranker = _stub_ranker([{"tile": "5条", "attack": 6.0, "defense": 3.0},
                               {"tile": "9条", "attack": 4.0, "defense": 1.0}])
        bot = EVBot("均衡", ranker=ranker)
        assert bot.choose(_obs()) == bot.choose(_obs())

    def test_no_legal_actions_raises(self):
        with pytest.raises(DecisionError):
            EVBot("均衡").choose(_obs(legal_actions=[]))


class TestRealRankerSmoke:
    def test_smoke_real_ranker_discard_choice(self):
        bot = EVBot("稳", samples=8, seed=0)
        choice = bot.choose(_obs())
        assert choice.action_id.startswith("d")
        assert "ev-稳" in choice.controller


class TestSeatRingMapping:
    def test_downstream_overstream_by_seat_offset(self):
        # 引擎回合序 0→1→2→3：对 seat=2，下家(right)=3、对家=0、上家(left)=1
        obs = {
            "seat": 2, "wall_count": 40, "locked_pairs": [], "events": [],
            "pending": None,
            "self": {"hand": "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条".split(),
                     "ron_blocked": False, "peng_blocked": [], "locked_with": [],
                     "held_flower_count": 0, "structural_shanten": 0},
            "players": [
                {"seat": 0, "river": ["8条"], "melds": [], "flowers": []},
                {"seat": 1, "river": ["7条"], "melds": [], "flowers": []},
                {"seat": 2, "river": [], "melds": [], "flowers": []},
                {"seat": 3, "river": ["9条"], "melds": [], "flowers": []},
            ],
            "legal_actions": [],
        }
        from src.decision.ev_bot import build_state_from_observation
        state = build_state_from_observation(obs)
        assert [str(t) for t in state.discards["right"]] == ["9条"]
        assert [str(t) for t in state.discards["opposite"]] == ["8条"]
        assert [str(t) for t in state.discards["left"]] == ["7条"]


class TestBotResilience:
    def test_exchanges_held_flowers_even_when_not_tenpai(self):
        # 花占位：未听牌也必须先换花，否则后续 EV 计算会炸
        obs = _obs(legal_actions=[
            {"id": "f1", "kind": "flower_kong", "tiles": ["中"]},
            {"id": "d1", "kind": "discard", "tiles": ["5条"]},
            {"id": "p1", "kind": "pass", "tiles": []},
        ])
        obs["self"]["hand"] = "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 中 春".split()
        obs["self"]["held_flower_count"] = 2
        obs["self"]["structural_shanten"] = 2
        choice = EVBot("均衡", ranker=_stub_ranker(
            [{"tile": "5条", "attack": 1.0, "defense": 0.0}])).choose(obs)
        assert choice.action_id == "f1"

    def test_ranker_failure_degrades_to_first_discard(self):
        def exploding_ranker(state, *, samples=128, seed=0):
            raise ValueError("手牌张数应为 13 或 14")
        obs = _obs(legal_actions=[
            {"id": "d1", "kind": "discard", "tiles": ["5条"]},
            {"id": "d2", "kind": "discard", "tiles": ["9条"]},
        ])
        choice = EVBot("均衡", ranker=exploding_ranker).choose(obs)
        assert choice.action_id in ("d1", "d2")
        assert "降级" in choice.reason


class TestSelectFlowers:
    def test_returns_strings_matching_engine_contract(self):
        obs = _obs(legal_actions=[
            {"id": "f1", "kind": "flower_kong", "tiles": ["中"]},
            {"id": "f2", "kind": "flower_kong", "tiles": ["春"]},
        ])
        obs["self"]["hand"] = "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 中 春".split()
        obs["wall_count"] = 30
        flowers = EVBot("均衡").select_flowers(obs)
        assert flowers == ["中", "春"]      # 字符串，不是 Tile 对象
        assert all(isinstance(f, str) for f in flowers)


class TestBotCalls:
    def _response_obs(self, hand, pending_tile, source=3):
        return {
            "seat": 1, "wall_count": 60, "locked_pairs": [],
            "events": [], "pending": {"source": source, "tile": pending_tile},
            "call_counts": [[0]*4 for _ in range(4)],
            "self": {"hand": hand, "ron_blocked": False, "peng_blocked": [],
                     "locked_with": [], "held_flower_count": 0,
                     "structural_shanten": 1},
            "players": [{"seat": i, "river": [], "melds": [], "flowers": []}
                        for i in range(4)],
            "legal_actions": [
                {"id": "p1", "kind": "peng", "tiles": [pending_tile]},
                {"id": "pass1", "kind": "pass", "tiles": []},
            ],
        }

    def test_takes_structurally_beneficial_peng(self):
        # 55饼 是散对（非雀头）：碰出成刻 1向听→听牌，必须碰
        obs = self._response_obs(
            "1万 2万 3万 4万 5万 6万 7万 8万 9万 5饼 5饼 2条 9条".split(), "5饼")
        choice = EVBot("均衡").choose(obs)
        assert choice.action_id == "p1"

    def test_passes_same_shanten_fewer_improving_peng(self):
        # 123万456万789条 三组 + 24饼嵌张（听3饼）+ 77饼雀头：
        # 碰7饼 = 拆雀眼，向听 0→1，必须过
        obs = self._response_obs(
            "1万 2万 3万 4万 5万 6万 7条 8条 9条 2饼 4饼 7饼 7饼".split(), "7饼")
        choice = EVBot("均衡").choose(obs)
        assert choice.action_id == "pass1"


class TestBotStructureDiscipline:
    def test_personality_never_breaks_structure(self):
        # 稳bot：保结构候选有点炮风险、拆结构候选安全——
        # 性格评分偏爱安全的拆结构项，但结构纪律必须否决它
        from src.decision.ev import CandidateEV
        keep = CandidateEV(tile=T("8万"), ev=-1.0, stand_shanten=2,
                           p_win_next=0.2, v_win=20, p_point=0.5,
                           p_lo=0.1, p_hi=0.5, v_deal=10.0,
                           exp_neff_1ply=20, exp_neff_exact=True, labels=[])
        break_ = CandidateEV(tile=T("9饼"), ev=0.0, stand_shanten=3,
                             p_win_next=0, v_win=0, p_point=0.0,
                             p_lo=0, p_hi=0, v_deal=0,
                             exp_neff_1ply=30, exp_neff_exact=True, labels=[])
        def ranker(state, *, samples=128, seed=0):
            return [break_, keep]   # 评分上 break_ 更优（稳：0 > -1）
        obs = _obs(legal_actions=[
            {"id": "d1", "kind": "discard", "tiles": ["8万"]},
            {"id": "d2", "kind": "discard", "tiles": ["9饼"]},
        ])
        choice = EVBot("稳", ranker=ranker).choose(obs)
        assert choice.action_id == "d1"   # 必须选保结构的 8万
