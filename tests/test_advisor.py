"""Advisor orchestration tests: analyze() + build_prompt() (no network)."""
import pytest

from src.core.tiles import create_tile, GameState, Meld
from src.core.hand_analyzer import calculate_shanten, get_waiting_tiles
from src.llm.advisor import analyze, build_prompt, get_advice, DEFAULT_MODEL
from src.main import parse_melds

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


def _state(spec, **kw):
    return GameState(my_hand=H(spec), **kw)


class TestAnalyze:
    def test_tenpai_bundle(self):
        state = _state("m2345666 p111 s222")  # tenpai, waits 1,2,4,5,7万
        a = analyze(state)
        assert a.shanten == 0
        assert a.is_tenpai is True
        assert set(a.waiting) == {
            create_tile("万", 1), create_tile("万", 2),
            create_tile("万", 4), create_tile("万", 5), create_tile("万", 7),
        }
        # for a tenpai hand, advancing tiles == winning tiles
        assert set(a.ukeire) == set(a.waiting)

    def test_shanten_matches_engine(self):
        state = _state("m123 p456 s78 南南 北 m49")  # 2-shanten
        a = analyze(state)
        assert a.shanten == calculate_shanten(state.my_hand)

    def test_remaining_total_positive(self):
        a = analyze(_state("m123 p456 s789 南南南 西"))
        assert a.remaining_total > 0
        assert a.remaining_total < 144

    def test_risks_cover_discard_candidates(self):
        state = _state("m123 p456 s789 南南南 西西 北")
        a = analyze(state)
        for tile, _shanten in a.discards_ranked:
            assert tile in a.risks
            assert a.risks[tile] in ("安全", "中", "危险")

    def test_non_tenpai_has_empty_waiting(self):
        a = analyze(_state("m13 p57 s9 南 北 西"))
        assert a.is_tenpai is False
        assert a.waiting == []


class TestBuildPrompt:
    def test_contains_hand_tiles(self):
        a = analyze(_state("m123 p456"))
        prompt = build_prompt(_state("m123 p456"), a)
        assert "1万" in prompt and "2万" in prompt and "6饼" in prompt

    def test_contains_shanten(self):
        a = analyze(_state("m123 p456 s789 南南南 西"))
        prompt = build_prompt(_state("m123 p456 s789 南南南 西"), a)
        assert "向听数" in prompt
        assert str(a.shanten) in prompt

    def test_contains_ukeire_or_waiting(self):
        a = analyze(_state("m2345666 p111 s222"))
        prompt = build_prompt(_state("m2345666 p111 s222"), a)
        assert "听牌" in prompt  # tenpai -> waiting tiles shown

    def test_contains_remaining_total(self):
        state = _state("m123 p456 s789 南南南 西")
        a = analyze(state)
        prompt = build_prompt(state, a)
        assert "剩余" in prompt
        assert str(a.remaining_total) in prompt

    def test_contains_opponent_discards(self):
        state = _state("m123 p456 s789 南南南 西")
        state.discards["left"] = [create_tile("万", 9), create_tile("饼", 1)]
        prompt = build_prompt(state, analyze(state))
        assert "上家" in prompt
        assert "9万" in prompt


# --- get_advice with an injected (fake) client — no network -----------------
class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_FakeBlock(text)]
        self.stop_reason = stop_reason


class _FakeClient:
    """Minimal stand-in for anthropic.Anthropic(): client.messages.create(...)."""

    def __init__(self, text="建议正文", stop_reason="end_turn"):
        self._text = text
        self._stop = stop_reason
        self.captured = None

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.captured = kwargs
        return _FakeResp(self._text, self._stop)


