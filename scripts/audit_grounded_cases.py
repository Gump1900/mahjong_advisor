"""Free interface/fact probes, NOT LLM answers or a playing-strength score."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if __package__ in (None,''):
    sys.path.insert(0,str(ROOT))

from scripts.strategy_casebook import DEFAULT_OUTPUT,load
from src.players.deliberation import Deliberation
from src.players.grounded import PROTOCOL, JUDGMENT_PROTOCOL


def probe_frame(board, selected):
    alternative=next((b for b in board.branches if b!=selected),selected)
    result={'protocol':board.protocol,'selected':selected,'alternative':alternative,'preference':'close',
        'opponents':[{'seat':s,'pattern_refs':[],'focus_suits':[],'watch_tiles':[],
                      'ankan_refs':[],'confidence':'low','evidence_ids':[]} for s in board.opponents],
        'comparisons':[{'topic':'speed','effect':'close','selected_refs':[selected+'.state'],
                        'alternative_refs':[alternative+'.state'],'opponent_refs':[]}],
        'changes':['own_improves']}
    if board.protocol==JUDGMENT_PROTOCOL:
        result['judgment']='这是合成接口探针，不评价哪种打法更好。[['+selected+'.state]]仅用于核对动作映射和引用，不能当成模型的真实策略成绩。'
    return result


def audit(bank):
    cases=[]
    for path in sorted((bank/'public').glob('*.json')):
        question=load(path);session=Deliberation(question['input']);board=session.grounded_board()
        roots={c['action_id'] for c,_ in board.branches.values()}
        assert roots=={a['id'] for a in session.obs['legal_actions']}
        assert len(board.branches)==sum(len(c.get('after_discards',[c])) for c in session.contract['decision_cards'])
        visible=set(board.payload['opponent_ankan_excluded_by_known_copy'])
        for options in board.opponents.values():
            assert not set(options['pattern_options'].values())&set(options['constraints']['excluded_patterns'])
            assert not set(options['ankan_options'].values())&visible
        for bid,(card,branch) in board.branches.items():
            # Exercise every legal branch, including retreats and passing a win.
            # This synthetic frame is NOT an expert answer or a model response.
            frame=probe_frame(board,bid)
            resolved=session.resolve_answer(frame)
            result=session.evaluate(resolved);session.flowers(resolved)
            assert resolved['action_id']==card['action_id']
            assert resolved.get('next_discard')==branch['receipt'].get('next_discard')
            assert result['receipt']==branch['receipt']
            assert result['grounding_protocol']==PROTOCOL
        cases.append({'case_id':question['case_id'],'legal_roots':len(roots),'concrete_branches':len(board.branches),
                      'facts':len(board.facts),'payload_bytes':len(json.dumps(board.payload,ensure_ascii=False).encode())})
    return {'scope':'synthetic interface and deterministic facts only; no LLM, no strategy score',
            'protocol':PROTOCOL,'cases':len(cases),'concrete_branches':sum(c['concrete_branches'] for c in cases),
            'all_legal_choices_retained':True,'rows':cases,'strategy_verdict':'not_evaluated'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    print(json.dumps(audit(args.bank),ensure_ascii=False,indent=2))
