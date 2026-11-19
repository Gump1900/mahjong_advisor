import copy
from collections import Counter
import json
import random
import threading
import time

import pytest

from src.core.tiles import parse_tile
from src.players.analysis import analyze_actions
from src.players.shapes import describe_hand
from src.players.solo_search import search, plans, plan_structure, _trial, _discard
from src.players.strategy import strategy_bundle, immediate_risk, check_plan_reference, for_adviser
from src.players.opponent_model import fit, predict, features, load_model
from src.players.heuristic import HeuristicPlayer
from src.simulation.engine import Table
from src.simulation.hidden_world import sample_world, unseen_counts, SampledWorld
from src.simulation.observation import observe
from src.simulation.state import full_deck
from src.simulation.experiment import run_hand
from src.simulation.web import DesktopTable
from tests.test_simulation import scenario, BASE
from tests.test_coaching import wait_until


def test_each_partition_conserves_tiles_and_does_not_reuse_overlapping_shapes():
    hand = "1万 2万 3万 4万 5万 6万 6饼 7饼 8饼 8饼 南风 南风 东风 春".split()
    shape = describe_hand(hand)
    for parts in shape["decompositions"]:
        assert Counter(t for part in parts for t in part["tiles"])+Counter(shape["held_flowers"]) == Counter(hand)
    assert "东风" not in [t for p in shape["decompositions"][0] for t in p["tiles"]]


def test_four_sou_in_12346_is_not_isolated_and_quad_counts_two_pair_slots():
    shape = describe_hand("1条 2条 3条 4条 6条 9条 9条 9条 9条".split())
    assert "4条" not in shape["isolated_playable"]
    assert shape["seven_pairs_pair_slots"] == 2


def test_candidate_comparison_has_real_lost_and_gained_outs():
    obs = observe(Table(42),0)
    report = analyze_actions(obs)
    discards = [c for c in report["candidates"] if c["kind"] == "discard"]
    by_id = {c["action_id"]:c for c in discards}
    for c in discards:
        comparison = c["comparison_to_speed_reference"]
        ref = by_id[comparison["action_id"]]
        assert set(comparison["lost_improving_tiles"]) == set(ref["improving_tiles"])-set(c["improving_tiles"])


def test_joint_world_keeps_144_copies_hand_counts_wall_and_hidden_ankan_constraints():
    table = scenario({0:BASE+" 春"},melds={1:[("an_gang","中 中 中 中")]})
    obs = observe(table,0)
    owned = {parse_tile(t) for t in obs["self"]["hand"]}
    for seed in range(25):
        world = sample_world(obs,random.Random(seed))
        total = Counter(t for hand in world.hands.values() for t in hand)
        total.update(t for melds in world.melds.values() for m in melds for t in m.tiles)
        total.update(world.wall)
        total.update(parse_tile(t) for p in obs["players"] for t in p["river"]+p["flowers"])
        assert total == Counter(full_deck())
        assert len(world.wall) == obs["wall_count"]
        for p in obs["players"]:
            assert len(world.hands[p["seat"]]) == p["hand_count"]
        assert world.melds[1][0].tiles[0] not in owned


def test_hidden_flower_can_occupy_opponent_hand_and_invalid_copies_are_not_clamped():
    obs = observe(Table(42),0)
    assert any(any(t.is_flower for t in sample_world(obs,random.Random(seed)).hands[1]) for seed in range(10))
    bad = copy.deepcopy(obs)
    bad["self"]["hand"] += ["1万"]*4
    with pytest.raises(ValueError,match="副本"):
        unseen_counts(bad)
    bad = copy.deepcopy(obs)
    bad["wall_count"] -= 1
    with pytest.raises(ValueError,match="守恒"):
        sample_world(bad,random.Random(0))


def test_private_referee_hand_changes_cannot_change_public_world_prior():
    table = Table(42)
    before = observe(table,0)
    table.seats[1].hand[0],table.seats[2].hand[0] = table.seats[2].hand[0],table.seats[1].hand[0]
    after = observe(table,0)
    assert before == after
    assert sample_world(before,random.Random(2)) == sample_world(after,random.Random(2))


