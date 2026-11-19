"""New runtime contract: no real requests and no claims about playing strength."""
import copy
import json

import pytest

from src.players.base import DecisionError
from src.players.deliberation import Deliberation
from src.players.grounded import PROTOCOL
from src.players.llm import LLMPlayer
from src.simulation.coaching import LLMCoach
from src.simulation.observation import observe
from tests.test_simulation import BASE, scenario, fake_client, checked_answer
from tests.test_decision_guard import waiting_position, action


def frame_for(session, selected=None, alternative=None):
    board=session.grounded_board();ids=list(board.branches)
    selected=selected or ids[0];alternative=alternative or next(i for i in ids if i!=selected)
    from scripts.audit_grounded_cases import probe_frame
    frame=probe_frame(board,selected);frame['alternative']=alternative
    frame['comparisons'][0]['alternative_refs']=[alternative+'.state']
    return frame


def branch_id(session,tile,kind='discard'):
    return next(bid for bid,(_,b) in session.grounded_board().branches.items()
                if b['receipt']['action']['kind']==kind and tile in b['receipt']['action']['tiles'])


def test_default_agent_and_live_coach_use_same_frame_not_code_rank():
    obs=waiting_position();s=Deliberation(obs)
    # A deliberate retreat remains legal, not replaced by a speed recommendation.
    selected=branch_id(s,'5饼');frame=frame_for(s,selected)
    client,calls=fake_client([json.dumps(frame),json.dumps(frame)])
    bot=LLMPlayer(client=client,model='fake',decision_protocol=PROTOCOL)
    chosen=bot.choose(obs)
    assert bot.decision_protocol==PROTOCOL and len(calls)==1
    assert chosen.action_id==s.grounded_board().branches[selected][0]['action_id']
    assert not bot.last_validation['receipt']['after']['ready']
    assert bot.last_validation['grounding_protocol']==PROTOCOL
    coach=LLMCoach(bot).explain({'observation':obs})
    assert coach['action_id']==chosen.action_id and coach['grounding_protocol']==PROTOCOL
    assert coach['explanation'] in chosen.reason
    assert 'fact_catalog' in json.loads(calls[0]['messages'][0]['content'])


@pytest.mark.parametrize('patterns',[['碰碰胡'],['七对'],['清一色']])
def test_excluded_patterns_are_absent_and_cannot_be_named_or_injected(patterns):
    obs=observe(scenario({0:BASE+' 5万'},melds={1:[('chi','7饼 8饼 9饼'),('peng','8万 8万 8万')]}),0)
    s=Deliberation(obs);board=s.grounded_board()
    assert not set(patterns)&set(board.opponents[1]['pattern_options'].values())
    frame=frame_for(s);p=next(p for p in frame['opponents'] if p['seat']==1)
    p['pattern_refs']=patterns
    with pytest.raises(DecisionError,match='本家合法牌型编号'):board.resolve(frame)
    frame=frame_for(s);frame['opponents'][0]['patterns']=patterns
    with pytest.raises(DecisionError,match='字段'):board.resolve(frame)


def test_pattern_reference_is_target_scoped_not_just_globally_valid():
    s=Deliberation(observe(scenario({0:BASE+' 5万'}),0));b=s.grounded_board();f=frame_for(s)
    f['opponents'][0]['pattern_refs']=[next(iter(b.opponents[f['opponents'][1]['seat']]['pattern_options']))]
    with pytest.raises(DecisionError,match='本家合法'):b.resolve(f)


def test_owned_tile_and_any_visible_copy_remove_opponent_ankan_option():
    obs=observe(scenario({0:BASE+' 5万'},melds={1:[('an_gang','中 中 中 中')]}),0)
    obs['players'][2]['river']=['白'];s=Deliberation(obs);b=s.grounded_board()
    values=set(b.opponents[1]['ankan_options'].values())
    assert '5万' not in values and '白' not in values and '春' not in values
    assert '东风' in values and not b.opponents[2]['ankan_options']
    payload=json.dumps(b.payload,ensure_ascii=False)
    assert obs['players'][1]['melds'][0]['tiles'] is None
    assert 'initial_wall' not in payload and 'ron_blocked' not in json.dumps(b.payload['public_table']['players'])


