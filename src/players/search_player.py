"""Experimental personal-search policy for OFFLINE comparisons, not a master."""
from .base import Choice
from .heuristic import HeuristicPlayer
from .solo_search import search


class SearchPlayer:
    def __init__(self, *, trials=8,horizon=3,time_budget=.3):
        self.trials,self.horizon,self.time_budget = trials,horizon,time_budget
        self.batch = []

    def choose(self,obs):
        self.batch = []
        win = next((a for a in obs["legal_actions"] if a["kind"] in ("win","ron")),None)
        if win:
            return Choice(win["id"],"search:take-win","实验约定：合法即胡")
        report = search(obs,trials=self.trials,horizon=self.horizon,time_budget=self.time_budget)
        if report["status"] == "insufficient-samples":
            baseline = HeuristicPlayer().choose(obs)
            return Choice(baseline.action_id,"search:insufficient-baseline","样本不足，显式采用代码基线，不冒充搜索最优")
        best = report["plans"][0]
        if best["action"]["kind"] == "flower_kong":
            selected = best["action"]["tiles"][0]
            legal = {a["tiles"][0] for a in obs["legal_actions"] if a["kind"] == "flower_kong"}
            flowers = [t for t in obs["self"]["hand"] if t in legal]
            flowers.remove(selected)
            self.batch = [selected,*flowers][:obs["wall_count"]]
        return Choice(best["action"]["id"],"search:personal-only",
            f"自身{best['samples']}个样本中{best['solo_wins']}次胡、{best['solo_reached_ready']}次到听；"
            "忽略对手先胡和鸣牌，不是全局净收益最优。")

    def select_flowers(self,obs):
        return list(self.batch)
