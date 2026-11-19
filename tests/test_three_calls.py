"""Confirmed directional three-call locks, pairwise payments and bot integration."""
import copy
import json

import pytest

from src.core.round_rules import settle_round
from src.players.analysis import analyze_actions
from src.players.base import DecisionError
from src.players.heuristic import HeuristicPlayer
from src.players.llm import LLMPlayer
from src.simulation.engine import Table
from src.simulation.observation import observe
from src.simulation.replay import record, replay
from src.simulation.state import LEGACY_RULES_VERSION
from src.simulation.web import DesktopTable
from tests.test_simulation import BASE, act, passes, scenario, fake_client, checked_answer


@pytest.mark.parametrize("method", ["zimo", "gangkai"])
def test_pairwise_lock_payments_not_global_or_transitive(method):
    pairs = [("me", "right"), ("me", "left")]
    middle = settle_round(method, {"me": 10}, locked_pairs=pairs)
    assert middle.net == {"me": 70, "right": -30, "opposite": -10, "left": -30}
    end = settle_round(method, {"right": 10}, locked_pairs=pairs)
    assert end.net == {"me": -30, "right": 50, "opposite": -10, "left": -10}
    outside = settle_round(method, {"opposite": 10}, locked_pairs=pairs)
    assert outside.net == {"me": -10, "right": -10, "opposite": 30, "left": -10}
    ron = settle_round("dianpao", {"opposite": 10}, "me", locked_pairs=pairs)
    assert ron.net == {"me": -10, "right": 0, "opposite": 10, "left": 0}
    with pytest.raises(ValueError, match="只能自摸"):
        settle_round("dianpao", {"right": 10}, "opposite", locked_pairs=pairs)
    assert not settle_round("draw", {}, locked_pairs=pairs).payments


def test_directional_counts_do_not_combine_and_locks_form_edges():
    t = Table(42)
    t.call_counts[1][0] = 2
    t.call_counts[0][1] = 1
    assert t.locked_pairs() == []
    t.call_counts[1][0] = 3
    t.call_counts[2][1] = 3
    assert t.locked_pairs() == [(0, 1), (1, 2)]
    assert t.locked_with(0) == [1] and t.locked_with(1) == [0, 2]
    assert t.locked_with(3) == []


@pytest.mark.parametrize("kind,hand", [
    ("chi", "3万 5万 6条 7条 8条 西风 西风"),
    ("peng", "4万 4万 6条 7条 8条 西风 西风"),
    ("ming_gang", "4万 4万 4万 6条 7条 西风 西风"),
])
def test_only_successfully_resolved_claim_counts_as_third_mouth(kind, hand):
    t = scenario({0: BASE+" 4万", 1: hand},
                 melds={1: [("peng", "1饼 1饼 1饼"), ("peng", "2饼 2饼 2饼")]})
    t.call_counts[1][0] = 2
    act(t, 0, "discard", "4万")
    obs = observe(t, 1)
    metrics = analyze_actions(obs)
    call = next(a for a in metrics["candidates"] if a["kind"] == kind)
    assert call["creates_lock"] and call["call_count_after"] == 3
    act(t, 1, kind)
    assert t.call_counts[1][0] == 2  # Still private/unresolved response window.
    passes(t)
    assert t.call_counts[1][0] == 3 and t.locked_pairs() == [(0, 1)]
    assert sum(e["kind"] == "three_calls_lock" for e in t.events) == 1
    assert observe(t, 0)["players"][1]["locked_with"] == [0]
    t.assert_consistent()


def test_add_kong_and_own_flower_exchange_do_not_add_a_mouth():
    t = scenario({1: "4万 6条 7条 南风 春"}, actor=1,
                 melds={1: [("peng", "4万 4万 4万"), ("peng", "1饼 1饼 1饼"), ("peng", "2饼 2饼 2饼")]})
    t.call_counts[1][0] = 2
    before = copy.deepcopy(t.call_counts)
    act(t, 1, "add_gang", "4万")
    assert t.call_counts == before
    act(t, 1, "flower_kong", "春")
    assert t.call_counts == before and not t.locked_pairs()


def test_lock_blocks_every_ron_and_wait_hints_but_not_self_draw():
    t = scenario({0: "1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 1条 2条 3条 9条", 1: "9条"},
                 actor=1, flowers={0: "春"})
    t.call_counts[0][2] = 3
    act(t, 1, "discard", "9条")
    assert not any(a.kind == "ron" for a in t.legal_actions(0))
    assert t._score(0, "dianpao", t.pending["tile"]) is None
    waits = observe(t, 0)["self"]["waiting_tiles"]
    assert waits and all(not w["can_ron"] and "三口" in w["reason"] for w in waits)
    # Temporary pass status has no bearing on the permanent pair lock.
    t.seats[0].ron_blocked = False
    assert t.locked_with(0) == [2]
    won = scenario({0: "1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 1条 2条 3条 9条 9条"}, flowers={0: "春"})
    won.call_counts[0][1] = 3
    won.call_counts[2][0] = 3
    action = next(a for a in observe(won, 0)["legal_actions"] if a["kind"] == "win")
    assert [p["amount"] for p in action["payments"]] == [15, 15, 5]
    act(won, 0, "win")
    assert won.result["net"] == [35, -15, -15, -5]


