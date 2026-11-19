"""Bounded common-random-world personal-hand rollouts, NOT full-table EV.

Opponents consume three normal draws but never win/call/replace flowers here.
Policy cannot inspect sampled future walls or other hands. Opponent competition
and immediate discard risk are reported separately, never silently subtracted.
"""
from collections import Counter
import copy
from dataclasses import dataclass
import random
import time
from functools import lru_cache

from ..core.hand_analyzer import calculate_shanten, get_waiting_tiles, get_ukeire, is_agari
from ..core.scoring import score_hand
from ..core.tiles import Meld, parse_tile, tile_sort_key
from ..simulation.hidden_world import sample_world, unseen_counts
from .analysis import analyze_actions
from .base import action_label
from .shapes import describe_hand


@dataclass
class Solo:
    hand: list
    melds: list
    flowers: list
    locks: set
    wall: list
    unseen: Counter
    konged: bool = False


def _structural(hand, melds):
    return calculate_shanten([t for t in hand if not t.is_flower],len(melds))


def _discard(hand, melds, unseen):
    choices = []
    packed = tuple(sorted((t for t in hand if not t.is_flower),key=tile_sort_key))
    for tile,shanten,improving in _discard_facts(packed,len(melds)):
        rest = hand.copy()
        rest.remove(tile)
        c = Counter(t for t in rest if not t.is_flower)
        quality = sum(2*(n>=2)+3*(n>=3) for n in c.values())
        for t in c:
            if t.suit in ("万","饼","条"):
                quality += sum((2 if abs(int(u.value)-int(t.value)) == 1 else 1)
                               for u in c if u.suit == t.suit and 0 < abs(int(u.value)-int(t.value)) <= 2)
        outs = sum(max(0,unseen[t]) for t in improving)
        choices.append((shanten,-outs,-quality,tile_sort_key(tile),tile))
    return min(choices)[-1] if choices else None


@lru_cache(maxsize=8192)
def _discard_facts(hand,groups):
    result = []
    minimum = None
    for tile in sorted(set(hand),key=tile_sort_key):
        rest = list(hand)
        rest.remove(tile)
        shanten = calculate_shanten(rest,groups)
        if minimum is None or shanten < minimum:
            minimum = shanten
        result.append((tile,shanten,rest))
    return tuple((tile,s,tuple(get_ukeire(rest,groups))) for tile,s,rest in result if s == minimum)


def _win(state, seat):
    if any(t.is_flower for t in state.hand) or len(state.hand) != 14-3*len(state.melds):
        return None
    if not is_agari(state.hand,len(state.melds)):
        return None
    score = score_hand(state.hand,state.melds,konged_flowers=state.flowers,
                       flower_kong_groups=[[t] for t in state.flowers],
                       win_method="gangkai" if state.konged else "zimo")
    return sum(score.hua*(3 if p in state.locks else 1) for p in range(4) if p != seat)


def _waits(state):
    if any(t.is_flower for t in state.hand) or len(state.hand) != 13-3*len(state.melds):
        return []
    own = Counter(state.hand)
    own.update(t for m in state.melds for t in m.tiles)
    return [t for t in get_waiting_tiles(state.hand,len(state.melds)) if own[t] < 4]


def _draw(state, replacement=False):
    if not state.wall:
        return False
    tile = state.wall.pop(-1 if replacement else 0)
    state.hand.append(tile)
    state.unseen[tile] -= 1
    state.konged |= replacement
    return True


def _new_meld(state, kind, tile):
    needed = 1 if kind == "add_gang" else 3 if kind == "ming_gang" else 4
    for _ in range(needed):
        state.hand.remove(tile)
    if kind == "add_gang":
        index = next(i for i,m in enumerate(state.melds) if m.type == "peng" and m.tiles[0] == tile)
        state.melds[index] = Meld("ming_gang",[tile]*4)
    else:
        state.melds.append(Meld("ming_gang" if kind == "ming_gang" else "an_gang",[tile]*4))


