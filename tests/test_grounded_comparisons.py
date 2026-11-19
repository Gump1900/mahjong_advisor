"""Free protocol/contrast regressions; synthetic answers are not model scores."""
import copy
import json
from pathlib import Path

import pytest

from src.players.base import DecisionError
from src.players.deliberation import Deliberation
from src.players.grounded import PROTOCOL
from src.players.strategy_guard import memory_note
from scripts.audit_grounded_cases import probe_frame, audit
from tests.test_grounded import frame_for, branch_id
from tests.test_decision_guard import waiting_position
from tests.test_simulation import BASE, scenario
from src.simulation.observation import observe

BANK=Path('tests/fixtures/history')


def paper(name):
    return Deliberation(json.loads((BANK/'public'/f'{name}.json').read_text())['input'])


def test_all_historical_legal_branches_remain_selectable_not_repaired_answers():
    result=audit(BANK)
    assert result['cases']==20 and result['concrete_branches']==168
    assert result['strategy_verdict']=='not_evaluated'


def test_e05_shared_shapes_cannot_be_used_to_invent_flexibility_advantage():
    s=paper('E05');b=s.grounded_board()
    f=frame_for(s,branch_id(s,'5条'),branch_id(s,'8条'))
    f['preference']='prefer';c=f['comparisons'][0]
    c.update(topic='flexibility',effect='selected')
    for side in ('selected','alternative'):
        c[side+'_refs']=[next(r for r,v in b.facts.items() if v.get('branch_id')==f[side]
                                and v.get('shape','').startswith('4饼、6饼'))]
    with pytest.raises(DecisionError,match='共有牌形'):b.resolve(f)
    c['effect']='close';f['preference']='close'
    result=s.evaluate(s.resolve_answer(f))
    assert '没有充分依据' in result['explanation']


def test_selecting_different_shared_shapes_does_not_manufacture_a_difference():
    s=paper('E05');b=s.grounded_board();f=frame_for(s,branch_id(s,'5条'),branch_id(s,'8条'))
    f['preference']='prefer';c=f['comparisons'][0];c.update(topic='flexibility',effect='selected')
    for side,prefix in [('selected','4饼、6饼'),('alternative','6饼、8饼')]:
        c[side+'_refs']=[next(r for r,v in b.facts.items() if v.get('branch_id')==f[side] and v.get('shape','').startswith(prefix))]
    with pytest.raises(DecisionError,match='共有牌形'):b.resolve(f)


def test_equal_speed_is_not_a_speed_advantage_and_never_changes_selected_action():
    s=paper('E01');f=frame_for(s,branch_id(s,'8条'),branch_id(s,'6饼'));b=s.grounded_board()
    f['preference']='prefer';f['comparisons'][0]['effect']='selected'
    with pytest.raises(DecisionError,match='相同指标'):b.resolve(f)
    f['preference']='close';f['comparisons'][0]['effect']='close'
    answer=b.resolve(f)
    assert answer['action']['tiles']==['8条']
    assert 'intent' not in f and 'priorities' not in f and 'arguments' not in f


def test_flower_decision_compares_both_sides_without_prohibiting_defer():
    s=paper('F04');b=s.grounded_board()
    for selected,alternative in [(branch_id(s,'中','flower_kong'),branch_id(s,'8饼')),
                                  (branch_id(s,'8饼'),branch_id(s,'中','flower_kong'))]:
        f=frame_for(s,selected,alternative);f['preference']='prefer'
        f['comparisons'][0].update(topic='flower_option',effect='selected')
        result=s.evaluate(s.resolve_answer(f))
        assert result['receipt']['action']==b.branches[selected][1]['receipt']['action']
        assert '补到7饼可杠开' in result['explanation']
        if result['receipt']['action']['kind']=='flower_kong':
            assert '本次选择先换' in result['explanation']
            assert '更看重留花后再选择' not in result['explanation']
        else:
            assert 'forego_gangkai' in result['reasoning']['accept_costs']


def test_win_summary_has_no_unknown_replacement_filler():
    s=paper('M03');f=frame_for(s)
    f['selected']=next(i for i,(_,br) in s.grounded_board().branches.items() if br['receipt']['action']['kind']=='win')
    f['alternative']=next(i for i in s.grounded_board().branches if i!=f['selected'])
    f['comparisons'][0].update(topic='cash_out',effect='selected',selected_refs=[f['selected']+'.state'],
        alternative_refs=[f['alternative']+'.state'])
    f['preference']='prefer'
    result=s.evaluate(s.resolve_answer(f))
    assert '当前已可合法胡牌' in result['explanation']
    assert '换牌结果未知' not in result['explanation']


def test_specific_danger_cannot_be_inferred_from_status_or_flowers_alone():
    s=paper('R01');b=s.grounded_board();f=frame_for(s)
    target=f['opponents'][0];target['watch_tiles']=['6饼'];target['evidence_ids']=[f"seat.{target['seat']}.status"]
    with pytest.raises(DecisionError,match='实际弃牌'):b.resolve(f)


