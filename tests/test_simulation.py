"""Rules, isolation, replay, player failures and complete-table regression."""
import copy
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.tiles import Meld, parse_tile
from src.players.base import Choice, DecisionError
from src.players.heuristic import HeuristicPlayer
from src.players.human import HumanPlayer
from src.players.llm import FallbackPlayer, LLMPlayer
from src.simulation.engine import Table
from src.simulation.observation import observe
from src.simulation.replay import record, replay, save
from src.simulation.runner import play
from src.simulation.state import SeatState, full_deck


def ts(text):
    return [parse_tile(t) for t in text.split()]


BASE = "1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 南风 南风 南风 西风"


def act(table, seat, kind, tile=None):
    action = next(a for a in table.legal_actions(seat)
                  if a.kind == kind and (tile is None or str(a.tiles[0]) == tile))
    table.apply(seat, action.id, controller="test")


def passes(table):
    for seat in list(table.waiting_seats()):
        act(table, seat, "pass")


def scenario(hands, *, actor=0, melds=None, flowers=None, wall_head="", wall_tail="",
             stage="turn", source="normal", can_kong=True, empty_wall=False):
    """Test-only full-world builder; conservation checked after construction."""
    table = Table(0, actor)
    table.seats = [SeatState() for _ in range(4)]
    used = Counter()
    for seat, text in hands.items():
        table.seats[seat].hand = ts(text)
        used.update(table.seats[seat].hand)
    for seat, groups in (melds or {}).items():
        table.seats[seat].melds = [Meld(kind, ts(text)) for kind, text in groups]
        for meld in table.seats[seat].melds:
            used.update(meld.tiles)
    for seat, text in (flowers or {}).items():
        table.seats[seat].flowers = ts(text)
        used.update(table.seats[seat].flowers)
    head, tail = ts(wall_head), ts(wall_tail)
    used.update(head+tail)
    full = Counter(full_deck())
    assert not used-full, used-full
    remaining = list((full-used).elements())
    for seat in range(4):
        target = 13-3*len(table.seats[seat].melds) + int(stage == "turn" and seat == actor)
        while len(table.seats[seat].hand) < target:
            table.seats[seat].hand.append(remaining.pop())
        assert len(table.seats[seat].hand) == target
    table.wall = head+remaining+tail
    if empty_wall:
        table.seats[(actor+1) % 4].river.extend(table.wall)
        table.wall = []
    table.stage, table.actor = stage, actor
    table.draw_source, table.can_kong = source, can_kong
    table.drawn_tile = table.seats[actor].hand[-1] if stage == "turn" else None
    table.assert_consistent()
    return table


@pytest.mark.parametrize("dealer", range(4))
def test_deal_initial_flow_and_seed(dealer):
    a, b = Table(42, dealer), Table(42, dealer)
    assert a.initial_wall == b.initial_wall
    assert [len(s.hand) for s in a.seats] == [14 if p == dealer else 13 for p in range(4)]
    assert len(a.wall) == 91
    assert a.actor == dealer and a.can_kong and a.stage == "turn"


def test_hold_flower_occupies_space_and_does_not_draw_for_free():
    table = scenario({0: BASE+" 春"})
    before = len(table.wall)
    assert any(a.kind == "flower_kong" for a in table.legal_actions(0))
    assert not any(a.kind == "discard" and a.tiles[0].is_flower for a in table.legal_actions(0))
    assert not any(a.kind == "win" for a in table.legal_actions(0))
    act(table, 0, "discard", "西风")
    assert len(table.seats[0].hand) == 13 and parse_tile("春") in table.seats[0].hand
    assert len(table.wall) == before


def test_flower_single_exchange_and_replacement_win():
    table = scenario({0: BASE+" 春"}, wall_tail="西风")
    act(table, 0, "flower_kong", "春")
    assert len(table.seats[0].hand) == 14 and not table.seats[0].melds
    assert table.draw_source == "replacement"
    assert table.seats[0].flowers == ts("春")
    act(table, 0, "win")
    # base8 + 春1 + 南刻1
    assert table.result["method"] == "gangkai" and table.result["net"] == [30, -10, -10, -10]


