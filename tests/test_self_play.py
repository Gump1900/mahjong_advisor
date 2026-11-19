import copy
import json
import os
from types import SimpleNamespace

import pytest

from src.players.base import Choice, DecisionError
from src.players.heuristic import HeuristicPlayer
from src.simulation.engine import Table
from src.simulation.experiment import Budget, MeteredClient, ExperimentPlayer, export_oracle_labels, consolidate_completed_campaign, run_hand
from src.simulation.replay import replay


def test_shared_budget_persists_and_failed_request_stays_reserved(tmp_path):
    budget = Budget(tmp_path/"budget.json", "0.7", 3)
    budget.reserve()
    restored = Budget(tmp_path/"budget.json", "0.7", 3)
    restored.reserve()
    with pytest.raises(DecisionError):
        restored.reserve()
    assert restored.summary()["calls"] == 2
    assert restored.summary()["unknown_usage_requests"] == 2
    assert os.stat(tmp_path/"budget.json").st_mode & 0o777 == 0o600


def test_authorized_call_increase_never_changes_money_or_old_requests(tmp_path):
    path=tmp_path/"budget.json"
    budget=Budget(path,"30",1500);budget.reserve()
    before=json.loads(path.read_text());summary_before=budget.summary()
    Budget.increase_authorized_calls(path,1800)
    after=json.loads(path.read_text())
    assert after["max_calls"]==1800 and after["limit_cny"]=="30"
    assert after["requests"]==before["requests"] and after["pricing"]==before["pricing"]
    assert Budget(path,"30",1800).summary()==summary_before
    for invalid in (1800,1500,True,0):
        with pytest.raises(ValueError):
            Budget.increase_authorized_calls(path,invalid)


def test_usage_accounts_for_cache_separately_at_peak_rates(tmp_path):
    budget = Budget(tmp_path/"budget.json", "1", 1)
    index = budget.reserve()
    budget._update(lambda d:d["requests"][index].update(time="2026-10-23T02:00:00+00:00"))
    budget.settle(index, SimpleNamespace(input_tokens=1000, output_tokens=100,
                                        cache_creation_input_tokens=None, cache_read_input_tokens=1000))
    assert budget.summary()["charged_upper_cny"] == "0.00284"
    with pytest.raises(DecisionError):
        budget.reserve()
    with pytest.raises(ValueError):
        Budget(tmp_path/"budget.json", "2", 1)


def test_explicit_budget_increase_preserves_all_existing_reservations(tmp_path):
    path = tmp_path/"budget.json"
    budget = Budget(path, "3", 180)
    budget.reserve()
    before = json.loads(path.read_text())["requests"]
    Budget.increase_authorized_limit(path, "10")
    updated = Budget(path, "10", 180)
    assert updated.summary()["calls"] == 1
    assert json.loads(path.read_text())["requests"] == before
    assert json.loads(path.read_text())["budget_changes"][0]["from"] == "3"
    with pytest.raises(ValueError):
        Budget.increase_authorized_limit(path, "31")


@pytest.mark.parametrize("limit", ["0", "-1", "30.01", "NaN", "Infinity"])
def test_budget_rejects_invalid_limits(tmp_path, limit):
    with pytest.raises(ValueError):
        Budget(tmp_path/"budget.json", limit)


def test_meter_rejects_wrong_model_and_oversized_context_before_network(tmp_path):
    class NoNetwork:
        messages = None
    budget = Budget(tmp_path/"budget.json")
    client = MeteredClient(NoNetwork(), budget)
    with pytest.raises(DecisionError):
        client.create(model="deepseek-v4-pro", max_tokens=100)
    with pytest.raises(DecisionError):
        client.create(model="deepseek-flash", max_tokens=100, system="x"*120001)
    assert budget.summary()["calls"] == 0


def test_meter_records_usage_even_if_answer_is_invalid(tmp_path):
    response = SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    raw = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: response))
    budget = Budget(tmp_path/"budget.json")
    with pytest.raises(AttributeError):
        MeteredClient(raw, budget).create(model="deepseek-flash", max_tokens=1024)
    assert budget.summary()["unknown_usage_requests"] == 0


def test_meter_timeout_consumes_reservation_no_retry(tmp_path):
    calls = []
    def fail(**kwargs):
        calls.append(1)
        raise TimeoutError()
    budget = Budget(tmp_path/"budget.json")
    client = MeteredClient(SimpleNamespace(messages=SimpleNamespace(create=fail)), budget)
    with pytest.raises(TimeoutError):
        client.create(model="deepseek-flash", max_tokens=1024)
    assert len(calls) == 1 and budget.summary()["unknown_usage_requests"] == 1


