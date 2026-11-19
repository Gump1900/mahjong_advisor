"""Explicitly paid, bounded ten-hand lab. Never relax legality or facts.

Recoveries are journalled new attempts, not SDK retries or fallback decisions.
Keep the same per-seat instances/notebooks throughout a hand's recoveries.
"""
import argparse
import hashlib
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from scripts.self_play import cny_balance
from src.players.llm import LLMPlayer
from src.players.strategy_guard import VERSION, memory_note
from src.simulation.engine import Table
from src.simulation.experiment import Budget, MeteredClient, ExperimentPlayer, private_json, run_hand, consolidate_completed_campaign


class AccountFloorGuard:
    """Refresh account balance at most every 30s, reserving intervening costs.

    One free endpoint failure may retry once; no model request is retried here.
    """
    def __init__(self,budget,balance=cny_balance,clock=time.monotonic):
        self.budget,self.balance,self.clock=budget,balance,clock
        self.available=None;self.checked_at=0;self.offset=0

    def __call__(self):
        from src.players.base import DecisionError
        since=self.budget._update(lambda d:sum((Decimal(r["charged_upper_cny"]) for r in d["requests"][self.offset:]),Decimal(0)))
        required=Decimal("2")+Budget.cost(Budget.MAX_INPUT,Budget.MAX_OUTPUT)
        if self.available is not None and self.clock()-self.checked_at<30 and self.available-since>=required:
            return
        for attempt in range(2):
            try:
                available=self.balance();break
            except ValueError:
                if attempt:
                    raise DecisionError("余额核验未完成，暂停，不发起付费请求") from None
                time.sleep(.5)
        if available<required:
            raise DecisionError("账户保留余额触发，当前不能覆盖2元保留及一个请求的最大费用")
        self.available,self.checked_at=available,self.clock()
        self.offset=self.budget.summary()["calls"]


def restore_notes(folder,table,players):
    """Only each seat's own verified, committed notes; no oracle labels."""
    committed={d["action"]["id"] for d in table.decisions}
    for path in sorted(Path(folder).glob("hand-*/decisions.jsonl"),key=lambda p:p.stat().st_mtime):
        for line in path.open(encoding="utf-8"):
            row=json.loads(line);note=row.get("decision_validation",{}).get("decision_note")
            if note and note.get("version")==VERSION and row["choice"]["action_id"] in committed:
                obs=row["observation"];p=getattr(players[obs["seat"]],"player",None)
                if p is not None:
                    p.notebooks[(table.game_id,obs["seat"])]= {"events":obs["events"],"note":memory_note(note,obs)}
    # Restore only each rejecting seat's own error, scoped to the same frozen
    # observation. Never share other seats' response proposals.
    from src.simulation.observation import observe
    for path in sorted(Path(folder).glob("hand-*/rejected-seat-*.json"),key=lambda p:p.stat().st_mtime):
        r=json.loads(path.read_text());seat=r["observation"]["seat"]
        p=getattr(players[seat],"player",None)
        if (p is not None and isinstance(r.get("answer"),dict) and r["answer"].get("action_id")
                and r["observation"]["observation_id"]==observe(table,seat)["observation_id"]):
            p.repair_feedback={"observation_id":r["observation"]["observation_id"],"error":r["error"],
                               "action_id":(r.get("answer") or {}).get("action_id")}