def test_four_flower_ankan_is_one_meld_and_one_replacement_no_double_scoring():
    table = scenario({0: "中 中 中 中 1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风"}, wall_tail="西风")
    wall_size = len(table.wall)
    act(table, 0, "an_gang", "中")
    assert len(table.wall) == wall_size-1 and len(table.seats[0].hand) == 11
    assert len(table.seats[0].melds) == 1 and not table.seats[0].flowers
    act(table, 0, "win")
    score = table.result["scores"]["0"]
    assert score["hua"] == 20 and score["flowers"] == 0
    assert table.result["net"] == [60, -20, -20, -20]


def test_four_single_flower_kongs_are_not_a_meld():
    table = scenario({0: "中 中 中 中 1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风"},
                     wall_tail="1饼 2饼 3饼 西风")
    for _ in range(4):
        act(table, 0, "flower_kong", "中")
    assert len(table.seats[0].hand) == 14 and not table.seats[0].melds
    assert table.seats[0].flowers == ts("中 中 中 中")
    act(table, 0, "win")
    assert table.result["scores"]["0"]["hua"] == 14  # base8 + four singles tier6


def test_flower_exchange_available_after_peng_without_draw():
    """2026-11-18 用户定稿：换花随时可做——吃/碰接管的回合不放弃换花。
    （推翻旧断言"碰后仅可弃牌"；旧断言编码的是实现不是规则。）"""
    table = scenario({0: "9万", 1: "9万 9万 春 1饼 2饼 3饼 4条 5条 6条 南风 南风 西风 北风"})
    act(table, 0, "discard", "9万")
    act(table, 1, "peng")
    passes(table)
    assert table.actor == 1 and table.draw_source == "claim"
    kinds = {a.kind for a in table.legal_actions(1)}
    assert "flower_kong" in kinds          # 手里还有春 → 仍可换
    assert "discard" in kinds


def test_add_gang_available_on_claim_turn():
    """用户实局：碰了111条手里还捏1条，吃一口牌接回合一一立即可加杠。"""
    table = scenario({0: "1条 1万 2万 3万 4万 5万 6万 1饼 2饼 4饼 5饼"},
                     melds={0: [("peng", "1条 1条 1条")]},
                     stage="turn", source="claim", can_kong=False)
    kinds = {a.kind for a in table.legal_actions(0)}
    assert "add_gang" in kinds and "discard" in kinds
    act(table, 0, "add_gang", "1条")
    assert any(m.type == "ming_gang" for m in table.seats[0].melds)


def test_an_gang_available_on_claim_turn():
    table = scenario({0: "2饼 2饼 2饼 2饼 1万 2万 3万 4万 5万 6万 9万"},
                     stage="turn", source="claim", can_kong=False)
    kinds = {a.kind for a in table.legal_actions(0)}
    assert "an_gang" in kinds and "discard" in kinds


def test_multi_ron_collects_full_window_and_pays_every_winner():
    table = scenario({0: "西风", 1: BASE, 2: BASE.replace("南风", "北风")})
    act(table, 0, "discard", "西风")
    act(table, 1, "ron")
    assert table.stage == "responses" and table.result is None
    act(table, 2, "ron")
    passes(table)
    assert table.result["winners"] == [1, 2]
    assert table.result["net"] == [-6, 3, 3, 0]


def test_no_flower_cannot_ron_even_with_qingyise():
    hand = "1万 2万 3万 4万 5万 6万 7万 8万 9万 2万 3万 4万 5万"
    table = scenario({0: BASE+" 5万", 1: hand})
    act(table, 0, "discard", "5万")
    assert "ron" not in {a.kind for a in table.legal_actions(1)}


def test_no_flower_self_draw_is_six_plus_patterns():
    hand = "1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 2条 3条 4条 西风 西风"
    table = scenario({0: hand})
    act(table, 0, "win")
    assert table.result["net"] == [18, -6, -6, -6]


def test_luxury_seven_pairs_is_legal_and_scored_by_same_rules():
    table = scenario({0: "1万 1万 1万 1万 2万 2万 3饼 3饼 4饼 4饼 5条 5条 6条 6条"})
    act(table, 0, "win")
    score = table.result["scores"]["0"]
    assert score["pattern_hua"] == 20 and score["hua"] == 26


