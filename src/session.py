"""Event-driven game session for the CLI and local web UI."""

import copy
from uuid import uuid4
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

from .core.hand_analyzer import can_chi, can_peng, calculate_shanten
from .core.probability import TileCounter, count_remaining_tiles
from .core.round_rules import (
    Claim, can_win_on_discard, note_claim, resolve_claims,
)
from .core.tiles import GameState, Meld, Tile, parse_tile
from .decision.models import AnalysisBundle, DecisionContext
from .decision.service import analyze

PHASE_NEED_DRAW = "need_draw"
PHASE_NEED_DISCARD = "need_discard"
PHASE_WON = "won"
PHASE_DRAWN = "drawn"

_PLAYERS = {
    "上家": "left", "left": "left", "l": "left",
    "下家": "right", "right": "right", "r": "right",
    "对家": "opposite", "opposite": "opposite", "o": "opposite",
}
_PLAYER_ZH = {"me": "我", "left": "上家", "right": "下家", "opposite": "对家"}
_UPSTREAM = {"me": "left", "right": "me", "opposite": "right", "left": "opposite"}

_MY_ACTIONS = [
    ("杠花", "kong_flower"), ("kg", "kong_flower"),
    ("暗杠", "ankan"), ("an", "ankan"),
    ("加杠", "kakan"), ("ka", "kakan"),
    ("摸", "draw"), ("m", "draw"),
    ("打", "discard"), ("d", "discard"),
]

_HELP = """命令：摸X / 打X | l/r/o + 牌（打）| 我碰X | 我吃X X X | 胡 | 过
       r碰X | l吃X X X | o杠X | l暗杠X
       kg X(杠花) an X(暗杠) ka X(加杠) | 看 局 撤 q"""


@dataclass
class Event:
    kind: str
    player: str = "me"
    tiles: List[Tile] = field(default_factory=list)
    arg: Optional[str] = None


def _parse_tiles(text: str) -> List[Tile]:
    return [parse_tile(token) for token in text.split() if token]


def parse_event(line: str) -> Optional[Event]:
    """Parse one CLI/web event line."""
    text = line.strip()
    if not text:
        return None
    if text in ("q", "quit", "退", "退出"):
        return Event("quit")
    if text in ("看", "分析"):
        return Event("analyze")
    if text in ("撤", "z", "undo"):
        return Event("undo")
    if text in ("局", "局面", "状态"):
        return Event("status")
    if text in ("过", "pass"):
        return Event("pass")
    if text in ("黄庄", "黄掉", "流局"):
        return Event("draw_round")
    for prefix in ("暗杠花", "杠花", "kg"):
        if text.startswith(prefix):
            tokens = text[len(prefix):].split()
            count = "4" if prefix == "暗杠花" else "1"
            if len(tokens) == 2 and tokens[1] in ("1", "4"):
                count = tokens.pop()
            if len(tokens) != 1:
                raise ValueError("杠花格式：kg 中（单张）或 kg 中 4（四张暗杠）")
            return Event("kong_flower", tiles=[parse_tile(tokens[0])],
                         arg="4" if count == "4" else None)
    if text == "胡" or text.startswith("胡 "):
        method = text[1:].strip() or None
        aliases = {"自摸": "zimo", "放炮": "dianpao", "杠开": "gangkai",
                   "zimo": "zimo", "dianpao": "dianpao", "gangkai": "gangkai"}
        if method not in (None, *aliases):
            raise ValueError("胡法只能是自摸、放炮或杠开")
        return Event("win", arg=aliases.get(method))
    for prefix in ("我碰", "me碰"):
        if text.startswith(prefix):
            tiles = _parse_tiles(text[len(prefix):])
            if len(tiles) != 1:
                raise ValueError("我碰只需要 1 张牌")
            return Event("my_peng", tiles=tiles)
    for prefix in ("我杠", "me杠"):
        if text.startswith(prefix):
            tiles = _parse_tiles(text[len(prefix):])
            if len(tiles) != 1:
                raise ValueError("明杠只需要给出被打出的 1 张牌")
            return Event("my_gang", tiles=tiles)
    for prefix in ("我吃", "me吃"):
        if text.startswith(prefix):
            tiles = _parse_tiles(text[len(prefix):])
            if len(tiles) != 3:
                raise ValueError("我吃需要给出完整的 3 张顺子")
            return Event("my_chi", tiles=tiles)

    for keyword, kind in _MY_ACTIONS:
        if text.startswith(keyword):
            tiles = _parse_tiles(text[len(keyword):].strip())
            if len(tiles) != 1:
                raise ValueError(f"{keyword!r} 后面需要 1 张牌")
            return Event(kind, "me", tiles)

    for prefix in sorted(_PLAYERS, key=len, reverse=True):
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix):].strip()
        if not rest:
            raise ValueError(f"{prefix} 后面缺少动作")
        player = _PLAYERS[prefix]
        if rest in ("花完整", "花未知"):
            return Event("flower_completeness", player, arg=rest)
        if rest in ("胡", "胡 放炮"):
            return Event("observed_ron", player)
        if rest.startswith("杠花"):
            parsed = parse_event(rest)
            return Event("opp_kong_flower", player, parsed.tiles, parsed.arg)
        if rest.startswith("花"):
            tiles = _parse_tiles(rest[1:])
            if not tiles or any(not tile.is_flower for tile in tiles):
                raise ValueError("花牌记录只能包含东风、中发白或季节花")
            return Event("opp_flowers", player, tiles)
        if rest.startswith("暗杠"):
            tiles = _parse_tiles(rest[2:])
            if len(tiles) != 1:
                raise ValueError("暗杠只需要 1 张牌")
            return Event("opp_ankan", player, tiles)
        for verb, kind, count in (("碰", "peng", 1), ("吃", "chi", 3), ("杠", "gang", 1)):
            if rest.startswith(verb):
                tiles = _parse_tiles(rest[len(verb):])
                if len(tiles) != count:
                    raise ValueError(f"{verb}需要 {count} 张牌")
                return Event(kind, player, tiles)
        if rest.startswith("打"):
            rest = rest[1:].strip()
        tiles = _parse_tiles(rest)
        if len(tiles) != 1:
            raise ValueError("打牌只需要 1 张牌")
        return Event("discard", player, tiles)
    raise ValueError(f"无法识别 {text!r}（输入 帮助 查看命令）")


