"""房间与座位生命周期（规划 §9.4/§9.5）。

状态基线：房间 等待准备 → 对局中 → 本局结束 → 等待准备（准备重置）。
连接状态与对局状态分开；断线只改连接状态；主动离开=中止（与正常结算可区分）。
开局必须显式且幂等：四座齐全 + 真人已准备 + 无进行中牌局，重复开始只产生一局。
"""
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class RoomState(Enum):
    WAITING = "waiting"
    PLAYING = "playing"


class RoomError(Exception):
    """编排规则拒绝（携带面向用户的原因说明）。"""


@dataclass
class Seat:
    kind: str = "empty"            # empty / human / bot
    visitor: Optional[str] = None
    nickname: str = ""
    ready: bool = False            # bot 恒视为就绪
    bot_persona: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "visitor": self.visitor,
                "nickname": self.nickname, "ready": self.ready,
                **({"bot_persona": self.bot_persona} if self.kind == "bot" else {})}


class Room:
    def __init__(self, room_id: str, host_visitor: str, host_nickname: str = ""):
        self.room_id = room_id
        self.host_visitor = host_visitor
        self.seats: List[Seat] = [Seat(kind="empty") for _ in range(4)]
        self.seats[0] = Seat(kind="human", visitor=host_visitor,
                             nickname=host_nickname or "房主")
        self.state = RoomState.WAITING
        self.active_game: Optional[dict] = None
        self.last_game: Optional[dict] = None
        self._connections: Dict[str, str] = {host_visitor: "online"}
        self.history: List[dict] = []

    # ---- 座位编排 -------------------------------------------------------
    def fill_bots(self, personas=("均衡", "稳", "凶")) -> None:
        if self.state is not RoomState.WAITING:
            raise RoomError("对局进行中不能调整机器人")
        it = iter(personas)
        for seat in self.seats:
            if seat.kind == "empty":
                persona = next(it, "均衡")
                seat.kind = "bot"
                seat.ready = True
                seat.nickname = f"机器人·{persona}"
                seat.bot_persona = persona

    def join(self, visitor: str, nickname: str) -> int:
        for index, seat in enumerate(self.seats):
            if seat.visitor == visitor:
                return index
        if self.state is not RoomState.WAITING:
            raise RoomError("对局已开始，请等待本局结束")
        target = next((i for i, s in enumerate(self.seats) if s.kind == "empty"), None)
        if target is None:
            target = next((i for i, s in enumerate(self.seats) if s.kind == "bot"), None)
        if target is None:
            raise RoomError("房间已满")
        self.seats[target] = Seat(kind="human", visitor=visitor, nickname=nickname)
        self._connections[visitor] = "online"
        for seat in self.seats:
            if seat.kind == "human":
                seat.ready = False
        return target

    def remove_bot(self, index: int) -> None:
        seat = self.seats[index]
        if seat.kind != "bot":
            raise RoomError("该座位不是机器人")
        if self.state is not RoomState.WAITING:
            raise RoomError("对局进行中不能移除机器人")
        self.seats[index] = Seat(kind="empty")

    def seat_of(self, visitor: str) -> int:
        for i, seat in enumerate(self.seats):
            if seat.kind == "human" and seat.visitor == visitor:
                return i
        raise RoomError("你不在这张桌上")

    def set_ready(self, visitor: str, flag: bool) -> None:
        self.seats[self.seat_of(visitor)].ready = flag

    # ---- 开局（显式且幂等）----------------------------------------------
    def start_game(self, seed: int, dealer: int = 0) -> dict:
        if self.state is RoomState.PLAYING and self.active_game:
            return dict(self.active_game)          # 重复开始：同一局
        if any(s.kind == "empty" for s in self.seats):
            raise RoomError("座位未满：先补齐机器人或等待玩家")
        if not all(s.ready for s in self.seats):
            raise RoomError("还有玩家未准备")
        self.active_game = {
            "game_id": f"g{secrets.token_hex(8)}",
            "seed": seed, "dealer": dealer,
            "started_at": time.time(), "outcome": None,
        }
        self.state = RoomState.PLAYING
        return dict(self.active_game)

    def hand_finished(self, result: str = "") -> dict:
        if self.state is not RoomState.PLAYING or not self.active_game:
            raise RoomError("没有进行中的对局")
        game = dict(self.active_game)
        game["outcome"], game["result"] = "normal", result
        self._archive(game)
        return game

    def abort(self, reason: str = "") -> dict:
        if self.state is not RoomState.PLAYING or not self.active_game:
            raise RoomError("没有进行中的对局")
        game = dict(self.active_game)
        game["outcome"], game["reason"] = "aborted", reason
        self._archive(game)
        return game

    def _archive(self, game: dict) -> None:
        self.last_game = game
        self.history.append(game)
        self.active_game = None
        self.state = RoomState.WAITING
        for seat in self.seats:                    # 下一局需重新准备
            if seat.kind == "human":
                seat.ready = False

    # ---- 连接状态（与对局状态分开）---------------------------------------
    def set_connection(self, visitor: str, status: str) -> None:
        self._connections[self.seat_of(visitor) and visitor or visitor] = status

    def connection(self, visitor: str) -> str:
        return self._connections.get(visitor, "offline")

    # ---- 持久化 ----------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id, "host_visitor": self.host_visitor,
            "state": self.state.value,
            "seats": [s.to_dict() for s in self.seats],
            "active_game": self.active_game, "last_game": self.last_game,
            "connections": dict(self._connections),
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Room":
        room = cls(data["room_id"], data["host_visitor"])
        room.state = RoomState(data.get("state", "waiting"))
        room.seats = [Seat(kind=s.get("kind", "empty"), visitor=s.get("visitor"),
                           nickname=s.get("nickname", ""), ready=bool(s.get("ready")),
                           bot_persona=s.get("bot_persona", "")) for s in data.get("seats", [])]
        if len(room.seats) != 4:
            room.seats += [Seat(kind="empty") for _ in range(4 - len(room.seats))]
        room.active_game = data.get("active_game")
        room.last_game = data.get("last_game")
        room._connections = dict(data.get("connections", {}))
        room.history = list(data.get("history", []))
        return room
