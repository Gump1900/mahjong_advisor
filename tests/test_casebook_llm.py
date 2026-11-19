import copy
import json

import pytest

from scripts.test_casebook_llm import request, run
from src.simulation.experiment import Budget, MeteredClient
from tests.test_simulation import fake_client
from tests.test_strategy_casebook import make_question, valid_answer
from scripts.audit_grounded_cases import probe_frame
from src.players.deliberation import Deliberation
from src.players.grounded import PROTOCOL, JUDGMENT_PROTOCOL
from src.players.table_decision import TABLE_PROTOCOL


def test_paper_run_is_one_shot_and_never_forwards_answers_or_feedback(tmp_path):
    q,_,_,_=make_question();second=copy.deepcopy(q);second['case_id']='T02'
    client,calls=fake_client(['invalid JSON',json.dumps(valid_answer(second))])
    budget=Budget(tmp_path/'budget.json','30',1800)
    meter=MeteredClient(client,budget,flower_batches=False)
    result=run([q,second],meter,'deepseek-flash','test knowledge',tmp_path/'out',budget,protocol='legacy-v2')
    assert len(calls)==2 and budget.summary()['calls']==2
    assert result['request_or_parse_failed']==1 and result['machine_pass']==1
    assert result['strategy_verdict']=='manual_review_pending'
    assert 'invalid JSON' not in calls[1]['messages'][0]['content']
    assert '实验接口补充' not in calls[0]['system']
    assert result['weights_updated'] is False and result['knowledge_promoted'] is False


def test_preflight_rejects_oversized_or_too_many_cases_before_any_request(tmp_path):
    q,_,_,_=make_question();client,calls=fake_client([]);budget=Budget(tmp_path/'budget.json','30',1800)
    with pytest.raises(ValueError):run([q]*21,client,'deepseek-flash','',tmp_path/'one',budget)
    q['question']='x'*120000
    with pytest.raises(ValueError):run([q],client,'deepseek-flash','',tmp_path/'two',budget)
    assert not calls and budget.summary()['calls']==0


def test_question_request_only_uses_public_case_and_never_injects_gold():
    q,review,_,_=make_question();r=request(q,'deepseek-flash','knowledge')
    serialized=json.dumps(r,ensure_ascii=False)
    assert 'SECRET_ORIGINAL_CHOICE' not in serialized
    assert review['source']['observation_id'] not in serialized
    assert r['max_tokens']==2048 and len(r['messages'])==1


def test_historical_grounded_paper_runner_uses_its_shared_evaluator(tmp_path):
    q,_,_,_=make_question();board=Deliberation(q['input']).grounded_board()
    frame=probe_frame(board,next(iter(board.branches)))
    client,calls=fake_client([json.dumps(frame)])
    budget=Budget(tmp_path/'budget.json','30',1800)
    result=run([q],client,'deepseek-flash','knowledge',tmp_path/'out',budget,protocol=PROTOCOL)
    assert len(calls)==1 and result['machine_pass']==1 and result['protocol']==PROTOCOL
    saved=json.loads((tmp_path/'out/T01.json').read_text())
    assert saved['check']['grounding_protocol']==PROTOCOL
    assert saved['check']['strategy_verdict']=='unreviewed'


def test_new_paper_runner_rejects_old_reply_without_retry(tmp_path):
    q,_,_,_=make_question();client,calls=fake_client([json.dumps(valid_answer(q))])
    budget=Budget(tmp_path/'budget.json','30',1800)
    result=run([q],client,'deepseek-flash','knowledge',tmp_path/'out',budget)
    assert len(calls)==1 and result['machine_rejected']==1 and result['protocol']==TABLE_PROTOCOL


def test_experiment_is_explicit_and_runner_cannot_mislabel_cross_protocol_answers(tmp_path):
    q,_,_,_=make_question();board=Deliberation(q['input']).grounded_board(JUDGMENT_PROTOCOL)
    frame=probe_frame(board,next(iter(board.branches)))
    client,calls=fake_client([json.dumps(frame),json.dumps(frame)])
    budget=Budget(tmp_path/'budget.json','30',1800)
    wrong=run([q],client,'deepseek-flash','knowledge',tmp_path/'default',budget)
    assert wrong['machine_rejected']==1 and wrong['protocol']==TABLE_PROTOCOL
    requested=run([q],client,'deepseek-flash','knowledge',tmp_path/'experiment',budget,protocol=JUDGMENT_PROTOCOL)
    assert requested['machine_pass']==1 and requested['protocol']==JUDGMENT_PROTOCOL
    assert JUDGMENT_PROTOCOL in calls[1]['system']


def test_default_paper_scores_action_and_analysis_separately_without_hiding_issues(tmp_path):
    from tests.test_table_decision import proposal
    q,_,_,_=make_question();frame=proposal(q['input']);frame['plan']=None
    client,calls=fake_client([json.dumps(frame)]);budget=Budget(tmp_path/'budget.json','30',1800)
    result=run([q],client,'deepseek-flash','knowledge',tmp_path/'new',budget)
    assert result['protocol']==TABLE_PROTOCOL and result['machine_pass']==1
    assert result['analysis_issue_cases']==1 and result['strategy_verdict']=='manual_review_pending'
    saved=json.loads((tmp_path/'new/T01.json').read_text())
    assert saved['check']['analysis_status']=='withheld'
    assert saved['answer']==frame and len(calls)==1