def _is_run(tiles: List[Tile]) -> bool:
    if len(tiles) != 3 or any(t.suit not in ("万", "饼", "条") for t in tiles):
        return False
    values = sorted(int(t.value) for t in tiles)
    return len({t.suit for t in tiles}) == 1 and values == list(range(values[0], values[0] + 3))


@dataclass
class GameSession:
    """Authoritative phase, pending-discard, draw-slot and win state."""

    state: GameState = field(default_factory=GameState)
    phase: str = PHASE_NEED_DRAW
    discard_seq: int = 0
    pending: Optional[dict] = None
    drawn_tile: Optional[Tile] = None
    win: Optional[dict] = None
    replacement_draw_pending: bool = False
    last_draw_was_replacement: bool = False
    winners: list = field(default_factory=list)
    game_id: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0
    events: list = field(default_factory=list)
    history: list = field(default_factory=list, repr=False)

    def __post_init__(self):
        if not self.history:
            self.history.append(self._snapshot())

    def base(self) -> int:
        return 13 - 3 * len(self.state.my_melds)

    def _snapshot(self):
        # History and discard_seq are intentionally excluded: snapshots stay flat,
        # and an undo never lets a stale client reuse a discard id.
        return copy.deepcopy((
            self.state, self.phase, self.pending, self.drawn_tile, self.win,
            self.replacement_draw_pending, self.last_draw_was_replacement,
            self.winners, self.events,
        ))

    def _restore(self, snapshot) -> None:
        (self.state, self.phase, self.pending, self.drawn_tile, self.win,
         self.replacement_draw_pending, self.last_draw_was_replacement,
         self.winners, self.events) = copy.deepcopy(snapshot)

    def decision_context(self) -> DecisionContext:
        return DecisionContext.from_session(self)

    def _record(self, events, pending_before, accepted=None):
        self.revision += 1
        pending = self.pending if events[0].kind == "discard" else pending_before
        self.events.append({
            "revision": self.revision,
            "pending_id": pending["id"] if pending else None,
            "actions": [{"kind": e.kind, "player": e.player,
                         "tiles": tuple(e.tiles), "arg": e.arg,
                         "discard_origin": "unknown" if e.kind == "discard" else None}
                        for e in events],
            "accepted": accepted,
        })

    def apply(self, line: str, *, expected_pending_id: Optional[int] = None) -> dict:
        try:
            event = parse_event(line)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if event is None:
            return {"ok": False, "error": "空输入"}
        if event.kind == "undo":
            return self.undo()
        if event.kind == "quit":
            return {"ok": False, "error": "网页模式直接关闭页面；命令行可按 Ctrl+C"}
        if event.kind in ("analyze", "status"):
            return {"ok": True, "noop": event.kind}
        if self.phase in (PHASE_WON, PHASE_DRAWN):
            return {"ok": False, "error": "本局已经结束，只能撤销或开始新对局"}

        before = self._snapshot()
        pending_before = copy.deepcopy(self.pending)
        try:
            self._dispatch(event, expected_pending_id)
        except ValueError as exc:
            self._restore(before)
            return {"ok": False, "error": str(exc)}
        self._record([event], pending_before)
        self.history.append(self._snapshot())
        return {"ok": True, "kind": event.kind}

    def undo(self) -> dict:
        if len(self.history) <= 1:
            return {"ok": False, "error": "没有可撤销的事件"}
        self.history.pop()
        self._restore(self.history[-1])
        self.revision += 1
        return {"ok": True, "undid": True}

    def apply_claims(self, lines: list[str], *, expected_pending_id: int) -> dict:
        """Apply a complete, observed response window as one undoable event.

        Other players' ron declarations are observations, not inferred legal
        hands: their concealed cards are not available to this assistant.
        """
        before = self._snapshot()
        pending_before = copy.deepcopy(self.pending)
        try:
            if self.phase in (PHASE_WON, PHASE_DRAWN):
                raise ValueError("本局已经结束")
            pending = self._require_pending(expected_pending_id)
            if not lines:
                raise ValueError("响应列表不能为空；无人响应请使用过")
            events = [parse_event(line) for line in lines]
            kinds = {"my_peng": "peng", "my_chi": "chi", "my_gang": "gang",
                     "peng": "peng", "chi": "chi", "gang": "gang",
                     "win": "ron", "observed_ron": "ron"}
            if any(event is None or event.kind not in kinds for event in events):
                raise ValueError("响应列表只能包含胡、碰、吃或明杠")
            for event in events:
                if event.tiles and pending["tile"] not in event.tiles:
                    raise ValueError("响应必须针对当前待响应弃牌")
            selected = resolve_claims(pending["player"],
                                      [Claim(event.player, kinds[event.kind]) for event in events])
            by_player = {event.player: event for event in events}
            for claim in selected:
                self._dispatch(by_player[claim.player], expected_pending_id)
        except ValueError as exc:
            self._restore(before)
            return {"ok": False, "error": str(exc)}
        self._record(events, pending_before, [claim.player for claim in selected])
        self.history.append(self._snapshot())
        return {"ok": True, "kind": "claims", "accepted": [claim.player for claim in selected]}

    def _dispatch(self, event: Event, expected_pending_id: Optional[int]) -> None:
        handlers = {
            "draw": self._draw, "discard": self._discard, "pass": self._pass,
            "my_peng": self._my_peng, "my_chi": self._my_chi,
            "my_gang": self._my_gang, "draw_round": self._draw_round,
            "peng": self._opponent_peng, "chi": self._opponent_chi,
            "gang": self._opponent_gang, "opp_ankan": self._opponent_ankan,
            "kong_flower": self._kong_flower, "ankan": self._ankan,
            "kakan": self._kakan, "win": self._win,
            "opp_flowers": self._opponent_flowers,
            "opp_kong_flower": self._opponent_kong_flower,
            "observed_ron": self._observed_ron,
            "flower_completeness": self._flower_completeness,
        }
        handler = handlers.get(event.kind)
        if handler is None:
            raise ValueError(f"暂不支持的操作：{event.kind}")
        handler(event, expected_pending_id)

    def _flower_completeness(self, event, _expected_id):
        self.state.opponent_flowers_complete[event.player] = event.arg == "花完整"

    def _remaining(self, tile: Tile) -> int:
        return count_remaining_tiles(self.state).get(tile, 0)

    def _set_pending(self, player: str, tile: Tile) -> None:
        self.discard_seq += 1
        self.pending = {"id": self.discard_seq, "player": player, "tile": tile}

    def _require_pending(self, expected_id: Optional[int] = None) -> dict:
        if self.pending is None:
            raise ValueError("没有可响应的弃牌")
        if expected_id is not None and self.pending["id"] != expected_id:
            raise ValueError("局面已更新，请按最新提示重新操作")
        return self.pending

    def _take_pending(self) -> dict:
        pending = self._require_pending()
        river = self.state.my_discards if pending["player"] == "me" else self.state.discards[pending["player"]]
        if not river or river[-1] != pending["tile"]:
            raise ValueError("待响应弃牌已不在对应牌河末尾，请撤销并检查记录")
        river.pop()
        self.pending = None
        return pending

    def _require_visible_capacity(self, additions: List[Tile]) -> None:
        remaining = count_remaining_tiles(self.state)
        for tile, count in Counter(additions).items():
            if remaining.get(tile, 0) < count:
                raise ValueError(f"{tile} 的可见数量将超过实体副本上限")

    def _require_no_opponent_pending(self) -> None:
        if self.pending and self.pending["player"] != "me":
            raise ValueError("请先处理当前待响应的对手弃牌（胡、碰、吃、杠或过）")

    def _draw(self, event: Event, _expected_id: Optional[int]) -> None:
        self._require_no_opponent_pending()
        if self.phase != PHASE_NEED_DRAW or len(self.state.my_hand) != self.base():
            raise ValueError("现在不是摸牌时机")
        tile = event.tiles[0]
        if self._remaining(tile) <= 0:
            raise ValueError(f"{tile} 已全部可见，请检查输入")
        self.pending = None
        self.state.my_passed_win_pending = False   # 轮到我摸牌，过圈窗口解除
        self.state.my_passed_peng_kinds = []
        self.drawn_tile = tile
        if tile.is_flower:
            self.state.flowers_in_hand.append(tile)
            return
        self.state.my_hand.append(tile)
        self.phase = PHASE_NEED_DISCARD
        self.last_draw_was_replacement = self.replacement_draw_pending
        self.replacement_draw_pending = False

    def _discard(self, event: Event, _expected_id: Optional[int]) -> None:
        tile = event.tiles[0]
        if tile.is_flower:
            raise ValueError("花牌不能打出，应记录为花牌或杠花")
        if event.player != "me":
            if self._remaining(tile) <= 0:
                raise ValueError(f"{tile} 已全部可见，请检查输入")
            self.pending = None
            self.state.discards[event.player].append(tile)
            # An unobserved draw may have added flowers since confirmation.
            self.state.opponent_flowers_complete[event.player] = False
            self._set_pending(event.player, tile)
            return
        if self.phase != PHASE_NEED_DISCARD or len(self.state.my_hand) != self.base() + 1:
            raise ValueError("先摸牌或完成碰/吃后才能打牌")
        if tile.is_flower or tile not in self.state.my_hand:
            raise ValueError("这张牌不能从当前手牌打出")
        self.pending = None
        self.state.my_hand.remove(tile)
        self.state.my_discards.append(tile)
        self.drawn_tile = None
        self.last_draw_was_replacement = False
        self.replacement_draw_pending = False
        self.phase = PHASE_NEED_DRAW
        self._set_pending("me", tile)

    def _pass(self, _event: Event, expected_id: Optional[int]) -> None:
        pending = self._require_pending(expected_id)
        if pending["player"] != "me" and len(self.state.my_hand) == self.base():
            tile = pending["tile"]
            hand = self.state.my_hand
            if not tile.is_flower and can_win_on_discard(
                    hand, tile, self.state.my_melds, self.state.flowers_in_hand,
                    self.state.konged_flowers,
                    flower_kong_groups=self.state.flower_kong_groups):
                self.state.my_passed_win_pending = True   # 过胡须过圈
            if not tile.is_flower and can_peng(hand, tile):
                self.state.my_passed_peng_kinds.append(tile)   # 过碰按牌种
        self.pending = None

    def _require_my_claim(self, expected_id: Optional[int]) -> dict:
        if self.phase != PHASE_NEED_DRAW or len(self.state.my_hand) != self.base():
            raise ValueError("只有在等摸牌阶段才能响应碰、吃或放炮胡")
        pending = self._require_pending(expected_id)
        if pending["player"] == "me":
            raise ValueError("不能响应自己打出的牌")
        return pending

    def _my_peng(self, event: Event, expected_id: Optional[int]) -> None:
        pending = self._require_my_claim(expected_id)
        tile = event.tiles[0]
        if tile != pending["tile"] or not can_peng(self.state.my_hand, tile):
            raise ValueError("当前手牌不能碰这张牌")
        for _ in range(2):
            self.state.my_hand.remove(tile)
        pending = self._take_pending()
        note_claim(self.state, "me", pending["player"])
        self.state.my_passed_win_pending = False   # 吃/碰取得回合，解除过圈
        self.state.my_passed_peng_kinds = []
        self.state.my_melds.append(Meld("peng", [tile] * 3))
        self.phase = PHASE_NEED_DISCARD
        self.drawn_tile = None

    def _my_chi(self, event: Event, expected_id: Optional[int]) -> None:
        pending = self._require_my_claim(expected_id)
        if pending["player"] != "left" or pending["tile"] not in event.tiles or not _is_run(event.tiles):
            raise ValueError("只能吃上家的弃牌，且必须组成同花色连续三张")
        concealed = list(event.tiles)
        concealed.remove(pending["tile"])
        legal_pairs = can_chi(self.state.my_hand, pending["tile"])
        if not any(Counter(concealed) == Counter(pair) for pair in legal_pairs):
            raise ValueError("手牌中没有这组吃牌所需的两张")
        for tile in concealed:
            self.state.my_hand.remove(tile)
        pending = self._take_pending()
        note_claim(self.state, "me", pending["player"])
        self.state.my_passed_win_pending = False   # 吃/碰取得回合，解除过圈
        self.state.my_passed_peng_kinds = []
        self.state.my_melds.append(Meld("chi", sorted(event.tiles, key=lambda t: int(t.value))))
        self.phase = PHASE_NEED_DISCARD
        self.drawn_tile = None

    def _my_gang(self, event: Event, expected_id: Optional[int]) -> None:
        pending = self._require_my_claim(expected_id)
        tile = event.tiles[0]
        if tile != pending["tile"] or tile.is_flower or self.state.my_hand.count(tile) != 3:
            raise ValueError("明杠需要手里三张同款结构牌及当前待响应弃牌")
        for _ in range(3):
            self.state.my_hand.remove(tile)
        pending = self._take_pending()
        note_claim(self.state, "me", pending["player"])   # 明杠本质也是碰，计一口
        self.state.my_passed_win_pending = False          # 取得回合，解除过圈窗口
        self.state.my_passed_peng_kinds = []
        self.state.my_melds.append(Meld("ming_gang", [tile] * 4))
        self.phase = PHASE_NEED_DRAW
        self.drawn_tile = None
        self.replacement_draw_pending = True
        self.last_draw_was_replacement = False

    def _draw_round(self, _event: Event, _expected_id: Optional[int]) -> None:
        # An observed table event, not inferred from the unseen-tile counter.
        self.phase = PHASE_DRAWN
        self.pending = None
        self.drawn_tile = None
        self.win = None
        self.winners = []
        self.replacement_draw_pending = False
        self.last_draw_was_replacement = False

    def _require_opponent_claim(self, event: Event, expected_id: Optional[int]) -> dict:
        pending = self._require_pending(expected_id)
        if pending["player"] == event.player:
            raise ValueError("不能鸣自己打出的牌")
        return pending

    def _opponent_peng(self, event: Event, expected_id: Optional[int]) -> None:
        pending = self._require_opponent_claim(event, expected_id)
        tile = event.tiles[0]
        if tile != pending["tile"]:
            raise ValueError(f"待响应的弃牌是 {pending['tile']}，不是 {tile}")
        self._require_visible_capacity([tile, tile])
        pending = self._take_pending()
        note_claim(self.state, event.player, pending["player"])
        self.state.melds[event.player].append(Meld("peng", [tile] * 3))
        self.state.opponent_flowers_complete[event.player] = False

    def _opponent_chi(self, event: Event, expected_id: Optional[int]) -> None:
        pending = self._require_opponent_claim(event, expected_id)
        if _UPSTREAM[event.player] != pending["player"]:
            raise ValueError("该玩家不能吃这个座位打出的牌")
        if pending["tile"] not in event.tiles or not _is_run(event.tiles):
            raise ValueError("吃牌必须包含待响应牌并组成同花色连续三张")
        additions = list(event.tiles)
        additions.remove(pending["tile"])
        self._require_visible_capacity(additions)
        pending = self._take_pending()
        note_claim(self.state, event.player, pending["player"])
        self.state.melds[event.player].append(Meld("chi", sorted(event.tiles, key=lambda t: int(t.value))))
        self.state.opponent_flowers_complete[event.player] = False

    def _opponent_gang(self, event: Event, expected_id: Optional[int]) -> None:
        pending = self._require_opponent_claim(event, expected_id)
        tile = event.tiles[0]
        if tile != pending["tile"]:
            raise ValueError(f"待响应的弃牌是 {pending['tile']}，不是 {tile}")
        self._require_visible_capacity([tile] * 3)
        pending = self._take_pending()
        note_claim(self.state, event.player, pending["player"])   # 明杠计一口
        self.state.melds[event.player].append(Meld("ming_gang", [tile] * 4))
        self.state.opponent_flowers_complete[event.player] = False

    def _opponent_ankan(self, event: Event, _expected_id: Optional[int]) -> None:
        tile = event.tiles[0]
        if tile.is_flower:
            raise ValueError("对手暗杠结构牌请使用万饼条或南西北")
        self._require_visible_capacity([tile] * 4)
        self.pending = None
        self.state.melds[event.player].append(Meld("an_gang", [tile] * 4))
        self.state.opponent_flowers_complete[event.player] = False

    def _opponent_flowers(self, event: Event, _expected_id: Optional[int]) -> None:
        self._require_visible_capacity(event.tiles)
        self.state.opponent_flowers[event.player].extend(event.tiles)
        self.state.opponent_flowers_complete[event.player] = False

    def _opponent_kong_flower(self, event: Event, _expected_id: Optional[int]) -> None:
        tile = event.tiles[0]
        count = 4 if event.arg == "4" else 1
        self._move_flowers(tile, count, self.state.opponent_flowers[event.player],
                           self.state.opponent_konged_flowers[event.player],
                           self.state.opponent_flower_kong_groups[event.player])
        self.state.opponent_flowers_complete[event.player] = False

    @staticmethod
    def _move_flowers(tile, count, held, konged, groups) -> None:
        if not tile.is_flower or (count == 4 and tile.suit == "季节"):
            raise ValueError("季节花只能逐张杠，中发白东可以逐张杠或四张暗杠")
        if held.count(tile) < count:
            raise ValueError(f"杠 {tile} 需要同款 {count} 张")
        group = [tile] * count
        for _ in range(count):
            held.remove(tile)
        konged.extend(group)
        groups.append(group)

    def _kong_flower(self, event: Event, _expected_id: Optional[int]) -> None:
        self._require_no_opponent_pending()
        if self.phase != PHASE_NEED_DRAW or len(self.state.my_hand) != self.base():
            raise ValueError("花牌应在等摸牌阶段杠出，再摸补牌")
        tile = event.tiles[0]
        self.pending = None
        count = 4 if event.arg == "4" else 1
        self._move_flowers(tile, count, self.state.flowers_in_hand,
                           self.state.konged_flowers, self.state.flower_kong_groups)
        self.drawn_tile = None
        self.replacement_draw_pending = True
        self.last_draw_was_replacement = False

    def _ankan(self, event: Event, _expected_id: Optional[int]) -> None:
        tile = event.tiles[0]
        if tile.is_flower:
            self._kong_flower(Event("kong_flower", tiles=[tile], arg="4"), _expected_id)
            return
        if self.phase != PHASE_NEED_DISCARD or len(self.state.my_hand) != self.base() + 1:
            raise ValueError("暗杠只能在摸牌后的出牌阶段执行")
        if self.state.my_hand.count(tile) < 4:
            raise ValueError(f"手里不足 4 张 {tile}")
        self.pending = None
        for _ in range(4):
            self.state.my_hand.remove(tile)
        self.state.my_melds.append(Meld("an_gang", [tile] * 4))
        self.phase = PHASE_NEED_DRAW
        self.drawn_tile = None
        self.replacement_draw_pending = True
        self.last_draw_was_replacement = False

    def _kakan(self, event: Event, _expected_id: Optional[int]) -> None:
        tile = event.tiles[0]
        if self.phase != PHASE_NEED_DISCARD or len(self.state.my_hand) != self.base() + 1:
            raise ValueError("加杠只能在摸牌后的出牌阶段执行")
        peng = next((m for m in self.state.my_melds
                     if m.type == "peng" and m.tiles and m.tiles[0] == tile), None)
        if peng is None or tile not in self.state.my_hand:
            raise ValueError(f"没有可升级的 {tile} 碰牌")
        self.pending = None
        self.state.my_hand.remove(tile)
        self.state.my_melds.remove(peng)
        self.state.my_melds.append(Meld("ming_gang", [tile] * 4))
        self.phase = PHASE_NEED_DRAW
        self.drawn_tile = None
        self.replacement_draw_pending = True
        self.last_draw_was_replacement = False

    def _win(self, event: Event, expected_id: Optional[int]) -> None:
        fuuro = len(self.state.my_melds)
        if self.pending and self.pending["player"] != "me":
            pending = self._require_my_claim(expected_id)
            if event.arg not in (None, "dianpao"):
                raise ValueError("当前只能选择放炮胡")
            if not can_win_on_discard(self.state.my_hand, pending["tile"],
                                      self.state.my_melds, self.state.flowers_in_hand,
                                      self.state.konged_flowers, self.state.flower_kong_groups):
                raise ValueError("当前手牌不能接炮：须牌型完成且有花（牌型加分不算资格花）")
            self.win = {"method": "dianpao", "tile": pending["tile"],
                        "source": pending["player"]}
        else:
            if self.phase != PHASE_NEED_DISCARD or self.drawn_tile is None or self.drawn_tile.is_flower:
                raise ValueError("当前没有可确认的自摸牌")
            if calculate_shanten(self.state.my_hand, fuuro) != -1:
                raise ValueError("当前手牌尚未胡牌")
            method = "gangkai" if self.last_draw_was_replacement else "zimo"
            if event.arg is not None and event.arg != method:
                raise ValueError("所选胡法与本次摸牌来源不符")
            self.win = {"method": method, "tile": self.drawn_tile, "source": None}
        self.phase = PHASE_WON
        self.winners.append({"player": "me", **self.win})

    def _observed_ron(self, event: Event, expected_id: Optional[int]) -> None:
        pending = self._require_pending(expected_id)
        if event.player == pending["player"]:
            raise ValueError("不能胡自己打出的牌")
        self.winners.append({"player": event.player, "method": "dianpao",
                             "tile": pending["tile"], "source": pending["player"]})
        self.phase = PHASE_WON


