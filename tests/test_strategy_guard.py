"""Offline boundaries, frozen mistakes and legitimate risky choices; no API."""
import copy
import json

import pytest

from src.players.base import DecisionError
from src.players.deliberation import Deliberation
from src.players.llm import LLMPlayer
from src.players.strategy_guard import VERSION, INTENTS, PRIORITIES, memory_note, refresh_memory
from src.simulation.coaching import LLMCoach
from src.simulation.observation import observe
from tests.test_simulation import BASE, scenario, checked_answer, fake_client
from tests.test_decision_guard import action, waiting_position


def with_public_chi():
    return observe(scenario({0:BASE+" 5万"},melds={1:[("chi","7饼 8饼 9饼"),
        ("peng","8万 8万 8万"),("peng","9条 9条 9条")]}),0)


def guess(answer, seat=1, **changes):
    item=next(p for p in answer["decision_note"]["opponents"] if p["seat"]==seat)
    item["evidence_ids"]=[f"seat.{seat}.status"]
    item.update(changes)
    return item


@pytest.mark.parametrize("pattern",["碰碰胡","七对","豪华七对","双豪华","三豪华","清一色","大吊车"])
def test_public_melds_hard_exclude_impossible_patterns(pattern):
    obs=with_public_chi();answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,patterns=[pattern])
    with pytest.raises(DecisionError,match="已排除牌型"):
        Deliberation(obs).evaluate(answer)


def test_same_constraint_is_shared_by_player_and_adviser_without_retry_or_memory():
    obs=with_public_chi();answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,patterns=["碰碰胡"],confidence="high")
    for coach in (False,True):
        client,calls=fake_client([json.dumps(answer)])
        bot=LLMPlayer(decision_protocol="legacy-v2", client=client,model="fake")
        before=copy.deepcopy(obs)
        with pytest.raises(DecisionError,match="已排除牌型"):
            LLMCoach(bot).explain({"observation":obs}) if coach else bot.choose(obs)
        assert len(calls)==1 and not bot.notebooks and obs==before


def test_free_form_hypothesis_cannot_bypass_typed_patterns():
    obs=with_public_chi();answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,hypothesis="一定是碰碰胡")
    with pytest.raises(DecisionError,match="结构化字段"):
        Deliberation(obs).evaluate(answer)


@pytest.mark.parametrize("tile",["5万","9万","春"])
def test_impossible_hidden_ankan_guesses_are_rejected(tile):
    obs=observe(scenario({0:BASE+" 5万"},melds={1:[("an_gang","中 中 中 中")]}),0)
    obs["players"][2]["river"]=["9万"]
    answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,ankan_candidates=[tile])
    with pytest.raises(DecisionError):
        Deliberation(obs).evaluate(answer)


def test_possible_ankan_is_labeled_guess_and_not_revealed_as_fact():
    obs=observe(scenario({0:BASE+" 5万"},melds={1:[("an_gang","中 中 中 中")]}),0)
    answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,ankan_candidates=["白"])
    answer["reasoning"]["focus_seats"]=[1]
    result=Deliberation(obs).evaluate(answer)
    assert "白，不是已知牌名" in result["explanation"]
    assert "暗杠中" not in result["explanation"]


@pytest.mark.parametrize("tile",["发","白","东风","春"])
def test_flowers_are_never_discard_danger_candidates(tile):
    obs=with_public_chi();answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,watch_tiles=[tile])
    with pytest.raises(DecisionError,match="推测危险牌"):
        Deliberation(obs).evaluate(answer)


def test_evidence_must_belong_to_the_hypothesis_target():
    obs=with_public_chi();answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,evidence_ids=["seat.2.status"],watch_tiles=["5万"])
    with pytest.raises(DecisionError,match="未关联"):
        Deliberation(obs).evaluate(answer)


def test_public_call_counts_have_seat_scoped_evidence_not_unrestricted_names():
    obs=with_public_chi();s=Deliberation(obs)
    assert s.evidence["seat.1.call_counts"]=={"seat":1,"call_counts":obs["call_counts"][1]}
    answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,evidence_ids=["seat.1.call_counts"])
    s.evaluate(answer)
    guess(answer,evidence_ids=["seat.2.call_counts"])
    with pytest.raises(DecisionError,match="未关联"):
        s.evaluate(answer)


