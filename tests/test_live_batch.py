"""Accounting migration and batch execution without real API calls."""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.simulation.experiment import Budget
from src.players.heuristic import HeuristicPlayer
from scripts.live_batch import run_batch


@pytest.mark.parametrize("stamp,off_peak",[("2026-10-24T02:00:00+00:00",True),
    ("2026-10-23T02:00:00+00:00",False),("2026-10-23T04:00:00+00:00",True),
    ("2026-10-23T06:00:00+00:00",False),("2026-10-23T10:00:00+00:00",True)])
def test_beijing_tariff_schedule(stamp,off_peak):
    assert Budget.off_peak_at(stamp)==off_peak


def test_migration_preserves_money_limit_unknown_reservations_and_audit(tmp_path):
    path=tmp_path/"budget.json"
    old={"limit_cny":"10","max_calls":180,"pricing":"legacy",
         "requests":[{"status":"usage_recorded","charged_upper_cny":".006","usage":{
             "input_tokens":1000,"cache_read_input_tokens":1000,"cache_creation_input_tokens":0,"output_tokens":100}},
             {"status":"reserved","charged_upper_cny":".34816"}]}
    path.write_text(json.dumps(old))
    result=Budget.migrate_cache_pricing(path,1500);new=json.loads(path.read_text())
    assert result["limit_cny"]=="10" and result["calls"]==2
    assert new["requests"][0]["legacy_charged_upper_cny"]==".006"
    assert new["requests"][0]["charged_upper_cny"]=="0.00284"
    assert new["requests"][1]==old["requests"][1]
    assert len(new["accounting_changes"])==1
    again=Budget.migrate_cache_pricing(path,1500)
    assert again["upper_cny"]==result["upper_cny"]
    with pytest.raises(ValueError):Budget.migrate_cache_pricing(path,1)


def test_batch_retains_one_player_set_per_hand_and_completes_isolated_games(tmp_path):
    budget=Budget(tmp_path/"budget.json","10",1500);made=[]
    def players():
        made.append(1);return [HeuristicPlayer() for _ in range(4)]
    result=run_batch(hands=2,seed=42,root=tmp_path/"batch",budget=budget,make_players=players,balance=lambda:Decimal("16.5"))
    assert result["completed"]==2 and len(made)==2
    assert len({r["game_id"] for r in result["hands"]})==2
    assert result["budget"]["calls"]==0


def test_batch_does_not_retry_budget_failure_or_reset_ledger(tmp_path,monkeypatch):
    from scripts import live_batch
    budget=Budget(tmp_path/"budget.json","10",1500);attempts=[]
    def fail(table,players,directory,**kw):
        attempts.append(1)
        return {"status":"paused","error":"实验共享预算／调用上限触发","stage":table.stage,"result":None}
    monkeypatch.setattr(live_batch,"run_hand",fail)
    result=run_batch(hands=10,seed=42,root=tmp_path/"batch",budget=budget,
                     make_players=lambda:[HeuristicPlayer() for _ in range(4)],balance=lambda:Decimal("16"))
    assert result["completed"]==0 and len(attempts)==1
    assert result["stop"] and result["budget"]["limit_cny"]=="10"


def test_paid_lab_defaults_to_one_attempt_not_paid_protocol_repair(tmp_path,monkeypatch):
    from scripts import live_batch
    budget=Budget(tmp_path/"budget.json","10",1500);calls=[]
    bot=SimpleNamespace(last_rejection={"observation":{"observation_id":"game:turn:0"},"answer":{"action_id":"A1"}})
    def fail(table,players,directory,**kw):
        calls.append(1)
        players[0].last_rejection=bot.last_rejection
        return {"status":"paused","error":"结构化策略不合法","stage":table.stage,"result":None}
    monkeypatch.setattr(live_batch,"run_hand",fail)
    result=run_batch(hands=5,seed=42,root=tmp_path/"batch",budget=budget,
        make_players=lambda:[SimpleNamespace(last_rejection=None) for _ in range(4)],balance=lambda:Decimal("16"))
    assert len(calls)==1 and result["completed"]==0 and result["stop"]
    assert json.loads((tmp_path/"batch/manifest.json").read_text())["max_recoveries_per_invocation"]==0


