"""Frozen live mistakes and compact protocol; no network or oracle inputs."""
import copy
import json

import pytest

from src.core.tiles import parse_tile
from src.players.base import DecisionError
from src.players.decision_guard import validate_decision
from src.players.deliberation import Deliberation
from src.players.llm import LLMPlayer
from src.players.tactical_facts import wait_shapes, flower_opportunities, opponent_constraints
from src.simulation.coaching import LLMCoach
from src.simulation.observation import observe
from tests.test_simulation import scenario, checked_answer, fake_client
from tests.test_decision_guard import waiting_position, action


def shapes(text, groups):
    return {r["tile"]: r for r in wait_shapes([parse_tile(t) for t in text.split()], groups)}


def test_single_kind_wait_is_not_necessarily_pair_wait():
    # Game 3: discard 8sou; pin 24 waits 3, not a pair wait.
    result = shapes("2饼 4饼 5饼 6饼 7饼 9条 9条", 2)
    assert result["3饼"]["forms"] == ["坎张"]
    assert result["3饼"]["own_copies"] == 0
    assert not result["3饼"]["opponent_ankan_excluded_by_own_copy"]


@pytest.mark.parametrize("hand,tile,form", [
    ("1条 2条 9万 9万", "3条", "边张"),
    ("8条 9条 9万 9万", "7条", "边张"),
    ("6条 7条 9万 9万", "8条", "两面"),
    ("南风", "南风", "单吊"),
    ("1条 1条 9万 9万", "1条", "刻子待牌"),
])
def test_exact_wait_shapes(hand, tile, form):
    result = shapes(hand, 4 if len(hand.split()) == 1 else 3)
    assert form in result[tile]["forms"]
    if form == "单吊":
        assert result[tile]["opponent_ankan_excluded_by_own_copy"]


def test_multiple_decompositions_and_local_luxury_pairs():
    result = shapes("1万 1万 1万 2万 3万 4万 5万 6万 7万 8万 9万 9万 9万", 0)
    assert len(result["1万"]["forms"]) > 1
    seven = shapes("1万 1万 1万 1万 2万 2万 2万 2万 3饼 3饼 4饼 4饼 5条", 0)
    assert "七对待牌" in seven["5条"]["forms"]


def flower_position(extra=""):
    return observe(scenario({3: "3万 5万 3饼 4饼 5饼 6条 6条 6条 7条 7条 白"}, actor=3,
        melds={3: [("chi", "7饼 8饼 9饼")]}, flowers={3: extra}), 3)


def test_real_game_white_exchange_can_win_immediately_and_locks_price_exactly():
    obs = flower_position()
    # Test supplies only public rivers, never a wall sample.
    for p in obs["players"]:
        p["river"] = []
    obs["players"][3]["locked_with"] = [0, 2]
    before = copy.deepcopy(obs)
    outcome = flower_opportunities(obs)[0]["immediate_gangkai"][0]
    assert outcome["tile"] == "4万"
    assert outcome["forms"] == ["坎张"]
    assert outcome["unseen_upper_bound"] == 4
    assert outcome["per_base_share"] == 9
    assert outcome["payments"] == {"0": 27, "1": 9, "2": 27}
    assert outcome["total_income"] == 63
    assert obs == before
    obs["players"][0]["river"] = ["4万"]*4
    assert not flower_opportunities(obs)[0]["immediate_gangkai"]


def test_remaining_flower_prevents_immediate_win():
    obs = flower_position()
    obs["self"]["hand"][0] = "春"
    for option in flower_opportunities(obs):
        assert option["remaining_held_flowers"] == 1
        assert not option["immediate_gangkai"]


def test_public_chi_excludes_pong_hand_but_flower_does_not_exclude_pure():
    obs = flower_position()
    p = obs["players"][0]
    p["melds"] = [{"type":"chi", "tiles":["4条","5条","6条"]},
                  {"type":"an_gang", "tiles":None}]
    result = next(p for p in opponent_constraints(obs) if p["seat"] == 0)
    assert "碰碰胡" in result["excluded_patterns"] and "七对" in result["excluded_patterns"]
    assert "清一色" not in result["excluded_patterns"]
    p["melds"].append({"type":"an_gang", "tiles":["东风"]*4})
    assert "清一色" not in opponent_constraints(obs)[0]["excluded_patterns"]
    p["melds"].append({"type":"peng", "tiles":["北风"]*3})
    assert "清一色" in opponent_constraints(obs)[0]["excluded_patterns"]


