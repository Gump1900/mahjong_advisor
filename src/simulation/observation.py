"""Allow-listed seat observations, never serialization of the referee state."""
import copy
from collections import Counter

from ..core.hand_analyzer import calculate_shanten, get_waiting_tiles
from ..core.scoring import score_hand, known_hua
from ..core.tiles import Meld, parse_tile, tile_sort_key


def waiting_information(table, seat, views):
    """Own waits and discard-to-tenpai previews using ONLY visible tile counts."""
    player = table.seats[seat]
    groups = len(player.melds)
    base = 13 - 3*groups
    visible = Counter(player.hand)
    own_melds = Counter(t for m in player.melds for t in m.tiles)
    for p in views:
        visible.update(parse_tile(t) for t in p["river"] + p["flowers"])
        for m in p["melds"]:
            visible.update(parse_tile(t) for t in (m["tiles"] or []))

    def details(hand):
        if len(hand) != base or any(t.is_flower for t in hand):
            return []
        result = []
        counts = Counter(hand)
        for tile in sorted(get_waiting_tiles(hand, groups), key=tile_sort_key):
            if counts[tile] + own_melds[tile] >= 4:
                continue  # Never suggest a physical fifth copy.
            kwargs = {"my_melds": player.melds, "konged_flowers": player.flowers,
                      "flower_kong_groups": [[t] for t in player.flowers]}
            zimo = score_hand(hand + [tile], win_method="zimo", **kwargs)
            try:
                ron = score_hand(hand + [tile], win_method="dianpao", **kwargs)
            except ValueError:
                ron = None
            locked = bool(table.locked_with(seat))
            reason = "吃三口互锁，本局只能自摸" if locked else "过胡未过圈，暂不能接炮" if player.ron_blocked else "无资格花，只能自摸" if ron is None else "可接炮或自摸"
            result.append({"tile":str(tile), "unseen":max(0, 4-visible[tile]),
                           "can_ron":ron is not None and not player.ron_blocked and not locked,
                           "ron_hua":ron.hua if ron is not None and not player.ron_blocked and not locked else None,
                           "self_draw_hua":zimo.hua,
                           "self_draw_payments": [{"payer": p, "amount": zimo.hua * (
                               3 if p in table.locked_with(seat) else 1)} for p in range(4) if p != seat],
                           "reason":reason})
        return result

    waits = details(player.hand)
    discard_waits = {}
    if len(player.hand) == base+1 and not any(t.is_flower for t in player.hand):
        for tile in sorted(set(player.hand), key=tile_sort_key):
            after = list(player.hand)
            after.remove(tile)
            found = details(after)
            if found:
                discard_waits[str(tile)] = found
    return {"waiting_tiles":waits, "discard_waits":discard_waits,
            "waiting_note":"未见张数仅扣自己的牌与公开牌，不等于牌墙活张；未知暗杠可能耗尽进张。"}


def observe(table, seat):
    if isinstance(seat, bool) or seat not in range(4):
        raise ValueError("未知座位")
    views = []
    # Public resolved claim order mirrors meld creation order. Derive display
    # provenance without changing the referee snapshot/hash or old replays.
    origins = {p: [] for p in range(4)}
    mouths = [[0]*4 for _ in range(4)]
    for event in table.events:
        if event["kind"] in ("chi", "peng", "ming_gang"):
            taker, source = event["seat"], event["source"]
            mouths[taker][source] += 1
            origins[taker].append({"source": source, "call_number": mouths[taker][source]})
        elif event["kind"] == "an_gang":
            origins[event["seat"]].append({})
    for p, state in enumerate(table.seats):
        melds = []
        origin_offset = len(state.melds)-len(origins[p])
        for index, meld in enumerate(state.melds):
            hidden = meld.type == "an_gang" and p != seat
            melds.append({"type": meld.type, "tiles": None if hidden else [str(t) for t in meld.tiles],
                          "size": len(meld.tiles), "hidden": hidden,
                          **(origins[p][index-origin_offset] if 0 <= index-origin_offset < len(origins[p]) else {})})
        known = known_hua(
            melds=[Meld(m["type"], [parse_tile(t) for t in m["tiles"]]) for m in melds if m["tiles"]],
            konged_flowers=state.flowers, flower_kong_groups=[[t] for t in state.flowers])
        views.append({"seat": p, "hand_count": len(state.hand), "melds": melds,
                      "locked_with": table.locked_with(p),
                      "call_counts": list(table.call_counts[p]),
                      "known_qualifying_hua": known,
                      "unknown_ankan_count": sum(m["hidden"] for m in melds),
                      "value_note": "仅当前可知资格花，不含未公开手牌和牌型加分；不是听牌概率或已获收入。未知暗杠每组10或12，不能据此猜名。",
                      "flowers": [str(t) for t in state.flowers], "river": [str(t) for t in state.river]})
    events = []
    for event in table.events:
        item = copy.deepcopy(event)
        if item["kind"] in ("draw", "an_gang") and item["seat"] != seat:
            item.pop("tile", None)
            item["hidden"] = True
        events.append(item)
    player = table.seats[seat]
    actions = [a.json() for a in table.legal_actions(seat)]
    for action in actions:
        if action["kind"] in ("win", "ron"):
            method = "dianpao" if action["kind"] == "ron" else (
                "gangkai" if table.draw_source == "replacement" else "zimo")
            tile = table.pending["tile"] if method == "dianpao" else None
            score = table._score(seat, method, tile)
            action["score_per_payer"] = score.hua
            action["score_breakdown"] = list(score.breakdown)
            action["payments"] = [
                {"payer": p, "amount": score.hua * (3 if p in table.locked_with(seat) else 1)}
                for p in ([table.pending["source"]] if method == "dianpao" else range(4)) if p != seat]
    waiting = waiting_information(table, seat, views)
    return {
        "observation_id": f"{table.game_id}:{table._token()}:{seat}",
        "rules_version": table.rules_version,
        "call_counts": copy.deepcopy(table.call_counts),
        "locked_pairs": [list(pair) for pair in table.locked_pairs()],
        "seat": seat, "dealer": table.dealer, "stage": table.stage, "actor": table.actor,
        "wall_count": len(table.wall),  # A referee-observed count, NOT unseen counts.
        "self": {"hand": [str(t) for t in sorted(player.hand, key=tile_sort_key)],
                 **waiting,
                 "ron_blocked": player.ron_blocked,
                 "peng_blocked": [str(t) for t in sorted(player.peng_blocked, key=tile_sort_key)],
                 "locked_with": table.locked_with(seat),
                 "held_flower_count": sum(t.is_flower for t in player.hand),
                 "drawn_tile": str(table.drawn_tile) if table.actor == seat and table.drawn_tile else None,
                 "draw_source": table.draw_source if table.actor == seat else None,
                 "structural_shanten": calculate_shanten(
                     [t for t in player.hand if not t.is_flower], len(player.melds)),
                 "analysis_note": "结构向听未单独评估留花换牌的策略价值；合法动作由裁判另行校验。"},
        "players": views, "events": events,
        "pending": None if table.pending is None else {
            **table.pending, "tile": str(table.pending["tile"])},
        "legal_actions": actions,
        "result": copy.deepcopy(table.result),
    }