def test_memory_expires_when_public_facts_change_and_never_reuses_legacy_prose():
    obs=observe(scenario({0:BASE+" 5万"},melds={1:[("peng","8万 8万 8万")]}),0)
    answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,patterns=["碰碰胡"],confidence="medium")
    result=Deliberation(obs).evaluate(answer)
    note=memory_note(result["decision_note"],obs)
    stable=Deliberation(obs,note)
    assert len(stable.payload["notebook"]["opponents"])==3
    changed=copy.deepcopy(obs)
    changed["players"][1]["melds"].append({"type":"chi","tiles":["7饼","8饼","9饼"],"hidden":False,"size":3})
    refreshed=Deliberation(changed,note)
    assert all(p["seat"]!=1 for p in refreshed.payload["notebook"]["opponents"])
    assert refreshed.payload["memory_invalidations"][0]["seat"]==1
    assert "碰碰胡" not in json.dumps(refreshed.payload["notebook"],ensure_ascii=False)
    legacy=Deliberation(obs,{"plan":"旧笔记注入","opponents":[{"hypothesis":"已知暗杠中"}]})
    assert legacy.payload["notebook"] is None
    assert "旧笔记注入" not in json.dumps(legacy.payload,ensure_ascii=False)


def test_still_possible_old_guess_expires_on_new_river_and_new_own_copy():
    obs=observe(scenario({0:BASE+" 5万"},melds={1:[("an_gang","中 中 中 中")]}),0)
    answer=checked_answer(obs,action(obs,"5万")["id"])
    guess(answer,ankan_candidates=["白"])
    note=memory_note(Deliberation(obs).evaluate(answer)["decision_note"],obs)
    changed=copy.deepcopy(obs);changed["players"][1]["river"].append("9万")
    assert all(p["seat"]!=1 for p in Deliberation(changed,note).payload["notebook"]["opponents"])
    changed=copy.deepcopy(obs);changed["self"]["hand"][-1]="白"
    refreshed,_=refresh_memory(note,changed,Deliberation(obs).evidence)
    assert all(p["seat"]!=1 for p in refreshed["opponents"])


def test_same_seat_memory_is_not_used_after_undo_or_other_game():
    obs=waiting_position();answer=checked_answer(obs,action(obs,"西风")["id"])
    client,calls=fake_client([json.dumps(answer),json.dumps(answer),json.dumps(answer)])
    bot=LLMPlayer(decision_protocol="legacy-v2", client=client,model="fake")
    bot.choose(obs)
    key=(obs["observation_id"].split(":",1)[0],obs["seat"])
    bot.notebooks[key]["events"]=[{"kind":"discard","seat":0,"tile":"9万"}]
    bot.choose(obs)
    assert json.loads(calls[-1]["messages"][0]["content"])["notebook"] is None
    other=copy.deepcopy(obs);other["observation_id"]="another:"+obs["observation_id"].split(":",1)[1]
    bot.choose(other)
    assert json.loads(calls[-1]["messages"][0]["content"])["notebook"] is None


def winter_position():
    table=scenario({3:"1饼 2饼 3饼 9条 冬"},actor=3,
        melds={3:[("chi","1万 2万 3万"),("peng","5万 5万 5万"),("peng","2条 2条 2条")]},
        flowers={3:"春 夏 秋 梅 兰 竹"})
    table.call_counts[3][2]=3
    return observe(table,3)


def test_known_missed_flower_requires_acknowledgment_but_does_not_force_swap():
    obs=winter_position();answer=checked_answer(obs,action(obs,"9条")["id"])
    assert set(answer["reasoning"]["accept_costs"])=={"held_flowers","forego_gangkai"}
    broken=copy.deepcopy(answer);broken["reasoning"]["accept_costs"]=[]
    with pytest.raises(DecisionError,match="接受代价"):
        Deliberation(obs).evaluate(broken)
    answer["reason"]="打9条留123饼就是单吊听牌"
    result=Deliberation(obs).evaluate(answer)
    assert result["receipt"]["action"]["tiles"]==["9条"]
    assert not result["receipt"]["after"]["ready"]
    assert "留123饼就是单吊" not in result["explanation"]
    assert "若补到9条可杠开" in result["explanation"]
    assert "当前不能胡牌" in result["explanation"]


def test_second_live_missed_flower_cannot_invent_6679_sou():
    obs=observe(scenario({0:"4万 5万 6万 8万 8万 8万 5条 5条 5条 7条 9条 北风 北风 中"},flowers={0:"春 夏"}),0)
    answer=checked_answer(obs,action(obs,"9条")["id"])
    answer["reasoning"]["shape_refs"]=["triplet:6条"]
    with pytest.raises(DecisionError,match="牌形引用"):
        Deliberation(obs).evaluate(answer)
    answer["reasoning"]["shape_refs"]=["triplet:5条"]
    result=Deliberation(obs).evaluate(answer)
    assert "若补到8条可杠开" in result["explanation"]
    assert not result["receipt"]["after"]["ready"]
    assert "forego_gangkai" in result["reasoning"]["accept_costs"]


