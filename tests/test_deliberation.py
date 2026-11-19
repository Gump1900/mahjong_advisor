"""Offline protocol tests, not a measurement of real LLM playing strength."""
import copy
import json

import pytest

from src.players.base import DecisionError
from src.players.deliberation import Deliberation
from src.players.llm import LLMPlayer
from src.simulation.engine import Table
from src.simulation.observation import observe
from src.simulation.coaching import LLMCoach
from tests.test_simulation import checked_answer, fake_client, scenario, act
from tests.test_decision_guard import waiting_position, action


def test_single_prefaced_json_is_accepted_but_multiple_proposals_are_not():
    from types import SimpleNamespace
    from src.players.llm import json_answer
    def response(text):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])
    assert json_answer(response('先查询。\n{"tool_requests":[]}')) == {"tool_requests":[]}
    with pytest.raises(ValueError):
        json_answer(response('{"action_id":"A1"}\n{"action_id":"A2"}'))
    with pytest.raises(ValueError):
        json_answer(response('{"action_id":"A1"}\n另一方案'))


def player(answers, **kwargs):
    client, calls = fake_client([json.dumps(a) for a in answers])
    return LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client, **kwargs), calls


def query(name, **args):
    return {"tool_requests":[{"name":name,"arguments":args}]}


def test_tool_dialogue_makes_final_choice_not_search_ranking():
    obs = observe(Table(42),0)
    final = checked_answer(obs, obs["legal_actions"][-1]["id"])
    bot,calls = player([query("compare_actions",action_ids=[obs["legal_actions"][0]["id"],final["action_id"]]),final])
    chosen = bot.choose(obs)
    assert chosen.action_id == final["action_id"] and bot.calls == 2
    assert "strategy_comparison" not in calls[0]["messages"][0]["content"]
    results = json.loads(calls[1]["messages"][-1]["content"])["tool_results"]
    assert len(results[0]["result"]["cards"]) == 2
    assert bot.last_validation["decision_note"]["version"] == "strategy-v2"
    assert [p["patterns"] for p in bot.last_validation["decision_note"]["opponents"]] == [[],[],[]]


def test_tools_bounded_and_budget_counts_every_request():
    obs = observe(Table(42),0)
    bot,calls = player([query("public_table"),query("analyze_hand"),query("public_table")])
    with pytest.raises(DecisionError,match="两轮"):
        bot.choose(obs)
    assert len(calls)==3 and not bot.notebooks
    bot,calls = player([query("public_table")],max_calls=1)
    with pytest.raises(DecisionError,match="预算"):
        bot.choose(obs)
    assert len(calls)==1


def test_invalid_tool_and_transport_fail_without_retry():
    obs = observe(Table(42),0)
    bot,calls = player([query("read_referee",path="config/local.toml")])
    with pytest.raises(DecisionError,match="未知工具"):
        bot.choose(obs)
    assert len(calls)==1 and not bot.notebooks


def test_notebook_is_separate_by_game_and_seat_and_invalid_reply_not_saved():
    t=Table(42); obs=observe(t,0)
    final=checked_answer(obs,obs["legal_actions"][0]["id"])
    bad=copy.deepcopy(final);bad["decision_note"]["opponents"][0]["evidence_ids"]=["event.99999"]
    bot,calls=player([final,final,bad])
    bot.choose(obs);bot.choose(obs)
    notebook=json.loads(calls[1]["messages"][0]["content"])["notebook"]
    assert [{k:v for k,v in p.items() if k!="public_fingerprint"} for p in notebook["opponents"]] == final["decision_note"]["opponents"]
    assert "alternative_action_id" not in notebook
    assert "past_alternative" not in notebook
    before=copy.deepcopy(bot.notebooks)
    with pytest.raises(DecisionError,match="证据"):
        bot.choose(obs)
    assert bot.notebooks==before
    other=Deliberation(observe(Table(43),0))
    assert other.payload["notebook"] is None
    assert (t.game_id,1) not in bot.notebooks


def test_missing_notes_or_fake_confidence_rejected():
    obs=observe(Table(42),0);s=Deliberation(obs)
    final=checked_answer(obs,obs["legal_actions"][0]["id"])
    final.pop("decision_note")
    with pytest.raises(DecisionError,match="缺少"):
        s.note(final)
    final=checked_answer(obs,obs["legal_actions"][0]["id"])
    final["decision_note"]["opponents"][0]["confidence"]="high"
    with pytest.raises(DecisionError,match="无证据"):
        s.note(final)


def test_regression_for_defense_is_allowed_with_actual_public_evidence():
    obs=waiting_position();final=checked_answer(obs,action(obs,"5饼")["id"],reason="这次愿意牺牲速度，防守判断仍可能有误。")
    final["tradeoff"]={"category":"defense","evidence_ids":["seat.0.status"],
                       "reason":"对手的公开状态值得重新审视，这次选择承担结构损失。"}
    bot,_=player([final])
    assert bot.choose(obs).action_id==final["action_id"]
    assert not bot.last_validation["receipt"]["after"]["ready"]


