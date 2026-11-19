import copy
import json

import pytest

from scripts.strategy_casebook import build, build_case, check_answer, redact
from src.players.deliberation import Deliberation
from src.simulation.observation import observe
from tests.test_simulation import BASE, scenario


def make_question(obs=None):
    obs=obs or observe(scenario({0:BASE+" 5万"}),0)
    row={"observation":obs,"choice":{"action_id":obs['legal_actions'][0]['id'],
                                      "controller":"llm","reason":"SECRET_ORIGINAL_CHOICE"}}
    spec={"id":"T01","category":"risk_value","source":"fake.jsonl",
          "token":obs['observation_id'].split(':',1)[1]}
    q,r=build_case(spec,[row])
    return q,r,row,spec


def valid_answer(question):
    obs=question['input']
    actions=obs['legal_actions']
    session=Deliberation(obs)
    def selection(a):
        card=next(c for c in session.cards if c['action_id']==a['id'])
        return {"action_id":a['id'],"next_discard":card['after_discards'][0]['tile'] if a['kind'] in ('chi','peng') else None}
    return {"case_id":question['case_id'],"choice":selection(actions[0]),"comparison":selection(actions[1]),
            "opponents":[{"seat":p['seat'],"patterns":[],"focus_suits":[],"watch_tiles":[],"ankan_candidates":[],
                           "confidence":"low","evidence_ids":[]} for p in obs['players'] if p['seat']!=obs['seat']],
            "reason":"信息不足，比较结构和条件风险，不能假装已知对手听口。",
            "change_if":"公开副露或花分变化时重新判断。","prior_revision":None}


def test_public_paper_excludes_original_choice_results_and_private_extra_fields():
    obs=observe(scenario({0:BASE+" 5万"}),0)
    obs['initial_wall']=['PRIVATE_WALL'];obs['oracle_hands']={'1':['PRIVATE_HAND']}
    obs['players'][1]['hand']=['PRIVATE_HAND'];obs['self']['oracle_next_draw']='PRIVATE_NEXT'
    q,r,_,_=make_question(obs)
    text=json.dumps(q,ensure_ascii=False)
    for secret in ('SECRET_ORIGINAL_CHOICE','PRIVATE_WALL','PRIVATE_HAND','PRIVATE_NEXT','original_choice_for_audit_only'):
        assert secret not in text
    assert 'result' not in q['input']
    assert r['original_is_not_gold'] and r['optimal_action'] is None
    assert r['strategy_verdict']=='unreviewed'


def test_valid_machine_check_is_never_a_strategy_pass_or_score():
    q,_,_,_=make_question();result=check_answer(q,valid_answer(q))
    assert result['automatic_checks_passed']
    assert result['strategy_verdict']=='unreviewed' and result['strategy_score'] is None
    assert result['manual_review_required']


@pytest.mark.parametrize('change',[
    lambda a:a.update(case_id='wrong'),
    lambda a:a['choice'].update(action_id='A999'),
    lambda a:a['choice'].update(next_discard='1万'),
    lambda a:a.update(comparison=copy.deepcopy(a['choice'])),
    lambda a:a.update(opponents=a['opponents'][:2]),
    lambda a:a['opponents'][0].update(evidence_ids=['not_real']),
    lambda a:a['opponents'][0].update(watch_tiles=['白']),
    lambda a:a.update(assertions={'structural_shanten':999}),
    lambda a:a.update(assertions={'probability':0.9}),
    lambda a:a.update(reason=''),
])
def test_machine_checker_rejects_invalid_claims(change):
    q,_,_,_=make_question();answer=valid_answer(q);change(answer)
    assert not check_answer(q,answer)['automatic_checks_passed']


def test_impossible_opponent_pattern_still_rejected():
    obs=observe(scenario({0:BASE+" 5万"},melds={1:[('chi','7饼 8饼 9饼')]}),0)
    q,_,_,_=make_question(obs);a=valid_answer(q)
    p=next(p for p in a['opponents'] if p['seat']==1)
    p.update(patterns=['碰碰胡'],evidence_ids=['seat.1.status'])
    result=check_answer(q,a)
    assert not result['automatic_checks_passed'] and '已排除' in result['errors'][0]


def test_redaction_rejects_revealed_opponent_kong_or_draw_and_ended_state():
    obs=observe(scenario({0:BASE+" 5万"},melds={1:[('an_gang','中 中 中 中')]}),0)
    assert redact(obs,'T')['players'][1]['melds'][0]['tiles'] is None
    broken=copy.deepcopy(obs);broken['players'][1]['melds'][0]['tiles']=['中']*4
    with pytest.raises(ValueError,match='暗杠'):redact(broken,'T')
    broken=copy.deepcopy(obs);broken['events'].append({'kind':'draw','seat':1,'hidden':True,'tile':'8万'})
    with pytest.raises(ValueError,match='摸牌'):redact(broken,'T')
    broken=copy.deepcopy(obs);broken['result']={'winner':1}
    with pytest.raises(ValueError,match='局末'):redact(broken,'T')


def test_old_assessment_must_precede_current_observation_and_remain_untrusted():
    q,_,row,spec=make_question();obs=row['observation'];gid=obs['observation_id'].split(':')[0]
    old=copy.deepcopy(row);old['observation']['observation_id']=gid+':turn0:0'
    old['decision_validation']={'decision_note':{'opponents':[{'seat':1,'hypothesis':'可能错误的旧推测'}]}}
    current=copy.deepcopy(row);current['observation']['observation_id']=gid+':turn1:0'
    current['observation']['events'].append({'kind':'discard','seat':1,'tile':'2万'})
    spec.update(category='revise_opponent',token='turn1:0',prior_token='turn0:0',target=1)
    q,_=build_case(spec,[old,current]);assert q['prior_assessment']['untrusted']
    assert q['prior_assessment']['as_of_event_count']<len(q['input']['events'])
    assert not check_answer(q,valid_answer(q))['automatic_checks_passed']
    with pytest.raises(ValueError,match='更早'):build_case(spec,[current,old])


def test_builder_separates_material_and_refuses_to_overwrite(tmp_path):
    _,_,row,spec=make_question()
    source=tmp_path/'source.jsonl';source.write_text(json.dumps(row)+'\n');spec['source']=str(source)
    manifest=tmp_path/'sources.json';manifest.write_text(json.dumps({'version':'test','cases':[spec]}))
    output=tmp_path/'bank';summary=build(manifest,output)
    assert summary['cases']==1
    public=(output/'public/T01.json').read_text()
    assert 'SECRET_ORIGINAL_CHOICE' not in public
    assert 'SECRET_ORIGINAL_CHOICE' in (output/'reviewer-only/T01.json').read_text()
    assert (output/'public/questions.md').exists()
    with pytest.raises(ValueError,match='拒绝覆盖'):build(manifest,output)