def _validate_initial(hand: List[Tile], flowers: List[Tile]) -> None:
    if len(hand) != 13:
        raise ValueError("起手暗牌必须恰好 13 张")
    if any(tile.is_flower for tile in hand):
        raise ValueError("起手暗牌中不能包含花牌")
    if any(not tile.is_flower for tile in flowers):
        raise ValueError("起手花牌区域只能放花牌")
    capacities = TileCounter()
    for tile, count in Counter(hand + flowers).items():
        if count > capacities.get_count(tile):
            raise ValueError(f"{tile} 超过实体副本上限 {capacities.get_count(tile)}")


def new_session(hand_line: str, flowers_line: str = "") -> GameSession:
    hand = _parse_tiles(hand_line)
    flowers = _parse_tiles(flowers_line)
    _validate_initial(hand, flowers)
    return GameSession(state=GameState(my_hand=hand, flowers_in_hand=flowers))


# Backwards-compatible stateless mutation helper for existing callers.
def _legacy_rivers(state: GameState):
    return [state.discards["opposite"], state.discards["right"],
            state.discards["left"], state.my_discards]


def _legacy_take(state: GameState, tiles: List[Tile]) -> str:
    """Pop the just-discarded tile from its river TAIL; returns the owner.

    只有河尾那张才是"待响应的弃牌"：深处同名牌是历史弃牌，不是来源。
    多条河同时以该牌结尾时按 opposite→right→left→me 顺序取第一个
    （无事件顺序信息时的确定性仲裁，残留歧义已在 docstring 声明）。
    """
    owners = ["opposite", "right", "left", "me"]
    for owner, river in zip(owners, _legacy_rivers(state)):
        if river and river[-1] in tiles:
            river.pop()
            return owner
    raise ValueError("牌河里找不到被碰/吃/杠的那张牌")


