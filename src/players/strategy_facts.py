"""Checkable local shape and flower-option facts, not a strategy oracle."""
from collections import Counter
from itertools import combinations

from ..core.scoring import FLOWER_KONG_HUA, flower_hua
from ..core.tiles import parse_tile


def pair_completions(values):
    a, b = sorted(values)
    if b-a == 2:
        return {a+1}
    if b-a == 1:
        return {v for v in (a-1, b+1) if 1 <= v <= 9}
    return set()


def strategy_facts(obs):
    hand = Counter(parse_tile(t) for t in obs["self"]["hand"])
    shapes = []
    for suit in ("万", "饼", "条"):
        values = {int(t.value) for t, n in hand.items() if t.suit == suit and n == 1}
        for triple in combinations(sorted(values), 3):
            if triple[2]-triple[0] == 2:
                continue  # Already a complete sequence, not this local claim.
            waits = set().union(*(pair_completions(pair) for pair in combinations(triple, 2)))
            if not waits or any(hand[parse_tile(f"{v}{suit}")] for v in waits):
                continue  # Do not label a shape containing its completion as an isolated wait.
            options = []
            for discard in triple:
                retained = tuple(v for v in triple if v != discard)
                after = pair_completions(retained)
                if after == waits:
                    options.append({"discard": f"{discard}{suit}", "retained": [f"{v}{suit}" for v in retained],
                                    "preserved_local_completions": [f"{v}{suit}" for v in sorted(after)]})
            if options:
                shapes.append({"tiles": [f"{v}{suit}" for v in triple], "options_preserving_all_local_waits": options,
                               "scope": "仅局部三张顺子搭子；不能代替整手向听、进张、对子、打点与防守比较"})

    visible = Counter(hand)
    for p in obs["players"]:
        visible.update(parse_tile(t) for t in p["river"]+p["flowers"])
        for meld in p["melds"]:
            visible.update(parse_tile(t) for t in (meld["tiles"] or []))
    legal_flowers = {a["tiles"][0] for a in obs["legal_actions"] if a["kind"] == "flower_kong"}
    flowers = []
    for tile, count in sorted(hand.items(), key=lambda x: str(x[0])):
        if str(tile) not in ("东风", "中", "发", "白") or count != 3:
            continue
        singles = flower_hua(konged_flowers=[tile]*4, flower_kong_groups=[[tile]]*4)
        unseen = max(0, 4-visible[tile])
        flowers.append({"tile": str(tile), "held_count": 3,
                        "possible_intent": "等第四张同花，四张一起暗杠，不应把留牌说成毫无目的",
                        "occupied_hand_slots": 3,
                        "immediate_replacements_available": min(3, obs["wall_count"]) if str(tile) in legal_flowers else 0,
                        "fourth_copy_unseen_upper_bound": unseen,
                        "can_still_complete_from_unseen": unseen > 0,
                        "four_singles_hua": singles, "four_concealed_kong_hua": FLOWER_KONG_HUA,
                        "incremental_hua_if_four_completed": FLOWER_KONG_HUA-singles,
                        "four_singles_replacements": 4, "four_concealed_kong_replacements": 1,
                        "concealed_kong_completed_melds": 1,
                        "cost_note": "三张花持续占位，可在合法时机换三张新牌；不能算成每过一圈又少摸三张。第四张未见不等于在牌墙。",
                        "comparison_note": "先比较等四暗杠的额外花分和成一组的价值，再比较立即换牌的速度、结构发展和别人先胡的风险；不能只看12分或只看多6分。"})
    return {"local_shape_checks": shapes, "three_identical_flower_options": flowers}
