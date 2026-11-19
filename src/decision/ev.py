"""Sampling EV layer: prior deal-in risk and payments over sampled worlds.

All probabilities here are PRIOR numbers under the joint-uniform deal
(belief.sample_world) plus observable rule gates (接炮资格 / 吃三口互锁).
Receipts must label them `先验采样N=…`. 对手过圈状态不可观测，不设门（设计
2026-11-15 §非目标），属于 p_hi 上界的一部分。
"""
import random
from dataclasses import dataclass, field
from typing import Dict, List, Set

from ..core.hand_analyzer import get_waiting_tiles, can_chi
from ..core.round_rules import (
    can_win_on_discard,
    locked_pairs,
    settle_round,
)
from ..core.scoring import known_hua, score_hand
from ..core.tiles import GameState, Tile
from .belief import HiddenWorld, sample_world
from .reading import world_weight
from .call_pressure import advances_on_claim

OPPONENTS = ("left", "opposite", "right")


@dataclass
class DealRisk:
    """Deal-in risk for one candidate discard, prior basis.

    p_point: worlds where at least one eligible, unlocked opponent rons.
    p_lo:    only worlds where the ronning seat's qualification is
             observable-confirmed (visible flowers / wind triplet / kong).
    p_hi:    structural waits only (no eligibility gate) — bound that also
             covers unobservable 过圈/hidden-qualification cases.
    v_deal:  mean payment I make across ron worlds (positive = my loss).
    """
    p_point: float
    p_lo: float
    p_hi: float
    v_deal: float
    labels: List[str] = field(default_factory=list)
    p_feed_chi: float = 0.0  # 下家有合法吃搭子的采样比例，不等于实际吃或成牌概率
    p_next_progress: float = 0.0  # 下家吃碰后可严格降低向听的加权样本比例
    p_call_progress: float = 0.0  # 任一家吃碰后可严格降低向听的加权样本比例


def _locked_seats(state: GameState) -> Set[str]:
    pairs = locked_pairs(state)
    if not pairs:
        return set()
    return set().union(*pairs)


def _qualification_confirmed(state: GameState, seat: str, world: HiddenWorld) -> bool:
    """Is this seat's ron qualification provable from observable info alone?"""
    if state.opponent_unknown_kongs.get(seat, 0):
        return True  # 已声明的暗杠至少有资格花，不需要猜牌种。
    visible_hua = known_hua(
        melds=state.melds.get(seat, []),
        flowers=state.opponent_flowers.get(seat, []),
        konged_flowers=state.opponent_konged_flowers.get(seat, []),
    )
    if visible_hua.get("total", 0) > 0:
        return True
    # 花观测完整且可见部分无资格 → 采样世界也只会给它这些花（belief 保证）
    return False


def evaluate_world(world: HiddenWorld, state: GameState,
                   candidates: List[Tile]) -> Dict[str, Dict[Tile, object]]:
    """One sampled world -> per-candidate ron sets and my payments.

    Pure function over (world, state); tests may pass hand-crafted worlds.
    """
    locked = _locked_seats(state)
    ronners: Dict[Tile, Set[str]] = {c: set() for c in candidates}
    structural: Dict[Tile, Set[str]] = {c: set() for c in candidates}
    confirmed: Dict[Tile, Set[str]] = {c: set() for c in candidates}

    for seat in OPPONENTS:
        if seat in locked:                      # 互锁者不能接任何人的炮
            continue
        hand = world.hands.get(seat, [])
        melds = world.melds.get(seat, state.melds.get(seat, []))
        konged = state.opponent_konged_flowers.get(seat, [])
        groups = state.opponent_flower_kong_groups.get(seat) or None
        flowers = world.flowers.get(seat, [])
        if state.opponent_hand_counts and flowers:
            continue  # 留花占手牌位；本次弃牌不能直接接炮。
        if len(hand) != 13 - 3 * len(melds):
            continue
        waits = get_waiting_tiles(hand, len(melds))
        seat_confirmed = _qualification_confirmed(state, seat, world)
        complete = bool(state.opponent_flowers_complete.get(seat, False))
        for cand in candidates:
            if cand not in waits:
                continue
            eligible = can_win_on_discard(hand, cand, melds, flowers, konged,
                                          flower_kong_groups=groups)
            # 花观测完整 => 资格已定：无资格的结构等待不进上界（hi 收敛到 point）
            if eligible or not complete:
                structural[cand].add(seat)
            if eligible:
                ronners[cand].add(seat)
                if seat_confirmed:
                    confirmed[cand].add(seat)

    hua_sum: Dict[Tile, int] = {}
    my_payment: Dict[Tile, int] = {}
    for cand in candidates:
        if ronners[cand]:
            amounts = {}
            for seat in sorted(ronners[cand]):
                hand = world.hands[seat] + [cand]
                amounts[seat] = score_hand(
                    hand, world.melds.get(seat, state.melds.get(seat, [])),
                    world.flowers.get(seat, []),
                    state.opponent_konged_flowers.get(seat, []), "dianpao",
                    flower_kong_groups=state.opponent_flower_kong_groups.get(seat) or None,
                ).hua
            hua_sum[cand] = sum(amounts.values())
            my_payment[cand] = settle_round("dianpao", amounts, source="me").net["me"]
        else:
            hua_sum[cand] = 0
            my_payment[cand] = 0

    return {"ronners": ronners, "structural": structural,
            "confirmed": confirmed, "hua_sum": hua_sum,
            "my_payment": my_payment}