def apply_event(state: GameState, event: Event) -> GameState:
    kind, player, tiles = event.kind, event.player, event.tiles
    if kind == "draw":
        (state.flowers_in_hand if tiles[0].is_flower else state.my_hand).append(tiles[0])
    elif kind == "discard":
        tile = tiles[0]
        if player == "me":
            if tile.is_flower or tile not in state.my_hand:
                raise ValueError("这张牌不能打出")
            state.my_hand.remove(tile)
            state.my_discards.append(tile)
        else:
            state.discards[player].append(tile)
    elif kind in ("peng", "chi", "gang"):
        source = _legacy_take(state, tiles)
        if kind in ("peng", "chi"):
            note_claim(state, player, source)   # 吃/碰计口，杠不计
        meld_type = {"peng": "peng", "chi": "chi", "gang": "ming_gang"}[kind]
        meld_tiles = list(tiles) if kind == "chi" else tiles * (3 if kind == "peng" else 4)
        state.melds[player].append(Meld(meld_type, meld_tiles))
    elif kind == "kong_flower":
        tile = tiles[0]
        GameSession._move_flowers(tile, 4 if event.arg == "4" else 1,
                                  state.flowers_in_hand, state.konged_flowers,
                                  state.flower_kong_groups)
    elif kind == "ankan":
        tile = tiles[0]
        if state.my_hand.count(tile) < 4:
            raise ValueError(f"手里不足 4 张 {tile}")
        for _ in range(4):
            state.my_hand.remove(tile)
        state.my_melds.append(Meld("an_gang", [tile] * 4))
    elif kind == "kakan":
        tile = tiles[0]
        peng = next((m for m in state.my_melds if m.type == "peng" and m.tiles[0] == tile), None)
        if peng is None or tile not in state.my_hand:
            raise ValueError(f"没有可升级的 {tile} 碰牌")
        state.my_hand.remove(tile)
        state.my_melds.remove(peng)
        state.my_melds.append(Meld("ming_gang", [tile] * 4))
    return state


