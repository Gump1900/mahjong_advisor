import threading
import time

import pytest

from src.simulation.engine import Table
from src.simulation.observation import observe
from src.simulation.web import DesktopTable
from tests.test_coaching import wait_until
from tests.test_simulation import BASE, act, passes, scenario


def test_resident_coach_starts_on_transition_not_get_and_respects_budget(tmp_path):
    calls = []
    class Coach:
        def explain(self, payload):
            calls.append(payload)
            return {"summary": "先留住两面搭子", "explanation": "上家两副露，先别拆现成搭子。"}
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True, coach_limit=1)
    d.coach = Coach()
    d.coach_settings(d.version, True, 1)
    wait_until(lambda: d.coach_job["status"] == "ready")
    for _ in range(10):
        d.view(); d._maybe_auto_coach()
    assert len(calls) == 1 and d.coach_calls == 1
    assert d.view()["coach_calls_remaining"] == 0
    assert d.coach_feed[0]["result"]["summary"] == "先留住两面搭子"
    d.coach_settings(d.version, False)
    assert not d.view()["coach_auto"]


def test_disabled_and_resumed_resident_never_launches_api_from_get(tmp_path):
    class Coach:
        def explain(self, payload):
            raise AssertionError("resume/GET must not bill")
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True, auto_coach=True, defer_bots=True)
    d.coach = Coach()
    for _ in range(10):
        assert d.view()["coach_suspended"]
    d._maybe_auto_coach()
    assert d.coach_calls == 0


def test_old_coach_reply_is_labelled_history_and_new_turn_is_analyzed(tmp_path):
    started, release = threading.Event(), threading.Event()
    calls = []
    class Coach:
        def explain(self, payload):
            calls.append(payload)
            if len(calls) == 1:
                started.set();release.wait(3)
            return {"summary": "留搭子，先打孤张", "explanation": "不能确定别人暗牌。"}
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True)
    d.coach = Coach()
    d.coach_settings(d.version, True, 3)
    assert started.wait(2)
    old = d.version
    view = d.view()
    flower = next(a for a in view["legal_actions"] if a["kind"] == "flower_kong")
    d.action(view["version"], flower["id"])
    assert d.version != old
    release.set()
    wait_until(lambda: len(calls) == 2 and d.coach_job["status"] == "ready")
    assert len(d.coach_feed) == 2 and d.coach_feed[0]["version"] == old
    assert d.coach_job["version"] == d.version
    assert calls[1]["coaching_memory"][0]["version"] == old


def test_coach_budget_settings_validate_before_mutation(tmp_path):
    d = DesktopTable(Table(42), output_dir=tmp_path)
    for bad in [0, 51, True, 2.5]:
        with pytest.raises(ValueError):
            d.coach_settings(d.version, False, bad)
    assert d.coach_limit == 20


def test_public_peng_source_and_number_survive_upgrade():
    t = scenario({0: BASE+" 4万", 1: "4万 4万 6条 7条 8条 西风 西风"},
                 melds={1: [("peng", "1饼 1饼 1饼"), ("peng", "2饼 2饼 2饼")]})
    t.call_counts[1][0] = 1
    act(t, 0, "discard", "4万")
    act(t, 1, "peng")
    passes(t)
    meld = observe(t, 0)["players"][1]["melds"][-1]
    assert meld["source"] == 0
    # Event count, not the artificial fixture's preloaded counter, is the
    # reconstructible ordinal. Real replays have all preceding claim events.
    assert meld["call_number"] == 1
    original_hash = t.state_hash()
    observe(t, 2)
    assert t.state_hash() == original_hash


def test_claim_provenance_is_per_direction_and_ankan_has_no_source():
    t = Table(42)
    # Public helper derives from resolved events, never from matching a river
    # tile name (which can appear repeatedly).
    from src.core.tiles import Meld, parse_tile
    t.seats[1].melds = [Meld("peng", [parse_tile("4万")]*3), Meld("an_gang", [parse_tile("5万")]*4)]
    t.events = [{"kind": "peng", "seat": 1, "source": 0, "tiles": ["4万"]*3},
                {"kind": "an_gang", "seat": 1, "tile": "5万"},
                {"kind": "add_gang", "seat": 1, "tile": "4万"}]
    # Use observe's redaction with scoring only; hand consistency is not needed
    # for this synthetic display-provenance fixture.
    obs = observe(t, 0)
    assert obs["players"][1]["melds"][0]["source"] == 0
    hidden = obs["players"][1]["melds"][1]
    assert "source" not in hidden and hidden["tiles"] is None


def test_real_added_kong_keeps_original_peng_source_and_mouth_number():
    t = scenario({1: "4万 6条 7条 南风 春"}, actor=1,
                 melds={1: [("peng", "4万 4万 4万"), ("peng", "1饼 1饼 1饼"), ("peng", "2饼 2饼 2饼")]})
    t.events = [{"kind":"peng","seat":1,"source":2,"tiles":["4万"]*3},
                {"kind":"peng","seat":1,"source":0,"tiles":["1饼"]*3},
                {"kind":"peng","seat":1,"source":2,"tiles":["2饼"]*3}]
    t.call_counts[1][2] = 2
    act(t, 1, "add_gang", "4万")
    shown = observe(t, 0)["players"][1]["melds"]
    assert shown[0]["source"] == 2 and shown[0]["call_number"] == 1 and shown[0]["size"] == 4
    assert shown[2]["source"] == 2 and shown[2]["call_number"] == 2
    assert t.call_counts[1][2] == 2


def test_coach_can_disagree_with_baseline_but_cannot_suggest_illegal_action():
    import json
    from src.players.llm import LLMPlayer
    from src.players.base import DecisionError
    from src.simulation.coaching import LLMCoach, teaching_report
    from tests.test_simulation import fake_client, checked_answer
    obs = observe(Table(42), 0)
    report = teaching_report(obs)
    other = next(a for a in obs["legal_actions"] if a["id"] != report["recommended_action"]["id"])
    client, calls = fake_client([json.dumps(checked_answer(obs, other["id"], summary="先保留这组搭子", explanation="现在不急着拆，先看下家下一张打什么。"))])
    answer = LLMCoach(LLMPlayer(decision_protocol="legacy-v2", provider="deepseek",client=client)).explain({"observation":obs,"code_report":report})
    assert answer["action_id"] == other["id"]
    assert "不是代码结果复读机" in calls[0]["system"]
    client, _ = fake_client([json.dumps({"summary":"非法", "explanation":"非法", "action_id":"not-legal"})])
    with pytest.raises(DecisionError):
        LLMCoach(LLMPlayer(decision_protocol="legacy-v2", provider="deepseek",client=client)).explain({"observation":obs,"code_report":report})
