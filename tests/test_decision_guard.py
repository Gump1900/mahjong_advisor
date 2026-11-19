"""Regression positions from the first DeepSeek game, without oracle hands."""
import copy
import json

import pytest

from src.players.base import DecisionError
from src.players.decision_guard import decision_contract, validate_decision, checked_summary
from src.players.llm import LLMPlayer
from src.simulation.coaching import LLMCoach
from src.simulation.observation import observe
from tests.test_simulation import scenario, checked_answer, fake_client


def action(obs, tile, kind="discard"):
    return next(a for a in obs["legal_actions"] if a["kind"] == kind and a["tiles"] == [tile])


def waiting_position():
    return observe(scenario({3: "4饼 5饼 5饼 6饼 7饼 8饼 8饼 7条 8条 9条 西风"}, actor=3,
        melds={3: [("peng", "5万 5万 5万")]}, flowers={3: "春 夏"}), 3)


def mismatch_position():
    return observe(scenario({0: "1万 2万 6万 6万 6饼 7饼 7饼 8饼 8饼 9饼 3条 3条 4条 5条"},
        flowers={0: "春 东风 中 中"}), 0)


def receipt(obs, tile):
    return checked_answer(obs, action(obs, tile)["id"])["fact_check"]


def test_real_game_discard5pin_breaks_ready_discard_west_preserves_it():
    obs = waiting_position()
    assert receipt(obs, "西风")["after"]["ready"]
    assert receipt(obs, "西风")["after"]["waiting_tiles"] == ["3饼", "6饼"]
    broken = receipt(obs, "5饼")
    assert broken["after"]["structural_shanten"] == 1 and not broken["after"]["ready"]
    forged = checked_answer(obs, action(obs, "5饼")["id"])
    forged["fact_check"]["after"]["ready"] = True
    with pytest.raises(DecisionError, match="回执"):
        validate_decision(forged, obs, decision_contract(obs))


def test_real_game_receipt_correct_but_prose_falsely_claims_still_ready():
    obs = waiting_position()
    answer = checked_answer(obs, action(obs, "5饼")["id"], reason="切一张5筒仍保持听牌，不打西风。")
    with pytest.raises(DecisionError, match="保持听牌"):
        validate_decision(answer, obs, decision_contract(obs))


def test_real_game_action5sou_but_final_reason_says3sou_is_rejected():
    obs = mismatch_position()
    assert receipt(obs, "3条")["after"]["waiting_tiles"] == ["3万"]
    assert receipt(obs, "5条")["after"]["structural_shanten"] == 1
    answer = checked_answer(obs, action(obs, "5条")["id"], reason="实际最优是打3条，综合考虑选择打3条更稳。")
    with pytest.raises(DecisionError, match="弃牌冲突"):
        validate_decision(answer, obs, decision_contract(obs))


def test_real_game_action_echo_cannot_disagree_with_action_id():
    obs = mismatch_position()
    answer = checked_answer(obs, action(obs, "5条")["id"])
    answer["action"]["tiles"] = ["3条"]
    with pytest.raises(DecisionError, match="编号与牌名"):
        validate_decision(answer, obs, decision_contract(obs))


def test_live_five_hand_triplet_wait_is_not_an_existing_triplet():
    obs = observe(scenario({0:"3万 3万 2饼 3饼 3饼 1条 1条 1条 3条 4条 5条 7条 8条 9条"},
                           flowers={0:"春"}), 0)
    answer = checked_answer(obs, action(obs,"2饼")["id"], reason="打2饼直接立听3万、3饼刻子待牌，凭资格花争取兑现。")
    assert validate_decision(answer,obs,decision_contract(obs))["after"]["ready"]
    answer["reason"] = "已有3饼刻子，争取兑现。"
    with pytest.raises(DecisionError, match="副本数"):
        validate_decision(answer,obs,decision_contract(obs))
    obs["self"]["hand"].remove("3饼")
    obs["self"]["hand"].append("8万")
    answer = checked_answer(obs, action(obs,"2饼")["id"], reason="3饼刻子待牌，继续推进。")
    with pytest.raises(DecisionError, match="副本数"):
        validate_decision(answer,obs,decision_contract(obs))


def test_real_game_67pin_is_not_free_to_break_and_outs_are_not_interchangeable():
    obs = observe(scenario({1: "1万 2万 5万 7万 9万 1饼 2饼 6饼 7饼 1条 5条 7条 北风 北风"}, actor=1,
        flowers={0: "春 东风", 1: "中 发 发 梅 白"}), 1)
    for p, river in zip(obs["players"], (["9万", "2饼"], ["8万"], ["北风"], ["8万"])):
        p["river"] = river
    assert receipt(obs, "1条")["after"]["unseen_improving"] == 26
    assert receipt(obs, "6饼")["after"]["unseen_improving"] == 18
    answer = checked_answer(obs, action(obs, "6饼")["id"], reason="打6筒保留26种进张，只比最优少零。")
    with pytest.raises(DecisionError, match="进张数量"):
        validate_decision(answer, obs, decision_contract(obs))


