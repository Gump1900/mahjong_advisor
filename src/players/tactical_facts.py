"""Exact local opportunities and exclusions, never an opponent-hand oracle."""
from collections import Counter
from functools import lru_cache

from ..core.hand_analyzer import get_waiting_tiles
from ..core.scoring import score_hand
from ..core.tiles import Meld, parse_tile, tile_sort_key


@lru_cache(maxsize=4096)
def _groups(tiles):
    """All complete set decompositions; unlike display shapes, no beam cutoff."""
    if not tiles:
        return ((),)
    counts = Counter(tiles)
    first = tiles[0]
    choices = []
    if counts[first] >= 3:
        choices.append((first,)*3)
    tile = parse_tile(first)
    if tile.suit in ("万", "饼", "条") and tile.value <= 7:
        sequence = tuple(f"{tile.value+i}{tile.suit}" for i in range(3))
        if all(counts[t] for t in sequence):
            choices.append(sequence)
    result = []
    for group in choices:
        rest = list(tiles)
        for t in group:
            rest.remove(t)
        result.extend((group,)+suffix for suffix in _groups(tuple(rest)))
    return tuple(result)


def wait_shapes(hand, meld_count=0):
    """Classify every possible use of the winning tile, not number of waits.

    Multiple interpretations may coexist. Seven pairs is reported separately;
    four equal tiles count as two pairs under Taihu rules.
    """
    if any(t.is_flower for t in hand) or len(hand) != 13-3*meld_count:
        return []
    own = Counter(str(t) for t in hand)
    result = []
    for tile in sorted(get_waiting_tiles(hand, meld_count), key=tile_sort_key):
        name = str(tile)
        if own[name] >= 4:
            continue
        full = own.copy()
        full[name] += 1
        forms = set()
        if not meld_count and all(n % 2 == 0 for n in full.values()):
            forms.add("七对待牌")
        for pair, count in full.items():
            if count < 2:
                continue
            rest = full.copy()
            rest[pair] -= 2
            tiles = tuple(sorted(rest.elements(), key=lambda t: tile_sort_key(parse_tile(t))))
            for groups in _groups(tiles):
                if len(groups) != 4-meld_count:
                    continue
                if pair == name:
                    forms.add("单吊")
                for group in groups:
                    if name not in group:
                        continue
                    if group[0] == group[1]:
                        forms.add("刻子待牌")
                    elif group[1] == name:
                        forms.add("坎张")
                    elif (parse_tile(group[0]).value == 1 and group[2] == name) or (
                            parse_tile(group[2]).value == 9 and group[0] == name):
                        forms.add("边张")
                    else:
                        forms.add("两面")
        result.append({"tile": name, "forms": sorted(forms),
                       "own_copies": own[name],
                       "opponent_ankan_excluded_by_own_copy": own[name] > 0})
    return result


def opponent_constraints(obs):
    reports = []
    for p in obs["players"]:
        if p["seat"] == obs["seat"]:
            continue
        public = [parse_tile(t) for m in p["melds"] for t in (m["tiles"] or [])]
        suits = {t.suit for t in public if not t.is_flower}
        excluded = []
        if p["melds"]:
            excluded.extend(["七对", "豪华七对", "双豪华", "三豪华"])
        if any(m["type"] == "chi" for m in p["melds"]):
            excluded.extend(["碰碰胡", "大吊车"])
        elif len(p["melds"]) == 4:
            excluded.append("小吊车")
        if len(suits) > 1 or "风" in suits:
            excluded.append("清一色")
        reports.append({"seat": p["seat"], "excluded_patterns": excluded,
                        "publicly_cannot_ron": bool(p["locked_with"]),
                        "unknown_ankan_note": "牌名未知；你手中或公开区已有任一副本的牌，不可能再藏于此人的未知暗杠中；未见不等于已暗杠",
                        "qualifying_hua_floor": p["known_qualifying_hua"]["total"]+10*p["unknown_ankan_count"],
                        "ron_note": "资格花大于0即满足花分门槛；是否成牌、私有过胡未知，互锁禁止接炮"})
    return reports


def flower_opportunities(obs):
    """Single-flower replacement outcomes conditional on drawing a named tile."""
    hand = [parse_tile(t) for t in obs["self"]["hand"]]
    player = obs["players"][obs["seat"]]
    melds = [Meld(m["type"], [parse_tile(t) for t in m["tiles"]]) for m in player["melds"]]
    flowers = [parse_tile(t) for t in player["flowers"]]
    visible = Counter(hand)
    for p in obs["players"]:
        visible.update(parse_tile(t) for t in p["river"]+p["flowers"])
        for m in p["melds"]:
            visible.update(parse_tile(t) for t in (m["tiles"] or []))
    result = []
    for action in obs["legal_actions"]:
        if action["kind"] != "flower_kong":
            continue
        flower = parse_tile(action["tiles"][0])
        rest = hand.copy()
        rest.remove(flower)
        outcomes = []
        for wait in wait_shapes(rest, len(melds)):
            tile = parse_tile(wait["tile"])
            unseen = max(0, 4-visible[tile])
            if not unseen:
                continue
            # Exact current exposed groups (including four-flower ankan) stay
            # in melds; previously exchanged singles remain single groups.
            exchanged = flowers+[flower]
            score = score_hand(rest+[tile], my_melds=melds, konged_flowers=exchanged,
                               flower_kong_groups=[[t] for t in exchanged], win_method="gangkai")
            payments = {str(p["seat"]): score.hua*(3 if p["seat"] in player["locked_with"] else 1)
                        for p in obs["players"] if p["seat"] != obs["seat"]}
            outcomes.append({**wait, "unseen_upper_bound": unseen, "per_base_share": score.hua,
                             "payments": payments, "total_income": sum(payments.values())})
        result.append({"action_id": action["id"], "remaining_held_flowers": sum(t.is_flower for t in rest),
                       "immediate_gangkai": outcomes,
                       "scope": "仅换出本张花后的条件结果；未见不等于在墙，未估概率，不保证摸到；多张批次须逐步重算"})
    return result