class TestGetAdvice:
    def test_returns_response_text(self):
        client = _FakeClient("打五万最稳")
        out = get_advice(_state("m123 p456 s789 南南南 西"), analyze(_state("m123 p456 s789 南南南 西")), client=client)
        assert out == "打五万最稳"

    def test_uses_default_model_and_adaptive_thinking(self):
        client = _FakeClient()
        get_advice(_state("m123 p456 s789 南南南 西"), analyze(_state("m123 p456 s789 南南南 西")), client=client)
        kw = client.captured
        assert kw["model"] == DEFAULT_MODEL
        assert kw["thinking"] == {"type": "adaptive"}
        # the rendered prompt is the user message content
        assert "向听数" in kw["messages"][0]["content"]

    def test_model_override(self):
        client = _FakeClient()
        get_advice(_state("m123 p456 s789 南南南 西"), analyze(_state("m123 p456 s789 南南南 西")),
                   client=client, model="claude-sonnet-5")
        assert client.captured["model"] == "claude-sonnet-5"

    def test_refusal_raises(self):
        client = _FakeClient(stop_reason="refusal")
        with pytest.raises(ValueError):
            get_advice(_state("m123 p456 s789 南南南 西"), analyze(_state("m123 p456 s789 南南南 西")), client=client)


class TestAnalyzeWithMelds:
    def test_meld_reduces_shanten(self):
        # concealed 10 + one peng: win shape is 3 melds + pair (+ the peng)
        state = GameState(
            my_hand=H("m123 p456 s789 南南"),
            my_melds=[Meld(type="peng", tiles=[create_tile("饼", 1)] * 3)],
        )
        a = analyze(state)
        assert a.shanten == -1
        assert a.remaining[create_tile("饼", 1)] == 1   # peng counted in remaining


class TestParseMelds:
    def test_empty(self):
        assert parse_melds("") == []
        assert parse_melds("  ") == []

    def test_single_peng(self):
        melds = parse_melds("peng 5饼")
        assert len(melds) == 1
        assert melds[0].type == "peng"
        assert melds[0].tiles == [create_tile("饼", 5)] * 3

    def test_chi_explicit_tiles(self):
        melds = parse_melds("chi 3万 4万 5万")
        assert melds[0].type == "chi"
        assert melds[0].tiles == [create_tile("万", i) for i in (3, 4, 5)]

    def test_multiple_melds(self):
        melds = parse_melds("peng 5饼, ming_gang 9条, an_gang 南风")
        assert [m.type for m in melds] == ["peng", "ming_gang", "an_gang"]
        assert melds[1].tiles == [create_tile("条", 9)] * 4
        assert melds[2].tiles == [create_tile("风", "南")] * 4

    def test_comma_or_space_separated(self):
        assert len(parse_melds("peng 1万 peng 2万")) == 2
        assert len(parse_melds("peng 1万，peng 2万")) == 2   # 全角逗号也认

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_melds("peng")             # no tile
        with pytest.raises(ValueError):
            parse_melds("bogus 5饼")       # unknown meld type


class TestRiskEstimates:
    def test_bundle_has_estimates(self):
        a = analyze(_state("m123 p456 s789 南南南 西西 北"))
        for tile, _ in a.discards_ranked:
            est = a.risk_estimates[tile]
            assert set(est) == {"chi", "peng", "ron", "label"}
            assert est["label"] == a.risks[tile]   # consistent with coarse label

    def test_prompt_contains_percentages(self):
        state = _state("m123 p456 s789 南南南 西西 北")
        prompt = build_prompt(state, analyze(state))
        assert "被吃" in prompt and "点炮" in prompt and "%" in prompt


