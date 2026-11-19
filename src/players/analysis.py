"""Deterministic candidate facts from a redacted observation, not an EV model."""
from collections import Counter

from ..core.hand_analyzer import calculate_shanten, get_ukeire
from ..core.tiles import parse_tile, tile_sort_key
from .strategy_facts import strategy_facts
from .shapes import describe_hand


def analyze_actions(observation):
    seat = observation["seat"]
    hand = [parse_tile(t) for t in observation["self"]["hand"]]
    groups = len(observation["players"][seat]["melds"])
    visible = Counter(hand)
    for player in observation["players"]:
        visible.update(parse_tile(t) for t in player["river"]+player["flowers"])
        for meld in player["melds"]:
            visible.update(parse_tile(t) for t in (meld["tiles"] or []))

    def facts(tiles, count):
        structural = [t for t in tiles if not t.is_flower]
        improving = sorted(get_ukeire(structural, count), key=tile_sort_key)
        return {"shanten": calculate_shanten(structural, count),
                "unseen_improving": sum(max(0, 4-visible[t]) for t in improving),
                "improving_tiles": [str(t) for t in improving]}

    candidates = []
    for action in observation["legal_actions"]:
        item = {"action_id": action["id"], "kind": action["kind"]}
        kind = action["kind"]
        if kind == "discard":
            after = hand.copy()
            after.remove(parse_tile(action["tiles"][0]))
            item.update(facts(after, groups))
        elif kind in ("chi", "peng", "ming_gang"):
            source = observation["pending"]["source"]
            tile = parse_tile(observation["pending"]["tile"])
            needed = ([tile]*(3 if kind == "ming_gang" else 2) if kind != "chi"
                      else [parse_tile(t) for t in action["tiles"]])
            if kind == "chi":
                needed.remove(tile)
            after = hand.copy()
            for t in needed:
                after.remove(t)
            counts = observation.get("call_counts", [[0]*4 for _ in range(4)])
            next_count = counts[seat][source]+1
            item.update(source=source, call_count_after=next_count,
                        creates_lock=next_count >= 3 and source not in observation["self"].get("locked_with", []))
            if kind == "ming_gang":
                item.update(facts(after, groups+1))
                item["replacement_unknown"] = True
            else:
                discards = []
                for t in sorted(set(after), key=tile_sort_key):
                    if not t.is_flower:
                        remaining = after.copy()
                        remaining.remove(t)
                        discards.append({"tile": str(t), **facts(remaining, groups+1)})
                item["after_discards"] = discards
                if discards:
                    best = min(discards, key=lambda d: (d["shanten"], -d["unseen_improving"], d["tile"]))
                    item.update({k: best[k] for k in ("shanten", "unseen_improving", "improving_tiles")})
                    item["best_discard"] = best["tile"]
                    item["discards_claimed_kind"] = best["tile"] == str(tile)
        candidates.append(item)
    discards = [c for c in candidates if c["kind"] == "discard"]
    if discards:
        reference = min(discards, key=lambda c: (c["shanten"],-c["unseen_improving"],c["action_id"]))
        for item in discards:
            item["comparison_to_speed_reference"] = {
                "action_id": reference["action_id"], "same_shanten": item["shanten"] == reference["shanten"],
                "lost_improving_tiles": sorted(set(reference["improving_tiles"])-set(item["improving_tiles"])),
                "gained_improving_tiles": sorted(set(item["improving_tiles"])-set(reference["improving_tiles"])),
                "note": "结构距离不同时，不能直接以两组进张数量比较优劣"}
    return {"baseline": facts(hand, groups), "candidates": candidates, "strategy_facts": strategy_facts(observation),
            "structure_before": describe_hand(hand, groups),
            "limitations": "只计算结构牌效和公开未见张；不是牌墙活张、胜率或净收益。吃碰须与放过后正常摸牌的机会比较，未做整局搜索。第三口会关闭双方全部接炮，并将双方自摸赔付乘三。"}