def test_resume_restores_only_structured_memory_with_public_fingerprints(tmp_path):
    from scripts.live_batch import restore_notes
    from src.players.deliberation import Deliberation
    from src.players.llm import LLMPlayer
    from src.simulation.engine import Table
    from src.simulation.observation import observe
    from tests.test_simulation import checked_answer,fake_client
    table=Table(42);obs=observe(table,0);a=obs["legal_actions"][0]
    note=Deliberation(obs).evaluate(checked_answer(obs,a["id"]))["decision_note"]
    table.apply(0,a["id"],controller="test")
    folder=tmp_path/"game"/"hand-001";folder.mkdir(parents=True)
    row={"observation":obs,"choice":{"action_id":a["id"]},"decision_validation":{"decision_note":note}}
    (folder/"decisions.jsonl").write_text(json.dumps(row)+"\n")
    players=[]
    for _ in range(4):
        client,_=fake_client([])
        players.append(SimpleNamespace(player=LLMPlayer(decision_protocol="legacy-v2", client=client,model="fake")))
    restore_notes(folder.parent,table,players)
    saved=players[0].player.notebooks[(table.game_id,0)]["note"]
    assert all(p["public_fingerprint"] for p in saved["opponents"])
    assert "plan" not in saved
    assert len(Deliberation(obs,saved).payload["notebook"]["opponents"])==3


def test_resume_keeps_finished_game_and_replays_paused_game(tmp_path):
    from src.players.base import DecisionError
    class Broken:
        def choose(self,obs):
            raise DecisionError("test pause")
    made=[]
    def players():
        made.append(1)
        return [HeuristicPlayer() if len(made)==1 else Broken() for _ in range(4)]
    budget=Budget(tmp_path/"budget.json","10",1500);root=tmp_path/"batch"
    first=run_batch(hands=2,seed=42,root=root,budget=budget,make_players=players,balance=lambda:Decimal("16"))
    assert first["completed"]==1 and first["hands"][1]["status"]=="paused"
    identities=[r["game_id"] for r in first["hands"]]
    second=run_batch(hands=2,seed=42,root=root,budget=budget,make_players=lambda:[HeuristicPlayer() for _ in range(4)],
                     balance=lambda:Decimal("16"),resume=True)
    assert second["completed"]==2
    assert [r["game_id"] for r in second["hands"]]==identities
    assert (root/"summary.json").is_file() and list(root.glob("summary-resume-*.json"))


def test_account_guard_reuses_only_recent_balance_and_reserves_intervening_costs(tmp_path):
    from scripts.live_batch import AccountFloorGuard
    from src.players.base import DecisionError
    budget=Budget(tmp_path/"budget.json","10",1500);now=[0];balances=iter([Decimal("3"),Decimal("2")]);calls=[]
    def balance():calls.append(1);return next(balances)
    guard=AccountFloorGuard(budget,balance=balance,clock=lambda:now[0]);guard()
    budget.reserve();guard();assert len(calls)==1
    now[0]=31
    with pytest.raises(DecisionError,match="保留余额"):guard()
    assert len(calls)==2


def test_balance_outage_after_hand_still_saves_progress_and_can_resume(tmp_path):
    budget=Budget(tmp_path/"budget.json","10",1500);root=tmp_path/"batch";calls=[]
    def broken_balance():
        calls.append(1)
        if len(calls)>1:raise ValueError("network")
        return Decimal("16")
    result=run_batch(hands=2,seed=42,root=root,budget=budget,make_players=lambda:[HeuristicPlayer() for _ in range(4)],balance=broken_balance)
    assert result["completed"]==1 and result["balance_after_cny"] is None
    assert list(root.glob("progress-01-*.json")) and (root/"summary.json").is_file()
    resumed=run_batch(hands=2,seed=42,root=root,budget=budget,make_players=lambda:[HeuristicPlayer() for _ in range(4)],balance=lambda:Decimal("16"),resume=True)
    assert resumed["completed"]==2