def test_malformed_model_json_keeps_only_returned_text_for_private_diagnostics(tmp_path):
    response = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text",text="非JSON回答")],
                               usage=SimpleNamespace(input_tokens=10,output_tokens=5))
    budget=Budget(tmp_path/"budget.json")
    client=MeteredClient(SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:response)),budget)
    with pytest.raises(json.JSONDecodeError):
        client.create(model="deepseek-flash",max_tokens=2048)
    assert client.last_answer is None
    assert client.last_model_output == {"stop_reason":"end_turn","text":"非JSON回答"}
    assert budget.summary()["calls"]==1 and budget.summary()["unknown_usage_requests"]==0


def test_four_bot_game_saved_replayable_private_and_not_promoted(tmp_path):
    table = Table(42)
    report = run_hand(table, [HeuristicPlayer() for _ in range(4)], tmp_path/"hand")
    assert report["status"] == "completed"
    assert sum(report["result"]["net"]) == 0
    assert not report["weights_updated"] and not report["knowledge_promoted"]
    restored = replay(json.loads((tmp_path/"hand/referee-private.json").read_text()))
    assert restored.state_hash() == table.state_hash()
    row = json.loads((tmp_path/"hand/decisions.jsonl").read_text().splitlines()[0])
    assert "initial_wall" not in json.dumps(row)
    for p in row["observation"]["players"]:
        assert "hand" not in p
    assert row["observation"]["result"] is None
    labels = [json.loads(line) for line in (tmp_path/"hand/labels-offline-only.jsonl").read_text().splitlines()]
    assert len(labels) == report["audit"]["decisions"]
    assert all(len(label["targets"]) == 3 for label in labels)
    assert len({label["wall_family"] for label in labels}) == 1
    assert all("targets" not in json.loads(line) for line in (tmp_path/"hand/decisions.jsonl").read_text().splitlines())


def test_failure_saves_without_applying_partial_response_window(tmp_path):
    class Fail:
        def choose(self, obs):
            raise DecisionError("test failure")
    table = Table(42)
    before = table.state_hash()
    report = run_hand(table, [Fail() for _ in range(4)], tmp_path/"paused")
    assert report["status"] == "paused"
    assert table.state_hash() == before
    assert (tmp_path/"paused/referee-private.json").exists()
    assert not (tmp_path/"paused/labels-offline-only.jsonl").exists()
    with pytest.raises(ValueError):
        export_oracle_labels(table, tmp_path/"paused/decisions.jsonl", tmp_path/"should-not-exist")


def test_mutating_player_cannot_modify_recorded_observation(tmp_path):
    class Mutating:
        def choose(self, obs):
            choice = HeuristicPlayer().choose(obs)
            obs["self"]["hand"].clear()
            return choice
    run_hand(Table(42), [Mutating() for _ in range(4)], tmp_path/"mutate", max_decisions=1)
    row = json.loads((tmp_path/"mutate/decisions.jsonl").read_text().splitlines()[0])
    assert len(row["observation"]["self"]["hand"]) == 14


def test_model_batch_validated_before_apply(tmp_path):
    from src.simulation.observation import observe
    obs = observe(Table(42), 0)
    flower = next(a for a in obs["legal_actions"] if a["kind"] == "flower_kong")
    batch = [a["tiles"][0] for a in obs["legal_actions"] if a["kind"] == "flower_kong"]
    class Fake:
        client = SimpleNamespace(last_answer={"flower_batch": batch})
        def choose(self, snapshot):
            return Choice(flower["id"], "llm", "一次换多张")
    player = ExperimentPlayer(Fake())
    assert player.choose(obs).action_id == flower["id"]
    assert player.select_flowers(obs) == batch
    Fake.client.last_answer = {"flower_batch": ["春"]*8}
    with pytest.raises(DecisionError):
        player.choose(obs)


def test_same_wall_rotations_share_split_and_label_alignment_is_verified(tmp_path):
    families = []
    for i in range(2):
        table = Table(43)
        run_hand(table, [HeuristicPlayer() for _ in range(4)], tmp_path/str(i))
        first = json.loads((tmp_path/str(i)/"labels-offline-only.jsonl").read_text().splitlines()[0])
        families.append((first["wall_family"], first["split"]))
    assert families[0] == families[1]
    path = tmp_path/"bad.jsonl"
    row = json.loads((tmp_path/"1/decisions.jsonl").read_text().splitlines()[0])
    row["observation"]["self"]["hand"] = []
    path.write_text(json.dumps(row)+"\n")
    with pytest.raises(ValueError, match="不一致"):
        export_oracle_labels(table, path, tmp_path/"bad-labels.jsonl")


def test_consolidation_excludes_uncommitted_response_proposals(tmp_path):
    table = Table(42)
    report = run_hand(table, [HeuristicPlayer() for _ in range(4)], tmp_path/"hand-001")
    stale = tmp_path/"hand-stale"
    stale.mkdir()
    (stale/"decisions.jsonl").write_text(json.dumps({"choice": {"action_id": "never-committed"}})+"\n")
    audit = consolidate_completed_campaign(tmp_path)
    assert audit["decisions"] == report["audit"]["decisions"]
    assert "never-committed" not in (tmp_path/"completed-decisions.jsonl").read_text()
