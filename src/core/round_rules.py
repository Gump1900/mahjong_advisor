"""Local table rules for simultaneous discard claims and round settlement.

This layer consumes validated hand scores. It does not infer hidden hands or
convert 花 to currency: every payment uses the same units as the input score.
"""

from dataclasses import dataclass
from typing import Mapping, Sequence

from .hand_analyzer import can_ron
from .scoring import score_hand


def can_win_on_discard(hand, tile, melds=None, flowers=None,
                       konged_flowers=None, flower_kong_groups=None) -> bool:
    """Structural completion plus the local non-pattern flower requirement.

    Past discards and passed wins deliberately impose no furiten restriction.
    """
    melds = melds or []
    if len(hand) != 13 - 3 * len(melds) or not can_ron(hand, tile, len(melds)):
        return False
    try:
        score_hand(list(hand) + [tile], melds, flowers, konged_flowers, "dianpao",
                   flower_kong_groups=flower_kong_groups)
    except ValueError:
        return False
    return True

PLAYERS = ("me", "right", "opposite", "left")
UPSTREAM = {"me": "left", "right": "me", "opposite": "right", "left": "opposite"}


@dataclass(frozen=True)
class Claim:
    player: str
    kind: str                 # ron / peng / gang / chi


def resolve_claims(discarder: str, claims: Sequence[Claim]) -> tuple[Claim, ...]:
    """Resolve a complete response window, independent of arrival order.

    Callers must collect the actual declarations before resolving; this is not
    a guess about whether another player will claim. All ron declarations win.
    Peng/gang beat chi. Two different peng/gang declarations for one physical
    tile are inconsistent and are rejected rather than resolved arbitrarily.
    """
    if discarder not in PLAYERS:
        raise ValueError("未知出牌者")
    seen = set()
    for claim in claims:
        if claim.player not in PLAYERS or claim.player == discarder:
            raise ValueError("响应者必须是出牌者以外的玩家")
        if claim.player in seen:
            raise ValueError("同一玩家只能声明一次响应")
        seen.add(claim.player)
        if claim.kind not in ("ron", "peng", "gang", "chi"):
            raise ValueError("未知响应类型")
        if claim.kind == "chi" and UPSTREAM[claim.player] != discarder:
            raise ValueError("只能吃上家的弃牌")
    winners = tuple(claim for claim in claims if claim.kind == "ron")
    if winners:
        return tuple(sorted(winners, key=lambda claim: PLAYERS.index(claim.player)))
    triplets = tuple(claim for claim in claims if claim.kind in ("peng", "gang"))
    if len(triplets) > 1:
        raise ValueError("同一张弃牌不能被不同玩家同时碰或杠，请检查记录")
    return triplets or tuple(claim for claim in claims if claim.kind == "chi")


@dataclass(frozen=True)
class Payment:
    payer: str
    winner: str
    amount: int


@dataclass(frozen=True)
class Settlement:
    payments: tuple[Payment, ...]
    net: dict[str, int]


def settle_round(method: str, winner_amounts: Mapping[str, int],
                 source: str | None = None, *, locked_pairs=()) -> Settlement:
    """Settle final validated scores; no nonwinning kong is ever paid.

    winner_amounts maps each winner to the amount one liable player pays them.
    A discard may have several winners. Self draw/kong draw has one winner,
    paid individually by the other three. A drawn round has no payments.
    """
    pairs = set()
    for pair in locked_pairs:
        pair = frozenset(pair)
        if len(pair) != 2 or not pair.issubset(PLAYERS):
            raise ValueError("互锁关系必须是两个不同的已知玩家")
        pairs.add(pair)
    locked = set().union(*pairs) if pairs else set()
    if method not in ("dianpao", "zimo", "gangkai", "draw"):
        raise ValueError("未知结算方式")
    if method == "draw":
        if winner_amounts or source is not None:
            raise ValueError("黄庄没有胡牌者或付款方")
        return Settlement((), {player: 0 for player in PLAYERS})
    if not winner_amounts:
        raise ValueError("胡牌结算必须包含胡牌者")
    for player, amount in winner_amounts.items():
        if player not in PLAYERS:
            raise ValueError("未知胡牌者")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("结算数额必须是正整数")
    if method == "dianpao":
        if any(player in locked for player in winner_amounts):
            raise ValueError("吃三口互锁者本局只能自摸，不能接炮")
        if source not in PLAYERS or source in winner_amounts:
            raise ValueError("放炮者必须是胡牌者以外的玩家")
        payments = tuple(Payment(source, player, amount)
                         for player, amount in winner_amounts.items())
    else:
        if source is not None or len(winner_amounts) != 1:
            raise ValueError("自摸或杠开只能有一位胡牌者且没有放炮者")
        winner, amount = next(iter(winner_amounts.items()))
        payments = tuple(Payment(player, winner, amount * (
                             3 if frozenset((player, winner)) in pairs else 1))
                         for player in PLAYERS if player != winner)
    net = {player: 0 for player in PLAYERS}
    for payment in payments:
        net[payment.payer] -= payment.amount
        net[payment.winner] += payment.amount
    return Settlement(payments, net)


# --- 吃三口互锁 / 过胡过圈 / 过碰过圈 谓词（EV 门控与 bot 合法性共用） -------------

def note_claim(state, taker: str, source: str) -> None:
    """吃或碰成组后计一口（取得成组者 taker ← 弃牌来源者 source）。"""
    if taker not in PLAYERS or source not in PLAYERS or taker == source:
        raise ValueError("计口双方必须是两个不同的已知玩家")
    counts = state.chi_peng_source_counts.setdefault(taker, {})
    counts[source] = counts.get(source, 0) + 1


def locked_pairs(state) -> set:
    """累计三口的对（frozenset 二元组）。锁不传递、不解除、下局清零。"""
    pairs = set()
    for taker, sources in state.chi_peng_source_counts.items():
        for source, count in sources.items():
            if count >= 3:
                pairs.add(frozenset((taker, source)))
    return pairs


def is_locked(state, a: str, b: str) -> bool:
    return frozenset((a, b)) in locked_pairs(state)


def can_ron_now(state, player: str = "me", *, win_method: str = "dianpao",
                tile=None) -> bool:
    """结构性胡牌之外的可胡资格谓词（只管可观测状态）。

    - 互锁者本局不能接任何人的炮，只能自摸/杠开（规则 L109）。
    - 过胡未过圈只禁我的接炮（规则 L80）；对手是否过胡不可观测，不设门。
    """
    if win_method not in ("dianpao", "zimo", "gangkai"):
        raise ValueError(f"未知胡法 {win_method!r}")
    if win_method in ("zimo", "gangkai"):
        return True
    locked = set().union(*locked_pairs(state)) if locked_pairs(state) else set()
    if player in locked:
        return False
    if player == "me" and state.my_passed_win_pending:
        return False
    return True


def can_peng_now(state, tile) -> bool:
    """过碰未过圈的牌种不能再碰（只对 me 可观测）。"""
    return tile not in state.my_passed_peng_kinds


def clear_round_marks(state) -> None:
    """新的一局：互锁、过胡、过碰全部清零（规则 L110、L113）。"""
    state.chi_peng_source_counts = {}
    state.my_passed_win_pending = False
    state.my_passed_peng_kinds = []