def test_shape_references_use_selected_branch_and_code_names_edge_correctly():
    obs=observe(scenario({0:"1万 1万 2万 3万 4万 5条 6条 7条 南风 南风 南风 6饼 8饼 9饼"}),0)
    answer=checked_answer(obs,action(obs,"9饼")["id"])
    answer["reasoning"]["shape_refs"]=["taatsu:6饼+8饼"]
    result=Deliberation(obs).evaluate(answer)
    assert "6饼、8饼坎张搭，等7饼" in result["explanation"]
    answer["reasoning"]["shape_refs"]=["taatsu:8饼+9饼"]
    with pytest.raises(DecisionError,match="牌形引用"):
        Deliberation(obs).evaluate(answer)
    answer["reasoning"]["shape_refs"]=["pair:1饼"]
    with pytest.raises(DecisionError,match="牌形引用"):
        Deliberation(obs).evaluate(answer)
    edge=checked_answer(obs,action(obs,"6饼")["id"])
    edge["reasoning"]["shape_refs"]=["taatsu:8饼+9饼"]
    assert "8饼、9饼边张搭，等7饼" in Deliberation(obs).evaluate(edge)["explanation"]


def test_live_single_four_real_shape_refs_are_not_a_rule_violation():
    obs=observe(scenario({0:"1万 1万 2万 2万 3万 5万 5万 7万 4饼 6饼 8饼 5条 8条 北风"}),0)
    answer=checked_answer(obs,action(obs,"北风")["id"])
    answer["reasoning"]["shape_refs"]=["pair:1万","pair:2万","pair:5万","sequence:1万+2万+3万"]
    result=Deliberation(obs).evaluate(answer)
    assert result["receipt"]["action"]["tiles"]==["北风"]
    assert "形状可能共享牌" in result["explanation"]
    duplicate=copy.deepcopy(answer)
    duplicate["reasoning"]["shape_refs"].append("pair:1万")
    with pytest.raises(DecisionError,match="牌形引用"):
        Deliberation(obs).evaluate(duplicate)
    nonexistent=copy.deepcopy(answer)
    nonexistent["reasoning"]["shape_refs"].append("pair:9万")
    with pytest.raises(DecisionError,match="牌形引用"):
        Deliberation(obs).evaluate(nonexistent)


@pytest.mark.parametrize("intent", list(INTENTS))
def test_primary_strategy_vocabulary_is_shared_and_preserved(intent):
    obs=waiting_position();answer=checked_answer(obs,action(obs,"西风")["id"])
    answer["reasoning"]["intent"]=intent
    answer["reasoning"]["focus_seats"]=[0]
    original=copy.deepcopy(answer)
    session=Deliberation(obs)
    assert set(PRIORITIES)<=set(session.payload["strategy_contract"]["intents"])
    result=session.evaluate(answer)
    assert answer==original
    assert result["reasoning"]["intent"]==intent
    assert result["receipt"]["action"]["tiles"]==["西风"]
    assert INTENTS[intent] in result["explanation"]


@pytest.mark.parametrize("intent",["defend","defense"])
def test_both_defensive_intents_require_target_in_live_and_review(intent):
    from src.players.strategy_guard import render_review
    obs=waiting_position();a=action(obs,"西风")
    answer=checked_answer(obs,a["id"])
    requirement=Deliberation(obs).payload["strategy_contract"]["conditional_requirements"]["focus_seats"]
    assert intent in requirement["required_if_intent_in"]
    assert requirement["required_if_priorities_contains"]=="defense"
    answer["reasoning"].update(intent=intent,priorities=["speed"],focus_seats=[])
    with pytest.raises(DecisionError,match="关注哪一家"):
        Deliberation(obs).evaluate(answer)
    candidate={"action_id":a["id"],"kind":"discard","tiles":["西风"],"shanten":0,"unseen_improving":6}
    review={"seat":obs["seat"],"decisions":[{"step":10,"actual":a,"public_then":obs["players"],"legal_candidates":[candidate]}]}
    point={"step":10,"alternative_action_id":a["id"],"alternative_next_discard":None,"intent":intent,"focus_seats":[]}
    with pytest.raises(DecisionError,match="关注哪一家"):
        render_review({"strategy_version":VERSION,"review_points":[point]},review)


