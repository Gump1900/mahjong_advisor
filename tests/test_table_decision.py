"""Offline gate/integration tests, NOT evidence that a real model plays well."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.players.base import DecisionError
from src.players.deliberation import Deliberation
from src.players.llm import LLMPlayer
from src.players.table_decision import TABLE_PROTOCOL, INSTRUCTIONS, compact_rules
from src.simulation.coaching import LLMCoach
from src.simulation.engine import Table
from src.simulation.experiment import run_hand
from src.simulation.observation import observe
from tests.test_simulation import BASE, scenario, fake_client
from tests.test_decision_guard import waiting_position


def proposal(obs,selected=None):
    board=Deliberation(obs).decision_board(TABLE_PROTOCOL);ids=list(board.branches)
    selected=selected or ids[0]
    return {'protocol':TABLE_PROTOCOL,'selected':selected,
        'alternative':next((i for i in ids if i!=selected),None),
        'plan':'我倾向保留后续调整余地，同时接受当前无法证明整局收益更高的不确定性。',
        'uncertainty':'对手暗牌未知，不能从公开动作断定听口。',
        'reconsider':'对手新增成组或自己得到明显改善后重新比较。','opponents':[]}


def test_default_actor_and_adviser_share_legal_action_and_fallible_analysis():
    obs=waiting_position();f=proposal(obs)
    client,calls=fake_client([json.dumps(f),json.dumps(f)])
    bot=LLMPlayer(client=client,model='fake');chosen=bot.choose(obs)
    assert bot.decision_protocol==TABLE_PROTOCOL
    audit=bot.last_validation['analysis_audit']
    assert audit['action_legal'] and audit['strategy_verdict']=='unreviewed'
    before=copy.deepcopy(obs);coached=LLMCoach(bot).explain({'observation':obs})
    assert coached['action_id']==chosen.action_id and obs==before
    assert len(calls)==2 and coached['analysis_audit']['issues']
    body=json.loads(calls[0]['messages'][0]['content'])
    assert body['protocol']==TABLE_PROTOCOL and 'options' in body
    assert 'fact_catalog' not in body and 'pairwise_facts' not in body


def test_unknown_flower_speed_is_flagged_not_a_reason_to_substitute_or_stop():
    source=Path('tests/fixtures/flower-speed-observation.json')
    obs=json.loads(source.read_text())['observation'];s=Deliberation(obs);b=s.decision_board(TABLE_PROTOCOL)
    # A new protocol proposal with the SAME choice, not relabelled old success.
    f=proposal(obs,'B10');f.update(alternative='B9',plan='我认为这样速度更快，但补牌结果仍未知，留花的实际收益也没有计算。')
    answer=s.resolve_answer(f);result=s.evaluate(answer)
    assert answer['action']['tiles']==['北风']
    assert any(i['code']=='unverified_speed_prediction' for i in result['analysis_audit']['issues'])
    assert result['analysis_audit']['raw_proposal']==f
    assert '不是已计算的优势' in result['explanation']


def test_bad_explanation_is_kept_for_audit_but_not_served_as_good_coaching():
    obs=waiting_position();f=proposal(obs)
    f['plan']='我这次还保留进张数999，说明我的收益已经被精确计算过。'
    client,calls=fake_client([json.dumps(f),json.dumps(f)])
    bot=LLMPlayer(client=client,model='fake');chosen=bot.choose(obs)
    assert '999' not in chosen.reason
    assert bot.last_validation['analysis_audit']['raw_proposal']['plan']==f['plan']
    coached=LLMCoach(bot).explain({'observation':obs})
    assert coached['analysis_audit']['status']=='withheld'
    assert '999' not in json.dumps(coached,ensure_ascii=False)
    assert coached['decision_frame']['analysis_withheld'] and len(calls)==2


@pytest.mark.parametrize('mutate',[
    lambda f:f.update(selected='B99999'),
    lambda f:f.update(action_id='wrong-action'),
    lambda f:f.update(action={'kind':'discard','tiles':['不存在']}),
    lambda f:f.update(next_discard='不存在'),
    lambda f:f.update(flower_batch=['中']),
])
def test_physical_or_action_identity_errors_still_fail_closed(mutate):
    obs=waiting_position();f=proposal(obs);mutate(f)
    client,calls=fake_client([json.dumps(f)]);bot=LLMPlayer(client=client,model='fake')
    before=copy.deepcopy(obs)
    with pytest.raises(DecisionError):bot.choose(obs)
    assert obs==before and not bot.notebooks and len(calls)==1


def test_impossible_opponent_hypotheses_are_not_downgraded_to_soft_warnings():
    obs=observe(scenario({0:BASE+' 5万'},melds={1:[('chi','7饼 8饼 9饼')]}),0)
    f=proposal(obs);f['opponents']=[{'seat':1,'patterns':['碰碰胡'],'evidence_ids':['seat.1.melds']}]
    with pytest.raises(DecisionError,match='已排除'):Deliberation(obs).resolve_answer(f)


def test_real_extra_opponent_note_remains_rejected_and_schema_is_explicit():
    path=Path('tests/fixtures/2026-10-27-table-v1-regressions.json')
    rejected=json.loads(path.read_text())['rejection']
    assert 'note' in rejected['answer']['opponents'][0]
    with pytest.raises(DecisionError,match='字段不合法'):
        Deliberation(rejected['observation']).resolve_answer(rejected['answer'])
    for field in ('seat','patterns','focus_suits','watch_tiles','ankan_candidates','confidence','evidence_ids'):
        assert field in INSTRUCTIONS
    assert '不要添加note' in INSTRUCTIONS


def test_missing_or_invalid_comparison_never_invents_a_backup_action():
    obs=waiting_position();s=Deliberation(obs);f=proposal(obs)
    f.update(alternative='B9999',plan=None,uncertainty=[],reconsider=None)
    answer=s.resolve_answer(f);result=s.evaluate(answer)
    assert result['analysis_audit']['status']=='withheld'
    assert result['decision_note']['alternative_action_id'] is None
    client,calls=fake_client([json.dumps(f)]);bot=LLMPlayer(client=client,model='fake')
    chosen=bot.choose(obs)
    assert chosen.action_id==answer['action_id'] and len(calls)==1
    assert next(iter(bot.notebooks.values()))['past_alternative'] is None


def test_all_public_chronology_and_all_concrete_branches_are_kept_once():
    obs=waiting_position();s=Deliberation(obs);b=s.decision_board(TABLE_PROTOCOL)
    assert [dict((k,v) for k,v in e.items() if k!='evidence_id') for e in b.payload['public_events']]==obs['events']
    assert {r['id'] for r in b.payload['options']}==set(s.grounded_board().branches)
    encoded=json.dumps(b.payload,ensure_ascii=False)
    assert 'initial_wall' not in encoded and 'referee' not in encoded


def test_rule_compaction_keeps_complete_rules_and_tricks_but_not_old_wire_format():
    from src.players.knowledge import load_knowledge
    raw=load_knowledge();result=compact_rules(raw)
    assert all(section in result for section in ('## 3.','## 7.','## 8.','## 9.','## 10.1 '))
    assert '689筒' in result and '## 10. 如何' not in result
    assert 'grounded-v3' not in result and '当前项目的能力限制' not in result
    appendix='\n太湖打法参考（软经验，不是新规则）：\n测试经验'
    assert compact_rules(raw+appendix).endswith(appendix)
    assert compact_rules('custom complete knowledge')=='custom complete knowledge'


def test_damaged_normalized_receipt_cannot_override_raw_model_selection():
    s=Deliberation(waiting_position());answer=s.resolve_answer(proposal(s.obs))
    answer['fact_check']['current_qualifying_hua']=999
    with pytest.raises(DecisionError,match='不一致'):s.evaluate(answer)


def test_unknown_prose_fields_are_audited_and_not_published_as_verified_advice():
    obs=waiting_position();f=proposal(obs);f['extra_prediction']='未经核对的私人预测'
    client,_=fake_client([json.dumps(f)])
    result=LLMCoach(LLMPlayer(client=client,model='fake')).explain({'observation':obs})
    assert result['analysis_audit']['status']=='withheld'
    assert '未经核对的私人预测' not in json.dumps(result,ensure_ascii=False)


def test_twenty_public_cases_preserve_all_168_branches_and_complete_events():
    paths=sorted(Path('tests/fixtures/history/public').glob('*.json'))
    assert len(paths)==20
    total=0
    for path in paths:
        obs=json.loads(path.read_text())['input'];s=Deliberation(obs);b=s.decision_board(TABLE_PROTOCOL)
        assert len(b.payload['public_events'])==len(obs['events'])
        assert len(b.payload['options'])==len(s.grounded_board().branches)
        for bid,(_,branch) in b.branches.items():
            f={'protocol':TABLE_PROTOCOL,'selected':bid,'plan':None}
            result=s.evaluate(s.resolve_answer(f))
            assert result['receipt']==branch['receipt']
            assert result['analysis_audit']['status']=='withheld'
        total+=len(b.branches)
    assert total==168


def test_entire_offline_game_continues_despite_flagged_analysis_without_fallback(tmp_path):
    calls=[]
    class Client:
        def __init__(self):self.messages=self
        def create(self,**kwargs):
            data=json.loads(kwargs['messages'][0]['content']);calls.append(data)
            # A deterministic MODEL STUB, only for lifecycle testing. It is not
            # a production policy, real LLM score, or reinforcement learning.
            answer={'protocol':TABLE_PROTOCOL,'selected':data['options'][0]['id'],'plan':None}
            return SimpleNamespace(content=[SimpleNamespace(type='text',text=json.dumps(answer))],stop_reason='end_turn')
    players=[LLMPlayer(client=Client(),model='fake',max_calls=500) for _ in range(4)]
    table=Table(42);result=run_hand(table,players,tmp_path/'offline')
    assert result['status']=='completed' and calls
    assert all(p.last_validation['analysis_audit']['status']=='withheld' for p in players if hasattr(p,'last_validation'))
    assert all('initial_wall' not in json.dumps(c) for c in calls)
    rows=[json.loads(line) for line in (tmp_path/'offline/decisions.jsonl').read_text().splitlines()]
    assert all(r['choice']['controller'] in ('llm','forced') for r in rows)
