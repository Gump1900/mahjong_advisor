"""Opinion prose is model-authored, bound to facts, not certified expertise."""
import copy
import json

import pytest

from src.players.base import DecisionError
from src.players.deliberation import Deliberation
from src.players.llm import LLMPlayer
from src.players.grounded import JUDGMENT_PROTOCOL, PROTOCOL
from src.players.table_decision import TABLE_PROTOCOL
from src.simulation.coaching import LLMCoach
from tests.test_decision_guard import waiting_position
from scripts.audit_grounded_cases import probe_frame
from tests.test_simulation import fake_client


def frame_for(session):
    board=session.grounded_board(JUDGMENT_PROTOCOL)
    return probe_frame(board,next(iter(board.branches)))


def opinion(frame):
    return ('这次我更愿意保留调整余地。[['+frame['selected']+'.state]]是当前能核对的依据；'
            '另一种打法也值得考虑，但对手还藏着什么并不清楚，我不想把猜测说成确定风险。'
            '这是经验取舍，不是已经算出了整局收益。')


def test_bot_and_coach_show_the_actual_model_opinion_not_a_template_substitute():
    obs=waiting_position();s=Deliberation(obs);f=frame_for(s);f['judgment']=opinion(f)
    client,calls=fake_client([json.dumps(f),json.dumps(f)])
    bot=LLMPlayer(client=client,model='fake',decision_protocol=JUDGMENT_PROTOCOL);choice=bot.choose(obs)
    assert '这次我更愿意保留调整余地' in choice.reason
    assert '[[B' not in choice.reason
    assert bot.last_validation['strategic_judgment']['text']==f['judgment']
    output=LLMCoach(bot).explain({'observation':obs})
    assert output['strategic_judgment']['text']==f['judgment']
    assert '军师的取舍（模型判断，不是计算证明）' in output['explanation']
    assert output['comparison_audit']['strategy_verdict']=='unreviewed'
    assert len(calls)==2


def test_only_model_wording_changes_while_action_and_checked_facts_stay_identical():
    s=Deliberation(waiting_position());f=frame_for(s);f['judgment']=opinion(f)
    first=s.evaluate(s.resolve_answer(f))
    changed=copy.deepcopy(f);changed['judgment']='我暂时不把这手评价为明显占优。[['+f['selected']+'.state]]说明了当前结构，但不知道对手的暗牌，不能据此保证最后收入。'
    second=s.evaluate(s.resolve_answer(changed))
    assert first['receipt']==second['receipt']
    assert first['explanation']!=second['explanation']
    assert second['strategic_judgment']['scope'].startswith('模型主观取舍')


def test_failed_experimental_protocol_is_not_promoted_to_the_default_or_cross_accepted():
    obs=waiting_position();s=Deliberation(obs);f=frame_for(s)
    client,calls=fake_client([json.dumps(f)])
    bot=LLMPlayer(client=client,model='fake')
    assert bot.decision_protocol==TABLE_PROTOCOL
    assert s.grounded_board().protocol==PROTOCOL
    assert 'judgment' not in s.grounded_board().template()
    with pytest.raises(DecisionError,match=TABLE_PROTOCOL):bot.choose(obs)
    assert len(calls)==1 and not bot.notebooks


@pytest.mark.parametrize('text',[
    '我选择打9条，这样留着8条对子一定可以胡，肯定安全，不需要看对手的牌。',
    '先打九筒是最好的选择，只要这样处理就可以保留更多机会，也不必考虑对手。',
    '上家已经听牌，所以这里不必继续思考，只要跟着这个建议打出去就会赢。',
    '我可以接炮，所以这里不用观察其他人的动作，继续等着别人给我机会就可以。',
    '这个选择能解除互锁，之后就不用再顾虑只能自摸，因此现在应该大胆地推进。',
    '我觉得这里做碰碰胡肯定最好，即使已经有吃牌也不必再看公开信息的限制。',
    '这样做最后能有70%的机会赢，比另一边的成功率高很多，应该放心选择。',
])
def test_no_independent_hand_score_rule_or_certain_hidden_information_prose(text):
    s=Deliberation(waiting_position());f=frame_for(s)
    f['judgment']=text+'[['+f['selected']+'.state]]'
    with pytest.raises(DecisionError):s.resolve_answer(f)


def test_opinion_cannot_borrow_an_uncompared_branch_or_unbound_fact():
    s=Deliberation(waiting_position());f=frame_for(s);b=s.grounded_board()
    other=next(i for i in b.branches if i not in (f['selected'],f['alternative']))
    f['judgment']='我认为当前仍然存在值得讨论的取舍，但这里的证据必须与实际方案一致，不能引用另一种打法。[['+other+'.state]]'
    with pytest.raises(DecisionError,match='另借分支'):s.resolve_answer(f)


def test_invalid_judgment_never_commits_note_executes_action_or_calls_again():
    obs=waiting_position();s=Deliberation(obs);f=frame_for(s);f['judgment']='我建议打9条，这张牌一定安全，也没有必要继续看局势。[['+f['selected']+'.state]]'
    client,calls=fake_client([json.dumps(f)]);bot=LLMPlayer(client=client,model='fake',decision_protocol=JUDGMENT_PROTOCOL);before=copy.deepcopy(obs)
    with pytest.raises(DecisionError):bot.choose(obs)
    assert obs==before and not bot.notebooks and len(calls)==1


@pytest.mark.parametrize('value',[None,'',12,'太短了','文字'*301])
def test_missing_or_unbounded_judgment_is_not_silently_replaced_by_code(value):
    s=Deliberation(waiting_position());f=frame_for(s);f['judgment']=value
    with pytest.raises(DecisionError,match='主观取舍理由'):s.resolve_answer(f)
