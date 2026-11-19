"""Frozen real failures and independent referee checks; no paid requests."""
import copy
import json
from pathlib import Path

import pytest

from src.players.base import DecisionError
from src.players.deliberation import Deliberation
from src.players.llm import LLMPlayer
from src.players.table_decision import TABLE_PROTOCOL
from src.players.table_facts import current_facts, check_table_claims
from src.simulation.coaching import LLMCoach
from src.simulation.observation import observe
from tests.test_simulation import BASE, scenario, act, fake_client
from tests.test_table_decision import proposal


REAL_HAND=Path('tests/fixtures/2026-10-27-table-v1-regressions.json')


def real_rows():
    return json.loads(REAL_HAND.read_text())['accepted_rows']


@pytest.mark.parametrize('index,wrong',[(1,'把手牌缩回13张'),(3,'南风本身刻子分已计入资格花')])
def test_real_wrong_explanation_is_withheld_without_replacing_action(index,wrong):
    row=real_rows()[index];obs=row['observation'];frame=row['decision_validation']['decision_frame']
    assert wrong in frame['plan']
    before=copy.deepcopy(obs)
    client,calls=fake_client([json.dumps(frame),json.dumps(frame)])
    bot=LLMPlayer(client=client,model='offline')
    choice=bot.choose(obs)
    assert choice.action_id==row['choice']['action_id'] and obs==before
    audit=bot.last_validation['analysis_audit']
    assert audit['status']=='withheld' and audit['raw_proposal']==frame
    assert any(i['code']=='known_fact_contradiction' for i in audit['issues'])
    result=LLMCoach(bot).explain({'observation':obs})
    assert result['analysis_audit']['status']=='withheld'
    assert wrong not in json.dumps(result,ensure_ascii=False)
    assert result['current_facts']['winds']['南风']['qualifying_hua']==0
    assert wrong not in json.dumps(list(bot.notebooks.values()),ensure_ascii=False)
    assert len(calls)==2  # Exactly one response per actor/adviser, no repair call.


@pytest.mark.parametrize('count,expected',[(1,0),(2,0),(3,1),(4,0)])
def test_unmelded_wind_only_exact_triplet_contributes_current_hua(count,expected):
    numbers='1万 2万 3万 4饼 5饼 6饼 7条 8条 9条'.split()
    fillers=['春','夏','秋','冬'][:5-count]
    hand=' '.join(numbers+['南风']*count+fillers)
    facts=current_facts(observe(scenario({0:hand}),0))
    assert facts['winds']['南风']=={'hand_copies':count,'meld_types':[], 'qualifying_hua':expected}
    assert facts['qualifying_hua']['total']==expected


@pytest.mark.parametrize('kind,count,expected',[
    ('peng',3,1),('ming_gang',4,6),('an_gang',4,12)])
def test_wind_meld_uses_scoring_engine_without_double_counting(kind,count,expected):
    table=scenario({0:'1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风 春'},
        melds={0:[(kind,' '.join(['南风']*count))]},flowers={0:'中 夏'})
    facts=current_facts(observe(table,0))
    assert facts['winds']['南风']['qualifying_hua']==expected
    q=facts['qualifying_hua']
    assert q['flowers']==2 and q['total']==expected+2
    assert sum(q[k] for k in ('flowers','wind_triplets','concealed_wind_triplets','kongs'))==q['total']


@pytest.mark.parametrize('tile,kind,hand,melds',[
    ('春','flower_kong',BASE+' 春',None),
    ('中','an_gang','1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风 中 中 中 中',None),
    ('南风','an_gang','1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风 南风 南风 南风 南风',None),
    ('南风','add_gang','1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风 南风',
     {0:[('peng','南风 南风 南风')]}),
])
def test_effect_matches_real_completed_replacement_for_normal_and_flower_kongs(tile,kind,hand,melds):
    table=scenario({0:hand},melds=melds,wall_tail='菊')
    obs=observe(table,0);s=Deliberation(obs);board=s.decision_board(TABLE_PROTOCOL)
    option=next(o for o in board.payload['options'] if o['action']=={'kind':kind,'tiles':[tile]})
    effect=option['action_effect']
    act(table,0,kind,tile)
    assert effect['replacement_count']==1
    assert effect['hand_count_after_completed_action']==len(table.seats[0].hand)
    assert effect['known_hand_count_before_replacement']+1==len(table.seats[0].hand)
    # The replacement was a flower. The payload must NOT promise the final
    # number of held flowers or the identity of this previously unseen draw.
    assert table.seats[0].hand[-1].is_flower
    assert effect['replacement_contents']=='unknown'
    assert 'held_flower_count_after' not in effect


def test_four_individual_flowers_and_flower_ankan_have_distinct_effects():
    hand='1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风 中 中 中 中'
    table=scenario({0:hand});obs=observe(table,0);s=Deliberation(obs);b=s.decision_board(TABLE_PROTOCOL)
    single=next(o for o in b.payload['options'] if o['action']=={'kind':'flower_kong','tiles':['中']})
    f=proposal(obs,single['id']);f['flower_batch']=['中']*4
    evaluated=s.evaluate(s.resolve_answer(f))
    effect=evaluated['action_effect'];table.exchange_flowers(0,['中']*4)
    assert effect['replacement_count']==4
    assert effect['hand_count_after_completed_action']==len(table.seats[0].hand)==14
    assert not table.seats[0].melds
    assert current_facts(observe(table,0))['qualifying_hua']['flowers']==6
    other=scenario({0:hand});act(other,0,'an_gang','中')
    assert len(other.seats[0].hand)==11 and len(other.seats[0].melds)==1
    assert current_facts(observe(other,0))['qualifying_hua']['kongs']==12


