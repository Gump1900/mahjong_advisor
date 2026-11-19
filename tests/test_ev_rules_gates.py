"""Rule predicates: 吃三口互锁 / 过胡过圈 / 过碰过圈（按牌种）。

规则依据 docs/rules.md（三口互锁章节）。
"""
from src.core.round_rules import (
    can_peng_now,
    can_ron_now,
    clear_round_marks,
    is_locked,
    locked_pairs,
    note_claim,
)
from src.core.tiles import GameState, create_tile, parse_tile


def _state() -> GameState:
    return GameState()


class TestInterlock:
    def test_three_bites_lock_pair(self):
        state = _state()
        note_claim(state, "me", "left")   # 我吃上家
        note_claim(state, "me", "left")   # 再吃
        assert not is_locked(state, "me", "left")
        note_claim(state, "me", "left")   # 第三口（吃或碰都计）
        assert is_locked(state, "me", "left")
        assert frozenset({"me", "left"}) in locked_pairs(state)

    def test_sources_counted_separately(self):
        state = _state()
        for _ in range(2):
            note_claim(state, "me", "left")
        note_claim(state, "me", "opposite")
        assert not is_locked(state, "me", "left")
        assert not is_locked(state, "me", "opposite")

    def test_lock_blocks_ron_not_zimo(self):
        state = _state()
        for _ in range(3):
            note_claim(state, "me", "left")
        assert can_ron_now(state, "me", win_method="dianpao") is False
        assert can_ron_now(state, "me", win_method="zimo") is True
        assert can_ron_now(state, "me", win_method="gangkai") is True

    def test_locked_opponent_cannot_ron_me(self):
        state = _state()
        for _ in range(3):
            note_claim(state, "left", "me")   # 上家吃/碰我三次
        assert can_ron_now(state, "left", win_method="dianpao") is False

    def test_lock_not_transitive(self):
        state = _state()
        for _ in range(3):
            note_claim(state, "me", "left")
        for _ in range(3):
            note_claim(state, "left", "opposite")
        assert is_locked(state, "me", "left")
        assert is_locked(state, "left", "opposite")
        assert not is_locked(state, "me", "opposite")

    def test_clear_round_marks_resets_everything(self):
        state = _state()
        for _ in range(3):
            note_claim(state, "me", "left")
        state.my_passed_win_pending = True
        state.my_passed_peng_kinds = [create_tile("万", 5)]
        clear_round_marks(state)
        assert locked_pairs(state) == set()
        assert state.my_passed_win_pending is False
        assert state.my_passed_peng_kinds == []


class TestGuoquan:
    def test_guoquan_blocks_ron_not_zimo(self):
        state = _state()
        state.my_passed_win_pending = True
        assert can_ron_now(state, "me", win_method="dianpao") is False
        assert can_ron_now(state, "me", win_method="zimo") is True

    def test_guoquan_cleared_allows_ron(self):
        state = _state()
        state.my_passed_win_pending = True
        state.my_passed_win_pending = False
        assert can_ron_now(state, "me", win_method="dianpao") is True

    def test_guoquan_only_applies_to_me(self):
        state = _state()
        state.my_passed_win_pending = True
        # 对手的过胡不可观测，谓词只管互锁
        assert can_ron_now(state, "left", win_method="dianpao") is True


class TestPassedPeng:
    def test_passed_peng_per_kind(self):
        state = _state()
        state.my_passed_peng_kinds = [parse_tile("5万")]
        assert can_peng_now(state, parse_tile("5万")) is False
        assert can_peng_now(state, parse_tile("6万")) is True

    def test_no_pass_no_restriction(self):
        assert can_peng_now(_state(), parse_tile("5万")) is True


# --- session 事件接线 ------------------------------------------------------------
from src.session import Event, apply_event, new_session
from src.core.round_rules import can_win_on_discard


