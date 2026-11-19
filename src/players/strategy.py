"""Combine separate, explicitly scoped route and opponent analyses."""
import random
import time
import copy

from ..core.hand_analyzer import get_waiting_tiles
from ..core.scoring import score_hand
from ..core.tiles import parse_tile
from ..simulation.hidden_world import sample_world
from .opponent_model import load_model, predict
from .solo_search import search
from .base import DecisionError


def check_plan_reference(answer, comparison):
    """Optional route citation must identify the SAME action/discard branch.

    Legal choices outside a bounded search remain allowed. Referencing a plan
    does not certify its free-form explanation or improve model calibration.
    """
    identity = answer.get("plan_id")
    if identity is None:
        return None
    plan = next((p for p in comparison["solo_search"]["plans"] if p["plan_id"] == identity),None)
    if (plan is None or plan["action"]["id"] != answer["action_id"]
            or plan["next_discard"] != answer.get("next_discard")):
        raise DecisionError("引用的模拟方案与实际动作／弃牌分支不符，未执行")
    return identity


def for_adviser(comparison):
    """Withhold unvalidated learned probabilities from the paid adviser input."""
    result = copy.deepcopy(comparison)
    result["opponent_baseline"] = [{"seat":p["seat"],"deployment":"shadow-only",
        "scope":"模型未真人校准，数值仅留在本地诊断，不作为当前推荐依据"}
        for p in comparison["opponent_baseline"]]
    return result


def immediate_risk(obs, *, samples=32,seed=0,time_budget=.25,extra_tiles=()):
    if type(samples) is not int or not 1 <= samples <= 256:
        raise ValueError("风险样本数须为1至256")
    if isinstance(time_budget,bool) or not .01 <= time_budget <= 5:
        raise ValueError("风险时间预算须为0.01至5秒")
    candidates = sorted({a["tiles"][0] for a in obs["legal_actions"] if a["kind"] == "discard"}|set(extra_tiles))
    for t in candidates:
        if t not in obs["self"]["hand"] or parse_tile(t).is_flower:
            raise ValueError("只评估当前持有的可弃结构牌")
    seats = [p["seat"] for p in obs["players"] if p["seat"] != obs["seat"]]
    stats = {t:{"hits":0,"loss":0,"opponents":{p:0 for p in seats},"payments":{p:0 for p in seats}} for t in candidates}
    rng,start,n = random.Random(seed),time.monotonic(),0
    if candidates:
        for _ in range(samples):
            if n and time.monotonic()-start >= time_budget:
                break
            world = sample_world(obs,rng)
            for p in obs["players"]:
                seat = p["seat"]
                if seat == obs["seat"] or p.get("locked_with"):
                    continue
                hand,melds = world.hands[seat],world.melds[seat]
                if any(t.is_flower for t in hand) or len(hand) != 13-3*len(melds):
                    continue
                waits = set(get_waiting_tiles(hand,len(melds)))
                flowers = [parse_tile(t) for t in p["flowers"]]
                for name in candidates:
                    tile = parse_tile(name)
                    if tile not in waits:
                        continue
                    try:
                        value = score_hand(hand+[tile],melds,konged_flowers=flowers,
                                           flower_kong_groups=[[t] for t in flowers],win_method="dianpao").hua
                    except ValueError:
                        continue
                    stats[name]["opponents"][seat] += 1
                    stats[name]["payments"][seat] += value
                    stats[name]["loss"] += value
            for name in candidates:
                # Multiple winners are additive; count a hit once per world.
                total = sum(stats[name]["opponents"].values())
                old = stats[name].get("last_hits",0)
                stats[name]["hits"] += int(total > old)
                stats[name]["last_hits"] = total
            n += 1
    return {"model":"v4-count-constrained-uniform-prior", "samples":n,"calibrated":False,
        "candidates":[{"tile":t,"ron_hit_worlds":s["hits"],"sum_loss_over_samples":s["loss"],
                       "per_opponent_hits":s["opponents"],"per_opponent_loss":s["payments"]} for t,s in stats.items()],
        "limitations":["当前弃牌风险，非整局净收益。联合物理先验，不使用弃牌策略的似然，不是拟合后的手牌后验。",
            "未知暗杠为四张同牌，手中持有的牌不可能被对手暗杠；留花占位并阻止胡牌。",
            "过胡是对手私有状态，未假装知道；只把公开互锁的接炮风险置零。零命中不代表安全。"]}


def strategy_bundle(obs, *, trials=8,horizon=3,time_budget=.6,model_path=None):
    solo = search(obs,trials=trials,horizon=horizon,time_budget=time_budget)
    risk = immediate_risk(obs,extra_tiles=[p["next_discard"] for p in solo["plans"] if p["next_discard"]])
    learned,error = [],None
    try:
        model = load_model(model_path) if model_path else load_model()
        if model:
            learned = [predict(model,obs,p["seat"]) for p in obs["players"] if p["seat"] != obs["seat"]]
    except (ValueError,KeyError,OSError):
        error = "离线对手模型不可用，未采用其输出"
    routes = []
    for plan in solo["plans"]:
        root = plan["action"]
        warning = None
        tile = root["tiles"][0] if root["kind"] == "discard" else plan["next_discard"]
        if tile:
            item = next((r for r in risk["candidates"] if r["tile"] == tile),None)
            if item:
                hits,loss = dict(item["per_opponent_hits"]),dict(item["per_opponent_loss"])
                if root["kind"] in ("chi","peng"):
                    source = obs["pending"]["source"]
                    if obs["call_counts"][obs["seat"]][source]+1 >= 3:
                        hits[source],loss[source] = 0,0
                warning = {"per_opponent_hits":hits,"sum_loss_over_samples":sum(loss.values()),"samples":risk["samples"],
                           "note":"与自身成牌模型分开，不合成伪精确净收益"}
        routes.append({**plan,"immediate_risk_check":warning})
    return {"solo_search":{**solo,"plans":routes},"immediate_risk":risk,
        "opponent_baseline":learned,"opponent_model_error":error,
        "scope":"比较不同路线的自身速度、价值与公开风险；不是全局最优或真人校准概率"}
