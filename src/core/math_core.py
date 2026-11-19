"""Closed-form mahjong math (effective tiles, wall model, draw probabilities).

Pure functions only: no IO, no randomness. Every number produced here is
`闭式` (closed-form) or an explicitly labeled approximation.

Two counting bases, never mixed (see design 2026-11-15):
- unseen basis: copies not visible anywhere (wall + opponents' concealed tiles).
- wall basis: unseen minus the uniform-prior expected share held by opponents.
"""
import math
import time
from typing import Dict, List, Tuple

from .hand_analyzer import get_ukeire
from .tiles import GameState, Tile


def n_eff(hand: List[Tile], fuuro: int, unseen: Dict[Tile, int]) -> int:
    """Unseen-basis effective tile count (活张总数).

    Σ_x (4 − c(x)) · 𝟙[shanten(S∪{x}) < shanten(S)] — tiles that reduce
    shanten, weighted by unseen copies. Flowers never qualify (ukeire
    already excludes them).
    """
    expected_len = 13 - 3 * fuuro
    if len(hand) != expected_len:
        raise ValueError(f"手牌张数应为 {expected_len}，实际 {len(hand)}")
    return sum(unseen.get(u, 0) for u in get_ukeire(hand, fuuro))


def n_eff_kinds(hand: List[Tile], fuuro: int = 0) -> List[Tile]:
    """Unseen-basis effective tile kinds (= ukeire)."""
    return get_ukeire(hand, fuuro)


def opp_structural_total(state: GameState) -> int:
    """Unseen entities outside the wall; live counts include retained flowers/hidden kongs.

    Legacy snapshots without slot counts retain their previous structural prior.
    This is still a uniform marginal approximation, not an exact wall posterior.
    """
    return sum(
        state.opponent_hand_counts.get(seat, max(13 - 3*(len(state.melds.get(seat, [])) + state.opponent_unknown_kongs.get(seat, 0)), 0))
        - len(state.opponent_flowers.get(seat, []))
        + 4*state.opponent_unknown_kongs.get(seat, 0)
        for seat in ("left", "opposite", "right")
    )


def wall_adjusted(unseen: Dict[Tile, int], opp_structural_total: int) -> Dict[Tile, int]:
    """Wall-basis tile counts: unseen minus the uniform-prior opponent share.

    Under the uniform prior, E[opponents hold i] = unseen_i × opp_total/unseen_total,
    so n_wall_i = unseen_i × (unseen_total − opp_total)/unseen_total — a single
    constant ratio across all tiles. Flowers in `unseen` pass through the same
    ratio; callers treat them via replacement-draw approximation (labeled).
    """
    unseen_total = sum(unseen.values())
    if unseen_total <= 0:
        return dict(unseen)
    ratio = max(unseen_total - opp_structural_total, 0) / unseen_total
    return {tile: count * ratio for tile, count in unseen.items()}


def e_efficiency(n_eff_wall: int, n_wall: int) -> float:
    """牌效率 E(S)：下一摸有效的先验概率（墙内口径）。"""
    if n_wall <= 0:
        return 0.0
    return max(n_eff_wall, 0) / n_wall


def _comb(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    return math.comb(n, k)


def hypergeom_pmf(x: int, n_wall: int, hits: int, k: int) -> float:
    """P(X=x)：墙内 k 摸中命中有效牌 x 张的超几何分布。"""
    if n_wall <= 0 or k <= 0:
        return 1.0 if x == 0 else 0.0
    return _comb(hits, x) * _comb(n_wall - hits, k - x) / _comb(n_wall, k)


def p_hit(k: int, n_wall: int, hits: int) -> float:
    """P_hit(k)：k 摸内至少命中 1 张有效牌（超几何无放回）。"""
    if n_wall <= 0 or k <= 0 or hits <= 0:
        return 0.0
    if hits >= n_wall or k >= n_wall:
        return 1.0
    return 1.0 - _comb(n_wall - hits, k) / _comb(n_wall, k)


def expected_neff_1ply(hand: List[Tile], fuuro: int, discard: Tile,
                        wall: Dict[Tile, int], *,
                        deadline_s: float = 0.4) -> Tuple[float, bool]:
    """𝔼[n_eff(S∖{x})] = Σ_y P(摸y) · n_eff((S∖{x}) ∪ {y})，墙内口径权重。

    Returns (value, exact). 超过 deadline_s 退化为静态种数代理（post-discard
    手牌的 ukeire 种数），exact=False —— receipt 必须标注 `近似`。
    """
    expected_len = 13 - 3 * fuuro
    if len(hand) != expected_len:
        raise ValueError(f"手牌张数应为 {expected_len}，实际 {len(hand)}")
    if discard not in hand:
        raise ValueError("弃牌不在手牌中")
    wall_total = sum(wall.values())
    rest = list(hand)
    rest.remove(discard)
    if wall_total <= 0:
        return 0.0, True
    deadline = time.monotonic() + deadline_s
    total = 0.0
    for y, w in wall.items():
        if w <= 0:
            continue
        if time.monotonic() > deadline:
            return float(len(n_eff_kinds(rest, fuuro))), False
        total += w / wall_total * n_eff(rest + [y], fuuro, wall)
    return total, True