def test_partial_batch_is_model_selected_and_bound_to_observation():
    obs=observe(Table(42),0)
    flowers=[a for a in obs["legal_actions"] if a["kind"]=="flower_kong"]
    final=checked_answer(obs,flowers[0]["id"],flower_batch=[flowers[0]["tiles"][0]])
    bot,_=player([final]);assert bot.select_flowers(obs)==[]
    bot.choose(obs)
    assert bot.select_flowers(obs)==final["flower_batch"]
    other=copy.deepcopy(obs);other["observation_id"]+="-new"
    assert bot.select_flowers(other)==[]
    bad=copy.deepcopy(final);bad["flower_batch"]=["不存在"]
    with pytest.raises(DecisionError,match="批次"):
        Deliberation(obs).flowers(bad)


def test_hidden_ankan_and_private_pass_do_not_leak_through_tools():
    t=scenario({1:"中 中 中 中 1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风"},actor=1)
    act(t,1,"an_gang","中")
    t.seats[1].ron_blocked=True
    s=Deliberation(observe(t,0));public=s.tool("public_table",{})
    assert public["players"][1]["melds"][0]["tiles"] is None
    assert "ron_blocked" not in public["players"][1]
    amount=s.tool("conditional_payment",{"winner":1})
    assert amount["unknown_ankan_hua_range"]==[10,12]
    assert amount["conditional_subtotal_range"]==[12,14]
    assert amount["unpriced"] and not amount["publicly_cannot_ron"]


def test_live_coach_uses_same_tools_without_touching_table_and_counts_permits():
    t=Table(42);obs=observe(t,0);before=t.state_hash()
    final=checked_answer(obs,obs["legal_actions"][0]["id"],summary="先保留调整余地",explanation="先比较推进机会，再观察其他家的新动作。")
    bot,calls=player([query("conditional_payment",winner=2),final]);permits=[]
    def permit():
        permits.append(1);return True
    result=LLMCoach(bot).explain({"observation":obs,"_request_permit":permit})
    assert len(permits)==len(calls)==2 and t.state_hash()==before
    assert result["decision_note"] and result["tool_trace"]


def test_coach_cap_stops_tool_continuation_before_second_api_call():
    obs=observe(Table(42),0);bot,calls=player([query("analyze_hand")]);permits=iter([True,False])
    with pytest.raises(DecisionError,match="预算"):
        LLMCoach(bot).explain({"observation":obs,"_request_permit":lambda:next(permits)})
    assert len(calls)==1 and not bot.notebooks


def test_coach_and_opponent_do_not_share_notebooks_or_call_counter():
    obs=observe(Table(42),0)
    final=checked_answer(obs,obs["legal_actions"][0]["id"],summary="先观察局势",explanation="先保留调整余地。")
    bot,_=player([final,final]);coach=LLMCoach(bot)
    bot.choose(obs)
    assert bot.notebooks and not coach.player.notebooks and coach.player.calls==0
    coach.explain({"observation":obs})
    assert bot.calls==coach.player.calls==1
    assert coach.player.notebooks is not bot.notebooks


def test_desktop_counts_actual_requests_including_tools_and_caches_result(tmp_path):
    from src.simulation.web import DesktopTable
    from tests.test_coaching import wait_until
    d=DesktopTable(Table(42),output_dir=tmp_path,paced=True,coach_limit=2)
    obs=observe(d.table,0)
    final=checked_answer(obs,obs["legal_actions"][0]["id"],summary="先保留机会",explanation="先观察下一轮的变化。")
    bot,calls=player([query("analyze_hand"),final]);d.coach=LLMCoach(bot)
    before=d.table.state_hash();d.request_coach(d.version)
    wait_until(lambda:d.view()["coach_job"]["status"]=="ready")
    assert d.coach_calls==len(calls)==2 and d.table.state_hash()==before
    d.request_coach(d.version)
    assert len(calls)==2


def test_metered_tool_rounds_use_real_sdk_serialization_without_network(tmp_path):
    import anthropic
    import httpx
    from src.simulation.experiment import Budget, MeteredClient
    obs=observe(Table(42),0);final=checked_answer(obs,obs["legal_actions"][0]["id"])
    replies=iter([query("conditional_payment",winner=2),final]);requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={"id":"msg-test","type":"message","role":"assistant",
            "model":"deepseek-flash","content":[{"type":"text","text":json.dumps(next(replies))}],
            "stop_reason":"end_turn","stop_sequence":None,"usage":{"input_tokens":100,"output_tokens":100}})
    budget=Budget(tmp_path/"budget.json","3",5)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        sdk=anthropic.Anthropic(api_key="fake-test",http_client=http,base_url="https://api.deepseek.com/anthropic",max_retries=0)
        bot=LLMPlayer(decision_protocol="legacy-v2", provider="deepseek",client=MeteredClient(sdk,budget))
        assert bot.choose(obs).action_id==final["action_id"]
    assert budget.summary()["calls"]==2 and budget.summary()["unknown_usage_requests"]==0
    assert requests[1]["messages"][1]["role"]=="assistant"
    assert requests[1]["max_tokens"]==2048