def test_regression_requires_tradeoff_but_explicit_defense_is_not_forbidden():
    obs = waiting_position()
    answer = checked_answer(obs, action(obs, "5饼")["id"])
    answer.pop("tradeoff")
    with pytest.raises(DecisionError, match="取舍类别"):
        validate_decision(answer, obs, decision_contract(obs))
    contract = decision_contract(obs)
    other = next(k for k,v in contract["public_evidence"].items() if v["seat"] != obs["seat"])
    answer["tradeoff"] = {"category": "defense", "evidence_ids": [other],
                           "reason": "明确承认拆听，以对手公开信息作为防守取舍的依据。"}
    assert not validate_decision(answer, obs, contract)["after"]["ready"]
    answer["tradeoff"]["evidence_ids"] = ["self.hand"]
    with pytest.raises(DecisionError, match="对手公开证据"):
        validate_decision(answer, obs, contract)


def test_held_flowers_never_masquerade_as_legal_tenpai():
    obs = observe(scenario({0: "1万 2万 3万 4万 5万 6万 1条 2条 3条 南风 南风 东风 中 春"}), 0)
    card = receipt(obs, "南风")
    assert card["after"]["held_flower_count"] == 3
    assert not card["after"]["ready"] and not card["after"]["eligible_ron_tiles"]
    assert "仍有留花" in checked_summary(card)


def test_qualification_uses_own_concealed_wind_but_not_unexchanged_flower():
    obs = observe(scenario({0: "1万 2万 3万 4万 5万 6万 7条 8条 9条 南风 南风 南风 西风 东风"}), 0)
    contract = decision_contract(obs)
    assert contract["self_facts"]["qualifying_hua"]["total"] == 1
    assert contract["self_facts"]["qualifying_hua"]["flowers"] == 0


def test_false_claim_no_qualification_is_rejected_when_public_flowers_exist():
    obs = mismatch_position()
    answer = checked_answer(obs, action(obs, "3条")["id"], reason="自身缺资格花，只能等自摸。")
    with pytest.raises(DecisionError, match="已有资格花"):
        validate_decision(answer, obs, decision_contract(obs))


def test_claims_about_own_pairs_and_receipt_types_are_checked():
    obs = mismatch_position()
    answer = checked_answer(obs, action(obs, "3条")["id"], reason="保留西风对子，继续推进。")
    with pytest.raises(DecisionError, match="副本数"):
        validate_decision(answer, obs, decision_contract(obs))
    answer["reason"] = "保留完整结构。"
    answer["fact_check"]["after"]["structural_shanten"] = False
    with pytest.raises(DecisionError, match="回执"):
        validate_decision(answer, obs, decision_contract(obs))


def test_llm_free_prose_is_not_displayed_or_used_to_rewrite_action():
    obs = mismatch_position()
    answer = checked_answer(obs, action(obs, "5条")["id"], reason="选择打3条更稳。")
    client, calls = fake_client([json.dumps(answer)])
    bot = LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client)
    before = copy.deepcopy(obs)
    choice=bot.choose(obs)
    assert choice.action_id == action(obs,"5条")["id"]
    assert "选择打3条更稳" not in choice.reason
    assert len(calls) == 1 and obs == before


def test_live_coach_checks_same_contract_and_generates_factual_summary():
    obs = waiting_position()
    answer = checked_answer(obs, action(obs, "西风")["id"], summary="先推进。", explanation="保留饼子的完整结构，先争取兑现。")
    client, calls = fake_client([json.dumps(answer)])
    coach = LLMCoach(LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client))
    out = coach.explain({"observation": obs})
    assert out["summary"].startswith("打 西风") and "3饼／6饼" in out["summary"]
    assert out["checked_facts"]["after"]["ready"]
    assert "decision_options" in calls[0]["messages"][0]["content"]
    assert "own_hand_counts" not in calls[0]["messages"][0]["content"]


def test_live_coach_quarantines_conflicting_free_advice():
    obs = mismatch_position()
    answer = checked_answer(obs, action(obs, "5条")["id"], summary="建议打3条。", explanation="这样保持听牌。")
    client, calls = fake_client([json.dumps(answer)])
    result=LLMCoach(LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client)).explain({"observation": obs})
    assert result["summary"].startswith("打 5条")
    assert "这样保持听牌" not in result["explanation"]
    assert result["verification_version"] == "strategy-v2"
    assert len(calls) == 1


def test_legacy_minimal_reply_no_longer_silently_passes_contract():
    obs = mismatch_position()
    client, _ = fake_client([json.dumps({"action_id": action(obs, "3条")["id"], "reason": "看着不错。"})])
    with pytest.raises(DecisionError, match="strategy-v2"):
        LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client).choose(obs)


