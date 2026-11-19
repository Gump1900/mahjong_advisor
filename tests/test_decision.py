"""Decision contracts, joint conservation, immediate settlement and stale jobs."""
import copy
import random
from collections import Counter

import pytest

from src.core.probability import count_remaining_tiles
from src.core.tiles import GameState, Meld, parse_tile
from src.decision.belief import HiddenWorld, OPPONENTS, sample_world
from src.decision.risk import evaluate_immediate_risk
from src.session import GameSession, new_session
from src import web

BASE = "1万 2万 3万 1饼 2饼 3饼 1条 2条 3条 南风 南风 南风 西风"


def tiles(text):
    return [parse_tile(t) for t in text.split()]


def ready():
    session = new_session(BASE)
    assert session.apply("摸 北风")["ok"]
    return session


def test_legacy_analysis_exports_are_compatible():
    from src.llm.advisor import analyze as legacy, AnalysisBundle
    from src.decision.service import analyze
    from src.decision.models import AnalysisBundle as Bundle
    assert legacy is analyze
    assert AnalysisBundle is Bundle


def test_versions_events_failed_actions_and_undo():
    s = ready()
    first_id = s.game_id
    assert s.revision == 1 and len(s.events) == 1
    assert s.events[0]["actions"][0]["kind"] == "draw"
    assert not s.apply("打 9饼")["ok"]
    assert s.revision == 1 and len(s.events) == 1
    assert s.apply("打 北风")["ok"]
    pending_id = s.pending["id"]
    assert s.events[-1]["pending_id"] == pending_id
    assert s.events[-1]["actions"][0]["discard_origin"] == "unknown"
    assert s.undo()["ok"]
    assert s.revision == 3 and len(s.events) == 1
    assert s.apply("打 北风")["ok"]
    assert s.revision == 4 and s.pending["id"] > pending_id
    assert s.game_id == first_id and new_session(BASE).game_id != first_id


def test_context_is_an_independent_snapshot():
    s = ready()
    context = s.decision_context()
    original = list(context.state.my_hand)
    s.apply("打 北风")
    assert context.state.my_hand == original
    assert context.revision == 1 and s.revision == 2
    context.events[0]["actions"][0]["arg"] = "test"
    assert s.events[0]["actions"][0]["arg"] is None


def test_flower_completeness_is_undoable_and_invalidated_by_new_discard():
    s = ready()
    assert s.apply("l花 春")["ok"]
    assert s.apply("l花完整")["ok"]
    assert s.state.opponent_flowers_complete["left"]
    assert s.apply("l 9饼")["ok"]
    assert not s.state.opponent_flowers_complete["left"]
    assert s.undo()["ok"]
    assert s.state.opponent_flowers_complete["left"]
    assert s.apply("l花未知")["ok"]
    assert not s.state.opponent_flowers_complete["left"]


@pytest.mark.parametrize("discard,claim", [("r 9饼", "l碰 9饼"), ("o 4万", "l吃 3万 4万 5万")])
def test_claim_invalidates_flower_completeness_and_undo_restores(discard, claim):
    s = new_session(BASE)
    assert s.apply(discard)["ok"]
    assert s.apply("l花完整")["ok"]
    assert s.state.opponent_flowers_complete["left"]
    pending_id = s.pending["id"]
    assert s.apply(claim, expected_pending_id=pending_id)["ok"]
    assert not s.state.opponent_flowers_complete["left"]
    assert s.undo()["ok"]
    assert s.state.opponent_flowers_complete["left"]
    assert s.pending["id"] == pending_id


def test_joint_world_conserves_every_unseen_entity_and_seed():
    s = ready()
    s.apply("l花 春")
    s.apply("l花完整")
    state = s.state
    rng = random.Random(42)
    expected = Counter({t:n for t,n in count_remaining_tiles(state).items() if n})
    for _ in range(30):
        world = sample_world(state, rng)
        assigned = Counter(world.wall)
        for player in OPPONENTS:
            assert len(world.hands[player]) == 13 - 3*len(state.melds[player])
            assert all(not t.is_flower for t in world.hands[player])
            assert all(t.is_flower for t in world.flowers[player])
            assigned.update(world.hands[player])
            assigned.update(Counter(world.flowers[player]) - Counter(state.opponent_flowers[player]))
        assert world.flowers["left"] == state.opponent_flowers["left"]
        assert assigned == expected
    assert sample_world(state, random.Random(7)) == sample_world(state, random.Random(7))


def test_insufficient_unseen_tiles_rejected():
    state = GameState()
    state.my_discards = [t for t,n in count_remaining_tiles(state).items() for _ in range(n)]
    with pytest.raises(ValueError, match="不足"):
        sample_world(state, random.Random(0))


def forced_context():
    s = ready()
    groups = [Meld("chi", tiles(text)) for text in (
        "1万 2万 3万", "4万 5万 6万", "7万 8万 9万", "1饼 2饼 3饼")]
    s.state.melds = {p: copy.deepcopy(groups) for p in OPPONENTS}
    s.state.opponent_flowers["left"] = tiles("春")
    s.state.opponent_flowers["right"] = tiles("夏")
    # Every physical copy remains possible, including both 西风 singleton waits.
    count_remaining_tiles(s.state)
    return s.decision_context()


def fixed_world(state, rng):
    return HiddenWorld({"left": tiles("西风"), "right": tiles("西风"),
                        "opposite": tiles("北风")},
                       copy.deepcopy(state.opponent_flowers), [])


def result_for(result, tile):
    return next(c for c in result["candidates"] if c["tile"] == tile)