@pytest.mark.parametrize("intent",[None,[],{},123,"unknown_strategy","SPEED"])
def test_intent_compatibility_does_not_guess_unknown_or_malformed_values(intent):
    obs=waiting_position();answer=checked_answer(obs,action(obs,"西风")["id"])
    answer["reasoning"]["intent"]=intent
    with pytest.raises(DecisionError,match="意图不合法"):
        Deliberation(obs).evaluate(answer)


def test_speed_intent_still_rejects_false_facts_and_impossible_shapes():
    obs=waiting_position();answer=checked_answer(obs,action(obs,"西风")["id"])
    answer["reasoning"]["intent"]="speed"
    broken=copy.deepcopy(answer);broken["fact_check"]["after"]["structural_shanten"]=7
    with pytest.raises(DecisionError,match="回执"):
        Deliberation(obs).evaluate(broken)
    broken=copy.deepcopy(answer);broken["reasoning"]["shape_refs"]=["triplet:6条"]
    with pytest.raises(DecisionError,match="牌形引用"):
        Deliberation(obs).evaluate(broken)


def test_frozen_live_speed_reply_keeps_its_action_without_repair_request():
    obs=observe(scenario({1:"3万 7万 2饼 6饼 7饼 8饼 1条 1条 2条 3条 6条 9条 西风 北风"},actor=1),1)
    answer=checked_answer(obs,action(obs,"北风")["id"])
    answer["reasoning"]={"intent":"speed","priorities":["speed","value","flexibility"],
        "focus_seats":[],"accept_costs":[],"change_triggers":["own_improves","opponent_claims","unseen_changes"],
        "shape_refs":["sequence:6饼+7饼+8饼","taatsu:2条+3条"]}
    for seat in (0,2,3):
        guess(answer,seat,evidence_ids=[f"seat.{seat}.status",f"seat.{seat}.known_qualifying_hua"])
    client,calls=fake_client([json.dumps(answer)])
    bot=LLMPlayer(decision_protocol="legacy-v2", client=client,model="fake")
    choice=bot.choose(obs)
    assert len(calls)==1
    assert choice.action_id==answer["action_id"]
    assert bot.last_validation["reasoning"]["intent"]=="speed"
    assert bot.last_validation["receipt"]["action"]["tiles"]==["北风"]


def test_rejection_feedback_contains_enriched_selected_branch_and_names_false_shape():
    obs=observe(scenario({3:"1万 4万 8万 9万 1饼 1饼 2饼 3饼 7饼 8饼 2条 5条 7条 8条"},actor=3),3)
    answer=checked_answer(obs,action(obs,"8条")["id"])
    broken=copy.deepcopy(answer);broken["reasoning"]["shape_refs"]=["taatsu:7条+8条"]
    with pytest.raises(DecisionError,match="所选动作处理后的手牌：taatsu:7条\\+8条"):
        Deliberation(obs).evaluate(broken)
    client,calls=fake_client([json.dumps(answer)])
    bot=LLMPlayer(decision_protocol="legacy-v2", client=client,model="fake")
    bot.repair_feedback={"observation_id":obs["observation_id"],"error":"冻结错误","action_id":answer["action_id"]}
    bot.choose(obs)
    card=json.loads(calls[0]["messages"][0]["content"])["previous_rejection"]["previous_selected_card"]
    assert "shape_catalog" in card and "required_accept_costs" in card
    assert "taatsu:7条+8条" not in card["shape_catalog"]
    assert "taatsu:5条+7条" in card["shape_catalog"]
    assert len(calls)==1


def test_compact_protocol_derives_omitted_costs_but_never_overwrites_wrong_echo():
    obs=waiting_position();s=Deliberation(obs)
    answer=checked_answer(obs,action(obs,"5饼")["id"])
    answer["action_id"]=s.reverse_handles[answer["action_id"]]
    del answer["reasoning"]["accept_costs"]
    resolved=s.resolve_answer(answer)
    assert "speed_loss" in resolved["reasoning"]["accept_costs"]
    assert "accept_costs" not in answer["reasoning"]
    s.evaluate(resolved)
    answer["reasoning"]["accept_costs"]=[]
    with pytest.raises(DecisionError,match="接受代价"):
        s.evaluate(s.resolve_answer(answer))