@pytest.mark.parametrize('kind,owned',[
    ('chi','1万 3万'),('peng','2万 2万'),('ming_gang','2万 2万 2万')])
def test_response_effect_matches_referee_claim_and_exact_followup_discard(kind,owned):
    fixed=owned.split()+['4饼','5饼','6饼','7条','8条','9条','南风','西风','北风','春']
    hand=' '.join(fixed[:13])
    table=scenario({0:hand,3:'2万'},actor=3)
    act(table,3,'discard','2万')
    obs=observe(table,0);s=Deliberation(obs);b=s.decision_board(TABLE_PROTOCOL)
    option=next(o for o in b.payload['options'] if o['action']['kind']==kind)
    selected=b.branches[option['id']][0]['action_id']
    for seat in list(table.waiting_seats()):
        if seat==0:
            table.apply(0,selected,controller='offline-test')
        else:
            act(table,seat,'pass')
    assert table.actor==0 and table.stage=='turn'
    if kind in ('chi','peng'):
        act(table,0,'discard',option['next_discard'])
    assert option['action_effect']['hand_count_after_completed_action']==len(table.seats[0].hand)==10+(kind=='ming_gang')


def test_true_current_wind_triplet_statement_is_not_withheld():
    obs=observe(scenario({0:BASE+' 春'}),0);s=Deliberation(obs);b=s.decision_board(TABLE_PROTOCOL)
    option=next(o for o in b.payload['options'] if o['action']['kind']=='flower_kong')
    check_table_claims('南风本身刻子分已计入资格花。',b.current_facts,option['action_effect'])


@pytest.mark.parametrize('text',[
    '把手牌缩回13张再争取资格花。',
    '换完后手牌只剩十三张。',
    '换花后暗牌从十四张变成十三张。',
    '先看看局势。如果对手加速我再变。现在手牌缩回13张。',
    '南风本身刻子分已计入资格花。',
    '南风单张也算1花。',
])
def test_known_false_claim_paraphrases_are_withheld(text):
    row=real_rows()[1];obs=row['observation'];s=Deliberation(obs)
    f=copy.deepcopy(row['decision_validation']['decision_frame']);f['plan']=text
    result=s.evaluate(s.resolve_answer(f))
    assert result['analysis_audit']['status']=='withheld'
    assert text not in result['explanation']


@pytest.mark.parametrize('text',[
    '单换移一补一，手牌仍有14张。',
    '补牌前手牌13张，补完仍是14张。',
    '如果以后碰成南风刻子，就有1花。',
    '南风本身不算已有资格花。',
    '南风刻子算1花，但现在没有成刻。',
    '下家目前手牌13张。',
    '对家南风已经计入资格花。',
    '这里不是说手牌缩回13张。',
])
def test_correct_intermediate_hypothetical_negated_and_other_seat_claims_remain_valid(text):
    row=real_rows()[1];obs=row['observation'];s=Deliberation(obs);b=s.decision_board(TABLE_PROTOCOL)
    option=next(o for o in b.payload['options'] if o['id']==row['decision_validation']['decision_frame']['selected'])
    check_table_claims(text,b.current_facts,option['action_effect'])


def test_boolean_cannot_impersonate_integer_fact_echo():
    obs=observe(scenario({0:BASE+' 春'},flowers={0:'夏'}),0);s=Deliberation(obs)
    f=proposal(obs);answer=s.resolve_answer(f)
    assert answer['fact_check']['current_qualifying_hua']==2  # 夏 + 南风刻
    # Numeric zero is also not False, even though Python equality says it is.
    f['fact_check']=copy.deepcopy(answer['fact_check'])
    f['fact_check']['after']['held_flower_count']=True
    assert answer['fact_check']['after']['held_flower_count']==1
    with pytest.raises(DecisionError,match='冲突'):s.resolve_answer(f)


@pytest.mark.parametrize('text',[
    '现在手牌四张花占着位置。','手牌有4张花牌，尚须换出。','手牌三张留花。'])
def test_flower_subset_count_is_not_misread_as_whole_hand_size(text):
    row=real_rows()[1];s=Deliberation(row['observation']);b=s.decision_board(TABLE_PROTOCOL)
    option=next(o for o in b.payload['options'] if o['id']==row['decision_validation']['decision_frame']['selected'])
    check_table_claims(text,b.current_facts,option['action_effect'])


def test_completed_live_game_false_positive_is_not_repeated():
    frozen=json.loads(Path('tests/fixtures/2026-10-27-flower-subset-false-positive.json').read_text())
    assert '手牌四张花' in frozen['frame']['plan']
    assert frozen['observation']['self']['held_flower_count']==4
    assert frozen['original_analysis_audit']['status']=='withheld'
    s=Deliberation(frozen['observation']);answer=s.resolve_answer(frozen['frame']);result=s.evaluate(answer)
    assert result['analysis_audit']['status']!='withheld'
    assert result['analysis_audit']['strategy_verdict']=='unreviewed'
    assert '四张花' in result['explanation']
