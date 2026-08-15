"""Advisor orchestration tests: analyze() + build_prompt() (no network)."""
import pytest

from src.core.tiles import create_tile, GameState, Meld
from src.core.hand_analyzer import calculate_shanten, get_waiting_tiles
from src.llm.advisor import analyze, build_prompt, get_advice, DEFAULT_MODEL

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
