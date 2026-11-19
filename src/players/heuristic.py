"""Deterministic baseline, NOT a trained/EV-maximizing opponent."""
from .analysis import analyze_actions
from .base import Choice, DecisionError


class HeuristicPlayer:
    def select_flowers(self, observation):
        """Only the initially held, legally exchangeable flowers; no new draws."""
        legal = {a["tiles"][0] for a in observation["legal_actions"] if a["kind"] == "flower_kong"}
        return [t for t in observation["self"]["hand"] if t in legal][:observation["wall_count"]]

    def choose(self, observation):
        actions = observation["legal_actions"]
        if not actions:
            raise DecisionError("没有合法动作")
        for kind in ("win", "ron", "an_gang", "add_gang", "flower_kong"):
            action = next((a for a in actions if a["kind"] == kind), None)
            if action:
                return Choice(action["id"], "heuristic", "基础策略：优先胡牌或换牌/成杠；非收益最优判断")
        analysis = analyze_actions(observation)
        rank = lambda a: (a["shanten"], -a["unseen_improving"])
        discards = [a for a in analysis["candidates"] if a["kind"] == "discard"]
        if discards:
            tiles = {a["id"]: a["tiles"][0] for a in actions}
            best = min(discards, key=lambda a: (*rank(a), tiles[a["action_id"]]))
            return Choice(best["action_id"], "heuristic", "基础牌效：结构向听与未见进张，不含完整防守/净收益搜索")
        calls = [a for a in analysis["candidates"] if a["kind"] in ("chi", "peng", "ming_gang") and "shanten" in a]
        baseline = analysis["baseline"]
        beneficial = [a for a in calls if rank(a) < rank(baseline)
                      and not (a.get("discards_claimed_kind") and a["shanten"] >= baseline["shanten"])
                      and not (a["creates_lock"] and a["shanten"] >= baseline["shanten"])]
        if beneficial:
            best = min(beneficial, key=lambda a: (*rank(a), a["creates_lock"], a["action_id"]))
            return Choice(best["action_id"], "heuristic", "基础策略：吃碰杠须有明确结构收益；第三口须降低向听，未评估完整互锁净收益")
        return Choice(next(a["id"] for a in actions if a["kind"] == "pass"), "heuristic", "基础策略：无明确吃碰收益，保留正常摸牌及接炮机会")