def test_branch_shapes_cannot_be_borrowed_from_discard_before_or_other_option():
    obs=observe(scenario({0:'1万 4万 8万 9万 1饼 1饼 2饼 3饼 7饼 8饼 2条 5条 7条 8条'}),0)
    s=Deliberation(obs);b=s.grounded_board();selected=branch_id(s,'8条');alt=branch_id(s,'2条')
    assert not any('7条、8条' in v['text'] for v in b.facts.values() if v.get('branch_id')==selected)
    foreign=next(k for k,v in b.facts.items() if v.get('branch_id')==alt and '7条、8条' in v['text'])
    f=frame_for(s,selected,alt);f['comparisons'][0]['selected_refs'].append(foreign)
    with pytest.raises(DecisionError,match='另一分支'):b.resolve(f)


def test_counterfactual_claim_branch_is_one_atomic_choice_with_legal_discard():
    from tests.test_simulation import act
    t=scenario({0:BASE+' 5万',1:'1万 1万 2万 3万 4万 2饼 3饼 4饼 5条 6条 7条 南风 西风'})
    act(t,0,'discard','1万')
    obs=observe(t,1);s=Deliberation(obs);b=s.grounded_board()
    peng=[(bid,c,br) for bid,(c,br) in b.branches.items() if br['receipt']['action']['kind']=='peng']
    assert peng
    f=frame_for(s,peng[0][0]);answer=b.resolve(f)
    assert answer['next_discard']==peng[0][2]['receipt']['next_discard']
    b.evaluate(answer)
    answer['next_discard']='不存在'
    with pytest.raises(DecisionError,match='不一致'):b.evaluate(answer)


@pytest.mark.parametrize('mutate',[
    lambda f:f.update(reason='两张8条是孤张'),
    lambda f:f.update(selected='B9999'),
    lambda f:f.update(alternative=f['selected']),
    lambda f:f.update(changes=['unlock']),
    lambda f:f['comparisons'][0].update(selected_refs=['invented']),
    lambda f:f['comparisons'][0].update(opponent_refs=['P99.public']),
    lambda f:f['comparisons'][0].update(effect='guaranteed_safe'),
])
def test_no_prose_injection_false_fact_or_implicit_action_replacement(mutate):
    s=Deliberation(waiting_position());f=frame_for(s);mutate(f)
    client,calls=fake_client([json.dumps(f)])
    bot=LLMPlayer(client=client,model='fake',decision_protocol=PROTOCOL);before=copy.deepcopy(s.obs)
    with pytest.raises(DecisionError):bot.choose(s.obs)
    assert len(calls)==1 and not bot.notebooks and s.obs==before


def test_old_reply_cannot_bypass_new_runtime_protocol():
    obs=waiting_position();old=checked_answer(obs,action(obs,'西风')['id'])
    client,calls=fake_client([json.dumps(old)])
    with pytest.raises(DecisionError,match='grounded-v2'):
        LLMPlayer(client=client,model='fake',decision_protocol=PROTOCOL).choose(obs)
    assert len(calls)==1


def test_defense_must_reference_both_actual_branch_and_target_public_facts():
    s=Deliberation(waiting_position());f=frame_for(s,branch_id(s,'5饼'))
    target=next(iter(s.grounded_board().opponents))
    f['comparisons'][0]['topic']='defense'
    with pytest.raises(DecisionError,match='防守比较'):s.grounded_board().resolve(f)
    f['comparisons'][0]['opponent_refs']=[f'P{target}.public']
    with pytest.raises(DecisionError,match='实际公开行动'):s.grounded_board().resolve(f)