def test_one_evidence_namespace_for_hypotheses_and_comparisons():
    s=paper('M03');b=s.grounded_board();f=frame_for(s)
    allowed=set(b.payload['evidence_catalog'])
    assert allowed=={r for r,v in b.facts.items() if 'seat' in v}
    assert 'seat.2.status' in allowed and 'P2.public' in allowed and not any(r.startswith('E:') for r in allowed)
    p=next(p for p in f['opponents'] if p['seat']==2)
    p['evidence_ids']=['P2.public','seat.2.melds']
    f['comparisons'][0]['opponent_refs']=['P2.public','seat.2.melds']
    resolved=b.resolve(f)
    assert resolved['_grounded_frame']==f
    assert resolved['decision_note']['opponents'][1]['evidence_ids']==['seat.2.status','seat.2.melds']
    assert '公开成组' in b.facts['seat.2.melds']['text']
    assert '{' not in b.facts['seat.2.melds']['text']
    p['evidence_ids']=['E:seat.2.melds']
    with pytest.raises(DecisionError,match='证据编号'):b.resolve(f)


def test_watching_a_different_players_history_is_not_evidence_for_this_target():
    s=paper('M03');f=frame_for(s)
    next(p for p in f['opponents'] if p['seat']==2)['evidence_ids']=['seat.3.status']
    with pytest.raises(DecisionError,match='不能跨家'):s.grounded_board().resolve(f)


def test_more_outs_is_speed_not_an_already_won_cashout():
    s=paper('R04');f=frame_for(s,branch_id(s,'9饼'),branch_id(s,'7条'))
    f['preference']='prefer';c=f['comparisons'][0];c['effect']='selected'
    c['topic']='cash_out'
    with pytest.raises(DecisionError,match='相同指标'):s.grounded_board().resolve(f)
    c['topic']='speed';result=s.evaluate(s.resolve_answer(f))
    assert result['receipt']['action']['tiles']==['9饼']
    c['effect']='alternative'
    with pytest.raises(DecisionError,match='方向与事实相反'):s.grounded_board().resolve(f)


def test_unknown_replacement_is_not_proven_speed_advantage_for_either_side():
    s=paper('F04');f=frame_for(s,branch_id(s,'中','flower_kong'),branch_id(s,'8饼'))
    c=f['comparisons'][0];c['effect']='alternative'
    with pytest.raises(DecisionError,match='相同指标'):s.grounded_board().resolve(f)
    c['effect']='uncertain';s.evaluate(s.resolve_answer(f))


def test_uncertain_risk_is_not_forced_to_invent_specific_dangerous_tiles():
    s=paper('R03');f=frame_for(s);c=f['comparisons'][0]
    c.update(topic='defense',effect='uncertain',opponent_refs=['seat.1.river'])
    result=s.evaluate(s.resolve_answer(f))
    assert all(not p['watch_tiles'] for p in result['decision_note']['opponents'])
    c['effect']='selected'
    with pytest.raises(DecisionError,match='哪张牌或牌门'):s.grounded_board().resolve(f)


def test_known_conditional_gangkai_is_a_value_difference_not_guaranteed_income():
    s=paper('F03');f=frame_for(s,branch_id(s,'中','flower_kong'),branch_id(s,'9条'))
    f['preference']='prefer';f['comparisons'][0].update(topic='value',effect='selected')
    result=s.evaluate(s.resolve_answer(f))
    assert '补到8条可杠开' in result['explanation']
    assert '不是墙内活张或命中概率' in result['explanation']


def test_all_pairwise_contrasts_are_input_facts_not_a_filtered_action_policy():
    s=paper('E01');b=s.grounded_board();pairs=b.payload['pairwise_facts'];n=len(b.branches)
    assert len(pairs)==n*(n-1)//2
    l,r=branch_id(s,'8条'),branch_id(s,'6饼')
    pair=next(v for k,v in pairs.items() if set(k.split('|'))=={l,r})
    assert pair['speed']=='same'
    assert not pair['immediate_win']
    assert 'best' not in json.dumps(pairs)


def test_decision_table_shows_actual_remaining_hand_without_asking_model_to_subtract():
    s=paper('M01');b=s.grounded_board();rows={r['id']:r for r in b.payload['decision_table']}
    keep_single=rows[branch_id(s,'8条')]['remaining_known_hand'].split()
    discard_single=rows[branch_id(s,'南风')]['remaining_known_hand'].split()
    assert s.obs['self']['hand'].count('南风')==1
    assert keep_single.count('南风')==1
    assert discard_single.count('南风')==0
    assert b.payload['decision_table'][0]['id']==next(iter(b.branches))
    assert list(b.payload)[:2]==['protocol','decision_table']