def test_compact_version_metadata_can_be_omitted_but_old_protocol_cannot_bypass():
    obs=waiting_position();s=Deliberation(obs)
    answer=checked_answer(obs,action(obs,"西风")["id"])
    answer["action_id"]=s.reverse_handles[answer["action_id"]]
    del answer["strategy_version"]
    assert s.evaluate(s.resolve_answer(answer))["verification_version"]==VERSION
    answer["strategy_version"]="strategy-v1"
    with pytest.raises(DecisionError,match="strategy-v2"):
        s.evaluate(s.resolve_answer(answer))
    del answer["strategy_version"];answer["reasoning"]="只看自由文字"
    with pytest.raises(DecisionError,match="策略判断"):
        s.evaluate(s.resolve_answer(answer))


def test_no_required_cost_does_not_force_fabricated_tradeoff_and_defense_remains_legal():
    obs=waiting_position();answer=checked_answer(obs,action(obs,"西风")["id"])
    answer["tradeoff"]=None
    assert answer["reasoning"]["accept_costs"]==[]
    result=Deliberation(obs).evaluate(answer)
    assert result["tradeoff"] is None
    defensive=checked_answer(obs,action(obs,"5饼")["id"])
    defensive["reasoning"].update(intent="defend",priorities=["defense"],focus_seats=[0])
    defensive["tradeoff"]={"category":"defense","evidence_ids":["seat.0.status"]}
    result=Deliberation(obs).evaluate(defensive)
    assert not result["receipt"]["after"]["ready"] and "speed_loss" in result["reasoning"]["accept_costs"]
    assert result["receipt"]["action"]["tiles"]==["5饼"]


def test_model_factual_echo_cannot_be_silently_corrected_in_new_protocol():
    obs=waiting_position();answer=checked_answer(obs,action(obs,"西风")["id"])
    answer["fact_check"]["after"]["structural_shanten"]=7
    with pytest.raises(DecisionError,match="回执"):
        Deliberation(obs).evaluate(answer)


def test_raw_factual_prose_is_not_shown_or_carried_forward():
    obs=waiting_position();answer=checked_answer(obs,action(obs,"西风")["id"])
    poison="错误讲解：吃345说456，凭空多了对子，旧猜测当事实"
    answer.update(reason=poison,summary=poison,explanation=poison)
    answer["decision_note"]["plan"]=poison
    client,calls=fake_client([json.dumps(answer),json.dumps(answer)])
    coach=LLMCoach(LLMPlayer(decision_protocol="legacy-v2", client=client,model="fake"))
    first=coach.explain({"observation":obs});coach.explain({"observation":obs})
    assert poison not in json.dumps(first,ensure_ascii=False)
    assert poison not in calls[1]["messages"][0]["content"]
    assert first["verification_version"]==VERSION


def test_historical_review_rejects_free_prose_and_nonexistent_decisions():
    from src.players.strategy_guard import render_review
    obs=waiting_position();a=action(obs,"西风")
    candidate={"action_id":a["id"],"kind":"discard","tiles":["西风"],"shanten":0,"unseen_improving":6}
    review={"seat":obs["seat"],"decisions":[{"step":10,"actual":a,"public_then":obs["players"],"legal_candidates":[candidate]}]}
    point={"step":10,"alternative_action_id":a["id"],"alternative_next_discard":None,"intent":"balance","focus_seats":[]}
    answer={"strategy_version":VERSION,"review_points":[point]}
    assert render_review(answer,review)["verification_version"]==VERSION
    legacy={"summary":"凭空多了对子","explanation":"对手暗杠中"}
    with pytest.raises(DecisionError,match="结构化"):
        render_review(legacy,review)
    wrong=copy.deepcopy(answer);wrong["review_points"][0]["step"]=999
    with pytest.raises(DecisionError,match="不存在"):
        render_review(wrong,review)
    wrong=copy.deepcopy(answer);wrong["review_points"][0]["alternative_action_id"]="future-action"
    with pytest.raises(DecisionError,match="当时的合法动作"):
        render_review(wrong,review)
    wrong=copy.deepcopy(answer);wrong["review_points"][0]["intent"]="defend"
    with pytest.raises(DecisionError,match="关注哪一家"):
        render_review(wrong,review)


def test_legacy_coach_caches_are_hidden_without_automatic_model_repair():
    from src.simulation.web import ASSETS
    script=(ASSETS/"table.js").read_text()
    assert 'fresh&&fresh.verification_version!=="strategy-v2"' in script
    assert 'previous.result.verification_version==="strategy-v2"' in script
    assert "不会自动重试或产生费用" in script