def deal_risks(state: GameState, candidates: List[Tile], *,
               samples: int = 128, seed: int = 0) -> Dict[Tile, DealRisk]:
    """Aggregate evaluate_world over `samples` uniform-prior worlds."""
    if samples <= 0:
        raise ValueError("采样次数必须是正整数")
    rng = random.Random(seed)
    n = len(candidates)
    point = [0.0] * n
    low = [0.0] * n
    high = [0.0] * n
    loss_sum = [0.0] * n
    loss_weight = [0.0] * n
    feed = [0.0] * n
    next_progress = [0.0] * n
    call_progress = [0.0] * n
    total_weight = 0.0
    for _ in range(samples):
        world = sample_world(state, rng)
        weight = world_weight(world, state)      # 读牌：弃牌加权先验
        total_weight += weight
        result = evaluate_world(world, state, candidates)
        next_hand = world.hands.get("right", [])
        can_next_call = len(world.melds.get("right", state.melds.get("right", []))) < 4 and len(next_hand) > 2
        for i, cand in enumerate(candidates):
            if can_next_call and can_chi(next_hand, cand):
                feed[i] += weight
            if not result["ronners"][cand]:
                accelerating = {seat for seat in OPPONENTS
                                if advances_on_claim(world.hands.get(seat, []),
                                                     len(world.melds.get(seat, state.melds.get(seat, []))), cand,
                                                     allow_chi=seat == "right")}
                if "right" in accelerating:
                    next_progress[i] += weight
                if accelerating:
                    call_progress[i] += weight
            if result["ronners"][cand]:
                point[i] += weight
                loss_weight[i] += weight
                loss_sum[i] += weight * -result["my_payment"][cand]
            if result["confirmed"][cand]:
                low[i] += weight
            if result["structural"][cand]:
                high[i] += weight
    out: Dict[Tile, DealRisk] = {}
    for i, cand in enumerate(candidates):
        label = [f"先验采样N={samples}·弃牌加权", "读牌:有序事件软推断" if state.public_events else "读牌:花色倾向v1",
                 "吃碰推进:同手牌反事实向听对比，非实际叫牌概率",
                 "未计入:对手过圈",
                 "上界:p_hi(结构)", "下界:p_lo(资格确证)"]
        out[cand] = DealRisk(
            p_next_progress=next_progress[i] / total_weight,
            p_call_progress=call_progress[i] / total_weight,
            p_feed_chi=feed[i] / total_weight,
            p_point=point[i] / total_weight,
            p_lo=low[i] / total_weight,
            p_hi=high[i] / total_weight,
            v_deal=(loss_sum[i] / loss_weight[i]) if loss_weight[i] else 0.0,
            labels=label,
        )
    return out


# --- V_win / EV 排序 ----------------------------------------------------------------

from collections import Counter  # noqa: E402
from ..core.hand_analyzer import calculate_shanten  # noqa: E402
from ..core.math_core import (  # noqa: E402
    expected_neff_1ply, n_eff, opp_structural_total, wall_adjusted,
)
from ..core.probability import count_remaining_tiles  # noqa: E402
from ..core.tiles import tile_sort_key  # noqa: E402


