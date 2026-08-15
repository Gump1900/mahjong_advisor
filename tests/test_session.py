"""Session-mode tests: event parsing and state bookkeeping (no I/O loop)."""
import pytest

from src.core.tiles import GameState, Meld, create_tile, parse_tile
from src.core.probability import count_remaining_tiles
from src.session import Event, parse_event, apply_event


def T(name):
    return parse_tile(name)


class TestParseEvent:
    def test_my_draw(self):
        assert parse_event("摸 5万") == Event("draw", "me", [T("5万")])
        assert parse_event("m5万") == Event("draw", "me", [T("5万")])

    def test_my_discard(self):
        assert parse_event("d 2万") == Event("discard", "me", [T("2万")])

    def test_opponent_discard(self):
        assert parse_event("l 3条") == Event("discard", "left", [T("3条")])
        assert parse_event("上家 3条") == Event("discard", "left", [T("3条")])
        assert parse_event("r打9饼") == Event("discard", "right", [T("9饼")])

    def test_opponent_calls(self):
        assert parse_event("r碰 5饼") == Event("peng", "right", [T("5饼")])
        assert parse_event("l吃 3万 4万 5万") == Event(
            "chi", "left", [T("3万"), T("4万"), T("5万")])
        assert parse_event("o杠 9条") == Event("gang", "opposite", [T("9条")])

    def test_my_kongs(self):
        assert parse_event("kg 中") == Event("kong_flower", "me", [T("中")])
        assert parse_event("杠花 春") == Event("kong_flower", "me", [T("春")])
        assert parse_event("an 9条") == Event("ankan", "me", [T("9条")])
        assert parse_event("加杠 南") == Event("kakan", "me", [T("南风")])

    def test_controls(self):
        assert parse_event("q").kind == "quit"
        assert parse_event("看").kind == "analyze"
        assert parse_event("撤").kind == "undo"
        assert parse_event("局").kind == "status"
        assert parse_event("") is None

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_event("乱写")
        with pytest.raises(ValueError):
            parse_event("碰 5饼")   # 碰必须带家前缀
        with pytest.raises(ValueError):
            parse_event("打 999")


class TestApplyEvent:
    def test_draw(self):
        st = apply_event(GameState(), Event("draw", "me", [T("5万")]))
        assert st.my_hand == [T("5万")]

    def test_draw_flower_goes_to_flowers(self):
        st = apply_event(GameState(), Event("draw", "me", [T("中")]))
        assert st.my_hand == []
        assert st.flowers_in_hand == [T("中")]

    def test_my_discard(self):
        st = GameState(my_hand=[T("2万"), T("3万")])
        apply_event(st, Event("discard", "me", [T("2万")]))
        assert st.my_hand == [T("3万")]
        assert st.my_discards == [T("2万")]

    def test_cannot_discard_flower(self):
        st = GameState(my_hand=[T("2万")], flowers_in_hand=[T("中")])
        with pytest.raises(ValueError):
            apply_event(st, Event("discard", "me", [T("中")]))

    def test_cannot_discard_not_held(self):
        with pytest.raises(ValueError):
            apply_event(GameState(my_hand=[T("2万")]), Event("discard", "me", [T("9条")]))

    def test_peng_removes_source_from_river(self):
        # left throws 5饼, right pengs it: the tile moves river -> meld, no double count
        st = GameState(my_hand=[])
        apply_event(st, Event("discard", "left", [T("5饼")]))
        assert count_remaining_tiles(st)[T("5饼")] == 3
        apply_event(st, Event("peng", "right", [T("5饼")]))
        assert st.discards["left"] == []
        assert st.melds["right"] == [Meld("peng", [T("5饼")] * 3)]
        assert count_remaining_tiles(st)[T("5饼")] == 1   # 4 - 3 in the meld

    def test_chi_removes_eaten_tile(self):
        st = GameState()
        apply_event(st, Event("discard", "opposite", [T("4万")]))
        apply_event(st, Event("chi", "left", [T("3万"), T("4万"), T("5万")]))
        assert st.discards["opposite"] == []
        assert count_remaining_tiles(st)[T("4万")] == 3    # only the meld's own copy...

    def test_peng_without_source_raises(self):
        with pytest.raises(ValueError):
            apply_event(GameState(), Event("peng", "right", [T("5饼")]))

    def test_kong_flower(self):
        st = GameState(flowers_in_hand=[T("中")] * 4)
        apply_event(st, Event("kong_flower", "me", [T("中")]))
        assert len(st.flowers_in_hand) == 3
        assert st.konged_flowers == [T("中")]

    def test_kong_flower_not_held_raises(self):
        with pytest.raises(ValueError):
            apply_event(GameState(), Event("kong_flower", "me", [T("发")]))

    def test_ankan(self):
        st = GameState(my_hand=[T("9条")] * 4 + [T("1万")])
        apply_event(st, Event("ankan", "me", [T("9条")]))
        assert st.my_hand == [T("1万")]
        assert st.my_melds == [Meld("an_gang", [T("9条")] * 4)]

    def test_kakan_upgrades_peng(self):
        st = GameState(my_hand=[T("南风")], my_melds=[Meld("peng", [T("南风")] * 3)])
        apply_event(st, Event("kakan", "me", [T("南风")]))
        assert st.my_hand == []
        assert st.my_melds == [Meld("ming_gang", [T("南风")] * 4)]

    def test_kakan_without_peng_raises(self):
        with pytest.raises(ValueError):
            apply_event(GameState(my_hand=[T("南风")]), Event("kakan", "me", [T("南风")]))


class TestSessionLoop:
    def test_run_session_drives_analysis(self):
        from src.session import run_session
        outputs = []
        inputs = iter([
            "摸 2万",           # 14 tiles -> auto analysis
            "l 9条",            # left discards
            "打 1饼",           # I discard
            "撤",               # undo -> discard reverted
            "q",
        ])
        start = GameState(my_hand=[parse_tile(t) for t in
            "1万 3万 4万 5万 6万 6万 6万 1饼 1饼 1饼 2条 2条 2条".split()])
        state = run_session(start, input_fn=lambda p="": next(inputs), print_fn=outputs.append)
        assert len(state.my_hand) == 14          # drew 2万, undo reverted the discard
        assert "听牌" in "".join(outputs) or "向听" in "".join(outputs)
        assert any("已撤销" in o for o in outputs)