class TestKongOpportunities:
    def test_concealed_quad_detected(self):
        # 9条×4 in hand -> an-kong opportunity (+10)
        state = _state("m123 p456 s9999 南南 南")
        opps = analyze(state).kong_opportunities
        assert any(op["kind"] == "暗杠" and str(op["tile"]) == "9条" and op["hua"] == 10
                   for op in opps)

    def test_peng_upgrade_detected(self):
        state = GameState(
            my_hand=H("m123 p456 s789 南南 南"),
            my_melds=[Meld(type="peng", tiles=[create_tile("风", "南")] * 3)],
        )
        opps = analyze(state).kong_opportunities
        assert any(op["kind"] == "加杠" and str(op["tile"]) == "南风" and op["hua"] == 6
                   for op in opps)

    def test_held_flower_set_detected(self):
        state = GameState(
            my_hand=H("m123 p456 s789 南南南 西"),
            flowers_in_hand=[create_tile("三元", "中")] * 4,
        )
        opps = analyze(state).kong_opportunities
        flower_ops = [op for op in opps if op["kind"] == "花牌自杠"]
        assert len(flower_ops) == 1
        assert flower_ops[0]["hua"] == 12
        assert "留4张=6花" in flower_ops[0]["note"]

    def test_no_opportunities_when_none(self):
        assert analyze(_state("m123 p456 s789 南南南 西")).kong_opportunities == []

    def test_tenpai_kongkai_note_in_prompt(self):
        # tenpai + a holdable flower set -> prompt carries the 杠开 line
        state = GameState(
            my_hand=H("m2345666 p111 s222"),           # tenpai waits 1,2,4,5,7万
            flowers_in_hand=[create_tile("三元", "中")] * 4,
        )
        prompt = build_prompt(state, analyze(state))
        assert "杠牌/杠开机会" in prompt
        assert "杠开" in prompt
        assert "现在杠任意一组" in prompt


class TestSeasonFlowerOpportunity:
    def test_held_season_detected(self):
        # every held season flower is a kong-able asset (1花, value = 杠开 timing)
        state = GameState(
            my_hand=H("m123 p456 s789 南南南 西"),
            flowers_in_hand=[create_tile("季节", "春"), create_tile("季节", "菊")],
        )
        opps = analyze(state).kong_opportunities
        season_ops = [op for op in opps if op["tile"].suit == "季节"]
        assert {str(op["tile"]) for op in season_ops} == {"春", "菊"}
        assert all(op["kind"] == "花牌自杠" and op["hua"] == 1 for op in season_ops)
        assert all("杠开" in op["note"] for op in season_ops)

    def test_season_and_multi_flower_together(self):
        state = GameState(
            my_hand=H("m2345666 p111 s222"),          # tenpai
            flowers_in_hand=[create_tile("三元", "中")] * 4 + [create_tile("季节", "夏")],
        )
        a = analyze(state)
        kinds = {(op["tile"], op["hua"]) for op in a.kong_opportunities}
        assert (create_tile("三元", "中"), 12) in kinds
        assert (create_tile("季节", "夏"), 1) in kinds
        assert "杠开" in build_prompt(state, a)


class TestFirstWinSpeed:
    """一胡即终局 -> 速度优先：同向听时进张（种数/张数）多的候选排前面。"""

    def test_discard_speed_covers_candidates(self):
        a = analyze(_state("m123 p456 s78 南南南 西西 北"))
        assert set(a.discard_speed) == {t for t, _ in a.discards_ranked}
        for v in a.discard_speed.values():
            assert v["types"] >= 0 and v["tiles"] >= 0

    def test_speed_matches_engine_ukeire(self):
        from src.core.hand_analyzer import get_ukeire as gu
        from src.core.tiles import parse_tile
        state = _state("m123 p456 s78 南南南 西西 北")
        a = analyze(state)
        tile = state.my_hand[0]
        rest = list(state.my_hand)
        rest.remove(tile)
        assert a.discard_speed[tile]["types"] == len(gu(rest))

    def test_same_shanten_sorted_by_speed(self):
        a = analyze(_state("m123 p456 s78 南南南 西西 北"))
        ranked = a.discards_ranked
        for (t1, s1), (t2, s2) in zip(ranked, ranked[1:]):
            if s1 == s2:
                assert a.discard_speed[t1]["tiles"] >= a.discard_speed[t2]["tiles"]

    def test_prompt_carries_first_win_rule(self):
        state = _state("m123 p456 s789 南南南 西")
        prompt = build_prompt(state, analyze(state))
        assert "一胡即终局" in prompt
        assert "快胡" in prompt
        assert "速度" in prompt or "进张" in prompt