def test_personal_search_is_reproducible_fair_and_nonmutating():
    obs = observe(Table(42),0)
    original = copy.deepcopy(obs)
    a = search(obs,trials=8,horizon=2,time_budget=5)
    b = search(obs,trials=8,horizon=2,time_budget=5)
    a.pop("elapsed_ms");b.pop("elapsed_ms")
    assert a == b and obs == original
    assert {p["samples"] for p in a["plans"]} == {8}
    assert all(p["action"]["id"] in {x["id"] for x in obs["legal_actions"]} for p in a["plans"])
    assert all(0 <= p["solo_wins"] <= 8 for p in a["plans"])


def test_three_flower_waiting_and_immediate_exchange_both_survive_candidate_selection():
    obs = observe(scenario({0:"1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 南风 西风 东风 东风 东风"}),0)
    selected,_ = plans(obs,analyze_actions(obs))
    assert any(p["flower_policy"] == "reserve_triplet" for p in selected)
    assert any(p["action"]["kind"] == "flower_kong" for p in selected)


def test_four_flower_ankan_is_one_meld_one_replacement_and_uses_real_kong_win_score():
    table = scenario({0:"中 中 中 中 1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 西风"},wall_tail="西风")
    table.call_counts[0][1] = table.call_counts[0][2] = 3
    obs = observe(table,0)
    selected,_ = plans(obs,analyze_actions(obs))
    plan = next(p for p in selected if p["action"]["kind"] == "an_gang")
    shape = plan_structure(obs,plan)
    assert shape["groups_still_needed"] == 3 and not shape["held_flowers"]
    world = SampledWorld({s:list(p.hand) for s,p in enumerate(table.seats)},
                         {s:list(p.melds) for s,p in enumerate(table.seats)},list(table.wall))
    result = _trial(obs,plan,world,1)
    # kong base8 + concealed-flower kong12 =20; 3+3+1 payer shares.
    assert result["win"] and result["receipt"] == 140
    world.wall = [parse_tile("9万")]
    result = _trial(obs,plan,world,1)
    assert not result["win"] and result["receipt"] == 0  # Kong alone earns nothing.


def test_rollout_policy_never_receives_or_uses_future_wall():
    obs = observe(Table(42),0)
    hand = [parse_tile(t) for t in obs["self"]["hand"]]
    assert _discard(hand,[],unseen_counts(obs)) == _discard(hand,[],Counter(reversed(list(unseen_counts(obs).elements()))))


def test_risk_uses_hidden_flower_and_public_lock_rules_not_private_passes(monkeypatch):
    own = BASE.replace("南风","北风")+" 4万"
    opponent = "1饼 2饼 3饼 7条 8条 9条 南风 南风 南风 西风 西风 5万 6万"
    table = scenario({0:own,1:opponent},flowers={1:"春"})
    def fixed(obs,rng):
        return SampledWorld({s:list(p.hand) for s,p in enumerate(table.seats)},
                            {s:list(p.melds) for s,p in enumerate(table.seats)},list(table.wall))
    monkeypatch.setattr("src.players.strategy.sample_world",fixed)
    obs = observe(table,0)
    report = immediate_risk(obs,samples=4,time_budget=5)
    risk = next(r for r in report["candidates"] if r["tile"] == "4万")
    assert risk["per_opponent_hits"][1] == 4
    table.seats[1].ron_blocked = True
    assert observe(table,0) == obs
    assert immediate_risk(obs,samples=4,time_budget=5) == report
    table.call_counts[1][2] = 3
    report = immediate_risk(observe(table,0),samples=4,time_budget=5)
    assert next(r for r in report["candidates"] if r["tile"] == "4万")["per_opponent_hits"][1] == 0