@dataclass
class CandidateEV:
    """One discard candidate with its per-turn EV decomposition.

    ev = p_win_next·v_win − p_point·v_deal（本巡口径；接炮侧不进决策）。
    exp_neff_1ply 为 13 张站姿手的静态有效牌数（未见口径）——同向听内作
    并列打破用；跨向听比较见设计文档的跨尺度限制。
    """
    tile: Tile
    ev: float
    stand_shanten: int = 0
    p_win_next: float = 0.0
    v_win: float = 0.0
    p_point: float = 0.0
    p_lo: float = 0.0
    p_hi: float = 0.0
    v_deal: float = 0.0
    exp_neff_1ply: float = 0.0
    exp_neff_exact: bool = True
    labels: List[str] = field(default_factory=list)
    p_feed_chi: float = 0.0  # 下家有合法吃搭子的采样比例，不等于实际吃或成牌概率
    p_next_progress: float = 0.0  # 下家吃碰后可严格降低向听的加权样本比例
    p_call_progress: float = 0.0  # 任一家吃碰后可严格降低向听的加权样本比例


def sort_candidates(candidates: List[CandidateEV], *,
                    tol: float = 0.0) -> List[CandidateEV]:
    """argmax EV；并列（|ΔEV| ≤ tol 视为并列）按有效牌数降序 → P_deal 升序 → 牌名序。

    tol 为采样噪声分辨率：点炮概率的采样误差 ~1/√N，乘以典型赔付后的 EV
    抖动小于 tol 时不作为信号，让结构分先决。真实 EV 差距（如听牌的进攻项）
    远大于 tol，仍然 EV 说了算。
    """
    def bucket(cand: CandidateEV) -> int:
        return round(cand.ev / tol) if tol > 0 else cand.ev

    return sorted(candidates, key=lambda c: (
        -bucket(c), c.stand_shanten, -c.exp_neff_1ply, round(c.p_next_progress, 1), round(c.p_call_progress, 1), round(c.p_feed_chi, 1), c.p_point,
        tile_sort_key(c.tile)))


def _zimo_payment(state: GameState, hua: int) -> int:
    """我自摸 X 花的净收益（互锁直接对家付 3 倍由 settle_round 保证）。"""
    return settle_round("zimo", {"me": hua},
                        locked_pairs=locked_pairs(state)).net["me"]


def _best_stand_n_eff(hand14: List[Tile], fuuro: int,
                      unseen: Dict[Tile, int]) -> float:
    """14张里弃掉最优一张后的最大 n_eff（下一摸弹性的内层最大化）。"""
    best = 0.0
    for drop in set(hand14):
        rest = list(hand14)
        rest.remove(drop)
        value = n_eff(rest, fuuro, unseen)
        if value > best:
            best = value
    return best


def _pair_discipline(stand: List[Tile], fuuro: int) -> float:
    """G1 对子纪律（题库挖掘 2026-11-17）：对子价值边际递减 + 碰期权。
    前两对：正贡献（将位 + 三家供牌的碰机会，n_eff 只算自摸看不见；
    CC-07 实测静态差3张，需 +3.5/对 才能正确翻转"前期保对"）；
    块数超标（六搭）时：过剩对与过剩块惩罚（两对半/五搭纪律）。
    挂在静态结构分上，只在与目标块数的关系里起作用，不碰向听。"""
    from ..core.hand_analyzer import best_decomposition
    sets, taatsu, toitsu = best_decomposition(stand, fuuro)
    pairs = toitsu
    blocks = sets + taatsu + toitsu + fuuro
    base = 3.5 * min(pairs, 2)                 # 碰期权：第1-2对（封顶护四对型）
    target = 5 - fuuro
    if blocks > target:
        base -= 0.6 * max(0, pairs - 2) + 1.2 * (blocks - target)
    return base


def _convention_key(tile: Tile, hand: List[Tile]) -> int:
    """近似平局时的教学决胜序（用户 2026-11-15 实局指正）：
    孤张字牌先走(0) > 幡九孤张(1) > 其余(2)。数牌有邻张、摸一张能成搭；
    字牌只能等同张成对，路径最少，平局时先弃。对子不算孤张（有 pair 价值，
    南西北刻还是接炮资格），不享此优先。"""
    if hand.count(tile) == 1:
        if tile.suit == "风":
            return 0
        if tile.suit in ("万", "饼", "条") and int(tile.value) in (1, 9):
            return 1
    return 2