def test_real_reported_eat_six_discard_six_is_declined():
    t = scenario({0: BASE+" 6万", 1: "5万 6万 7万 1饼 2饼 7饼 7饼 4条 5条 5条"},
                 melds={1: [("peng", "北风 北风 北风")]})
    act(t, 0, "discard", "6万")
    obs = observe(t, 1)
    choice = HeuristicPlayer().choose(obs)
    assert next(a for a in obs["legal_actions"] if a["id"] == choice.action_id)["kind"] == "pass"


def test_old_rules_replay_remains_old_and_new_games_use_new_rules():
    old = Table(42, rules_version=LEGACY_RULES_VERSION)
    act(old, 0, "discard", "1万")
    passes(old)
    assert "call_counts" not in old.snapshot()
    restored = replay(record(old))
    assert restored.state_hash() == old.state_hash()
    assert restored.rules_version == LEGACY_RULES_VERSION
    assert Table(42).rules_version != LEGACY_RULES_VERSION


def test_llm_payload_receives_only_code_metrics_and_public_lock_information():
    t = Table(42)
    t.call_counts[0][1] = 2
    obs = observe(t, 0)
    client, payloads = fake_client([json.dumps(checked_answer(obs, obs["legal_actions"][0]["id"], reason="基于公开信息"))])
    LLMPlayer(decision_protocol="legacy-v2", client=client, model="test").choose(obs)
    payload = json.loads(payloads[0]["messages"][0]["content"])
    assert payload["call_counts"][0][1] == 2 and payload["decision_options"]
    assert all("hand" not in p for p in payload["players"])
    assert "initial_wall" not in payload and "wall" not in payload and "seed" not in payload
    assert "不刻意锁人" in payloads[0]["system"]


def test_web_uses_separate_llm_players_and_safely_pauses_without_autopass(tmp_path):
    class Broken:
        def choose(self, obs):
            raise DecisionError("测试服务不可用，已暂停")
    bots = {p: Broken() for p in (1, 2, 3)}
    d = DesktopTable(Table(42, dealer=1), bots=bots, output_dir=tmp_path, paced=True)
    before = d.table.state_hash()
    v = d.view()
    assert v["bot_error"] and not v["can_advance"] and not v["awaiting_human"]
    assert d.saved and not d.table.decisions
    d.bots = {p: HeuristicPlayer() for p in (1, 2, 3)}
    retried = d.retry_bots(v["version"])
    assert retried["bot_error"] is None and retried["can_advance"]
    assert d.table.state_hash() == before  # Only prepared, not yet applied.
    d.step(retried["version"])
    assert d.table.decisions


def test_deepseek_configuration_pins_official_endpoint_and_uses_separate_key(monkeypatch):
    import anthropic
    monkeypatch.setattr("src.players.llm.load_local_config", lambda: {})
    captured = []
    client, _ = fake_client([])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: captured.append(kwargs) or client)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-credential")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unrelated-anthropic-credential")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://unrelated.invalid")
    monkeypatch.delenv("MAHJONG_BOT_MODEL", raising=False)
    bot = LLMPlayer(decision_protocol="legacy-v2", provider="deepseek")
    assert bot.model == "deepseek-flash"
    assert captured[0]["api_key"] == "test-deepseek-credential"
    assert captured[0]["base_url"] == "https://api.deepseek.com/anthropic"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        LLMPlayer(decision_protocol="legacy-v2", provider="deepseek")


def test_deepseek_real_sdk_serialization_with_mock_http_no_network():
    import anthropic
    import httpx
    obs = observe(Table(42), 0)
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": "deepseek-flash",
            "content": [{"type": "thinking", "thinking": "测试内部推理", "signature": "test"},
                        {"type": "text", "text": json.dumps(checked_answer(obs, obs["legal_actions"][0]["id"], reason="根据代码牌效选择"))}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 20}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client = anthropic.Anthropic(api_key="test-key", base_url="https://api.deepseek.com/anthropic", http_client=http)
        choice = LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client).choose(obs)
    assert choice.controller == "llm" and "内部推理" not in choice.reason
    request = requests[0]
    assert str(request.url) == "https://api.deepseek.com/anthropic/v1/messages"
    body = json.loads(request.content)
    assert body["model"] == "deepseek-flash" and body["thinking"] == {"type": "disabled"}
    assert "output_config" not in body and body["max_tokens"] == 2048
    assert request.headers["x-api-key"] == "test-key"


def test_authentication_failure_is_actionable_and_never_retried():
    class BadKey(Exception):
        status_code = 401
    obs = observe(Table(42), 0)
    client, payloads = fake_client([BadKey("secret-from-provider")])
    bot = LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client)
    with pytest.raises(DecisionError) as error:
        bot.choose(obs)
    assert len(payloads) == 1 and bot.calls == 1
    assert "HTTP 401" in str(error.value) and "重启" in str(error.value)
    assert "secret-from-provider" not in str(error.value)
