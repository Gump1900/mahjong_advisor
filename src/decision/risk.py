"""Immediate discard losses under an explicit baseline hidden-world prior.

This is not a full-round EV evaluator. Sampling intervals quantify Monte Carlo
error only, not model error; unseen historical actions are not reconstructed.
"""
import math
import random
import time

from ..core.hand_analyzer import get_waiting_tiles
from ..core.round_rules import can_win_on_discard, settle_round
from ..core.scoring import score_hand
from .belief import MODEL, OPPONENTS, sample_world
from .models import DecisionContext


def _interval(hits, n):
    # Wilson 95% interval: zero sampled wins must not imply proven safety.
    z = 1.96
    p = hits / n
    den = 1 + z*z/n
    center = (p + z*z/(2*n)) / den
    width = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return [max(0.0, center-width), min(1.0, center+width)]


def evaluate_immediate_risk(context: DecisionContext, *, samples=256, seed=0,
                            time_budget=1.0) -> dict:
    if context.phase != "need_discard":
        raise ValueError("逐家舍牌评估仅在轮到我打牌时运行")
    if context.pending and context.pending["player"] != "me":
        raise ValueError("请先处理当前待响应的对手弃牌")
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 2048:
        raise ValueError("抽样次数必须在1到2048之间")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("随机种子必须是整数")
    if (isinstance(time_budget, bool) or not isinstance(time_budget, (int, float))
            or not math.isfinite(time_budget) or not 0 < time_budget <= 5):
        raise ValueError("计算预算必须大于0且不超过5秒")
    state = context.state
    if len(state.my_hand) != 14 - 3 * len(state.my_melds):
        raise ValueError("当前暗牌张数不符合打牌阶段")
    candidates = sorted(set(state.my_hand), key=str)
    stats = {t: {p: [0, 0] for p in OPPONENTS} for t in candidates}
    totals = {t: {"hits": 0, "multi_hits": 0, "loss": 0} for t in candidates}
    rng = random.Random(seed)
    start = time.monotonic()
    n = 0
    for _ in range(samples):
        if n and time.monotonic() - start >= time_budget:
            break
        world = sample_world(state, rng)
        wins = {t: {} for t in candidates}
        for player in OPPONENTS:
            hand, melds = world.hands[player], state.melds[player]
            waiting = set(get_waiting_tiles(hand, len(melds)))
            for tile in candidates:
                if tile not in waiting:
                    continue
                args = (hand, tile, melds, world.flowers[player],
                        state.opponent_konged_flowers[player],
                        state.opponent_flower_kong_groups[player])
                if not can_win_on_discard(*args):
                    continue
                score = score_hand(hand + [tile], melds, world.flowers[player],
                                   state.opponent_konged_flowers[player], "dianpao",
                                   flower_kong_groups=state.opponent_flower_kong_groups[player])
                wins[tile][player] = score.hua
                stats[tile][player][0] += 1
                stats[tile][player][1] += score.hua
        for tile, amounts in wins.items():
            if amounts:
                totals[tile]["hits"] += 1
                totals[tile]["multi_hits"] += int(len(amounts) > 1)
                totals[tile]["loss"] -= settle_round("dianpao", amounts, "me").net["me"]
        n += 1
    results = []
    for tile in candidates:
        per_opponent = {}
        for player, (hits, loss) in stats[tile].items():
            per_opponent[player] = {
                "ron_rate": hits/n, "ron_hits": hits,
                "sampling_interval_95": _interval(hits, n),
                "mean_payment_if_ron": loss/hits if hits else None,
                "expected_immediate_loss": loss/n,
                "flowers_complete": state.opponent_flowers_complete[player],
            }
        results.append({
            "tile": str(tile), "opponents": per_opponent,
            "any_ron_rate": totals[tile]["hits"]/n,
            "any_ron_interval_95": _interval(totals[tile]["hits"], n),
            "multi_ron_rate": totals[tile]["multi_hits"]/n,
            "expected_immediate_loss": totals[tile]["loss"]/n,
        })
    return {
        "game_id": context.game_id, "revision": context.revision,
        "model": MODEL, "calibrated": False, "scope": "immediate_discard_only",
        "samples": n, "requested_samples": samples, "seed": seed,
        "budget_exhausted": n < samples,
        "elapsed_ms": round((time.monotonic()-start)*1000, 1),
        "warnings": [
            "基于未见牌联合随机分配，未利用弃牌策略推断；不是校准后的实战概率。",
            "假定其他三家处于13减3倍明牌组数的暗牌状态；牌墙长度及历史摸花过程未知。",
            "花牌记录完整度仅针对当前观察；未记录花牌会按基础分配模型抽样。",
            "区间只反映抽样误差；零次放炮样本不证明安全；当前结果不是整局净收益。",
        ],
        "candidates": results,
    }
