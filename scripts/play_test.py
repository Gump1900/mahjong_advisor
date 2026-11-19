"""Desktop test table: python scripts/play_test.py --seed 42.

Saved replay files are private referee data. Never put them into LLM prompts.
"""
import argparse
import json
import hashlib
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.players.knowledge import load_knowledge
from src.players.base import DecisionError
from src.players.heuristic import HeuristicPlayer
from src.players.human import HumanPlayer
from src.players.render import tile_line
from src.simulation.engine import Table
from src.simulation.replay import replay, save
from src.simulation.runner import play


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地麻将四人测试桌（电脑终端）")
    parser.add_argument("--seed", type=int, default=42, help="洗牌种子")
    parser.add_argument("--dealer", type=int, choices=range(4), default=0)
    parser.add_argument("--human-seat", type=int, choices=range(4), default=0)
    parser.add_argument("--all-bots", action="store_true", help="四个机器人自动回归")
    parser.add_argument("--tiles", choices=("unicode", "text"), default="unicode", help="麻将牌面或纯文字显示")
    parser.add_argument("--bot", choices=("heuristic", "llm"), default="heuristic")
    parser.add_argument("--llm-provider", choices=("anthropic", "deepseek"), help="也可设置MAHJONG_BOT_PROVIDER")
    parser.add_argument("--fallback", choices=("pause", "heuristic"), default="pause")
    parser.add_argument("--llm-max-calls", type=int, default=100, help="每机器人含重试的API调用上限")
    parser.add_argument("--hands", type=int, default=1, help="独立测试局数，逐局轮庄，不代表正式连庄规则")
    parser.add_argument("--max-decisions", type=int, default=2000)
    parser.add_argument("--output-dir", type=Path, default=Path("runs/mahjong"))
    parser.add_argument("--replay", type=Path, help="校验重放牌谱，不调用机器人或API")
    parser.add_argument("--resume", type=Path, help="从保存牌谱重放到暂停点后继续")
    args = parser.parse_args(argv)
    if args.replay and args.resume:
        parser.error("--replay 与 --resume 不可同时使用")
    if args.hands < 1 or args.max_decisions < 1 or args.llm_max_calls < 1:
        parser.error("局数、动作上限和调用上限必须大于0")
    restored = None
    if args.replay or args.resume:
        with (args.replay or args.resume).open(encoding="utf-8") as stream:
            restored = replay(json.load(stream))
        print(f"重放校验通过：{len(restored.decisions)} 个动作，阶段 {restored.stage}")
        if args.replay:
            if restored.result:
                print(json.dumps(restored.result, ensure_ascii=False, indent=2))
            return 0
    if restored and args.hands != 1:
        parser.error("续局时只允许 --hands 1")
    players = []
    try:
        for seat in range(4):
            if not args.all_bots and seat == args.human_seat:
                player = HumanPlayer(tile_style=args.tiles)
            elif args.bot == "llm":
                from src.players.llm import FallbackPlayer, LLMPlayer
                player = LLMPlayer(max_calls=args.llm_max_calls, provider=args.llm_provider)
                if args.fallback == "heuristic":
                    player = FallbackPlayer(player, HeuristicPlayer())
            else:
                player = HeuristicPlayer()
            players.append(player)
    except (ValueError, ImportError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    print("普通摸牌取牌墙前端、补牌取后端，不留死墙：这是本测试桌的发牌约定。")
    print("全知牌谱仅供本地调试/局末验牌，不发送给玩家或LLM。")
    if args.tiles == "unicode" and not args.all_bots:
        print("牌面预览：🀇 🀈 🀉  🀙 🀚 🀛  🀐 🀑 🀒  🀁 🀂 🀃；若显示方框，用 --tiles text。")
    total = [0]*4
    for index in range(args.hands):
        table = restored or Table(args.seed+index, (args.dealer+index) % 4)
        run_info = {"start_decision_index": len(table.decisions)}
        run_info["players"] = [
            {"seat": seat, "controller": type(player).__name__,
             "provider": getattr(getattr(player, "primary", player), "provider", None),
             "model": getattr(getattr(player, "primary", player), "model", None)}
            for seat, player in enumerate(players)]
        run_info["knowledge_sha256"] = hashlib.sha256(
            load_knowledge().encode()).hexdigest()
        run_info["fallback"] = args.fallback
        run_info["tile_style"] = args.tiles
        table.metadata.setdefault("runs", []).append(run_info)
        print(f"\n第{index+1}局：seed={table.seed}，庄家=座位{table.dealer}")
        status = 0
        try:
            play(table, players, max_decisions=args.max_decisions)
        except (KeyboardInterrupt, EOFError):
            print("\n已暂停，将保存当前局面。")
            status = 130
        except DecisionError as exc:
            print(f"\n{exc}")
            status = 1
        finally:
            # Unique filenames also allow safe resaving a resumed game.
            from uuid import uuid4
            run_info["llm_calls_this_process"] = [
                getattr(getattr(p, "primary", p), "calls", 0) for p in players]
            path = args.output_dir / f"{table.game_id}-{uuid4().hex[:8]}.json"
            save(table, path)
            print(f"裁判完整牌谱（私有）：{path}")
        if table.result:
            print(json.dumps(table.result, ensure_ascii=False, indent=2))
            for seat, state in enumerate(table.seats):
                hidden = [tile_line(m.tiles, args.tiles) for m in state.melds if m.type == "an_gang"]
                print(f"局末验牌 座位{seat}：手牌 {tile_line(state.hand, args.tiles)}；暗杠 {hidden}")
            total = [a+b for a,b in zip(total, table.result["net"])]
        if status:
            return status
    print("测试累计净收支：", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