def test_claim_receipt_requires_branch_and_correct_relative_source():
    from tests.test_simulation import act
    table = scenario({0: "1万 2万 6万 6万 6饼 7饼 7饼 8饼 8饼 9饼 3条 3条 4条", 3: "3万"}, actor=3)
    act(table, 3, "discard", "3万")
    obs = observe(table, 0)
    chi = next(a for a in obs["legal_actions"] if a["kind"] == "chi")
    card = next(c for c in decision_contract(obs)["decision_cards"] if c["action_id"] == chi["id"])
    assert "receipt" not in card  # Only concrete after-discard receipts are selectable.
    answer = checked_answer(obs, chi["id"])
    assert answer["fact_check"]["source_relative"] == "上家"
    assert answer["fact_check"]["call_count_after"] == 1
    answer["reason"] = "此吃碰为对家一次，继续推进。"
    with pytest.raises(DecisionError, match="取牌来源"):
        validate_decision(answer, obs, decision_contract(obs))
    answer["reason"] = "先固定这组，保留后续调整。"
    answer["next_discard"] = "东风"
    with pytest.raises(DecisionError, match="后续弃牌"):
        validate_decision(answer, obs, decision_contract(obs))


def test_contract_does_not_reveal_opponent_private_state_or_ankan_identity():
    hand = "1万 2万 3万 4万 5万 6万 1条 2条 3条 南风 南风 西风 北风 春"
    table = scenario({0: hand}, melds={1: [("an_gang", "中 中 中 中")]})
    obs = observe(table, 0)
    contract = decision_contract(obs)
    evidence = contract["public_evidence"]["seat.1.melds"]["value"]
    assert evidence[0]["hidden"] and evidence[0]["tiles"] is None
    assert "initial_wall" not in json.dumps(contract)
    assert all("counts" not in v for k,v in contract["public_evidence"].items() if k != "self.hand")


@pytest.mark.parametrize("kind,hand",[("chi","3万 5万 6条 7条 8条 西风 西风"),
                                    ("peng","4万 4万 6条 7条 8条 西风 西风")])
def test_third_mouth_projected_receipt_closes_ron_before_actual_claim(kind,hand):
    from tests.test_simulation import BASE,act
    t=scenario({0:BASE+" 4万",1:hand},melds={1:[("peng","1饼 1饼 1饼"),("peng","2饼 2饼 2饼")]},flowers={1:"春"})
    t.call_counts[1][0]=2;act(t,0,"discard","4万")
    obs=observe(t,1);a=next(a for a in obs["legal_actions"] if a["kind"]==kind)
    card=next(c for c in decision_contract(obs)["decision_cards"] if c["action_id"]==a["id"])
    assert any(b["receipt"]["after"]["ready"] for b in card["after_discards"])
    for branch in card["after_discards"]:
        assert branch["receipt"]["after"]["eligible_ron_tiles"]==[]
        assert branch["receipt"]["after"]["locked_with"]==[0]
        assert branch["receipt"]["after"]["conditional_zimo_payer_multipliers"]=={"0":3,"2":1,"3":1}
    assert obs["self"]["locked_with"]==[] and t.call_counts[1][0]==2
    t.call_counts[1][0]=1
    unlocked=decision_contract(observe(t,1))
    card=next(c for c in unlocked["decision_cards"] if c["action_id"]==a["id"])
    assert any(b["receipt"]["after"]["eligible_ron_tiles"] for b in card["after_discards"])


def test_code_exposes_local_taatsu_instead_of_making_model_guess_isolation():
    obs = mismatch_position()
    shapes = decision_contract(obs)["self_facts"]["local_shapes"]
    pair = next(p for p in shapes["taatsu"] if p["tiles"] == ["6饼", "7饼"])
    assert pair["completions"] == ["5饼", "8饼"]
    assert "6万" in shapes["pairs"] and "共享" in shapes["scope"]


def test_own_exposed_triplet_is_not_misclassified_as_missing_copies():
    obs = waiting_position()
    answer = checked_answer(obs, action(obs, "西风")["id"], reason="保留5万刻子，继续推进。")
    assert validate_decision(answer, obs, decision_contract(obs))["after"]["ready"]


def test_flat_action_wire_format_is_only_accepted_when_both_fields_match():
    obs = mismatch_position()
    answer = checked_answer(obs, action(obs, "3条")["id"])
    answer["action"], answer["tiles"] = "discard", ["3条"]
    assert validate_decision(answer, obs, decision_contract(obs))["after"]["ready"]
    answer["tiles"] = ["5条"]
    with pytest.raises(DecisionError, match="编号与牌名"):
        validate_decision(answer, obs, decision_contract(obs))


def test_single_wind_pair_potential_is_not_a_claim_to_already_hold_two():
    obs = waiting_position()
    answer = checked_answer(obs, action(obs, "5饼")["id"], reason="保留西风对子潜力，同时明确承认这次结构退步。")
    assert not validate_decision(answer, obs, decision_contract(obs))["after"]["ready"]
    answer["reason"] = "保留西风对子，先争取兑现。"
    with pytest.raises(DecisionError, match="副本数"):
        validate_decision(answer, obs, decision_contract(obs))