def _one_ply_flexibility(stand13: List[Tile], fuuro: int,
                         wall: Dict[Tile, int], n_wall: float,
                         unseen: Dict[Tile, int]) -> float:
    """𝔼[n_eff(下一摸后的最优站姿)] —— 区分"今天同分、明天不同命"的候选。"""
    if n_wall <= 0:
        return 0.0
    total = 0.0
    for y, w in wall.items():
        if w > 0:
            total += w * _best_stand_n_eff(stand13 + [y], fuuro, unseen)
    return total / n_wall


def rank_candidates(state: GameState, *, samples: int = 128,
                    seed: int = 0, refine_ties: bool = True) -> List[CandidateEV]:
    """决策规则：本巡 EV 排序（设计 §公式 7）。"""
    hand = [t for t in state.my_hand if not t.is_flower]
    fuuro = len(state.my_melds)
    base = 13 - 3 * fuuro
    consult_mode = len(hand) == base
    if len(hand) == base + 1:
        def standing(x):
            rest = list(hand)
            rest.remove(x)          # 只移除一张：对子候选不能整组剥掉
            return rest
    elif consult_mode:
        # 摸牌前咨询：结构按当前 13 张评估（对所有候选一致，供提前参考）
        standing = lambda x: list(hand)
    else:
        raise ValueError(f"手牌张数应为 {base} 或 {base + 1}，实际 {len(hand)}")

    candidates = sorted(Counter(hand), key=tile_sort_key)
    unseen = count_remaining_tiles(state)
    wall = wall_adjusted(unseen, opp_structural_total(state))
    n_wall = sum(wall.values())
    risks = deal_risks(state, candidates, samples=samples, seed=seed)

    out: List[CandidateEV] = []
    for x in candidates:
        stand = standing(x)
        risk = risks[x]
        sh = calculate_shanten(stand, fuuro) if len(stand) == base else 1
        labels = list(risk.labels)
        exact = True
        if consult_mode:
            labels.append("咨询:摸牌前")
            # 咨询态结构分：P(下一摸使向听数下降)。原始 n_eff 跨向听不可比
            # （退向听反而"可改善牌种"更多），必须以当前向听为基准的概率化指标。
            cur_shanten = calculate_shanten(hand, fuuro)
            rest12 = list(hand)
            rest12.remove(x)          # 只移除一张
            improved = 0.0
            for y, w in wall.items():
                if w > 0 and calculate_shanten(rest12 + [y], fuuro) < cur_shanten:
                    improved += w
            exp_neff = improved / n_wall if n_wall > 0 else 0.0
            labels.append("咨询:下摸改善概率")
        else:
            exp_neff = (float(n_eff(stand, fuuro, unseen)) + _pair_discipline(stand, fuuro)
                        if len(stand) == base else 0.0)
        if sh == 0:
            waits = get_waiting_tiles(stand, fuuro)
            weights = [wall.get(w, 0) for w in waits]
            p_win = sum(weights) / n_wall if n_wall > 0 else 0.0
            if p_win > 0:
                total = 0.0
                for w, weight in zip(waits, weights):
                    hua = score_hand(
                        stand + [w], state.my_melds, state.flowers_in_hand,
                        state.konged_flowers, "zimo",
                        flower_kong_groups=state.flower_kong_groups or None,
                    ).hua
                    total += weight * _zimo_payment(state, hua)
                # total = Σ_w (n_wall_w · pay(w))；条件均值 = total / Σ_w n_wall_w
                weights_sum = sum(weights)
                v_win = total / weights_sum if weights_sum else 0.0
                labels.append("闭式:P_win(墙内)")
            else:
                v_win = 0.0
                labels.append("近似:听牌但墙内无活张")
        else:
            p_win = 0.0
            known = known_hua(melds=state.my_melds,
                              flowers=state.flowers_in_hand,
                              konged_flowers=state.konged_flowers)
            v_win = float(_zimo_payment(state, 6 + known.get("total", 0)))
            labels.append("近似:V_win保守代理(6+已知花分)")
        ev = p_win * v_win - risk.p_point * risk.v_deal
        out.append(CandidateEV(
            tile=x, ev=ev, p_feed_chi=risk.p_feed_chi,
            p_next_progress=risk.p_next_progress, p_call_progress=risk.p_call_progress,
            stand_shanten=(sh if not consult_mode else 0),
            p_win_next=p_win, v_win=v_win,
            p_point=risk.p_point, p_lo=risk.p_lo, p_hi=risk.p_hi,
            v_deal=risk.v_deal,
            exp_neff_1ply=float(exp_neff), exp_neff_exact=exact, labels=labels))
    ordered = sort_candidates(out, tol=10.0 / (samples ** 0.5))
    if not consult_mode and refine_ties:
        # 顶层静态同分组（同向听+同活张）用 1-ply 弹性决胜（视频 E[N_eff] 公式）
        head = ordered[0]
        tie = [c for c in ordered
               if c.stand_shanten == head.stand_shanten
               and abs(c.exp_neff_1ply - head.exp_neff_1ply) < 0.5
               and round(c.ev / (10.0 / samples ** 0.5))
                   == round(head.ev / (10.0 / samples ** 0.5))]
        if len(tie) > 1:
            for cand in tie:
                rest = list(hand)
                rest.remove(cand.tile)
                cand.exp_neff_1ply = _one_ply_flexibility(
                    rest, fuuro, wall, n_wall, unseen)
                if "1-ply" not in " ".join(cand.labels):
                    cand.labels.append("决胜:1-ply弹性")
            tie.sort(key=lambda c: (-c.exp_neff_1ply, c.p_point,
                                    tile_sort_key(c.tile)))
            # 教学决胜：后劲差<2 视为平局，平局内孤字先走（用户实局指正，
            # 6饼/南 74.0/73.7 的微差不抵邻张期权，按拆搭教学先打孤字）
            best_flex = tie[0].exp_neff_1ply
            near = [c for c in tie if best_flex - c.exp_neff_1ply < 2.0]
            if len(near) > 1:
                flex_first = near[0]
                near.sort(key=lambda c: (round(c.p_next_progress, 1), round(c.p_call_progress, 1), round(c.p_feed_chi, 1), _convention_key(c.tile, hand),
                                         -c.exp_neff_1ply, c.p_point,
                                         tile_sort_key(c.tile)))
                if near[0] is not flex_first:
                    if (round(near[0].p_next_progress, 1), round(near[0].p_call_progress, 1)) < (round(flex_first.p_next_progress, 1), round(flex_first.p_call_progress, 1)):
                        near[0].labels.append("决胜:少送吃碰")
                    if round(near[0].p_feed_chi, 1) < round(flex_first.p_feed_chi, 1):
                        near[0].labels.append("决胜:少喂下家")
                    if _convention_key(near[0].tile, hand) < _convention_key(flex_first.tile, hand):
                        near[0].labels.append("教学:孤字先走")
                rest = [c for c in tie if c not in near]
                rest.sort(key=lambda c: (-c.exp_neff_1ply, c.p_point,
                                         tile_sort_key(c.tile)))
                tie = near + rest
            ordered = tie + [c for c in ordered if c not in tie]
    return ordered