def test_old_duplicate_intent_and_priorities_cannot_bypass_pairwise_contract():
    s=Deliberation(waiting_position());f=frame_for(s);f['intent']='defend'
    with pytest.raises(DecisionError,match='重复字段'):s.grounded_board().resolve(f)


def test_batch_validated_and_no_state_or_memory_committed_on_illegal_batch():
    obs=observe(scenario({0:BASE+' 中'}),0);s=Deliberation(obs)
    f=frame_for(s,branch_id(s,'中','flower_kong'));f['flower_batch']=['中','不存在']
    client,calls=fake_client([json.dumps(f)]);bot=LLMPlayer(client=client,model='fake',decision_protocol=PROTOCOL)
    with pytest.raises(DecisionError,match='批次'):bot.choose(obs)
    assert len(calls)==1 and not bot.notebooks


def test_flower_explanation_reports_actual_batch_not_one_tile_or_free_prose():
    obs=observe(scenario({0:'1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 南风 南风 中 白 春'}),0)
    s=Deliberation(obs);f=frame_for(s,branch_id(s,'中','flower_kong'))
    single=s.evaluate(s.resolve_answer(f))
    assert '原手牌的留花还剩2张' in single['explanation']
    f['flower_batch']=['中','白','春']
    batch=s.evaluate(s.resolve_answer(f))
    assert '共3张；原手牌的留花还剩0张' in batch['explanation']
    assert '补进什么牌尚未知' in batch['explanation']


def test_current_fact_render_never_depends_on_raw_model_factual_prose():
    s=Deliberation(waiting_position());f=frame_for(s)
    result=s.evaluate(s.resolve_answer(f))
    assert result['grounding_protocol']==PROTOCOL
    assert result['decision_note']['grounding_protocol']==PROTOCOL
    assert '下次合法决策' in result['explanation'] and '互锁不解除' in result['explanation']
    assert result['decision_frame']==f


def test_grounded_request_uses_real_sdk_serialization_with_mock_transport(tmp_path):
    import anthropic
    import httpx
    from src.simulation.experiment import Budget,MeteredClient
    obs=waiting_position();s=Deliberation(obs);frame=frame_for(s);requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'msg-test','type':'message','role':'assistant','model':'deepseek-flash',
            'content':[{'type':'text','text':json.dumps(frame)}],'stop_reason':'end_turn','stop_sequence':None,
            'usage':{'input_tokens':100,'output_tokens':100}})
    budget=Budget(tmp_path/'budget.json','3',5)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        sdk=anthropic.Anthropic(api_key='fake-test',http_client=http,base_url='https://api.deepseek.com/anthropic',max_retries=0)
        bot=LLMPlayer(provider='deepseek',client=MeteredClient(sdk,budget),decision_protocol=PROTOCOL)
        bot.choose(obs)
    assert len(requests)==budget.summary()['calls']==1
    assert budget.summary()['unknown_usage_requests']==0
    assert requests[0]['thinking']['type']=='disabled'
    assert json.loads(requests[0]['messages'][0]['content'])['protocol']==PROTOCOL


def test_desktop_live_coach_frame_does_not_execute_or_recharge_cached_result(tmp_path):
    from src.simulation.engine import Table
    from src.simulation.web import DesktopTable
    from tests.test_coaching import wait_until
    d=DesktopTable(Table(42),output_dir=tmp_path,paced=True,coach_limit=2)
    obs=observe(d.table,0);frame=frame_for(Deliberation(obs))
    client,calls=fake_client([json.dumps(frame)])
    d.coach=LLMCoach(LLMPlayer(provider='deepseek',client=client,decision_protocol=PROTOCOL))
    before=d.table.state_hash();d.request_coach(d.version)
    wait_until(lambda:d.view()['coach_job']['status']=='ready')
    assert len(calls)==d.coach_calls==1 and d.table.state_hash()==before
    d.request_coach(d.version)
    assert len(calls)==1