class TestSessionWiring:
    def test_stateless_opponent_claims_count_bites(self):
        st = GameState()
        for tile in ("5饼", "7条", "9万"):
            apply_event(st, Event("discard", "left", [parse_tile(tile)]))
            apply_event(st, Event("peng", "right", [parse_tile(tile)]))
        assert st.chi_peng_source_counts == {"right": {"left": 3}}
        assert is_locked(st, "right", "left")

    def test_session_my_chi_counts_bite_via_pending(self):
        session = new_session("7万 8万 1条 2条 3条 4条 5条 6条 2饼 4饼 6饼 8饼 9饼")
        assert session.apply("上家打 9万")["ok"]
        assert session.apply("我吃 7万 8万 9万")["ok"]
        assert session.state.chi_peng_source_counts == {"me": {"left": 1}}

    def test_pass_legal_win_sets_guoquan_until_my_draw(self):
        session = new_session(
            "1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条", "中")
        assert session.apply("对家打 5条")["ok"]
        assert can_win_on_discard(session.state.my_hand, parse_tile("5条"),
                                  session.state.my_melds,
                                  session.state.flowers_in_hand,
                                  session.state.konged_flowers)
        assert session.apply("过")["ok"]
        assert session.state.my_passed_win_pending is True
        assert session.apply("摸 6条")["ok"]
        assert session.state.my_passed_win_pending is False

    def test_pass_non_win_does_not_set_guoquan(self):
        session = new_session("1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条")
        assert session.apply("对家打 9条")["ok"]
        assert session.apply("过")["ok"]
        assert session.state.my_passed_win_pending is False

    def test_pass_legal_peng_records_kind(self):
        session = new_session("5万 5万 7万 8万 1条 2条 3条 4条 5条 6条 2饼 4饼 6饼")
        assert session.apply("上家打 5万")["ok"]
        assert session.apply("过")["ok"]
        assert session.state.my_passed_peng_kinds == [parse_tile("5万")]

    def test_my_claim_clears_guoquan_windows(self):
        # 听 3饼/6饼（345饼未完成）；过掉合法胡后，用吃取得回合应解除过圈
        session = new_session(
            "1万 2万 3万 4万 5万 6万 7万 8万 9万 4饼 5饼 9条 9条", "中")
        assert session.apply("对家打 6饼")["ok"]
        assert session.apply("过")["ok"]
        assert session.state.my_passed_win_pending is True
        assert session.apply("上家打 3饼")["ok"]
        assert session.apply("我吃 3饼 4饼 5饼")["ok"]
        assert session.state.my_passed_win_pending is False
        assert session.state.chi_peng_source_counts == {"me": {"left": 1}}

    def test_new_session_starts_clean(self):
        session = new_session("1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条")
        st = session.state
        assert st.chi_peng_source_counts == {}
        assert st.my_passed_win_pending is False
        assert st.my_passed_peng_kinds == []


class TestMingGangBite:
    def test_my_ming_gang_counts_bite_and_clears_guoquan(self):
        # 规则 L107：接弃牌明杠本质也是碰，计一口；取得回合解除过圈（同吃/碰路径）
        session = new_session(
            "1万 2万 3万 4万 5万 6万 7万 8万 8条 9条 9万 9万 9万")
        assert session.apply("对家打 5条")["ok"]
        assert session.apply("过")["ok"]
        assert session.state.my_passed_win_pending is False   # 5条非我可胡，无过胡
        assert session.apply("上家打 9万")["ok"]
        assert session.apply("我杠 9万")["ok"]
        assert session.state.chi_peng_source_counts == {"me": {"left": 1}}

    def test_opponent_ming_gang_counts_bite(self):
        session = new_session("1万 2万 3万 4万 5万 6万 7万 8万 9万 1饼 2饼 3饼 5条")
        assert session.apply("摸 9条")["ok"]
        assert session.apply("打 5条")["ok"]
        assert session.apply("上家杠 5条")["ok"]
        assert session.state.chi_peng_source_counts == {"left": {"me": 1}}


class TestLegacyTakeSource:
    def test_peng_source_is_fresh_tail_not_old_copy(self):
        # 对家河里早就有旧 5饼（深埋），上家刚打的 5饼 在河尾：
        # 碰的来源必须是上家（河尾那张），不是对家（旧的那张）
        st = GameState()
        st.discards["opposite"] = [parse_tile("5饼"), parse_tile("7万")]
        apply_event(st, Event("discard", "left", [parse_tile("5饼")]))
        apply_event(st, Event("peng", "right", [parse_tile("5饼")]))
        assert st.chi_peng_source_counts == {"right": {"left": 1}}
