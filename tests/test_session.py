"""Session-mode tests: event parsing and state bookkeeping (no I/O loop)."""
import pytest
import copy

from src.core.tiles import GameState, Meld, create_tile, parse_tile
from src.core.probability import count_remaining_tiles
from src.session import (
    Event,
    GameSession,
    PHASE_NEED_DISCARD,
    PHASE_NEED_DRAW,
    PHASE_WON,
    apply_event,
    new_session,
    parse_event,
)


@pytest.mark.parametrize("command,flowers", [("摸 9万", ""), ("摸 春", ""),
                                           ("kg 中", "中"), ("kg 中 4", "中 中 中 中")])
def test_draw_and_flower_kong_do_not_implicitly_pass(command, flowers):
    session = new_session("1万 2万 3万 1饼 2饼 3饼 1条 2条 3条 南风 南风 南风 西风", flowers)
    assert session.apply("l 9条")["ok"]
    before = copy.deepcopy(session)
    result = session.apply(command)
    assert not result["ok"] and "请先处理当前待响应" in result["error"]
    assert session == before
    pending_id = session.pending["id"]
    assert not session.apply("过", expected_pending_id=pending_id+1)["ok"]
    assert session == before
    assert session.apply("过", expected_pending_id=pending_id)["ok"]
    assert session.apply(command)["ok"]
    assert session.undo()["ok"]
    assert session.undo()["ok"]
    assert session.pending == before.pending


@pytest.mark.parametrize("command", ["摸 9万", "kg 中"])
def test_own_previous_discard_does_not_block_next_turn(command):
    session = new_session("1万 2万 3万 1饼 2饼 3饼 1条 2条 3条 南风 南风 南风 西风", "中")
    assert session.apply("摸 北风")["ok"]
    assert session.apply("打 北风")["ok"]
    assert session.pending["player"] == "me"
    assert session.apply(command)["ok"]


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


BASE = "1万 2万 3万 1饼 2饼 3饼 1条 2条 3条 南风 南风 南风 西风"