def run_batch(*,hands,seed,root,budget,make_players,balance=cny_balance,max_recoveries=0,resume=False):
    root=Path(root);current_balance=balance();reports=[];stop=None
    if resume:
        manifest=json.loads((root/"manifest.json").read_text())
        if manifest["hands_requested"]!=hands or manifest["seed"]!=seed or Path(manifest["budget_ledger"])!=budget.path.resolve():
            raise ValueError("续批次的局数、种子或共享账本不一致")
        snapshots=list(root.glob("summary*.json"))+list(root.glob("progress-*.json"))
        previous=json.loads(max(snapshots,key=lambda p:p.stat().st_mtime).read_text())
        reports=previous["hands"];before=Decimal(manifest["balance_before_cny"])
        private_json(root/f"resume-{uuid4().hex[:8]}.json",{"balance_cny":str(current_balance),"budget":budget.summary(),
            "change":"explicit resume; current protocol recorded, no rules/strategy override",
            "max_recoveries_per_invocation":max_recoveries,
            "llm_sha256":hashlib.sha256((Path(__file__).resolve().parents[1]/"src/players/llm.py").read_bytes()).hexdigest(),
            "decision_guard_sha256":hashlib.sha256((Path(__file__).resolve().parents[1]/"src/players/decision_guard.py").read_bytes()).hexdigest()})
    else:
        root.mkdir(parents=True,exist_ok=False);before=current_balance
        private_json(root/"manifest.json",{"hands_requested":hands,"seed":seed,"paid":True,
        "budget_ledger":str(budget.path.resolve()),"budget_before":budget.summary(),"balance_before_cny":str(before),
        "policy":"four isolated LLMs; frozen rules and prompts; no code fallback; bounded explicit rejection recovery",
        "max_recoveries_per_invocation":max_recoveries,"same_observation_recovery_limit":3,
        "notebooks":"same seat instances retained across recoveries within each hand"})
    start=sum(r["status"]=="completed" for r in reports)
    pending=reports.pop() if reports and reports[-1]["status"]!="completed" else None
    for index in range(start,hands):
        players=make_players();folder=root/f"game-{index+1:02d}"
        recover_files=resume and folder.exists() and bool(list(folder.glob("hand-*/referee-private.json")))
        folder.mkdir(exist_ok=bool(pending) or recover_files)
        attempts=[];failures={};last_print=[0.0]
        if pending or recover_files:
            from src.simulation.replay import replay
            paths=list(folder.glob("hand-*/referee-private.json"))
            table=replay(json.loads(max(paths,key=lambda p:p.stat().st_mtime).read_text()))
            attempts=pending["attempts"] if pending else [json.loads(p.read_text()) for p in sorted(folder.glob("hand-*/report.json"))]
            restore_notes(folder,table,players);pending=None
        else:
            table=Table(seed+index,dealer=index%4)
        def progress(current,seat,choice):
            now=time.monotonic()
            if now-last_print[0]>=20:
                print(f"第{index+1}/{hands}局：动作{len(current.decisions)}，牌墙{len(current.wall)}，总请求{budget.summary()['calls']}",flush=True)
                last_print[0]=now
        attempt_offset = len(attempts)
        for attempt in range(attempt_offset,attempt_offset+max_recoveries+1):
            if attempt:
                # Short, bounded recovery after an already journalled failure.
                time.sleep(1)
            for p in players:
                p.last_rejection=None
            started=time.monotonic()
            report=run_hand(table,players,folder/f"hand-{attempt+1:03d}",progress=progress)
            report["elapsed_seconds"]=round(time.monotonic()-started,3)
            attempts.append(report)
            if report["status"]=="completed":
                break
            error=report["error"] or report["status"]
            print(f"第{index+1}局暂停：{error}；第{attempt+1}次尝试已保存",flush=True)
            if any(s in error for s in ("预算","调用上限","上下文超过","动作上限","账户保留","余额核验","HTTP 401","HTTP 402","HTTP 403","HTTP 404")):
                stop=error;break
            rejected=next((p for p in players if p.last_rejection),None)
            if rejected is None:
                stop=error;break
            r=rejected.last_rejection;identity=r["observation"]["observation_id"]
            failures[identity]=failures.get(identity,0)+1
            if failures[identity]>=3 or attempt==attempt_offset+max_recoveries:
                stop="当前局面连续失败或本局恢复次数触顶："+error;break
            if isinstance(r.get("answer"),dict) and r["answer"].get("action_id"):
                rejected.player.repair_feedback={"observation_id":identity,"error":error,
                                                "action_id":r["answer"]["action_id"]}
        item={"seed":table.seed,"game_id":table.game_id,"dealer":table.dealer,
              "status":"completed" if table.stage=="ended" else "paused","actions":len(table.decisions),
              "result":table.result,"attempts":attempts}
        if table.stage=="ended":
            item["audit"]=consolidate_completed_campaign(folder)
        reports.append(item)
        try:
            remaining=balance()
        except ValueError:
            remaining=None;stop="余额核验未完成，已保存，不发起下一局"
        private_json(root/f"progress-{index+1:02d}-{uuid4().hex[:6]}.json",{"hands":reports,"budget":budget.summary(),"balance_cny":str(remaining) if remaining is not None else None})
        print(f"第{index+1}局：{item['status']}，净收支{table.result['net'] if table.result else '未结束'}；余额{remaining}元",flush=True)
        if table.stage!="ended" or remaining is None:
            break
        # Account-wide balance guard catches concurrent external spending too;
        # it never resets or releases the shared ledger's unknown reservations.
        if remaining<2:
            stop="账户保留余额触发";break
    try:
        after=balance()
    except ValueError:
        after=None
    result={"hands_requested":hands,"completed":sum(r["status"]=="completed" for r in reports),
            "hands":reports,"budget":budget.summary(),"balance_before_cny":str(before),"balance_after_cny":str(after) if after is not None else None,
            "account_balance_delta_cny":str(before-after) if after is not None else None,"stop":stop,
            "scope":"真实LLM试验，无权重更新、无知识自动提升；余额变化可能包含充值和账户其他调用，不作为本批实际费用"}
    summary_path=root/(f"summary-resume-{uuid4().hex[:8]}.json" if resume else "summary.json")
    private_json(summary_path,result)
    print(f"批次报告：{summary_path}",flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm",action="store_true",required=True)
    parser.add_argument("--hands",type=int,default=10)
    parser.add_argument("--seed",type=int,default=2026102410)
    parser.add_argument("--budget-ledger",type=Path,required=True)
    parser.add_argument("--budget-cny",default="10")
    parser.add_argument("--max-calls",type=int,default=1500)
    parser.add_argument("--resume",type=Path)
    parser.add_argument("--max-recoveries",type=int,default=0,help="单次运行自动恢复次数；默认0，失败即停。另行续打须显式--resume")
    args=parser.parse_args()
    if not 1<=args.hands<=10 or not args.budget_ledger.is_file():
        parser.error("局数须1至10，必须指定已有共享账本")
    if not 0<=args.max_recoveries<=24:
        parser.error("每局累计恢复次数须0至24，不能无限重试")
    budget=Budget(args.budget_ledger,args.budget_cny,args.max_calls)
    if cny_balance()<2:
        parser.error("账户保留余额不足")
    guard_funds=AccountFloorGuard(budget)
    def make_players():
        players=[]
        for _ in range(4):
            p=LLMPlayer(provider="deepseek",max_calls=args.max_calls)
            p.client=MeteredClient(p.client.with_options(timeout=45,max_retries=0),budget,funds_guard=guard_funds)
            players.append(ExperimentPlayer(p))
        return players
    root=args.resume or Path("runs/live-batch")/f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    result=run_batch(hands=args.hands,seed=args.seed,root=root,budget=budget,make_players=make_players,resume=bool(args.resume),max_recoveries=args.max_recoveries)
    return 0 if result["completed"]==args.hands else 1


if __name__=="__main__":
    raise SystemExit(main())