def plans(obs, analysis, max_candidates=8):
    result = []
    facts = {f["action_id"]:f for f in analysis["candidates"]}
    for action in obs["legal_actions"]:
        fact = facts[action["id"]]
        branches = sorted(fact.get("after_discards",[]),key=lambda x:(x["shanten"],-x["unseen_improving"],x["tile"]))[:2]
        for branch in branches or [None]:
            result.append({"plan_id":action["id"]+(":"+branch["tile"] if branch else ""),
                "action":action, "label":action_label(action).strip()+("后打"+branch["tile"] if branch else ""),
                "next_discard":branch["tile"] if branch else None, "flower_policy":"exchange",
                "root_shanten":(branch or fact).get("shanten",analysis["baseline"]["shanten"]),
                "root_unseen":(branch or fact).get("unseen_improving",0)})
    rank = lambda p:(-10 if p["action"]["kind"] in ("win","ron") else p["root_shanten"],-p["root_unseen"],p["plan_id"])
    result.sort(key=rank)
    chosen, kinds = [], set()
    # Preserve alternative action TYPES, rather than filling every slot with
    # similar discards and never comparing flowers/calls/pass/kongs.
    for plan in result:
        if plan["action"]["kind"] not in kinds and len(chosen) < max_candidates:
            chosen.append(plan)
            kinds.add(plan["action"]["kind"])
    for plan in result:
        if len(chosen) >= max_candidates:
            break
        if plan not in chosen:
            chosen.append(plan)
    held = Counter(obs["self"]["hand"])
    triple = any(held[name] == 3 for name in ("东风","中","发","白"))
    if triple:
        base = next((p for p in chosen if p["action"]["kind"] == "discard"),None)
        if base:
            variant = {**base,"plan_id":base["plan_id"]+":reserve-triplet", "flower_policy":"reserve_triplet",
                       "label":base["label"]+"，留三同花等四张（末次机会释放）"}
            if len(chosen) == max_candidates and len(chosen) > len(kinds):
                chosen.pop()
            if len(chosen) < max_candidates:
                chosen.append(variant)
    return chosen,len(result)


def _trial(obs,plan,world,horizon):
    seat = obs["seat"]
    state = Solo(list(world.hands[seat]),copy.deepcopy(world.melds[seat]),
                 [parse_tile(t) for t in obs["players"][seat]["flowers"]],
                 set(obs["self"].get("locked_with",[])),list(world.wall),unseen_counts(obs),
                 obs["self"].get("draw_source") == "replacement")
    action = plan["action"]
    kind = action["kind"]
    tile = parse_tile(action["tiles"][0]) if action["tiles"] else None
    mode,skip = "normal",3
    if kind in ("win","ron"):
        return {"win":True,"receipt":sum(p["amount"] for p in action["payments"]),"ready":True,"shanten":-1,"waits":0}
    if kind == "discard":
        state.hand.remove(tile)
    elif kind == "pass":
        skip = (seat-obs["pending"]["source"]-1) % 4
    elif kind in ("chi","peng"):
        source = obs["pending"]["source"]
        offered = parse_tile(obs["pending"]["tile"])
        group = [parse_tile(t) for t in action["tiles"]] if kind == "chi" else [offered]*3
        needed = group.copy()
        needed.remove(offered)
        for t in needed:
            state.hand.remove(t)
        state.melds.append(Meld(kind,group))
        state.hand.remove(parse_tile(plan["next_discard"]))
        if obs["call_counts"][seat][source]+1 >= 3:
            state.locks.add(source)
    elif kind in ("an_gang","ming_gang","add_gang"):
        _new_meld(state,kind,tile)
        if kind == "ming_gang" and obs["call_counts"][seat][obs["pending"]["source"]]+1 >= 3:
            state.locks.add(obs["pending"]["source"])
        mode = "replacement"
    elif kind == "flower_kong":
        state.hand.remove(tile)
        state.flowers.append(tile)
        mode = "replacement"
    reached_ready = mode == "normal" and bool(_waits(state))
    normal_turn = 0
    phases = horizon+int(mode == "replacement")
    for _phase in range(phases):
        if mode == "normal":
            normal_turn += 1
            state.konged = False
            if len(state.wall) <= skip:
                break
            del state.wall[:skip]
        if not _draw(state,mode == "replacement"):
            break
        # Each normal opportunity can chain legal replacement draws. Only the
        # sampled CURRENT draw is observed by policy, never the future wall.
        for _ in range(40):
            value = _win(state,seat)
            if value is not None:
                return {"win":True,"receipt":value,"ready":True,"shanten":-1,"waits":0}
            counts = Counter(state.hand)
            kong = next((t for t,n in counts.items() if n == 4 and len(state.melds) < 4),None)
            if kong is not None and state.wall:
                rest = [t for t in state.hand if t != kong]
                discard = _discard(state.hand,state.melds,state.unseen)
                old = state.hand.copy()
                if discard is not None:
                    old.remove(discard)
                if _structural(rest,state.melds+[Meld("an_gang",[kong]*4)]) <= _structural(old,state.melds):
                    _new_meld(state,"an_gang",kong)
                    _draw(state,True)
                    continue
            add = next((m.tiles[0] for m in state.melds if m.type == "peng" and counts[m.tiles[0]]),None)
            if add is not None and state.wall:
                _new_meld(state,"add_gang",add)
                _draw(state,True)
                continue
            reserve = plan["flower_policy"] == "reserve_triplet" and normal_turn < horizon
            flower = next((t for t in state.hand if t.is_flower and not (
                reserve and counts[t] == 3 and str(t) in ("东风","中","发","白"))),None)
            if flower is not None and state.wall:
                state.hand.remove(flower)
                state.flowers.append(flower)
                _draw(state,True)
                continue
            discard = _discard(state.hand,state.melds,state.unseen)
            if discard is not None:
                state.hand.remove(discard)
            break
        ready = bool(_waits(state))
        reached_ready |= ready
        mode,skip = "normal",3
    shanten = _structural(state.hand,state.melds)
    waits = sum(max(0,state.unseen[t]) for t in _waits(state))
    return {"win":False,"receipt":0,"ready":reached_ready,"shanten":shanten,"waits":waits}


