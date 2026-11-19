import copy
import json
import threading
import time
from types import SimpleNamespace

import pytest

from src.players.base import Choice, DecisionError
from src.players.heuristic import HeuristicPlayer
from src.players.llm import LLMPlayer
from src.simulation.coaching import LLMCoach, historical_review, teaching_report
from src.simulation.engine import Table
from src.simulation.observation import observe
from src.simulation.web import DesktopTable
from tests.test_simulation import fake_client


def wait_until(predicate):
    deadline = time.monotonic()+3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(.01)


def test_code_coach_uses_visible_evidence_and_never_calls_model():
    obs = observe(Table(42), 0)
    p = obs["players"][1]
    p["melds"] = [{"type": "chi", "size": 3, "hidden": False, "tiles": ["1万", "2万", "3万"]}]
    report = teaching_report(obs)
    opponent = next(p for p in report["opponents"] if p["seat"] == 1)
    assert opponent["suit_hint"] == "万"
    assert any("不能做碰碰胡" in s for s in opponent["exclusions"])
    assert isinstance(opponent["known_hua"], int)
    assert report["recommended_action"]["id"] in {a["id"] for a in obs["legal_actions"]}
    assert "initial_wall" not in json.dumps(report)
    assert any("不是" in s for s in report["limitations"])


def test_lock_removes_ron_pressure_but_not_self_draw_warning():
    obs = observe(Table(42), 0)
    p = obs["players"][1]
    p["locked_with"] = [0]
    report = teaching_report(obs)
    assert next(p for p in report["opponents"] if p["seat"] == 1)["cannot_ron"]
    assert any("自摸" in s for s in report["opponents"][0]["evidence"])


def test_background_model_does_not_hold_table_lock_or_apply_action(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Slow:
        def choose(self, obs):
            entered.set()
            assert release.wait(3)
            return Choice(obs["legal_actions"][0]["id"], "test")
    d = DesktopTable(Table(42, dealer=1), output_dir=tmp_path,
                     bots={s: Slow() for s in (1, 2, 3)}, paced=True, background=True)
    assert entered.wait(2)
    started = time.monotonic()
    v = d.view()
    assert time.monotonic()-started < .5
    assert v["bot_thinking"] and not v["can_advance"]
    assert not d.table.decisions
    release.set()
    wait_until(lambda: not d.view()["bot_thinking"])
    assert d.view()["can_advance"] and not d.table.decisions


def test_late_bot_reply_cannot_overwrite_new_game(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Slow:
        def choose(self, obs):
            entered.set(); release.wait(3)
            return Choice(obs["legal_actions"][0]["id"], "old")
    d = DesktopTable(Table(42, dealer=1), output_dir=tmp_path,
                     bots={s: Slow() for s in (1, 2, 3)}, paced=True, background=True)
    assert entered.wait(2)
    d.new_game(d.version, seed=43, dealer=0)
    version = d.version
    wait_until(lambda: not d.thinking)
    release.set()
    time.sleep(.05)
    assert d.version == version and d.view()["awaiting_human"]
    assert not d.table.decisions


def test_discard_animation_response_does_not_wait_for_next_model(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Slow:
        def choose(self, obs):
            entered.set(); release.wait(3)
            return Choice(obs["legal_actions"][0]["id"], "test")
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True, background=True,
                     bots={s: Slow() for s in (1, 2, 3)})
    wait_until(lambda: not d.thinking)
    view = d.view()
    action = next(a for a in view["legal_actions"] if a["kind"] == "discard")
    started = time.monotonic()
    result = d.action(view["version"], action["id"])
    assert time.monotonic()-started < .5
    assert any(f["presentation"]["kind"] == "discard" for f in result["frames"])
    release.set()
    wait_until(lambda: not d.thinking)


def test_opening_llm_flowers_are_not_chosen_without_model(tmp_path):
    class NoAPI:
        class Messages:
            def create(self, **kwargs):
                raise TimeoutError("test unavailable")
        messages = Messages()
    bot = LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=NoAPI())
    d = DesktopTable(Table(42, dealer=1), output_dir=tmp_path, paced=True,
                     bots={s: bot for s in (1, 2, 3)})
    assert not d.batch
    flowers = bot.select_flowers(observe(d.table, 1))
    assert flowers == [] and bot.calls == 1
    assert not d.table.seats[1].flowers


def test_deepseek_timeout_is_not_retried():
    client, calls = fake_client([TimeoutError("do not expose me")])
    bot = LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client)
    with pytest.raises(DecisionError, match="TimeoutError"):
        bot.choose(observe(Table(42), 0))
    assert len(calls) == 1 and bot.calls == 1