def print_analysis(bundle: AnalysisBundle, print_fn=print) -> None:
    if bundle.shanten == -1:
        print_fn("【分析】已经胡了！请显式输入 胡 确认")
    elif bundle.shanten == 0:
        print_fn(f"【分析】听牌！胡：{' '.join(str(t) for t in bundle.waiting) or '（无）'}")
    else:
        print_fn(f"【分析】向听数 {bundle.shanten}；进张："
                 f"{' '.join(str(t) for t in bundle.ukeire) or '无'}")
    print_fn(f"全桌剩余牌：{bundle.remaining_total} 张")
    for tile, after in bundle.discards_ranked[:6]:
        speed = bundle.discard_speed[tile]
        risk = bundle.risk_estimates[tile]
        print_fn(f"  - 打 {tile}：向听{after}；进张 {speed['types']}种/{speed['tiles']}张；"
                 f"风险 {bundle.risks[tile]}（吃{risk['chi']:.0%}/碰{risk['peng']:.0%}/炮{risk['ron']:.0%}）")


def print_status(session, print_fn=print) -> None:
    if isinstance(session, GameState):
        session = GameSession(state=session)
    state = session.state
    phase = {PHASE_NEED_DRAW: "等摸牌", PHASE_NEED_DISCARD: "须打一张", PHASE_WON: "已胡",
             PHASE_DRAWN: "黄庄，全部零结算"}[session.phase]
    print_fn(f"【局面】阶段：{phase}" + (f"｜刚摸：{session.drawn_tile}" if session.drawn_tile else ""))
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


def run_session(session, input_fn=input, print_fn=print):
    """Run the interactive CLI; accepts GameSession or legacy GameState."""
    legacy = isinstance(session, GameState)
    if legacy:
        session = GameSession(state=session)
    print_fn(_HELP)
    while True:
        try:
            line = input_fn("\n事件 > ")
        except (EOFError, StopIteration):
            break
        if line.strip() in ("q", "quit", "退", "退出"):
            break
        result = session.apply(line)
        if not result.get("ok"):
            print_fn(f"输入错误：{result.get('error', '操作失败')}")
        elif result.get("undid"):
            print_fn("已撤销上一步")
            print_status(session, print_fn)
        elif result.get("noop") == "analyze":
            print_analysis(analyze(session.state), print_fn)
        elif result.get("noop") == "status":
            print_status(session, print_fn)
        elif result.get("kind") == "draw" and session.phase == PHASE_NEED_DISCARD:
            print_analysis(analyze(session.state), print_fn)
    return session.state if legacy else session
