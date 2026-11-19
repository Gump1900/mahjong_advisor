"""Budgeted four-bot experiment. Default is offline: no API or credentials read."""
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.players.base import DecisionError
from src.players.heuristic import HeuristicPlayer
from src.simulation.engine import Table
from src.simulation.experiment import Budget, MeteredClient, ExperimentPlayer, experiment_context, private_json, run_hand

_balance_client = None

def cny_balance():
    # Only the official origin ever receives the key. Never persist the response
    # except a single numeric CNY balance. No key, request headers or raw errors.
    import httpx
    global _balance_client
    from src.players.config import load_local_config
    key = load_local_config().get("deepseek", {}).get("api_key", "").strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise ValueError("没有配置DeepSeek密钥")
    try:
        if _balance_client is None:
            # Reuse TLS for the FREE balance endpoint; a single connect retry
            # never retries a model request or incurs generation fees.
            _balance_client=httpx.Client(timeout=15,follow_redirects=False,transport=httpx.HTTPTransport(retries=1))
        response = _balance_client.get("https://api.deepseek.com/user/balance",
                            headers={"Authorization": "Bearer "+key})
        response.raise_for_status()
        data = response.json()
        amount = next(Decimal(b["total_balance"]) for b in data["balance_infos"] if b["currency"] == "CNY")
        if not data.get("is_available") or not amount.is_finite() or amount < 0:
            raise ValueError("unavailable")
        return amount
    except Exception as exc:
        raise ValueError(f"余额检查失败（{type(exc).__name__}），未发起付费实验") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="太湖麻将四机器人实验；不是模型权重强化学习")
    parser.add_argument("--llm", action="store_true", help="显式允许付费；默认四个代码机器人离线验证")
    parser.add_argument("--candidate",choices=("heuristic","search"),default="heuristic",help="离线候选策略；search为试验性的自身多步搜索")
    parser.add_argument("--hands", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--budget-cny", default="3", help="整批共享上限，含失败请求保守预留；最高30元，须用户授权")
    parser.add_argument("--max-calls", type=int, default=240)
    parser.add_argument("--max-decisions", type=int, default=2000)
    parser.add_argument("--output-dir", type=Path, default=Path("runs/self-play"))
    parser.add_argument("--evaluate", action="store_true", help="每个种子轮换候选座位，与三个固定代码基线对照；小样本不证明棋力")
    parser.add_argument("--resume", type=Path, help="续跑已暂停实验，复用同一预算账本，最多续这一局")
    parser.add_argument("--budget-ledger", type=Path, help="新对局复用已有总预算账本，旧费用不清零")
    args = parser.parse_args(argv)
    if args.hands < 1 or args.max_calls < 1 or args.max_decisions < 1:
        parser.error("局数、调用上限、动作上限须大于0")
    if args.llm and args.candidate != "heuristic":
        parser.error("--llm与离线--candidate search不可同时使用")
    # One process owns a campaign. Restart with a NEW dir does not authorize
    # another spend: operator must account for earlier campaign reports.
    campaign = args.resume or args.output_dir/f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    if not args.resume:
        campaign.mkdir(parents=True, exist_ok=False)
    saved_ledger = None
    if args.resume and (campaign/"manifest.json").is_file():
        saved_ledger = json.loads((campaign/"manifest.json").read_text()).get("budget_ledger")
    budget_path = args.budget_ledger or (Path(saved_ledger) if saved_ledger else campaign/"budget.json")
    if (args.budget_ledger or saved_ledger) and not budget_path.is_file():
        parser.error("共享预算账本必须已存在，不能借此新建或清零预算")
    budget = Budget(budget_path, args.budget_cny, args.max_calls)
    before = None
    try:
        restored, previous = None, None
        if args.resume:
            if not args.llm or args.hands != 1 or args.evaluate:
                raise ValueError("续跑仅允许--llm --hands 1，不允许--evaluate")
            from src.simulation.replay import replay
            previous = json.loads((campaign/"summary.json").read_text())
            originals = sorted(campaign.glob("hand-*/referee-private.json"), key=lambda p: p.stat().st_mtime)
            if not originals or previous["hands"][-1]["stage"] == "ended":
                raise ValueError("实验没有可续的暂停局")
            restored = replay(json.loads(originals[-1].read_text()))
            if restored.stage == "ended":
                raise ValueError("最近一次续局已经结束，无需继续调用")
        if args.llm:
            before = cny_balance()
            if before < Decimal(args.budget_cny)+Decimal("2"):
                raise ValueError("余额不足以覆盖本批预算及2元保留余额；请降低本批预算")
            print(f"余额检查通过：{before}元；本批上限{args.budget_cny}元，未知用量按整请求预留，不自动重试。", flush=True)
        from src.players.knowledge import export_knowledge
        knowledge = export_knowledge()
        private_json(campaign/("resume-"+uuid4().hex[:8]+".json" if args.resume else "manifest.json"), {
            "purpose": "collection-and-evaluation-not-weight-training", "paid": args.llm,
            "candidate": "deepseek-flash" if args.llm else args.candidate, "hands_requested": args.hands,
            "seed_start": args.seed, "rotation": args.evaluate, "balance_before_cny": str(before) if before is not None else None,
            "budget_ledger": str(budget_path.resolve()),
            "knowledge_sha256": hashlib.sha256(knowledge.read_bytes()).hexdigest(),
            "privacy": "私有实验数据；全知牌谱与各座位决策分离；不自动修改军师知识或权重",
            "experiment_convention": "代码策略合法胡牌立即胡；LLM自主决定所有非强制动作；普通摸前端补牌后端；每局独立不模拟连庄"})
        reports, totals = [], [0]*4
        stop = False
        for index in range(args.hands):
            for candidate_seat in (range(4) if args.evaluate else (None,)):
                players = []
                for seat in range(4):
                    if args.llm and (candidate_seat is None or seat == candidate_seat):
                        from src.players.llm import LLMPlayer
                        player = LLMPlayer(provider="deepseek", max_calls=args.max_calls,
                                           strategy_context=experiment_context)
                        player.client = MeteredClient(player.client.with_options(timeout=45.0, max_retries=0), budget)
                        player = ExperimentPlayer(player)
                    elif args.candidate == "search" and (candidate_seat is None or seat == candidate_seat):
                        from src.players.search_player import SearchPlayer
                        player = SearchPlayer()
                    else:
                        player = HeuristicPlayer()
                    players.append(player)
                # For each seed rotation, identical wall/dealer; only policy seat
                # changes. Dealer changes across seeds, not within a rotation.
                table = restored or Table(args.seed+index, dealer=index % 4)
                table.metadata["experiment"] = {"campaign": campaign.name, "candidate_seat": candidate_seat}
                started = time.monotonic()
                last_print = [0.0]
                def progress(current, seat, choice):
                    now = time.monotonic()
                    if now-last_print[0] >= 15:
                        print(f"第{len(reports)+1}局：动作{len(current.decisions)}，牌墙{len(current.wall)}，累计API {budget.summary()['calls']}次", flush=True)
                        last_print[0] = now
                hand_name = f"hand-{len(reports)+1:03d}"+("-resume-"+uuid4().hex[:8] if args.resume else "")
                report = run_hand(table, players, campaign/hand_name,
                                  max_decisions=args.max_decisions, progress=progress)
                report.update(seed=table.seed, dealer=table.dealer, candidate_seat=candidate_seat,
                              elapsed_seconds=round(time.monotonic()-started, 2))
                reports.append(report)
                if table.result:
                    totals = [a+b for a,b in zip(totals, table.result["net"])]
                print(f"第{len(reports)}局：{report['status']}；净收支{table.result['net'] if table.result else '未结束'}；{budget.summary()}", flush=True)
                if report["status"] != "completed":
                    stop = True
                    break
            if stop:
                break
        balance_after = None
        if args.llm:
            try:
                balance_after = cny_balance()
            except ValueError:
                pass
        summary = {"weights_updated": False, "knowledge_promoted": False, "budget": budget.summary(),
                   "balance_after_cny": str(balance_after) if balance_after is not None else None,
                   "account_balance_delta_cny": str(before-balance_after) if before is not None and balance_after is not None else None,
                   "balance_note": "账户余额变化可能包含同时运行的牌桌等其他调用，不单独归因本实验",
                   "hands": reports, "seat_net_totals": totals,
                   "candidate_net": sum(r["result"]["net"][r["candidate_seat"]] for r in reports
                                        if r["result"] and r["candidate_seat"] is not None),
                   "conclusion": "试跑／数据收集；小样本、同模型互打或赢弱基线均不证明老师傅水平"}
        if args.evaluate:
            groups = {}
            for report in reports:
                if report["result"]:
                    groups.setdefault(report["seed"],[]).append(report["result"]["net"][report["candidate_seat"]])
            seed_means = [sum(values)/4 for values in groups.values() if len(values) == 4]
            summary["evaluation"] = {"complete_wall_families":len(seed_means),
                "mean_candidate_net_per_game":sum(seed_means)/len(seed_means) if seed_means else None,
                "seed_family_means":seed_means,
                "scope":"同墙轮四席为一个相关组，不把四场当四个独立样本；小样本不证明提升"}
        summary_name = "summary-resume-"+uuid4().hex[:8]+".json" if args.resume else "summary.json"
        summary["continued_from"] = "summary.json" if args.resume else None
        private_json(campaign/summary_name, summary)
        print(f"实验报告：{campaign/summary_name}", flush=True)
        return 0 if not stop else 1
    except (ValueError, DecisionError, KeyboardInterrupt) as exc:
        print(f"已停止：{str(exc) if isinstance(exc, (ValueError, DecisionError)) else 'KeyboardInterrupt'}；实验目录：{campaign}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