def test_triple_luxury_self_draw_and_discard_settlement():
    hand = "1万 1万 1万 1万 2饼 2饼 2饼 2饼 3条 3条 3条 3条 北风 北风"
    table = scenario({0: hand})
    act(table, 0, "win")
    assert table.result["net"] == [198, -66, -66, -66]
    waiting = " ".join(hand.split()[:-1])
    table = scenario({0: "北风", 1: waiting}, flowers={1: "春"})
    act(table, 0, "discard", "北风")
    act(table, 1, "ron")
    passes(table)
    assert table.result["net"] == [-33, 33, 0, 0]


def test_pass_ron_blocks_other_wait_until_own_normal_turn():
    # Two-sided wait 4/7万, 南刻 supplies qualification.
    hand = "1饼 2饼 3饼 7条 8条 9条 南风 南风 南风 西风 西风 5万 6万"
    table = scenario({0: "4万", 1: hand})
    act(table, 0, "discard", "4万")
    assert any(a.kind == "ron" for a in table.legal_actions(1))
    act(table, 1, "pass")
    assert table.seats[1].ron_blocked
    assert table._score(1, "dianpao", parse_tile("7万")) is None
    passes(table)
    assert table.actor == 1 and not table.seats[1].ron_blocked


def test_peng_turn_clears_existing_ron_lock():
    table = scenario({0: "9万", 1: "9万 9万 春 1饼 2饼 3饼 4条 5条 6条 南风 南风 西风 北风"})
    table.seats[1].ron_blocked = True
    act(table, 0, "discard", "9万")
    act(table, 1, "peng")
    passes(table)
    assert table.actor == 1 and not table.seats[1].ron_blocked


def test_chi_turn_clears_ron_lock_without_drawing():
    table = scenario({0: "3万", 1: "1万 2万 春 1饼 2饼 3饼 4条 5条 6条 南风 西风 北风 夏"})
    table.seats[1].ron_blocked = True
    wall_size = len(table.wall)
    act(table, 0, "discard", "3万")
    act(table, 1, "chi")
    passes(table)
    assert table.actor == 1 and not table.seats[1].ron_blocked
    assert len(table.wall) == wall_size and table.draw_source == "claim"


def test_pass_without_legal_ron_does_not_create_lock():
    table = scenario({0: "9万", 1: "春 夏 秋 冬 梅 兰 竹 菊 中 发 白 东风 南风"})
    act(table, 0, "discard", "9万")
    assert {a.kind for a in table.legal_actions(1)} == {"pass"}
    act(table, 1, "pass")
    assert not table.seats[1].ron_blocked


def test_call_cannot_leave_only_undiscardable_flowers():
    hand = "9万 9万 春 夏 秋 冬 梅 兰 竹 菊 中 发 白"
    table = scenario({0: "9万", 1: hand})
    act(table, 0, "discard", "9万")
    assert "peng" not in {a.kind for a in table.legal_actions(1)}


def test_peng_beats_chi_without_order_bias():
    table = scenario({0: BASE+" 5万", 1: "3万 4万 1饼 2饼 3饼 4条 5条 6条 南风 西风 北风 春 夏",
                      2: "5万 5万 1饼 2饼 3饼 4条 5条 6条 西风 西风 北风 秋 冬"})
    act(table, 0, "discard", "5万")
    act(table, 1, "chi")
    act(table, 2, "peng")
    passes(table)
    assert table.actor == 2 and table.seats[2].melds[-1].type == "peng"
    assert not table.seats[1].melds


def test_ron_beats_ming_gang():
    # Source owns fourth 2万; seat1 can kong while seat2 wins with 1/3万.
    table = scenario({0: "2万", 1: "2万 2万 2万 1饼 2饼 3饼 4条 5条 6条 西风 北风 春 夏",
                      2: "1万 3万 4饼 5饼 6饼 7条 8条 9条 北风 北风 北风 西风 西风"})
    act(table, 0, "discard", "2万")
    act(table, 1, "ming_gang")
    act(table, 2, "ron")
    passes(table)
    assert table.result["winners"] == [2]
    assert not table.seats[1].melds and table.seats[1].hand.count(parse_tile("2万")) == 3


def test_added_kong_has_no_rob_response_and_wind_one_replaced():
    table = scenario({0: "南风 1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风"},
                     melds={0: [("peng", "南风 南风 南风")]}, wall_tail="西风")
    act(table, 0, "add_gang", "南风")
    assert table.stage == "turn" and table.actor == 0
    assert table.seats[0].melds[0].type == "ming_gang"
    act(table, 0, "win")
    score = table.result["scores"]["0"]
    assert score["hua"] == 14 and score["qualifying_hua"] == 6
    assert not any("风刻" in s for s in score["breakdown"])