def test_four_distinct_topics_are_not_rejected_by_a_non_rule_cardinality_limit():
    obs=waiting_position();obs['players'][1]['river']=['3饼']
    s=Deliberation(obs);b=s.grounded_board();original=frame_for(s,branch_id(s,'西风'),branch_id(s,'5饼'))
    original['preference']='prefer';original['comparisons'][0]['effect']='selected'
    for topic in ['flexibility','value','defense']:
        c=copy.deepcopy(original['comparisons'][0]);c.update(topic=topic,effect='uncertain')
        if topic=='defense':c['opponent_refs']=['seat.1.river']
        original['comparisons'].append(c)
    assert len(original['comparisons'])==4
    answer=b.resolve(original);result=b.evaluate(answer)
    assert result['decision_frame']==original
    assert len(result['reasoning']['priorities'])==4
    assert answer['action']['tiles']==['西风']
    duplicate=copy.deepcopy(original);duplicate['comparisons'].append(copy.deepcopy(duplicate['comparisons'][0]))
    with pytest.raises(DecisionError,match='主题不得重复'):b.resolve(duplicate)


def test_machine_pass_does_not_hide_unjustified_flower_deferral_or_promote_knowledge():
    s=paper('F03');f=frame_for(s,branch_id(s,'9条'),branch_id(s,'中','flower_kong'))
    f['preference']='prefer';f['comparisons'][0].update(topic='flower_option',effect='selected')
    result=s.evaluate(s.resolve_answer(f))
    assert result['receipt']['action']['tiles']==['9条']
    assert result['comparison_audit']['strategy_verdict']=='unreviewed'
    assert result['comparison_audit']['quality_warnings']
    assert '延期理由仍不足' in result['explanation']


def test_declining_win_cannot_be_described_as_immediate_cashout():
    s=paper('M03');win=next(i for i,(_,br) in s.grounded_board().branches.items() if br['receipt']['action']['kind']=='win')
    discard=branch_id(s,'2饼');f=frame_for(s,discard,win)
    f['preference']='prefer';f['comparisons'][0].update(topic='cash_out',effect='selected')
    with pytest.raises(DecisionError,match='立即兑现优势'):s.grounded_board().resolve(f)


def test_defensive_retreat_has_target_history_and_concrete_tile_relation():
    obs=waiting_position();obs['players'][1]['river']=['3饼'];obs['events'].append({'kind':'discard','seat':1,'tile':'3饼'})
    s=Deliberation(obs);f=frame_for(s,branch_id(s,'5饼'));b=s.grounded_board()
    f['preference']='prefer';c=f['comparisons'][0];c.update(topic='defense',effect='selected',opponent_refs=['seat.1.river'])
    with pytest.raises(DecisionError,match='哪张牌或牌门'):b.resolve(f)
    p=next(p for p in f['opponents'] if p['seat']==1)
    p.update(focus_suits=['饼'],evidence_ids=['seat.1.river'])
    result=s.evaluate(s.resolve_answer(f))
    assert 'speed_loss' in result['reasoning']['accept_costs']
    assert result['receipt']['action']['tiles']==['5饼']
    assert '下家' in result['explanation'] and '这是推测' in result['explanation']


def test_still_possible_history_is_reassessed_but_impossible_guess_is_not_reintroduced():
    obs=observe(scenario({0:BASE+' 5万'},melds={1:[('peng','8万 8万 8万')]}),0)
    s=Deliberation(obs);f=frame_for(s);p=next(p for p in f['opponents'] if p['seat']==1)
    p['pattern_refs']=[next(k for k,v in s.grounded_board().opponents[1]['pattern_options'].items() if v=='碰碰胡')]
    p['evidence_ids']=['seat.1.melds']
    note=memory_note(s.evaluate(s.resolve_answer(f))['decision_note'],obs)
    changed=copy.deepcopy(obs);changed['players'][1]['river'].append('9条')
    changed['events'].append({'kind':'discard','seat':1,'tile':'9条'})
    b=Deliberation(changed,note).grounded_board()
    context=b.payload['previous_hypotheses_to_reassess']
    assert any(c['previous_hypothesis']['patterns']==['碰碰胡'] and c['new_event_ids'] for c in context)
    changed['players'][1]['melds'].append({'type':'chi','tiles':['7饼','8饼','9饼'],'size':3,'hidden':False})
    b=Deliberation(changed,note).grounded_board()
    assert not any('碰碰胡' in c['previous_hypothesis']['patterns'] for c in b.payload['previous_hypotheses_to_reassess'])


@pytest.mark.parametrize('mutate',[
    lambda f:f.update(protocol='grounded-v1'),
    lambda f:f.update(priorities=['speed']),
    lambda f:f.update(intent='attack'),
    lambda f:f['comparisons'][0].update(topic='flower_timing'),
    lambda f:f.update(changes=['对手出牌后重评']),
    lambda f:f['comparisons'][0].update(selected_refs=[]),
])
def test_schema_errors_are_rejected_without_repair_or_action_replacement(mutate):
    s=Deliberation(waiting_position());f=frame_for(s);mutate(f)
    with pytest.raises(DecisionError):s.grounded_board().resolve(f)
