import pytest

from src.players.analysis import analyze_actions
from src.players.strategy_facts import strategy_facts
from src.simulation.coaching import teaching_report
from src.simulation.observation import observe
from tests.test_simulation import scenario


BASE = "1万 2万 3万 4万 5万 6万 1条 2条 3条 南风 南风"


@pytest.mark.parametrize("shape,discard,retained,waits", [
    ("6饼 8饼 9饼", "9饼", ["6饼", "8饼"], ["7饼"]),
    ("1饼 2饼 4饼", "1饼", ["2饼", "4饼"], ["3饼"]),
    ("4饼 6饼 7饼", "4饼", ["6饼", "7饼"], ["5饼", "8饼"]),
])
def test_redundant_waits_are_not_counted_twice(shape, discard, retained, waits):
    obs = observe(scenario({0: BASE+" "+shape}), 0)
    checked = strategy_facts(obs)["local_shape_checks"]
    group = next(s for s in checked if set(s["tiles"]) == set(shape.split()))
    option = next(c for c in group["options_preserving_all_local_waits"] if c["discard"] == discard)
    assert option["retained"] == retained and option["preserved_local_completions"] == waits


def test_689_discard9_retains_7_in_full_hand_not_just_a_prompt_assertion():
    obs = observe(scenario({0: BASE+" 6饼 8饼 9饼"}), 0)
    facts = analyze_actions(obs)
    actions = {a["tiles"][0]: a["id"] for a in obs["legal_actions"] if a["kind"] == "discard"}
    by_id = {c["action_id"]: c for c in facts["candidates"]}
    actual = by_id[actions["9饼"]]
    alternative = by_id[actions["1万"]]
    assert actual["shanten"] == 0 and actual["improving_tiles"] == ["7饼"]
    assert alternative["shanten"] > actual["shanten"]
    assert teaching_report(obs)["strategy_facts"] == facts["strategy_facts"]


def test_three_east_options_include_intent_bonus_meld_and_slot_cost():
    hand = "1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 南风 西风 东风 东风 东风"
    obs = observe(scenario({0: hand}), 0)
    flower = strategy_facts(obs)["three_identical_flower_options"][0]
    assert flower["tile"] == "东风" and flower["occupied_hand_slots"] == 3
    assert flower["immediate_replacements_available"] == 3
    assert flower["four_singles_hua"] == 6 and flower["four_concealed_kong_hua"] == 12
    assert flower["incremental_hua_if_four_completed"] == 6
    assert flower["concealed_kong_completed_melds"] == 1
    assert flower["four_singles_replacements"] == 4 and flower["four_concealed_kong_replacements"] == 1
    assert flower["fourth_copy_unseen_upper_bound"] == 1


def test_public_fourth_east_rules_out_waiting_but_hidden_copy_does_not_leak():
    hand = "1万 2万 3万 4饼 5饼 6饼 7条 8条 9条 南风 西风 东风 东风 东风"
    public = strategy_facts(observe(scenario({0: hand}, flowers={1: "东风"}), 0))["three_identical_flower_options"][0]
    hidden = strategy_facts(observe(scenario({0: hand, 1: "东风"}), 0))["three_identical_flower_options"][0]
    assert public["fourth_copy_unseen_upper_bound"] == 0 and not public["can_still_complete_from_unseen"]
    assert hidden["fourth_copy_unseen_upper_bound"] == 1 and hidden["can_still_complete_from_unseen"]


def test_review_does_not_drop_early_flower_intent_when_many_later_differences(tmp_path):
    from src.simulation.engine import Table
    from src.simulation.web import DesktopTable
    from tests.test_coaching import wait_until
    d = DesktopTable(Table(42), output_dir=tmp_path, paced=True)
    decisions = [{"step": i, "different": True, "actual": {"kind":"discard","tiles":["9饼"]},
                  "strategy_facts": {"three_identical_flower_options":[{"tile":"东风"}]} if i == 1 else {}}
                 for i in range(1, 21)]
    # Isolate the request selection logic from the separately-tested replay.
    d.table.stage = "ended"
    d.view = lambda: {"review":{"decisions":decisions}}
    captured = []
    class Coach:
        def explain(self, payload):
            captured.append(payload)
            return {"summary":"先理解等第四张的意图", "explanation":"再比较花分、成组与占位。"}
    d.coach = Coach()
    d.request_coach(d.version, "review")
    wait_until(lambda: d.coach_job["status"] == "ready")
    selected = captured[0]["review"]["decisions"]
    assert len(selected) == 8 and selected[0]["step"] == 1 and selected[-1]["step"] == 20