def test_last_discard_can_ron_before_drawn_round():
    table = scenario({0: "西风", 1: BASE}, empty_wall=True)
    act(table, 0, "discard", "西风")
    act(table, 1, "ron")
    passes(table)
    assert table.result["method"] == "dianpao"


def test_last_wall_flower_without_playable_discard_ends_zero():
    groups = [("chi", "1万 2万 3万"), ("chi", "4万 5万 6万"),
              ("chi", "1饼 2饼 3饼"), ("chi", "4饼 5饼 6饼")]
    table = scenario({0: "1条", 1: "春"}, melds={1: groups}, wall_head="夏")
    # Move the remaining pool to old rivers except one physically reserved 夏.
    summer = parse_tile("夏")
    table.wall.remove(summer)
    table.seats[2].river.extend(table.wall)
    table.wall = [summer]
    table.assert_consistent()
    act(table, 0, "discard", "1条")
    passes(table)
    assert table.stage == "ended" and table.result["method"] == "draw"
    assert table.result["net"] == [0]*4


def test_drawn_round_does_not_pay_kongs():
    table = scenario({0: "1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 春 夏"},
                     melds={0: [("an_gang", "中 中 中 中")]}, empty_wall=True)
    act(table, 0, "discard", "1万")
    passes(table)
    assert table.result["method"] == "draw" and table.result["net"] == [0]*4


def test_unknown_ankan_and_draw_are_redacted_from_other_seats():
    table = scenario({0: "中 中 中 中 1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风"}, wall_tail="西风")
    act(table, 0, "an_gang", "中")
    other = observe(table, 1)
    own = observe(table, 0)
    assert other["players"][0]["melds"][0] == {
        "type": "an_gang", "tiles": None, "size": 4, "hidden": True}
    assert own["players"][0]["melds"][0]["tiles"] == ["中"]*4
    assert all("tile" not in e for e in other["events"] if e["kind"] in ("draw", "an_gang"))
    assert "wall" not in other and "hand" not in other["players"][0]
    assert "ron_blocked" not in other["players"][0]
    own["self"]["hand"].clear()
    assert len(table.seats[0].hand) == 11


def test_changing_hidden_ankan_identity_does_not_change_other_seat_observation():
    table = scenario({0: "中 中 中 中 1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风"},
                     wall_tail="发 发 发 发")
    act(table, 0, "an_gang", "中")
    before = observe(table, 1)
    other = copy.deepcopy(table)
    red, green = parse_tile("中"), parse_tile("发")
    other.seats[0].melds[0].tiles = [green]*4
    other.seats[0].hand = [red if t == green else t for t in other.seats[0].hand]
    other.drawn_tile = red
    other.wall = [red if t == green else t for t in other.wall]
    for event in other.events:
        if event.get("seat") == 0 and event["kind"] in ("draw", "an_gang"):
            event["tile"] = "发" if event["kind"] == "an_gang" else "中"
    other.assert_consistent()
    assert observe(other, 1) == before
    assert observe(other, 0) != observe(table, 0)


def test_response_choices_are_not_observable_to_other_responders():
    table = scenario({0: "西风", 1: BASE, 2: BASE.replace("南风", "北风")})
    act(table, 0, "discard", "西风")
    before = observe(table, 2)
    act(table, 1, "pass")
    assert observe(table, 2) == before


def test_illegal_and_stale_actions_do_not_mutate():
    table = Table(42)
    action = next(a for a in table.legal_actions(0) if a.kind == "discard")
    before = table.snapshot()
    with pytest.raises(ValueError):
        table.apply(1, action.id)
    assert table.snapshot() == before
    table.apply(0, action.id)
    before = table.snapshot()
    with pytest.raises(ValueError):
        table.apply(0, action.id)
    assert table.snapshot() == before


@pytest.mark.parametrize("seed", range(12))
def test_complete_bot_rounds_and_exact_replay(seed):
    table = Table(seed, dealer=seed % 4)
    play(table, [HeuristicPlayer() for _ in range(4)])
    assert table.stage == "ended" and sum(table.result["net"]) == 0
    table.assert_consistent()
    restored = replay(record(table))
    assert restored.snapshot() == table.snapshot()


