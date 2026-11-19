import copy

import pytest

from src.core.tiles import parse_tile
from src.players.heuristic import HeuristicPlayer
from src.simulation.engine import Table
from src.simulation.observation import observe
from src.simulation.replay import record, replay
from src.simulation.state import RULES_VERSION, PREVIOUS_RULES_VERSION
from tests.test_simulation import act, passes, scenario


HAND = "1万 1万 3饼 3饼 2条 3条 4条 5条 6条 7条 南风 西风 北风"


def after_passed_peng():
    t = scenario({0: HAND, 1: "1万", 2: "1万 3饼"}, actor=1)
    act(t, 1, "discard", "1万")
    assert any(a.kind == "peng" for a in t.legal_actions(0))
    act(t, 0, "pass")
    assert parse_tile("1万") in t.seats[0].peng_blocked
    passes(t)
    assert t.actor == 2
    return t


def test_same_tile_is_blocked_until_own_turn():
    t = after_passed_peng()
    act(t, 2, "discard", "1万")
    assert not any(a.kind == "peng" for a in t.legal_actions(0))
    assert observe(t, 0)["self"]["peng_blocked"] == ["1万"]
    assert not t.seats[0].ron_blocked
    assert all("peng_blocked" not in p for p in observe(t, 2)["players"])


def test_other_tile_is_still_pongable_and_resets_after_claim():
    t = after_passed_peng()
    act(t, 2, "discard", "3饼")
    assert any(a.kind == "peng" for a in t.legal_actions(0))
    act(t, 0, "peng")
    passes(t)
    assert t.actor == 0 and not t.seats[0].peng_blocked


def test_several_missed_tile_kinds_are_recorded_independently():
    t = after_passed_peng()
    act(t, 2, "discard", "3饼")
    act(t, 0, "pass")
    assert {str(tile) for tile in t.seats[0].peng_blocked} == {"1万", "3饼"}


def test_normal_turn_resets_passed_peng():
    t = after_passed_peng()
    act(t, 2, "discard", "1万");passes(t)
    action = next(a for a in t.legal_actions(3) if a.kind == "discard")
    t.apply(3, action.id);passes(t)
    assert t.actor == 0 and not t.seats[0].peng_blocked


def test_chi_turn_resets_peng_block():
    t = scenario({0: "3万", 1: "1万 2万 春 1饼 2饼 3饼 4条 5条 6条 南风 西风 北风 夏"})
    t.seats[1].peng_blocked.add(parse_tile("9饼"))
    act(t, 0, "discard", "3万");act(t, 1, "chi");passes(t)
    assert t.actor == 1 and not t.seats[1].peng_blocked


def test_pass_without_legal_peng_does_not_block():
    t = scenario({0: "9万", 1: "春 夏 秋 冬 梅 兰 竹 菊 中 发 白 东风 南风"})
    act(t, 0, "discard", "9万");act(t, 1, "pass")
    assert not t.seats[1].peng_blocked


@pytest.mark.parametrize("version", [RULES_VERSION, PREVIOUS_RULES_VERSION])
def test_record_replay_preserves_version_and_private_pass_state(version):
    t = Table(42, rules_version=version)
    bot = HeuristicPlayer()
    found = False
    for _ in range(800):
        if t.stage == "ended":
            break
        seat = t.waiting_seats()[0]
        actions = t.legal_actions(seat)
        peng = next((a for a in actions if a.kind == "peng"), None)
        action = next(a for a in actions if a.kind == "pass") if peng else None
        choice = action.id if action else bot.choose(observe(t, seat)).action_id
        t.apply(seat, choice)
        if peng:
            found = True
            break
    assert found
    data = copy.deepcopy(record(t))
    restored = replay(data)
    assert restored.state_hash() == t.state_hash()
    assert restored.rules_version == version
    if version == RULES_VERSION:
        assert any(p.peng_blocked for p in restored.seats)
        assert all("peng_blocked" in p for p in data["final_state"]["seats"])
    else:
        assert not any(p.peng_blocked for p in restored.seats)
        assert all("peng_blocked" not in p for p in data["final_state"]["seats"])