def test_coach_accepts_fenced_json_and_only_receives_supplied_report():
    obs=observe(Table(42),0);candidate=next(c for c in teaching_report(obs)["candidates"] if c["kind"]=="discard")
    review={"seat":0,"decisions":[{"step":1,"actual":{"kind":"discard","tiles":candidate["tiles"]},
        "hand_then":obs["self"]["hand"],"public_then":obs["players"],"legal_candidates":[candidate]}]}
    answer={"strategy_version":"strategy-v2","review_points":[{"step":1,"alternative_action_id":candidate["action_id"],
        "alternative_next_discard":None,"intent":"balance","focus_seats":[]}]}
    client, calls = fake_client(["```json\n"+json.dumps(answer)+"\n```"])
    player = LLMPlayer(decision_protocol="legacy-v2", provider="deepseek", client=client)
    result = LLMCoach(player).explain({"review":review,"coaching_memory":[{"summary":"未验证旧文字"}]})
    assert result["verification_version"] == "strategy-v2"
    assert calls[0]["extra_body"]["thinking"] == {"type": "disabled"}
    assert "initial_wall" not in calls[0]["messages"][0]["content"]
    assert "未验证旧文字" not in calls[0]["messages"][0]["content"]


def test_coach_job_is_async_cached_and_does_not_reset_own_choice(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True)
    entered, release = threading.Event(), threading.Event()
    class Coach:
        def explain(self, payload):
            assert "observation" in payload and "initial_wall" not in json.dumps(payload)
            entered.set(); release.wait(3)
            return {"summary": "解释", "explanation": "代码进张不是牌墙活张"}
    d.coach = Coach()
    before = d.table.state_hash()
    result = d.request_coach(d.version)
    assert entered.wait(2) and result["coach_job"]["status"] == "thinking"
    with pytest.raises(ValueError, match="进行中"):
        d.request_coach(d.version)
    release.set()
    wait_until(lambda: d.view()["coach_job"]["status"] == "ready")
    d.request_coach(d.version)
    assert d.coach_calls == 1 and d.table.state_hash() == before


def test_historical_review_reconstructs_predecision_views_not_end_hands(monkeypatch, tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path)
    bot = HeuristicPlayer()
    for _ in range(500):
        v = d.view()
        if v["stage"] == "ended":
            break
        d.action(v["version"], bot.choose(v).action_id)
    assert d.table.stage == "ended"
    from src.simulation import coaching
    original = coaching.teaching_report
    seen = []
    def spy(obs):
        seen.append(copy.deepcopy(obs))
        assert obs["result"] is None
        assert "revealed_hands" not in obs and "initial_wall" not in obs
        assert all(m["tiles"] is None for p in obs["players"] if p["seat"] != 0 for m in p["melds"] if m["hidden"])
        return original(obs)
    monkeypatch.setattr(coaching, "teaching_report", spy)
    before = d.table.state_hash()
    review = historical_review(d.table, 0)
    assert review["decision_count"] == len(seen) > 0
    assert review["decisions"][0]["hand_then"] == observe(Table(42), 0)["self"]["hand"]
    assert d.table.state_hash() == before


def test_revealed_side_slots_clear_overlap_and_keep_seat_orientation():
    from src.simulation.web import ASSETS
    css = (ASSETS / "board-layout.css").read_text()
    assert '.table .seat-surface .concealed .table-tile { margin:0; }' in css
    assert '.table .left .seat-surface' in css
    assert '.table .right .seat-surface' in css
    assert 'transform:none; object-fit:fill' in css  # Faces inherit the surface rotation.