def plan_structure(obs,plan):
    hand = [parse_tile(t) for t in obs["self"]["hand"]]
    melds = [Meld(m["type"],[parse_tile(t) for t in m["tiles"]]) for m in obs["players"][obs["seat"]]["melds"]]
    action = plan["action"]
    kind = action["kind"]
    if kind in ("discard","flower_kong","add_gang"):
        hand.remove(parse_tile(action["tiles"][0]))
    elif kind in ("chi","peng","ming_gang","an_gang"):
        tile = parse_tile(obs["pending"]["tile"] if kind in ("chi","peng","ming_gang") else action["tiles"][0])
        group = [parse_tile(t) for t in action["tiles"]] if kind == "chi" else [tile]*(4 if "gang" in kind else 3)
        needed = group.copy()
        if kind != "an_gang":
            needed.remove(tile)
        for t in needed:
            hand.remove(t)
        melds.append(Meld("an_gang" if kind == "an_gang" else "ming_gang" if kind == "ming_gang" else kind,group))
        if plan["next_discard"]:
            hand.remove(parse_tile(plan["next_discard"]))
    return {**describe_hand(hand,len(melds)),
            "replacement_pending":kind in ("flower_kong","an_gang","add_gang","ming_gang")}


def search(obs, *, trials=8,horizon=3,max_candidates=8,time_budget=.6,seed=0):
    for value,low,high in ((trials,1,64),(horizon,1,6),(max_candidates,1,16)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("搜索规模超出上限")
    if isinstance(time_budget,bool) or not .01 <= time_budget <= 5:
        raise ValueError("搜索时间预算须在0.01至5秒之间")
    started = time.monotonic()
    analysis = analyze_actions(obs)
    selected,total = plans(obs,analysis,max_candidates)
    if not selected:
        return {"status":"no-actions","plans":[]}
    stats = {p["plan_id"]:[] for p in selected}
    rng,n = random.Random(seed),0
    for _ in range(trials):
        if n and time.monotonic()-started >= time_budget:
            break
        world = sample_world(obs,rng)
        for plan in selected:
            stats[plan["plan_id"]].append(_trial(obs,plan,world,horizon))
        n += 1
    result = []
    for plan in selected:
        rows = stats[plan["plan_id"]]
        result.append({**plan,"samples":n,"solo_wins":sum(r["win"] for r in rows),
            "structure_after_root":plan_structure(obs,plan),
            "solo_reached_ready":sum(r["ready"] for r in rows),
            "mean_terminal_shanten":sum(r["shanten"] for r in rows)/n,
            "mean_solo_win_receipt":sum(r["receipt"] for r in rows)/n,
            "mean_terminal_public_unseen_waits":sum(r["waits"] for r in rows)/n})
    result.sort(key=lambda p:(-p["solo_wins"],-p["solo_reached_ready"],p["mean_terminal_shanten"],-p["mean_terminal_public_unseen_waits"],p["plan_id"]))
    return {"model":"personal-rollout-v1","status":"experimental" if n >= 4 else "insufficient-samples",
        "validated_for_policy":False,
        "samples":n,"requested_samples":trials,"horizon_own_draw_opportunities":horizon,
        "candidate_count_before_cap":total,"plans":result,"elapsed_ms":round((time.monotonic()-started)*1000),
        "limitations":["自身成牌试验，不是实战胜率或净收益；其他三家不会胡、吃碰或补花，仅消耗普通摸牌。",
            "所有候选共享抽样世界；策略不读取未来牌墙或对手私牌。未见张仍包含他家暗牌与暗杠。",
            "后续弃牌采用最小向听、公开未见进张与局部形状平手规则；有限候选、步数和小样本不保证最优。",
            "花牌可留占位；三同花保留策略在最后一次机会释放。杠补一张，未胡不计收入。"]}
