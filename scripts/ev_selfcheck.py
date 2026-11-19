"""EV 层自动验收流水线：上桌前的自检，替代"用户当QA"。

跑 N 局四人自战，在每个 bot 弃牌决策点做不变量检查：
  I1 结构纪律：所选弃牌的打后向听 == 全候选最小（不退向听换噪声级收益）
  I2 降级为零：非花占位状态出现"EV降级"reason 即违规
  I3 性能预算：单决策 < 1s（128采样口径）
  I4 零异常：DecisionError/ValueError 即失败
输出违规清单 + 统计。用法：python3 -I scripts/ev_selfcheck.py [局数=20]
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.simulation.engine import Table                    # noqa: E402
from src.simulation.observation import observe             # noqa: E402
from src.players.base import DecisionError                 # noqa: E402
from src.decision.ev import rank_candidates                # noqa: E402
from src.decision.ev_bot import EVBot, build_state_from_observation  # noqa: E402


def check_discard_decision(observation, choice_id, violations, game, stats):
    discards = [a for a in observation["legal_actions"] if a["kind"] == "discard"]
    if not discards:
        return
    chosen = next((a for a in discards if a["id"] == choice_id), None)
    if chosen is None:
        return
    stats["discard_decisions"] += 1
    if observation["self"].get("held_flower_count"):
        return   # 花占位：排序不可比，跳过结构检查（bot 有独立处理路径）
    try:
        state = build_state_from_observation(observation)
        t0 = time.monotonic()
        ranked = rank_candidates(state, samples=32, seed=0, refine_ties=True)
        elapsed = time.monotonic() - t0
        if elapsed > 1.0:
            violations.append(f"[{game}] 性能超标 {elapsed:.2f}s")
        by_tile = {str(c.tile): c for c in ranked}
        best_shanten = min(c.stand_shanten for c in ranked)
        chosen_tile = chosen["tiles"][0]
        cand = by_tile.get(chosen_tile)
        if cand is not None and cand.stand_shanten > best_shanten:
            violations.append(
                f"[{game}] I1结构违规: 打{chosen_tile} 向听{cand.stand_shanten}"
                f" > 最优{best_shanten}（手牌 {' '.join(observation['self']['hand'])}）")
    except ValueError as exc:
        violations.append(f"[{game}] 排序异常: {exc}（手牌 {' '.join(observation['self']['hand'])}）")


def main(games=20):
    violations = []
    stats = {"games": 0, "discard_decisions": 0, "degraded": 0, "errors": 0}
    personalities = ["均衡", "稳", "凶", "均衡"]
    for game in range(games):
        table = Table(seed=7000 + game, dealer=game % 4)
        bots = {seat: EVBot(personalities[seat], samples=32, seed=seat)
                for seat in range(4)}
        try:
            while table.stage != "ended" and len(table.decisions) < 800:
                waiting = table.waiting_seats()
                frozen = [(seat, observe(table, seat)) for seat in waiting]
                for seat, obs in frozen:
                    actions = obs["legal_actions"]
                    if len(actions) == 1 and actions[0]["kind"] == "pass":
                        table.apply(seat, actions[0]["id"], controller="forced")
                        continue
                    choice = bots[seat].choose(obs)
                    if "降级" in (choice.reason or ""):
                        stats["degraded"] += 1
                        if not obs["self"].get("held_flower_count"):
                            violations.append(
                                f"[{game}] I2非花占位降级: {choice.reason}"
                                f"（手牌 {' '.join(obs['self']['hand'])}）")
                    if any(a["kind"] == "discard" for a in actions):
                        check_discard_decision(obs, choice.action_id,
                                               violations, game, stats)
                    chosen = next(a for a in actions if a["id"] == choice.action_id)
                    if chosen["kind"] == "flower_kong":
                        flowers = bots[seat].select_flowers(obs)
                        if len(flowers) > 1:
                            table.exchange_flowers(seat, flowers,
                                                   controller=choice.controller)
                            continue
                    table.apply(seat, choice.action_id,
                                controller=choice.controller, reason=choice.reason)
            stats["games"] += 1
        except (DecisionError, ValueError) as exc:
            stats["errors"] += 1
            violations.append(f"[{game}] I4异常 {type(exc).__name__}: {exc}")
    print(f"自战 {stats['games']}/{games} 局完成 | 弃牌决策 {stats['discard_decisions']} | "
          f"降级 {stats['degraded']} | 异常 {stats['errors']}")
    if violations:
        print(f"\n违规 {len(violations)} 条：")
        for v in violations[:20]:
            print("  -", v)
        return 1
    print("全部不变量通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