class TestGameSessionV2:
    def test_no_furiten_after_passing_same_tile(self):
        session = new_session(BASE)
        assert session.apply("l 西风")["ok"]
        assert session.apply("过")["ok"]
        assert session.apply("r 西风")["ok"]
        assert session.apply("胡 放炮")["ok"]

    def test_opponent_cannot_discard_a_flower(self):
        session = new_session(BASE)
        assert not session.apply("l 中")["ok"]
        assert not session.state.discards["left"]

    def test_response_window_records_all_winners_and_beats_a_kong(self):
        session = new_session(BASE)
        session.apply("l 西风")
        pending_id = session.pending["id"]
        result = session.apply_claims(["o杠 西风", "r胡", "胡 放炮"],
                                      expected_pending_id=pending_id)
        assert result["ok"] and result["accepted"] == ["me", "right"]
        assert {winner["player"] for winner in session.winners} == {"me", "right"}
        assert session.win["method"] == "dianpao"
        assert session.state.discards["left"] == [T("西风")]
        assert not session.state.melds["opposite"]
        assert session.undo()["ok"]
        assert session.phase == PHASE_NEED_DRAW and session.winners == []
        assert session.pending["id"] == pending_id

    def test_response_window_peng_intercepts_chi_regardless_of_arrival_order(self):
        session = new_session(BASE)
        session.apply("l 4万")
        result = session.apply_claims(["我吃 2万 3万 4万", "r碰 4万"],
                                      expected_pending_id=session.pending["id"])
        assert result["ok"] and result["accepted"] == ["right"]
        assert not session.state.my_melds
        assert session.state.melds["right"] == [Meld("peng", [T("4万")] * 3)]

    def test_response_window_is_atomic_when_my_ron_is_illegal(self):
        hand = "1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 1条 2条 3条 9条"
        session = new_session(hand)
        session.apply("l 9条")
        result = session.apply_claims(["r胡", "胡"], expected_pending_id=session.pending["id"])
        assert not result["ok"]
        assert not session.winners and session.phase == PHASE_NEED_DRAW

    def test_zero_flower_cannot_ron_even_with_a_flush(self):
        session = new_session("1万 1万 1万 2万 2万 2万 3万 4万 5万 6万 7万 8万 9万")
        session.apply("l 9万")
        assert not session.apply("胡 放炮")["ok"]
        assert session.phase == PHASE_NEED_DRAW

    def test_flower_single_kong_and_four_tile_kong_are_distinct_events(self):
        session = new_session(BASE, "中 中 中 中")
        assert session.apply("kg 中")["ok"]
        assert len(session.state.flowers_in_hand) == 3
        assert session.state.flower_kong_groups == [[T("中")]]
        session.undo()
        assert session.apply("kg 中 4")["ok"]
        assert not session.state.flowers_in_hand
        assert session.state.flower_kong_groups == [[T("中")] * 4]

    def test_opponent_flower_kong_moves_known_tiles_without_double_counting(self):
        session = new_session(BASE)
        assert session.apply("l花 中 春")["ok"]
        before = count_remaining_tiles(session.state)
        assert session.apply("l杠花 中")["ok"]
        assert session.state.opponent_flowers["left"] == [T("春")]
        assert session.state.opponent_konged_flowers["left"] == [T("中")]
        assert count_remaining_tiles(session.state) == before

    def test_opponent_flowers_are_visible_counted_and_undoable(self):
        session = new_session(BASE)
        assert session.apply("l花 中 中 春")["ok"]
        assert session.state.opponent_flowers["left"] == [T("中"), T("中"), T("春")]
        assert count_remaining_tiles(session.state)[T("中")] == 2
        assert count_remaining_tiles(session.state)[T("春")] == 0
        assert not session.apply("r花 春")["ok"]
        assert not session.state.opponent_flowers["right"]
        assert session.undo()["ok"]
        assert not session.state.opponent_flowers["left"]

    def test_exposed_kong_requires_three_held_tiles_and_replacement_draw(self):
        session = new_session(BASE)
        assert session.apply("l 南风")["ok"]
        claim_id = session.pending["id"]
        assert session.apply("我杠 南风", expected_pending_id=claim_id)["ok"]
        assert session.phase == PHASE_NEED_DRAW
        assert len(session.state.my_hand) == session.base() == 10
        assert session.state.my_melds == [Meld("ming_gang", [T("南风")] * 4)]
        assert not session.state.discards["left"]
        assert session.apply("摸 西风")["ok"]
        assert session.last_draw_was_replacement
        assert session.apply("胡 杠开")["ok"]

    def test_draw_round_closes_game_without_awarding_kongs_and_can_undo(self):
        session = new_session(BASE)
        session.apply("l 南风")
        session.apply("我杠 南风")
        assert session.apply("黄庄")["ok"]
        assert session.phase == "drawn" and session.win is None
        assert not session.apply("摸 西风")["ok"]
        assert session.undo()["ok"]
        assert session.phase == PHASE_NEED_DRAW
        assert session.replacement_draw_pending

    def test_new_game_validation(self):
        with pytest.raises(ValueError, match="13"):
            new_session("1万 2万")
        with pytest.raises(ValueError, match="花牌"):
            new_session(BASE.replace("西风", "中"))
        with pytest.raises(ValueError, match="副本上限"):
            new_session(BASE, "春 春")

    def test_draw_discard_and_undo_restore_draw_slot(self):
        session = new_session(BASE)
        assert session.apply("摸 9万")["ok"]
        assert session.phase == PHASE_NEED_DISCARD
        assert session.drawn_tile == T("9万")
        assert session.apply("打 西风")["ok"]
        discarded_id = session.pending["id"]
        assert session.phase == PHASE_NEED_DRAW
        assert session.apply("撤")["ok"]
        assert session.drawn_tile == T("9万")
        assert session.pending is None
        session.apply("打 9万")
        assert session.pending["id"] > discarded_id

    def test_flower_draw_keeps_need_draw(self):
        session = new_session(BASE)
        assert session.apply("摸 春")["ok"]
        assert session.phase == PHASE_NEED_DRAW
        assert len(session.state.my_hand) == 13
        assert session.state.flowers_in_hand == [T("春")]

    def test_my_peng_binds_pending_id_and_enters_discard(self):
        hand = "5万 5万 1万 2万 3万 1饼 2饼 3饼 1条 2条 3条 南风 西风"
        session = new_session(hand)
        session.apply("l 5万")
        pending_id = session.pending["id"]
        stale = session.apply("我碰 5万", expected_pending_id=pending_id + 1)
        assert stale["ok"] is False and len(session.state.my_hand) == 13
        assert session.apply("我碰 5万", expected_pending_id=pending_id)["ok"]
        assert session.phase == PHASE_NEED_DISCARD
        assert len(session.state.my_hand) == 11
        assert session.state.my_melds[0] == Meld("peng", [T("5万")] * 3)

    def test_claim_rejected_during_need_discard(self):
        hand = "5万 5万 1万 2万 3万 1饼 2饼 3饼 1条 2条 3条 南风 西风"
        session = new_session(hand)
        session.apply("摸 9万")
        session.apply("l 5万")
        result = session.apply("我碰 5万", expected_pending_id=session.pending["id"])
        assert result["ok"] is False and "等摸牌" in result["error"]

    def test_my_chi_consumes_exact_latest_discard(self):
        hand = "2万 4万 1万 5万 6万 1饼 2饼 3饼 1条 2条 3条 南风 西风"
        session = new_session(hand)
        session.apply("l 3万")
        pending_id = session.pending["id"]
        assert session.apply("我吃 2万 3万 4万", expected_pending_id=pending_id)["ok"]
        assert session.state.discards["left"] == []
        assert session.state.my_melds[0].type == "chi"

    def test_opponent_claim_shape_direction_and_capacity(self):
        session = new_session(BASE)
        session.apply("o 4万")
        assert session.apply("l吃 3万 4万 5万", expected_pending_id=session.pending["id"])["ok"]
        session.apply("r 8万")
        bad = session.apply("l吃 7万 8万 9万", expected_pending_id=session.pending["id"])
        assert bad["ok"] is False and "座位" in bad["error"]

    def test_ron_and_explicit_terminal_state(self):
        session = new_session(BASE)
        session.apply("l 西风")
        assert session.apply("胡 放炮", expected_pending_id=session.pending["id"])["ok"]
        assert session.phase == PHASE_WON
        assert session.win == {"method": "dianpao", "tile": T("西风"), "source": "left"}
        assert session.apply("摸 9万")["ok"] is False

    def test_replacement_draw_is_the_only_gangkai_source(self):
        session = new_session(BASE, "中 中 中 中")
        assert session.apply("kg 中")["ok"]
        assert session.replacement_draw_pending is True
        assert session.apply("摸 西风")["ok"]
        assert session.last_draw_was_replacement is True
        assert session.apply("胡 杠开")["ok"]
        assert session.win["method"] == "gangkai"