def test_opponent_fit_uses_only_training_partition_and_public_features(tmp_path):
    roots = []
    for index,split in enumerate(("train","validation","test")):
        root = tmp_path/str(index)
        run_hand(Table(42+index),[HeuristicPlayer() for _ in range(4)],root/"hand-001")
        path = root/"hand-001/labels-offline-only.jsonl"
        labels = [json.loads(line) for line in path.read_text().splitlines()]
        for label in labels:
            label["split"] = split
        path.write_text("".join(json.dumps(x)+"\n" for x in labels))
        roots.append(root)
    model = fit(roots)
    assert model["family_counts"] == {"train":1,"validation":1,"test":1}
    assert model["evaluation"]["test"]["n"] > 0
    obs = observe(Table(99),0)
    before = features(obs,1)
    obs["self"]["hand"] = ["secret-not-used"]
    assert features(obs,1) == before
    result = predict(model,obs,1)
    assert 0 <= result["training_distribution_tenpai_estimate"] <= 1
    assert not result["human_calibrated"] and result["deployment"] == "shadow-only"
    assert all(p <= result["training_distribution_tenpai_estimate"]+1e-9 for p in result["training_distribution_wait_rates"].values())
    path = tmp_path/"model.json";path.write_text(json.dumps(model))
    assert load_model(path)["version"] == model["version"]
    model["global"]["ready"] = model["global"]["n"]+1
    path.write_text(json.dumps(model))
    with pytest.raises(ValueError):
        load_model(path)
    label_path = roots[2]/"hand-001/labels-offline-only.jsonl"
    first_family = json.loads((roots[0]/"hand-001/labels-offline-only.jsonl").read_text().splitlines()[0])["wall_family"]
    labels = [json.loads(line) for line in label_path.read_text().splitlines()]
    for label in labels:
        label["wall_family"] = first_family
    label_path.write_text("".join(json.dumps(x)+"\n" for x in labels))
    with pytest.raises(ValueError,match="泄漏"):
        fit(roots)


def test_local_strategy_worker_is_free_nonblocking_cached_and_stale_safe(tmp_path,monkeypatch):
    entered,release = threading.Event(),threading.Event()
    def compute(obs,**kwargs):
        entered.set()
        assert release.wait(3)
        return {"scope":"test","solo_search":{"plans":[]}}
    monkeypatch.setattr("src.players.strategy.strategy_bundle",compute)
    desktop = DesktopTable(Table(42),output_dir=tmp_path,paced=True)
    before = desktop.table.state_hash()
    view = desktop.request_strategy(desktop.version)
    assert entered.wait(1)
    start = time.monotonic();assert desktop.view()["strategy_job"]["status"] == "thinking"
    assert time.monotonic()-start < .3 and desktop.coach_calls == 0
    assert desktop.table.state_hash() == before
    desktop.request_strategy(desktop.version)  # Duplicate doesn't dispatch another job.
    desktop.new_game(desktop.version,seed=43)
    version = desktop.version
    release.set();time.sleep(.05)
    assert desktop.version == version and desktop.view()["strategy_job"] is None


def test_plan_citation_cannot_borrow_another_action_results():
    from src.players.base import DecisionError
    obs = observe(Table(42),0)
    report = strategy_bundle(obs,trials=4,horizon=1,time_budget=5)
    plan = report["solo_search"]["plans"][0]
    answer = {"plan_id":plan["plan_id"],"action_id":plan["action"]["id"],"next_discard":plan["next_discard"]}
    assert check_plan_reference(answer,report) == plan["plan_id"]
    answer["action_id"] = "different"
    with pytest.raises(DecisionError):
        check_plan_reference(answer,report)


def test_unvalidated_learned_rates_stay_out_of_paid_adviser_context():
    raw = {"solo_search":{"plans":[]},"opponent_baseline":[{"seat":1,
        "training_distribution_tenpai_estimate":.7,"training_distribution_wait_rates":{"4条":.5}}]}
    safe = for_adviser(raw)
    assert "estimate" not in json.dumps(safe) and "wait_rates" not in json.dumps(safe)
    assert "shadow-only" in json.dumps(safe) and raw["opponent_baseline"][0]["training_distribution_tenpai_estimate"] == .7


def test_local_strategy_ready_results_are_cached_and_do_not_charge_llm(tmp_path,monkeypatch):
    calls = []
    def compute(obs,**kwargs):
        calls.append(obs["observation_id"])
        return {"solo_search":{"plans":[]},"scope":"test"}
    monkeypatch.setattr("src.players.strategy.strategy_bundle",compute)
    desktop = DesktopTable(Table(42),output_dir=tmp_path,paced=True)
    version = desktop.version
    desktop.request_strategy(version)
    wait_until(lambda: desktop.view()["strategy_job"]["status"] == "ready")
    desktop.request_strategy(version)
    assert len(calls) == 1 and desktop.coach_calls == 0 and desktop.version == version