def compact_answer(obs):
    session = Deliberation(obs)
    answer = checked_answer(obs, action(obs, "西风")["id"])
    answer["action_id"] = session.reverse_handles[answer["action_id"]]
    answer["decision_note"]["alternative_action_id"] = session.reverse_handles[
        answer["decision_note"]["alternative_action_id"]]
    answer.pop("action")
    answer.pop("fact_check")
    return session, answer


def test_compact_choice_and_coach_share_server_receipt_without_silent_correction():
    obs = waiting_position()
    session, answer = compact_answer(obs)
    resolved = session.resolve_answer(answer)
    assert validate_decision(resolved, obs, session.contract)["after"]["ready"]
    client, calls = fake_client([json.dumps(answer)])
    bot = LLMPlayer(decision_protocol="legacy-v2", client=client, model="fake")
    assert bot.choose(obs).action_id == action(obs, "西风")["id"]
    assert "逐字段原样填写" not in calls[0]["system"]
    answer.update(summary="争取兑现", explanation="保持饼子搭子，先清掉风牌。")
    client, _ = fake_client([json.dumps(answer)])
    result = LLMCoach(LLMPlayer(decision_protocol="legacy-v2", client=client, model="fake")).explain({"observation":obs})
    assert result["checked_facts"]["after"]["ready"]
    answer["fact_check"] = {"forged": True}
    with pytest.raises(DecisionError, match="回执"):
        validate_decision(session.resolve_answer(answer), obs, session.contract)
    answer.pop("fact_check")
    answer["action"] = {"kind":"discard", "tiles":["5饼"]}
    with pytest.raises(DecisionError, match="编号与牌名"):
        validate_decision(session.resolve_answer(answer), obs, session.contract)


def test_unknown_short_handle_is_not_guessed_and_old_ids_still_need_receipts():
    obs = waiting_position()
    session, answer = compact_answer(obs)
    answer["action_id"] = "A999"
    with pytest.raises(DecisionError, match="非法"):
        validate_decision(session.resolve_answer(answer), obs, session.contract)
    answer["action_id"] = action(obs, "西风")["id"]
    with pytest.raises(DecisionError):
        validate_decision(session.resolve_answer(answer), obs, session.contract)


def test_analysis_tool_uses_current_handles_and_claim_can_compare_other_discard():
    from tests.test_simulation import BASE, act
    table = scenario({0:BASE+" 4万", 1:"3万 5万 6条 7条 8条 西风 西风"},
        melds={1:[("peng","1饼 1饼 1饼"),("peng","2饼 2饼 2饼")]}, flowers={1:"春"})
    act(table, 0, "discard", "4万")
    obs = observe(table, 1)
    session = Deliberation(obs)
    chi = next(a for a in obs["legal_actions"] if a["kind"] == "chi")
    answer = checked_answer(obs, chi["id"])
    card = next(c for c in session.contract["decision_cards"] if c["action_id"] == chi["id"])
    alternative = next(b["tile"] for b in card["after_discards"] if b["tile"] != answer["next_discard"])
    answer["decision_note"].update(alternative_action_id=chi["id"], alternative_next_discard=alternative)
    assert session.note(answer)["alternative_next_discard"] == alternative
    analysis = session.tool("analyze_hand", {})
    assert {c["action_id"] for c in analysis["candidates"]} == set(session.handles)
    assert session.tool("compare_actions", {"action_ids":[session.reverse_handles[chi["id"]]]})["cards"][0]["after_discards"]
    answer["decision_note"]["alternative_next_discard"] = "东风"
    with pytest.raises(DecisionError, match="吃碰对照"):
        session.note(answer)


def test_payload_reduces_repeated_facts_not_legal_choices_or_public_information():
    obs = flower_position()
    session = Deliberation(obs)
    old = {**obs, "decision_analysis": session.analysis,
           "decision_contract_v1":session.contract,"evidence_catalog":session.evidence}
    size = lambda x: len(json.dumps(x, ensure_ascii=False).encode())
    assert size(session.payload) < size(old)*0.8
    assert session.payload["players"] == obs["players"]
    assert session.payload["events"] == obs["events"]
    assert len(session.cards) == len(obs["legal_actions"])
    assert not any("receipt" in c for c in session.cards)
