"""Game-session mode: incremental event input that maintains the GameState.

真实对局的用法：开局输一次起手牌，之后每回合只输事件（摸/打/吃/碰/杠），
工具自动维护局面，并在你摸牌后输出完整分析。引擎只吃**可见信息**（牌河 +
明牌），绝不模拟对手手牌——对手意图推断是 LLM 读牌层的事。

事件语法（中文/拼音均可，l/r/o = 上/下/对家）：
  摸 5万 / m 5万        我摸牌（花牌自动进"未杠花牌"）
  打 2万 / d 2万        我打牌
  l 3条 / l打3条        上家打牌
  r碰 5饼               下家碰（自动从牌河移走源牌，不重复计数）
  l吃 3万 4万 5万        上家吃
  o杠 9条               对家杠
  kg 中 / 杠花 中        我杠手里的一张花牌（留花搏杠开的时机操作）
  an 9条 / 暗杠 9条      我暗杠手里的 4 张同款
  ka 南 / 加杠 南        我加杠（碰后摸回第 4 张）
  看 / 撤 / 局 / q      重新分析 / 撤销上一步 / 看局面 / 结束
"""
import copy
from dataclasses import dataclass, field
from typing import List, Optional

from .core.tiles import GameState, Meld, Tile, parse_tile
from .llm.advisor import AnalysisBundle, analyze

_PLAYERS = {
    "上家": "left", "left": "left", "l": "left",
    "下家": "right", "right": "right", "r": "right",
    "对家": "opposite", "opposite": "opposite", "o": "opposite",
}

# my one-tile actions; keyword -> kind
_MY_ACTIONS = [
    ("杠花", "kong_flower"), ("kg", "kong_flower"),
    ("暗杠", "ankan"), ("an", "ankan"),
    ("加杠", "kakan"), ("ka", "kakan"),
    ("摸", "draw"), ("m", "draw"),
    ("打", "discard"), ("d", "discard"),
]

_HELP = """命令：摸X / 打X | l/r/o + 牌（打）| r碰X | l吃X X X | o杠X
       kg X(杠花) an X(暗杠) ka X(加杠) | 看(分析) 局(局面) 撤(撤销) q(结束)"""


@dataclass
class Event:
    kind: str            # draw/discard/peng/chi/gang/kong_flower/ankan/kakan/analyze/status/undo/quit
    player: str = "me"   # me | left | right | opposite
    tiles: List[Tile] = field(default_factory=list)


def parse_event(line: str) -> Optional[Event]:
    """Parse one session input line into an Event; None for blank input."""
    s = line.strip()
    if not s:
        return None
    if s in ("q", "quit", "退", "退出"):
        return Event("quit")
    if s in ("看", "分析"):
        return Event("analyze")
    if s in ("撤", "z", "undo"):
        return Event("undo")
    if s in ("局", "局面", "状态"):
        return Event("status")

    for kw, kind in _MY_ACTIONS:
        if s.startswith(kw):
            names = [t for t in s[len(kw):].strip().split() if t]
            tiles = [parse_tile(t) for t in names]
            if not tiles:
                raise ValueError(f"{kw!r} 后面缺少牌")
            return Event(kind, "me", tiles)

    for pref in sorted(_PLAYERS, key=len, reverse=True):
        if s.startswith(pref):
            rest = s[len(pref):].strip()
            if not rest:
                raise ValueError(f"{pref} 后面缺少动作")
            player = _PLAYERS[pref]
            if rest[0] == "碰":
                return Event("peng", player, [parse_tile(t) for t in rest[1:].split()])
            if rest[0] == "吃":
                return Event("chi", player, [parse_tile(t) for t in rest[1:].split()])
            if rest[0] == "杠":
                return Event("gang", player, [parse_tile(t) for t in rest[1:].split()])
            if rest[0] == "打":   # optional explicit verb: "l打9饼"
                rest = rest[1:].strip()
            return Event("discard", player, [parse_tile(t) for t in rest.split()])

    raise ValueError(f"无法识别 {s!r}（输入 帮助 查看命令）")


def _rivers(state: GameState) -> List[List[Tile]]:
    """All discard piles, most-recently-added rivers first for source lookup."""
    return [state.discards["opposite"], state.discards["right"],
            state.discards["left"], state.my_discards]


def _take_from_rivers(state: GameState, tiles: List[Tile]) -> Tile:
    """Remove the just-discarded source tile from any river (chi/peng/gang).

    A called tile leaves the river and joins the meld — without this the
    remaining-tile count would double-subtract it.
    """
    for river in _rivers(state):
        for i in range(len(river) - 1, -1, -1):
            if river[i] in tiles:
                return river.pop(i)
    raise ValueError("牌河里找不到被碰/吃/杠的那张牌——请先输入它被打出的事件")