@pytest.mark.parametrize("seed", range(6))
def test_random_legal_policies_also_finish(seed):
    class RandomPlayer:
        def __init__(self, seed):
            self.rng = random.Random(seed)
        def choose(self, obs):
            return Choice(self.rng.choice(obs["legal_actions"])["id"], "random")
    table = Table(seed, seed % 4)
    play(table, [RandomPlayer(seed+p) for p in range(4)])
    table.assert_consistent()
    assert replay(record(table)).result == table.result


def test_replay_detects_tampering_and_saves_without_overwriting(tmp_path):
    table = Table(2)
    action = next(a for a in table.legal_actions(0) if a.kind == "discard")
    table.apply(0, action.id)
    data = record(table)
    assert replay(data).state_hash() == table.state_hash()
    old_rules = copy.deepcopy(data)
    old_rules["rules_version"] = "local-2026-10-21-desktop-v1"
    with pytest.raises(ValueError, match="不支持"):
        replay(old_rules)
    data["decisions"][0]["state_hash"] = "tampered"
    with pytest.raises(ValueError, match="重放不一致"):
        replay(data)
    save(table, tmp_path/"round.json")
    import stat
    assert stat.S_IMODE((tmp_path/"round.json").stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        save(table, tmp_path/"round.json")


def test_runner_does_not_commit_partial_window_on_player_failure():
    table = scenario({0: "西风", 1: BASE, 2: BASE.replace("南风", "北风")})
    act(table, 0, "discard", "西风")
    before = table.snapshot()
    class Fail:
        def choose(self, obs):
            raise DecisionError("failure")
    with pytest.raises(DecisionError):
        play(table, [HeuristicPlayer(), HeuristicPlayer(), Fail(), HeuristicPlayer()])
    assert table.snapshot() == before


def test_human_reads_numbers_and_can_pause():
    table = Table(42)
    obs = observe(table, 0)
    answers = iter(["0", "wrong", "1"])
    output = []
    human = HumanPlayer(lambda _: next(answers), output.append)
    choice = human.choose(obs)
    assert choice.action_id == obs["legal_actions"][0]["id"] and choice.controller == "human"
    with pytest.raises(KeyboardInterrupt):
        HumanPlayer(lambda _: "q", output.append).choose(obs)


def test_human_hand_count_order_and_deduplicated_menu_are_distinct():
    text = "1万 2万 2万 2饼 3条 4饼 6万 6饼 7饼 8万 8万 8饼 8饼 9饼"
    table = scenario({0: text})
    observation = observe(table, 0)
    assert len(observation["self"]["hand"]) == 14
    assert len(observation["legal_actions"]) == 11
    before = copy.deepcopy(observation)
    output = []
    # UI menu item 4 is discard 8万 (two copies), not raw engine menu item 4.
    choice = HumanPlayer(lambda _: "4", output.append, tile_style="text").choose(observation)
    assert "你的手牌（共14张" in "\n".join(output)
    assert "可选动作（共11项，不是手牌张数）" in "\n".join(output)
    assert "  万：1万 2万 2万 6万 8万 8万" in output
    assert "  饼：2饼 4饼 6饼 7饼 8饼 8饼 9饼" in output
    assert "  条：3条" in output
    assert observation == before
    chosen = next(a for a in observation["legal_actions"] if a["id"] == choice.action_id)
    assert chosen["tiles"] == ["8万"]
    table.apply(0, choice.action_id)
    assert len(table.seats[0].hand) == 13
    assert table.seats[0].hand.count(parse_tile("8万")) == 1


def test_human_groups_flowers_and_rejects_multiple_menu_items():
    table = scenario({0: BASE+" 春"})
    observation = observe(table, 0)
    answers = iter(["10 11", "1"])
    output = []
    HumanPlayer(lambda _: next(answers), output.append, tile_style="text").choose(observation)
    assert "  留花：春" in output
    assert "  字牌：南风 南风 南风 西风" in output
    assert any("一次只能选一个动作" in line for line in output)


def test_declining_upstream_chi_peng_still_draws_south_like_user_transcript():
    hand = "2万 2万 2饼 4饼 6万 6饼 7饼 8万 8万 8饼 8饼 9万 9饼"
    table = scenario({0: hand, 3: "8饼"}, actor=3, wall_head="南风")
    act(table, 3, "discard", "8饼")
    before_wall = len(table.wall)
    observation = observe(table, 0)
    assert len(table.seats[0].hand) == 13
    assert {a["kind"] for a in observation["legal_actions"]} == {"pass", "peng", "chi"}
    output = []
    choice = HumanPlayer(lambda _: str(len(observation["legal_actions"])), output.append).choose(observation)
    table.apply(0, choice.action_id)
    passes(table)
    assert table.actor == 0 and table.draw_source == "normal"
    assert len(table.wall) == before_wall-1 and len(table.seats[0].hand) == 14
    assert table.drawn_tile == parse_tile("南风")
    assert any("不是跳过自己的回合" in line for line in output)
    assert any("照常摸牌" in line for line in output)
    output = []
    HumanPlayer(lambda _: "1", output.append).choose(observe(table, 0))
    assert any("【本次摸牌】🀁（南风）" in line for line in output)


def test_terminal_tile_faces_cover_all_types_without_changing_names():
    import unicodedata
    from src.players.render import tile_face, tile_line
    from src.core.probability import TileCounter
    types = list(TileCounter().all_counts())
    faces = [tile_face(t) for t in types]
    assert len(set(faces)) == len(types) == 42
    assert all(unicodedata.name(face).startswith("MAHJONG TILE ") for face in faces)
    assert tile_line(ts("1万 1饼 1条 南风 春")) == "🀇 🀙 🀐 🀁 🀦"
    assert tile_line(ts("1万 1饼 1条 南风 春"), "text") == "1万 1饼 1条 南风 春"
    assert tile_face("中", with_name=True) == "🀄（中）"
    with pytest.raises(ValueError):
        HumanPlayer(tile_style="unknown")


def test_terminal_unknown_ankan_renders_only_backs():
    table = scenario({0: "中 中 中 中 1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风"}, wall_tail="西风")
    act(table, 0, "an_gang", "中")
    act(table, 0, "discard", "西风")
    output = []
    HumanPlayer(lambda _: "1", output.append).choose(observe(table, 1))
    rendered = "\n".join(output)
    assert "暗杠[🀫 🀫 🀫 🀫]" in rendered and "🀄" not in rendered


def fake_client(answers):
    payloads = []
    def create(**kwargs):
        payloads.append(kwargs)
        value = answers.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=value)])
    return SimpleNamespace(messages=SimpleNamespace(create=create)), payloads