def opponent_panel(state: GameState, *, samples: int = 128,
                   seed: int = 0) -> Dict[str, dict]:
    """Per-opponent prior panel: tenpai frequency and top waiting tiles."""
    rng = random.Random(seed)
    tenpai = {seat: 0.0 for seat in OPPONENTS}
    waits: Dict[str, Counter] = {seat: Counter() for seat in OPPONENTS}
    total_weight = 0.0
    for _ in range(samples):
        world = sample_world(state, rng)
        weight = world_weight(world, state)
        total_weight += weight
        for seat in OPPONENTS:
            hand = world.hands.get(seat, [])
            melds = len(world.melds.get(seat, state.melds.get(seat, [])))
            if (state.opponent_hand_counts and world.flowers.get(seat)) or len(hand) != 13 - 3 * melds:
                continue
            if calculate_shanten(hand, melds) == 0:
                tenpai[seat] += weight
                for w in get_waiting_tiles(hand, melds):
                    waits[seat][str(w)] += weight
    wait_top = {seat: [(tile, round(count, 1)) for tile, count
                       in waits[seat].most_common(5)] for seat in OPPONENTS}
    return {seat: {
        "tenpai_prior": tenpai[seat] / total_weight,
        "wait_top": wait_top[seat],
        "labels": [f"先验采样N={samples}·弃牌加权"],
    } for seat in OPPONENTS}
