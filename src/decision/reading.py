"""Reading layer v1: discard-weighted world prior.

把对手弃牌河的信息变成世界权重：他狂弃某花色/字牌的世界里，
"他手里还囤着该花色"的世界被降权。这是启发式似然，不是精确贝叶斯；
校准依赖复盘双通道（P-C）。设计：docs/strategy.md。
"""
import math
from typing import Dict, List, Tuple

from ..core.tiles import GameState, Tile
from .belief import HiddenWorld

SUITS = ("万", "饼", "条")
WINDS = ("南", "西", "北")
ALPHA = 0.35
FLOOR = 0.01

# 边张读牌（分级证据）：弃 t 对"持有 t±1/t±2"的降权强度。
# 人证 vs 牌证：7899 弃9 完全正常（冗余解释多）→ 终张证据必须轻；
# 弃中张（如5）时"手里还有46"的解释少 → 证据重。centrality 从牌谱校准。
_ADJ_BASE = {1: 1.8, 2: 0.6}          # ±1 / ±2 邻张的基础强度（对数证据）
def _centrality(tile: Tile) -> float:
    if tile.suit not in SUITS:
        return 0.3                      # 字牌弃张：对字对持有证据轻微
    v = int(tile.value)
    return {1: 0.15, 2: 0.5, 3: 1.0, 4: 1.0, 5: 1.0,
            6: 1.0, 7: 1.0, 8: 0.5, 9: 0.15}[v]


def _adjacency_penalty(discarded: Tile, held: List[Tile]) -> float:
    """弃牌对邻张持有的对数证据惩罚（越大越降权）。"""
    if discarded.suit not in SUITS:
        return 0.0
    v = int(discarded.value)
    penalty = 0.0
    cent = _centrality(discarded)
    for t in held:
        if t.suit != discarded.suit:
            continue
        d = abs(int(t.value) - v)
        if d == 1:
            penalty += _ADJ_BASE[1] * cent / 13
        elif d == 2:
            penalty += _ADJ_BASE[2] * cent / 13
    return penalty


def _river_counts(state: GameState) -> Dict[str, Dict[str, int]]:
    """每家弃牌河的花色与字牌张数（可见事实）。"""
    out: Dict[str, Dict[str, int]] = {}
    for seat, river in state.discards.items():
        counts = {s: 0 for s in SUITS}
        for w in WINDS:
            counts[w] = 0
        for tile in river:
            if tile.suit in SUITS:
                counts[tile.suit] += 1
            elif tile.suit == "风" and tile.value in WINDS:
                counts[tile.value] += 1
        out[seat] = counts
    return out


def world_weight(world: HiddenWorld, state: GameState) -> float:
    """P(观察到这些弃牌 | 该世界) 的启发式代理，下限 FLOOR。"""
    if any(e.get("kind") == "discard" and e.get("seat") != "me" for e in state.public_events):
        from .dynamic_reading import history_weight
        return history_weight(world, state)
    rivers = _river_counts(state)
    log_w = 0.0
    for seat, hand in world.hands.items():
        river = rivers.get(seat)
        if not river:
            continue
        held: Dict[str, int] = {s: 0 for s in SUITS}
        for w in WINDS:
            held[w] = 0
        for tile in hand:
            if tile.suit in SUITS:
                held[tile.suit] += 1
            elif tile.suit == "风" and tile.value in WINDS:
                held[tile.value] += 1
        for suit in SUITS:
            if river[suit]:
                log_w -= ALPHA * river[suit] * held[suit] / 13
        for wind in WINDS:
            if river[wind]:
                log_w -= ALPHA * min(river[wind], 2) * held[wind] / 2
    # 边张粒度分级证据：逐张弃牌 × 邻张持有
    for seat, river in state.discards.items():
        hand = world.hands.get(seat)
        if not hand:
            continue
        for tile in river:
            log_w -= _adjacency_penalty(tile, hand)
    return max(math.exp(log_w), FLOOR)


def suit_reads(state: GameState,
               weighted_hands: List[Tuple[str, List[Tile]]]) -> Dict[str, Dict[str, str]]:
    """对手花色倾向读牌：弃得多的花色标记 ↓（持有低于均匀期望）。

    weighted_hands: [(seat, hand)] —— 调用方给的已（或未）加权世界手牌样本；
    v1 直接与均匀期望（13 张 × 全牌花色占比）比较。
    """
    uniform_expect = {}
    total = sum(9 for _ in SUITS) + 8  # 万饼条 27 + 南西北 8 ≈ 35 结构张/玩家池
    for suit in SUITS:
        uniform_expect[suit] = 13 * 9 / total
    rivers = _river_counts(state)
    reads: Dict[str, Dict[str, str]] = {}
    sample_by_seat: Dict[str, List[List[Tile]]] = {}
    for seat, hand in weighted_hands:
        sample_by_seat.setdefault(seat, []).append(hand)
    for seat, hands in sample_by_seat.items():
        entry: Dict[str, str] = {}
        for suit in SUITS:
            held = sum(1 for h in hands for t in h if t.suit == suit) / len(hands)
            dumped = rivers.get(seat, {}).get(suit, 0)
            if dumped >= 3 and held < uniform_expect[suit] * 0.75:
                entry[suit] = "↓"
            elif dumped == 0 and held > uniform_expect[suit] * 1.25:
                entry[suit] = "↑"
            else:
                entry[suit] = "≈"
        reads[seat] = entry
    return reads


def river_facts(state: GameState) -> Dict[str, Dict[str, int]]:
    """对手弃牌河的可见事实（供展示层直读）。"""
    return {seat: {k: v for k, v in counts.items() if v}
            for seat, counts in _river_counts(state).items()}