def apply_event(state: GameState, event: Event) -> GameState:
    """Apply one event to the state (mutates and returns it)."""
    k, p, tiles = event.kind, event.player, event.tiles

    if k == "draw":
        tile = tiles[0]
        if tile.is_flower:
            state.flowers_in_hand.append(tile)
        else:
            state.my_hand.append(tile)
    elif k == "discard":
        tile = tiles[0]
        if p == "me":
            if tile.is_flower:
                raise ValueError("花牌不能打出")
            if tile not in state.my_hand:
                raise ValueError(f"手里没有 {tile}")
            state.my_hand.remove(tile)
            state.my_discards.append(tile)
        else:
            state.discards[p].append(tile)
    elif k == "peng":
        if len(tiles) != 1:
            raise ValueError("碰只需要 1 张牌")
        _take_from_rivers(state, tiles)
        state.melds[p].append(Meld("peng", tiles * 3))
    elif k == "chi":
        if len(tiles) != 3:
            raise ValueError("吃需要 3 张连续的牌")
        _take_from_rivers(state, tiles)
        state.melds[p].append(Meld("chi", list(tiles)))
    elif k == "gang":
        if len(tiles) != 1:
            raise ValueError("杠只需要 1 张牌")
        _take_from_rivers(state, tiles)
        state.melds[p].append(Meld("ming_gang", tiles * 4))
    elif k == "kong_flower":
        tile = tiles[0]
        if tile not in state.flowers_in_hand:
            raise ValueError(f"未杠花牌里没有 {tile}")
        state.flowers_in_hand.remove(tile)
        state.konged_flowers.append(tile)
    elif k == "ankan":
        tile = tiles[0]
        if sum(1 for t in state.my_hand if t == tile) < 4:
            raise ValueError(f"手里不足 4 张 {tile}，无法暗杠")
        for _ in range(4):
            state.my_hand.remove(tile)
        state.my_melds.append(Meld("an_gang", [tile] * 4))
    elif k == "kakan":
        tile = tiles[0]
        peng = next((m for m in state.my_melds
                     if m.type == "peng" and m.tiles and m.tiles[0] == tile), None)
        if peng is None:
            raise ValueError(f"没有碰过 {tile}，无法加杠")
        if tile not in state.my_hand:
            raise ValueError(f"手里没有 {tile}")
        state.my_hand.remove(tile)
        state.my_melds.remove(peng)
        state.my_melds.append(Meld("ming_gang", [tile] * 4))
    else:   # analyze/status/undo/quit carry no state change
        pass
    return state


# --- display ----------------------------------------------------------------
def print_analysis(bundle: AnalysisBundle, print_fn=print) -> None:
    a = bundle
    if a.shanten == -1:
        print_fn("【分析】已经胡了！")
    elif a.shanten == 0:
        print_fn(f"【分析】听牌！胡：{' '.join(str(t) for t in a.waiting) or '（无）'}")
    else:
        print_fn(f"【分析】向听数 {a.shanten}；进张：{' '.join(str(t) for t in a.ukeire) or '无'}")
    print_fn(f"全桌剩余牌：{a.remaining_total} 张")
    print_fn("出牌候选（向听数优先，同向听按进张速度——一胡即终局，快胡优先）：")
    for tile, after in a.discards_ranked[:6]:
        s = a.discard_speed[tile]
        est = a.risk_estimates[tile]
        print_fn(f"  - 打 {tile}：向听{after}；进张 {s['types']}种/{s['tiles']}张；"
                 f"风险 {a.risks[tile]}（吃{est['chi']:.0%}/碰{est['peng']:.0%}/炮{est['ron']:.0%}）")
    if a.kong_opportunities:
        print_fn("杠牌/杠开机会：")
        for op in a.kong_opportunities:
            print_fn(f"  - {op['kind']} {op['tile']}：杠分 {op['hua']}花；{op['note']}")
        if a.is_tenpai:
            print_fn("  ★ 已听牌：现在杠任意一组，补牌成胡 = 杠开（底分8花，上不封顶叠加）")


def print_status(state: GameState, print_fn=print) -> None:
    print_fn(f"我的暗牌（{len(state.my_hand)}张）：{' '.join(str(t) for t in state.my_hand)}")
    if state.my_melds:
        print_fn("我的明牌：" + " ".join(
            f"{m.type}[{' '.join(str(t) for t in m.tiles)}]" for m in state.my_melds))
    if state.flowers_in_hand:
        print_fn(f"未杠花牌：{' '.join(str(t) for t in state.flowers_in_hand)}")
    if state.my_discards:
        print_fn(f"我的弃牌：{' '.join(str(t) for t in state.my_discards)}")
    for label, key in (("上家", "left"), ("下家", "right"), ("对家", "opposite")):
        river = " ".join(str(t) for t in state.discards[key]) or "无"
        melds = " ".join(f"{m.type}[{' '.join(str(t) for t in m.tiles)}]"
                         for m in state.melds[key]) or "无"
        print_fn(f"{label}弃牌：{river} | 明牌：{melds}")


def run_session(state: GameState, input_fn=input, print_fn=print) -> GameState:
    """Interactive session loop: events in, analysis out after each draw."""
    history = [copy.deepcopy(state)]
    print_fn(_HELP)
    while True:
        try:
            line = input_fn("\n事件 > ")
            event = parse_event(line)
        except EOFError:
            break
        except ValueError as e:
            print_fn(f"输入错误：{e}")
            continue

        if event is None:
            continue
        if event.kind == "quit":
            break
        if event.kind == "undo":
            if len(history) > 1:
                history.pop()
                state = history[-1]
                print_fn("已撤销上一步")
                print_status(state, print_fn)
            else:
                print_fn("没有可撤销的事件")
            continue
        if event.kind == "analyze":
            print_analysis(analyze(state), print_fn)
            continue
        if event.kind == "status":
            print_status(state, print_fn)
            continue

        try:
            apply_event(state, event)
        except ValueError as e:
            print_fn(f"无法执行：{e}")
            continue

        history.append(copy.deepcopy(state))
        if event.kind == "draw" and len(state.my_hand) % 3 == 2:
            # 刚摸牌（14/11/8/5 张）——决策时刻，自动出完整分析
            print_analysis(analyze(state), print_fn)
    return state
