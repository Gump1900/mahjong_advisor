"""房间与联机逻辑层（批次A）：访客/房间/座位/开局编排的纯逻辑测试。

语义依据 product-and-module-plan §9.4（访客、房间与生命周期）与 §9.5（状态基线）：
- 打开页面不创建对局；开局必须显式且幂等（重复开始只产生一局）
- 房间：等待准备 → 对局中 → 本局结束 → 等待准备（准备重置）
- 连接状态与对局状态分开；断线≠主动中止；主动离开=中止
- 引擎可脱离网页推进；策略经座位观察选动作（边界级验收 ②③）
"""
import pytest

from src.rooms.identity import VisitorRegistry
from src.rooms.room import Room, RoomError, RoomState
from src.rooms.service import RoomService


class TestVisitorIdentity:
    def test_create_and_resolve_by_token(self):
        reg = VisitorRegistry()
        vid, token = reg.create(nickname="测试员")
        v = reg.resolve(token)
        assert v["id"] == vid and v["nickname"] == "测试员"

    def test_bad_token_rejected(self):
        reg = VisitorRegistry()
        with pytest.raises(KeyError):
            reg.resolve("not-a-token")

    def test_roundtrip_export_import(self):
        reg = VisitorRegistry()
        reg.create(nickname="甲")
        reg2 = VisitorRegistry.from_dict(reg.to_dict())
        vid, token = list(reg2.to_dict()["visitors"].items())[0][0], None
        data = reg.to_dict()
        reg3 = VisitorRegistry.from_dict(data)
        any_token = next(iter(data["tokens"]))
        assert reg3.resolve(any_token)["id"] == data["tokens"][any_token]


class TestRoomLifecycle:
    def _room(self):
        return Room(room_id="r1", host_visitor="v1", host_nickname="房主")

    def test_create_room_has_host_seat_and_three_empty(self):
        room = self._room()
        assert room.state is RoomState.WAITING
        assert room.seats[0].visitor == "v1"
        assert [s.kind for s in room.seats[1:]] == ["empty", "empty", "empty"]

    def test_fill_and_remove_bots_before_start(self):
        room = self._room()
        room.fill_bots()
        assert all(s.kind == "bot" for s in room.seats[1:])
        room.remove_bot(3)
        assert room.seats[3].kind == "empty"

    def test_start_requires_full_seats_and_ready(self):
        room = self._room()
        with pytest.raises(RoomError, match="座位"):
            room.start_game(seed=1)
        room.fill_bots()
        with pytest.raises(RoomError, match="准备"):
            room.start_game(seed=1)
        room.set_ready("v1", True)
        ref = room.start_game(seed=1)
        assert ref["game_id"] and ref["seed"] == 1

    def test_start_is_idempotent_one_game_only(self):
        room = self._room()
        room.fill_bots(); room.set_ready("v1", True)
        ref1 = room.start_game(seed=42)
        ref2 = room.start_game(seed=43)          # 重复开始：不产生第二局
        assert ref2["game_id"] == ref1["game_id"] and ref2["seed"] == 42

    def test_normal_finish_resets_ready_for_next_hand(self):
        room = self._room()
        room.fill_bots(); room.set_ready("v1", True)
        room.start_game(seed=1)
        room.hand_finished(result="zimo")
        assert room.state is RoomState.WAITING
        assert room.seats[0].ready is False   # 下一局需重新准备

    def test_abort_is_distinct_from_normal_end(self):
        room = self._room()
        room.fill_bots(); room.set_ready("v1", True)
        ref = room.start_game(seed=1)
        room.abort(reason="房主离开")
        assert room.last_game["outcome"] == "aborted"
        assert room.last_game["game_id"] == ref["game_id"]
        assert room.state is RoomState.WAITING

    def test_connection_state_separate_from_room_state(self):
        room = self._room()
        room.fill_bots(); room.set_ready("v1", True)
        room.start_game(seed=1)
        room.set_connection("v1", "offline")     # 断线：不改变对局/房间状态
        assert room.state is RoomState.PLAYING
        assert room.connection("v1") == "offline"


class TestRoomService:
    def test_page_open_does_not_create_game(self):
        svc = RoomService()
        room = svc.create_room(visitor="anon", nickname="访客")
        assert room.active_game is None          # 边界级验收①：不开局

    def test_full_flow_creates_engine_backed_game(self):
        svc = RoomService()
        vid, _ = svc.registry.create(nickname="玩家")
        room = svc.create_room(visitor=vid, nickname="玩家")
        svc.fill_bots(room.room_id)
        svc.set_ready(room.room_id, vid, True)
        ref = svc.start_hand(room.room_id)
        table = svc.active_table(room.room_id)
        assert table is not None and table.stage == "turn"   # 引擎已就绪
        assert svc.observation_for(room.room_id, seat=0)["seat"] == 0

    def test_engine_advances_without_any_web(self):
        svc = RoomService()
        vid, _ = svc.registry.create(nickname="玩家")
        room = svc.create_room(visitor=vid, nickname="玩家")
        svc.fill_bots(room.room_id); svc.set_ready(room.room_id, vid, True)
        svc.start_hand(room.room_id)
        table = svc.active_table(room.room_id)
        for _ in range(4):                       # 边界级验收②：脱离网页推进
            for seat in table.waiting_seats():
                obs = svc.observation_for(room.room_id, seat)
                action = obs["legal_actions"][0]
                table.apply(seat, action["id"], controller="forced")
            if table.stage == "ended":
                break
        assert table.revision > 1

    def test_strategy_chooses_via_observation_only(self):
        from src.decision.ev_bot import EVBot
        svc = RoomService()
        vid, _ = svc.registry.create(nickname="玩家")
        room = svc.create_room(visitor=vid, nickname="玩家")
        svc.fill_bots(room.room_id); svc.set_ready(room.room_id, vid, True)
        svc.start_hand(room.room_id)
        obs = svc.observation_for(room.room_id, seat=0)      # 边界级验收③
        choice = EVBot("均衡", samples=8, seed=0).choose(obs)
        assert choice.action_id

    def test_export_import_roundtrip(self):
        svc = RoomService()
        vid, token = svc.registry.create(nickname="玩家")
        room = svc.create_room(visitor=vid, nickname="玩家")
        svc.fill_bots(room.room_id); svc.set_ready(room.room_id, vid, True)
        ref = svc.start_hand(room.room_id)
        svc2 = RoomService.from_dict(svc.to_dict())
        assert svc2.room(ref_source := room.room_id).room_id == room.room_id
        assert svc2.registry.resolve(token)["id"] == vid
