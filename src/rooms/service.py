"""房间服务：编排引擎对局（批次A边界级验收的落点）。

边界纪律（docs/architecture.md（接口与信息边界））：
- 引擎只认（座位，动作）；身份与重复请求校验留在房间层
- 策略经座位观察（observe）选动作，不接触完整状态
- 页面/HTTP 层不进本模块：纯逻辑，可脱离网络测试
"""
import secrets
from typing import Dict, Optional

from ..simulation.engine import Table
from ..simulation.observation import observe
from .identity import VisitorRegistry
from .room import Room, RoomError, RoomState


def _default_table_factory(seed: int, dealer: int) -> Table:
    return Table(seed, dealer)


class RoomService:
    def __init__(self, table_factory=None):
        self.registry = VisitorRegistry()
        self._rooms: Dict[str, Room] = {}
        self._tables: Dict[str, Table] = {}
        self._factory = table_factory or _default_table_factory

    # ---- 房间编排 -------------------------------------------------------
    def create_room(self, visitor: str, nickname: str = "") -> Room:
        room = Room(room_id="r" + secrets.token_hex(6),
                    host_visitor=visitor, host_nickname=nickname)
        self._rooms[room.room_id] = room
        return room

    def room(self, room_id: str) -> Room:
        if room_id not in self._rooms:
            raise RoomError("房间不存在或已关闭")
        return self._rooms[room_id]

    def fill_bots(self, room_id: str) -> None:
        self.room(room_id).fill_bots()

    def set_ready(self, room_id: str, visitor: str, flag: bool) -> None:
        self.room(room_id).set_ready(visitor, flag)

    def start_hand(self, room_id: str, seed: Optional[int] = None) -> dict:
        room = self.room(room_id)
        already = room.state is RoomState.PLAYING
        seed = seed if seed is not None else secrets.randbits(53)
        ref = room.start_game(seed=seed)
        if not already:
            self._tables[room_id] = self._factory(ref["seed"], ref["dealer"])
        return ref

    def hand_finished(self, room_id: str, result: str = "") -> dict:
        return self.room(room_id).hand_finished(result=result)

    def abort(self, room_id: str, reason: str = "") -> dict:
        return self.room(room_id).abort(reason=reason)

    # ---- 引擎接口落点 -----------------------------------------------------
    def active_table(self, room_id: str) -> Optional[Table]:
        room = self.room(room_id)
        if room.state is not RoomState.PLAYING:
            return None
        return self._tables.get(room_id)

    def observation_for(self, room_id: str, seat: int) -> dict:
        table = self.active_table(room_id)
        if table is None:
            raise RoomError("没有进行中的对局")
        return observe(table, seat)

    # ---- 持久化（重启恢复的钩子；活动牌局的牌谱恢复属第二步任务6）----------
    def to_dict(self) -> dict:
        return {
            "registry": self.registry.to_dict(),
            "rooms": {rid: room.to_dict() for rid, room in self._rooms.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoomService":
        svc = cls()
        svc.registry = VisitorRegistry.from_dict(data.get("registry", {}))
        svc._rooms = {rid: Room.from_dict(rd)
                      for rid, rd in data.get("rooms", {}).items()}
        return svc
