"""One explicit paid hand with contextual tricks; no retry or policy override."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import re
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
if __package__ in (None,''):sys.path.insert(0,str(ROOT))

from scripts.live_batch import AccountFloorGuard, run_batch
from scripts.self_play import cny_balance
from src.core.tiles import parse_tile
from src.players.grounded import instructions
from src.players.table_decision import TABLE_PROTOCOL, INSTRUCTIONS as TABLE_INSTRUCTIONS, compact_rules
from src.players.llm import LLMPlayer
from src.simulation.experiment import Budget, MeteredClient, ExperimentPlayer, private_json


class TrickBook:
    def __init__(self, text):
        self.text=text
        self.sha256=hashlib.sha256(text.encode()).hexdigest()
        self.cards={m[1]:m[0].strip() for m in re.finditer(
            r'(?ms)^### (T\d{2})[^\n]*\n.*?(?=^### T\d{2} |^## |\Z)',text)}
        if len(self.cards)!=24:raise ValueError('经验文档必须包含24个不重复经验卡')

    def candidates(self, obs):
        ids=['T08','T11','T20']
        if any(parse_tile(t).is_flower for t in obs['self']['hand']):ids+=['T24','T12']
        elif obs.get('pending'):ids+=['T18','T10']
        else:ids+=['T13','T14']
        if any(p['unknown_ankan_count'] for p in obs['players']):ids.insert(3,'T21')
        if any(p['locked_with'] for p in obs['players']):ids.insert(3,'T22')
        if any(p['melds'] for p in obs['players'] if p['seat']!=obs['seat']):ids+=['T04','T05']
        return list(dict.fromkeys(ids))


class TricksPlayer(LLMPlayer):
    def __init__(self, *, book, **kwargs):
        super().__init__(**kwargs)
        self.book=book

    def _grounded_dialogue(self, session, key, coach, request_permit):
        original=self.knowledge
        board=session.decision_board(self.decision_protocol)
        prefix='\n太湖打法参考（软经验，不改变任何玩法或输出协议，不是概率或最优性证明）：\n'
        selected=[];body=''
        for card in self.book.candidates(session.obs):
            if len(selected)>=6:break
            candidate=body+'\n'+self.book.cards[card]
            # Leave room for the SDK wrapper's flower-batch instruction. Never
            # truncate public events, legal choices or computed facts to fit.
            knowledge=original+prefix+candidate
            if self.decision_protocol==TABLE_PROTOCOL:knowledge=compact_rules(knowledge)
            instruction=TABLE_INSTRUCTIONS if self.decision_protocol==TABLE_PROTOCOL else instructions(self.decision_protocol)
            request={'model':self.model,'max_tokens':2048,
                'system':knowledge+'\n'+instruction+json.dumps(board.template(),ensure_ascii=False),
                'messages':[{'role':'user','content':json.dumps(board.payload,ensure_ascii=False)}]}
            if len(json.dumps(request,ensure_ascii=False).encode())>117000:continue
            selected.append(card);body=candidate
        self.knowledge=original+(prefix+body if selected else '')
        session.trace.append({'kind':'tricks_context','document_sha256':self.book.sha256,
            'selected_ids':selected,'scope':'relevance selection only; no action ranking or hidden information'})
        try:
            return super()._grounded_dialogue(session,key,coach,request_permit)
        finally:
            self.knowledge=original


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llm',action='store_true',required=True)
    parser.add_argument('--budget-ledger',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=2026102601)
    args=parser.parse_args()
    if not args.budget_ledger.is_file():parser.error('必须指定已有账本，不新建或重置预算')
    book=TrickBook((ROOT/'data/knowledge/experience.md').read_text())
    budget=Budget(args.budget_ledger,'30',1800)
    funds=AccountFloorGuard(budget)
    stamp=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')
    root=ROOT/'runs/live-batch'/f'{stamp}-tricks-{uuid4().hex[:8]}'
    print('报告目录：'+str(root),flush=True)
    def make_players():
        private_json(root/'tricks-context.json',{'document_sha256':book.sha256,'document':book.text,
            'selection':'up to six relevant cards, within existing context budget; per-decision IDs in tool_trace',
            'default_protocol':TABLE_PROTOCOL,'automatic_recoveries':0})
        players=[]
        for _ in range(4):
            player=TricksPlayer(provider='deepseek',max_calls=1800,book=book)
            player.client=MeteredClient(player.client.with_options(timeout=45,max_retries=0),budget,funds_guard=funds)
            players.append(ExperimentPlayer(player))
        return players
    result=run_batch(hands=1,seed=args.seed,root=root,budget=budget,make_players=make_players,
                     balance=cny_balance,max_recoveries=0)
    print(json.dumps({'completed':result['completed'],'stop':result.get('stop'),'budget':result['budget']},ensure_ascii=False),flush=True)
    return 0 if result['completed']==1 else 1


if __name__=='__main__':raise SystemExit(main())