def checked_answer(obs, action_id, **fields):
    """Build a schema-valid fixture; tests may deliberately corrupt its fields."""
    from src.players.deliberation import Deliberation
    from src.players.strategy_guard import VERSION, required_costs
    session = Deliberation(obs)
    contract = session.contract
    card = next(c for c in contract["decision_cards"] if c["action_id"] == action_id)
    branch = card.get("after_discards", [card])[0]
    answer = {"action_id": action_id, "action": copy.deepcopy(branch["receipt"]["action"]),
              "fact_check": copy.deepcopy(branch["receipt"]), "reason": "比较结构与后续调整机会。", **fields}
    if "next_discard" in branch["receipt"]:
        answer["next_discard"] = branch["receipt"]["next_discard"]
    if branch["requires_tradeoff"]:
        answer["tradeoff"] = {"category": "shape_improvement", "evidence_ids": ["self.hand"],
                              "reason": "测试中明确选择另一种结构改良路线，不声称已经证明最优。"}
    answer["strategy_version"] = VERSION
    answer["reasoning"] = {"intent":"balance","priorities":["flexibility"],"focus_seats":[],
        "accept_costs":required_costs(session,answer,branch),"change_triggers":["opponent_claims"],"shape_refs":[]}
    answer["decision_note"] = {"opponents": [{"seat":p["seat"],"patterns":[],"focus_suits":[],
        "watch_tiles":[],"ankan_candidates":[],"confidence":"low", "evidence_ids":[]}
        for p in obs["players"] if p["seat"] != obs["seat"]],
        "plan":"根据公开局势比较推进与风险", "alternative_action_id":next((a["id"] for a in obs["legal_actions"] if a["id"] != action_id),action_id),
        "alternative_reason":"另一方案的机会与风险仍不确定", "change_if":"对手出现新副露时调整"}
    alt = next(c for c in contract["decision_cards"] if c["action_id"]==answer["decision_note"]["alternative_action_id"])
    if alt.get("after_discards"):
        answer["decision_note"]["alternative_next_discard"] = alt["after_discards"][0]["tile"]
    return answer