def test_multi_ron_adds_payments_and_no_flower_cannot_ron(monkeypatch):
    monkeypatch.setattr("src.decision.risk.sample_world", fixed_world)
    context = forced_context()
    result = evaluate_immediate_risk(context, samples=4)
    west = result_for(result, "西风")
    assert west["any_ron_rate"] == west["multi_ron_rate"] == 1
    assert west["expected_immediate_loss"] == 16  # (2 + 小吊车5 + 花1) * 2
    assert west["opponents"]["left"]["mean_payment_if_ron"] == 8
    north = result_for(result, "北风")
    assert north["any_ron_rate"] == 0
    assert north["opponents"]["opposite"]["mean_payment_if_ron"] is None
    assert north["any_ron_interval_95"][1] > 0
    assert not result["calibrated"] and result["scope"] == "immediate_discard_only"


def test_more_flowers_increase_loss_not_forced_wait_probability(monkeypatch):
    monkeypatch.setattr("src.decision.risk.sample_world", fixed_world)
    context = forced_context()
    low = result_for(evaluate_immediate_risk(context, samples=2), "西风")
    context.state.opponent_flowers["left"].extend(tiles("秋 冬"))
    high = result_for(evaluate_immediate_risk(context, samples=2), "西风")
    assert high["any_ron_rate"] == low["any_ron_rate"]
    assert high["expected_immediate_loss"] == low["expected_immediate_loss"] + 2


@pytest.mark.parametrize("samples", [0, -1, 2049, True, "10"])
def test_invalid_sample_counts(samples):
    with pytest.raises(ValueError):
        evaluate_immediate_risk(ready().decision_context(), samples=samples)


def test_wrong_phase_and_impossible_hand_rejected():
    with pytest.raises(ValueError, match="打牌"):
        evaluate_immediate_risk(new_session(BASE).decision_context())
    s = ready()
    s.state.my_hand.pop()
    with pytest.raises(ValueError, match="暗牌张数"):
        evaluate_immediate_risk(s.decision_context())


def test_real_sampling_reproducible_and_does_not_mutate():
    context = ready().decision_context()
    before = copy.deepcopy(context)
    a = evaluate_immediate_risk(context, samples=8)
    b = evaluate_immediate_risk(context, samples=8)
    a.pop("elapsed_ms")
    b.pop("elapsed_ms")
    assert a == b and context == before


def test_web_cache_and_revision_checks(monkeypatch):
    session = ready()
    monkeypatch.setitem(web._GAME, "session", session)
    web._DECISION_CACHE.clear()
    result = web.op_decision(2)
    assert result["ok"] and not result["cached"]
    assert web.op_decision(2)["cached"]
    assert web.op_decision(2, game_id="old")["stale"]
    old_revision = session.revision
    session.apply("打 北风")
    assert web.op_decision(2, revision=old_revision)["stale"]


def test_recording_can_proceed_during_analysis_and_stale_result_is_discarded(monkeypatch):
    import threading
    session = ready()
    monkeypatch.setitem(web._GAME, "session", session)
    web._DECISION_CACHE.clear()
    worker_results = []
    def evaluate(context, **kwargs):
        worker = threading.Thread(target=lambda: worker_results.append(web.op_event("打 北风")))
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive(), "analysis held the recording lock"
        return {"game_id": context.game_id, "revision": context.revision}
    monkeypatch.setattr(web, "evaluate_immediate_risk", evaluate)
    assert web.op_decision(2)["stale"]
    assert worker_results[0]["ok"]
    assert not web._DECISION_CACHE


def test_new_game_cannot_reuse_old_job_even_at_same_revision(monkeypatch):
    monkeypatch.setitem(web._GAME, "session", ready())
    web._DECISION_CACHE.clear()
    def evaluate(context, **kwargs):
        web._GAME["session"] = ready()
        return {}
    monkeypatch.setattr(web, "evaluate_immediate_risk", evaluate)
    assert web.op_decision(2)["stale"]


def test_pending_opponent_response_blocks_discard_evaluation():
    s = ready()
    assert s.apply("l 9饼")["ok"]
    with pytest.raises(ValueError, match="待响应"):
        evaluate_immediate_risk(s.decision_context())


def test_batch_claim_log_is_atomic_and_undoable():
    s = new_session(BASE)
    assert s.apply("r 西风")["ok"]
    pending_id = s.pending["id"]
    assert s.apply_claims(["l胡", "o胡"], expected_pending_id=pending_id)["ok"]
    assert len(s.events) == 2
    assert len(s.events[-1]["actions"]) == 2
    assert set(s.events[-1]["accepted"]) == {"left", "opposite"}
    assert s.events[-1]["pending_id"] == pending_id
    assert s.undo()["ok"]
    assert len(s.events) == 1 and s.pending["id"] == pending_id


def test_busy_job_fails_fast_and_invalid_requests_never_enter_worker(monkeypatch):
    monkeypatch.setitem(web._GAME, "session", ready())
    web._DECISION_CACHE.clear()
    assert web._DECISION_SLOT.acquire(blocking=False)
    try:
        assert "正在计算" in web.op_decision(1)["error"]
    finally:
        web._DECISION_SLOT.release()
    assert not web.op_decision(True)["ok"]
    assert not web.op_decision(2, seed="bad")["ok"]


def test_budget_finishes_whole_samples_and_reports_actual_count(monkeypatch):
    monkeypatch.setattr("src.decision.risk.sample_world", fixed_world)
    ticks = iter([0, 2, 2])  # start, next-sample budget check, elapsed
    monkeypatch.setattr("src.decision.risk.time.monotonic", lambda: next(ticks))
    result = evaluate_immediate_risk(forced_context(), samples=10)
    assert result["samples"] == 1 and result["budget_exhausted"]
    assert result["elapsed_ms"] == 2000