def test_llm_only_selects_legal_action_and_loads_knowledge():
    obs = observe(Table(42), 0)
    client, payloads = fake_client([json.dumps(checked_answer(obs, obs["legal_actions"][0]["id"], reason="测试"))])
    bot = LLMPlayer(decision_protocol="legacy-v2", client=client, model="fake")
    choice = bot.choose(obs)
    assert choice.controller == "llm" and bot.calls == 1
    assert "留花有占位成本" in payloads[0]["system"]
    sent = json.loads(payloads[0]["messages"][0]["content"])
    options = sent.pop("decision_options")
    assert sent.pop("self_facts")["hand_counts"]
    analysis = sent.pop("hand_analysis")
    assert sent.pop("opponent_constraints")
    sent.pop("flower_opportunities")
    assert sent.pop("strategy_contract")["version"] == "strategy-v2"
    assert sent.pop("memory_invalidations") == []
    assert sent.pop("notebook") is None
    assert sent.pop("notebook_context")["as_of_event_count"] == 0
    assert sent.pop("available_tools")
    assert sent.pop("evidence_catalog")
    assert "strategy_comparison" not in sent
    compact_actions = sent.pop("legal_actions")
    assert sent == {k:v for k,v in obs.items() if k != "legal_actions"}
    assert [{k:v for k,v in a.items() if k != "id"} for a in compact_actions] == [
        {k:v for k,v in a.items() if k != "id"} for a in obs["legal_actions"]]
    assert {a["action_id"] for a in options} == {a["id"] for a in compact_actions}
    assert "不是牌墙活张" in analysis["limitations"]


def test_llm_failure_pauses_or_records_explicit_fallback_without_leaking_errors():
    obs = observe(Table(42), 0)
    client, _ = fake_client([RuntimeError("secret-key"), RuntimeError("secret-key")])
    with pytest.raises(DecisionError) as err:
        LLMPlayer(decision_protocol="legacy-v2", client=client, model="fake").choose(obs)
    assert "secret-key" not in str(err.value)
    client, _ = fake_client(["{}", "{}"])
    fallback = FallbackPlayer(LLMPlayer(decision_protocol="legacy-v2", client=client, model="fake"), HeuristicPlayer())
    assert fallback.choose(obs).controller == "fallback:heuristic"


def test_llm_call_budget_is_enforced():
    obs = observe(Table(42), 0)
    client, payloads = fake_client(["{}"])
    with pytest.raises(DecisionError):
        LLMPlayer(decision_protocol="legacy-v2", client=client, model="fake", max_calls=1).choose(obs)
    assert len(payloads) == 1


def test_desktop_cli_all_bots_and_replay(tmp_path):
    script = Path(__file__).resolve().parents[1]/"scripts/play_test.py"
    run = subprocess.run([sys.executable, str(script), "--all-bots", "--seed", "42",
                          "--output-dir", str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout+run.stderr
    path = next(tmp_path.glob("*.json"))
    check = subprocess.run([sys.executable, str(script), "--replay", str(path)],
                           capture_output=True, text=True, timeout=30)
    assert check.returncode == 0 and "重放校验通过" in check.stdout


def test_desktop_human_can_pause_then_resume_without_api(tmp_path):
    script = Path(__file__).resolve().parents[1]/"scripts/play_test.py"
    paused = subprocess.run([sys.executable, str(script), "--output-dir", str(tmp_path)],
                            input="q\n", capture_output=True, text=True, timeout=30)
    assert paused.returncode == 130 and "你的手牌" in paused.stdout
    path = next(tmp_path.glob("*.json"))
    data = json.loads(path.read_text())
    assert data["final_state"]["stage"] != "ended"
    resumed = subprocess.run([sys.executable, str(script), "--resume", str(path), "--all-bots",
                              "--output-dir", str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert resumed.returncode == 0, resumed.stdout+resumed.stderr
    assert len(list(tmp_path.glob("*.json"))) == 2
