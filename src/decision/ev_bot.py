"""EV bot: three personalities over the math decision core.

Consumes the simulation engine's observation dict (import-only; this module
never modifies `simulation/` or `players/`). Own legality gates sit BEFORE
the math: win/ron/flower_kong decisions respect 过圈/听牌 state as exposed
by the observation; discard choices are personality-weighted EV argmax.
"""
from dataclasses import dataclass
from typing import Callable, List

from ..core.tiles import GameState, Meld, Tile, parse_tile
from ..core.hand_analyzer import calculate_shanten
from ..players.base import Choice, DecisionError
from .ev import CandidateEV, rank_candidates
from .dynamic_reading import public_events
from .call_decision import evaluate_calls, is_beneficial, call_rank


@dataclass(frozen=True)
class Personality:
    a: float   # 进攻权重（P_win·V_win）
    d: float   # 防守权重（P_deal·V_deal）


PERSONALITIES = {
    "稳": Personality(a=1.0, d=2.0),
    "均衡": Personality(a=1.0, d=1.0),
    "凶": Personality(a=1.6, d=0.4),
}


def _default_ranker(state, *, samples=128, seed=0):
    # 与军师共用一步后劲比较；读牌和自身手牌优化同时参与。
    return rank_candidates(state, samples=samples, seed=seed, refine_ties=True)


def build_state_from_observation(observation: dict) -> GameState:
    """Rebuild a GameState (relative to the observing seat) from an engine
    observation dict. Opponents map to left/opposite/right by seat order;
    interlock pairs are restored as >=3-mouth counts."""
    seat = observation["seat"]
    hand_tiles = [parse_tile(t) for t in observation["self"]["hand"]]
    state = GameState(
        public_events=public_events(observation),
        my_hand=[t for t in hand_tiles if not t.is_flower],
        flowers_in_hand=[t for t in hand_tiles if t.is_flower],
        my_passed_win_pending=bool(observation["self"].get("ron_blocked")),
        my_passed_peng_kinds=[parse_tile(t) for t in
                              observation["self"].get("peng_blocked", [])],
    )
    # 引擎回合序 0→1→2→3：offset 1=下家(right)，2=对家，3=上家(left)
    others = sorted((p for p in observation.get("players", []) if p["seat"] != seat),
                    key=lambda p: (p["seat"] - seat) % 4)
    names = ("right", "opposite", "left")
    seat_name = {seat: "me"}
    for player, name in zip(others, names):
        seat_name[player["seat"]] = name
        if type(player.get("hand_count")) is int:
            state.opponent_hand_counts[name] = player["hand_count"]
        state.opponent_unknown_kongs[name] = sum(
            m["type"] == "an_gang" and not m.get("tiles") for m in player.get("melds", []))
        for meld in player.get("melds", []):
            tiles = [parse_tile(t) for t in meld["tiles"]] if meld.get("tiles") else []
            if tiles:
                state.melds[name].append(Meld(meld["type"], tiles))
        state.discards[name] = [parse_tile(t) for t in player.get("river", [])]
        state.opponent_konged_flowers[name] = [
            parse_tile(t) for t in player.get("flowers", [])]
    mine = next((p for p in observation.get("players", []) if p["seat"] == seat), None)
    if mine:
        for meld in mine.get("melds", []):
            tiles = [parse_tile(t) for t in meld["tiles"]] if meld.get("tiles") else []
            if tiles:
                state.my_melds.append(Meld(meld["type"], tiles))
        state.my_discards = [parse_tile(t) for t in mine.get("river", [])]
        state.konged_flowers = [parse_tile(t) for t in mine.get("flowers", [])]
    for taker, row in enumerate(observation.get("call_counts", [])):
        for source, count in enumerate(row):
            if count and taker in seat_name and source in seat_name:
                state.chi_peng_source_counts.setdefault(seat_name[taker], {})[seat_name[source]] = count
    for pair in observation.get("locked_pairs", []):
        a, b = (seat_name.get(int(s)) for s in pair)
        if a and b:
            state.chi_peng_source_counts.setdefault(a, {})[b] = 3
    return state


def self_kong_advice(observation: dict):
    """共享的自家杠决策：合法性只接受裁判，不自行补造动作。"""
    actions = observation.get("legal_actions") or []
    added = next((a for a in actions if a["kind"] == "add_gang"), None)
    if added:
        return added, (f"{added['tiles'][0]}已有碰：加杠补牌，保留其余手牌结构；"
                       "本玩法无抢杠，杠分须胡后结算")
    concealed = [a for a in actions if a["kind"] == "an_gang"]
    if not concealed or observation["self"].get("held_flower_count", 0):
        return None
    hand = [parse_tile(t) for t in observation["self"]["hand"]]
    mine = next((p for p in observation.get("players", [])
                 if p["seat"] == observation["seat"]), {})
    groups = len(mine.get("melds", []))
    discards = [a for a in actions if a["kind"] == "discard"]
    if not discards:
        return None
    def discard_shanten(action):
        after = hand.copy()
        after.remove(parse_tile(action["tiles"][0]))
        return calculate_shanten(after, groups)

    baseline = min(discard_shanten(action) for action in discards)
    for action in concealed:
        after = hand.copy()
        for _ in range(4):
            after.remove(parse_tile(action["tiles"][0]))
        shanten = calculate_shanten(after, groups + 1)
        if shanten <= baseline:
            return action, (f"暗杠{action['tiles'][0]}：补牌前向听{shanten}，"
                            f"不劣于当前最优弃牌的{baseline}向听；补牌未知，杠分须胡后结算")
    return None


class EVBot:
    """同一数学引擎，性格 = (进攻权重, 防守权重)。"""

    def __init__(self, personality: str = "均衡", *, samples: int = 128,
                 seed: int = 0, ranker: Callable = _default_ranker):
        if personality not in PERSONALITIES:
            raise ValueError(f"未知性格 {personality!r}（可用：{'/'.join(PERSONALITIES)}）")
        self.personality = PERSONALITIES[personality]
        self.name = personality
        self.samples = samples
        self.seed = seed
        self._ranker = ranker

    # --- state reconstruction ------------------------------------------------
    def _build_state(self, observation: dict) -> GameState:
        return build_state_from_observation(observation)

    # --- decision ------------------------------------------------------------
    def _score(self, cand: CandidateEV) -> float:
        attack = cand.p_win_next * cand.v_win
        defense = cand.p_point * cand.v_deal
        return self.personality.a * attack - self.personality.d * defense

    def _discard_choice(self, observation: dict, discards: List[dict]) -> Choice:
        state = self._build_state(observation)
        ranked = self._ranker(state, samples=self.samples, seed=self.seed)
        # 结构纪律先行：只在"打后向听最优"的候选里做性格加权（含花占位态，
        # 此时 ranked 的 stand_shanten 全 0 由 ranker 自身保证可比性）
        best_shanten = min(cand.stand_shanten for cand in ranked) if ranked else 0
        eligible = [cand for cand in ranked if cand.stand_shanten == best_shanten]
        by_tile = {}
        for index, cand in enumerate(ranked):
            cand_key = str(cand.tile)
            if cand_key not in by_tile:
                by_tile[cand_key] = (cand, index)
        best = min(
            (by_tile[str(cand.tile)][0] for cand in eligible
             if str(cand.tile) in by_tile),
            key=lambda cand: (
                -self._score(cand), by_tile[str(cand.tile)][1]),
            default=None)
        if best is None:
            first = min(discards, key=lambda a: a["tiles"])
            return Choice(first["id"], f"ev-{self.name}", "EV降级：无可用候选")
        tile = str(best.tile)
        action = next((a for a in discards if a["tiles"][0] == tile), discards[0])
        return Choice(action["id"], f"ev-{self.name}",
                      f"性格={self.name} a={self.personality.a} d={self.personality.d}；"
                      f"结构最优内向EV加权，打 {tile}；下家可吃机会估计{best.p_feed_chi:.0%}（非实际吃牌概率）")

    def _best_call(self, observation: dict):
        """吃/碰/明杠：仅取严格结构收益（与 heuristic 同判据，含第三口互锁守卫）。"""
        analysis = evaluate_calls(observation, samples=min(self.samples, 16), seed=self.seed)
        baseline = analysis["baseline"]
        best = None
        for cand in analysis["candidates"]:
            if not is_beneficial(cand, baseline):
                continue
            key = call_rank(cand)
            if best is None or key < best[0]:
                best = (key, cand)
        if best is None:
            return None
        cand = best[1]
        return Choice(cand["action_id"], f"ev-{self.name}",
                      f"{cand['kind']}有结构收益（向听{baseline['shanten']}→{cand['shanten']}），"
                      f"接牌后弃{cand.get('best_discard', '待补牌')}，结合动态读牌比较")

    def choose(self, observation: dict) -> Choice:
        actions = observation.get("legal_actions") or []
        if not actions:
            raise DecisionError("没有合法动作")
        by_kind = {}
        for action in actions:
            by_kind.setdefault(action["kind"], []).append(action)
        self_info = observation.get("self", {})

        for kind in ("win",):
            if kind in by_kind:
                return Choice(by_kind[kind][0]["id"], f"ev-{self.name}",
                              "自摸/杠开：正向收益即终局")
        if "ron" in by_kind and not self_info.get("ron_blocked"):
            return Choice(by_kind["ron"][0]["id"], f"ev-{self.name}",
                          "可接炮：过圈已解除，快胡原则")
        kong = self_kong_advice(observation)
        if kong:
            action, reason = kong
            return Choice(action["id"], f"ev-{self.name}", reason)
        if "flower_kong" in by_kind:
            if self_info.get("structural_shanten") == 0:
                return Choice(by_kind["flower_kong"][0]["id"], f"ev-{self.name}",
                              "已听牌：换花搏杠开（底分8）")
            if self_info.get("held_flower_count", 0):
                # 花占位：占着结构位且 EV 层不支持该状态，先换先补
                return Choice(by_kind["flower_kong"][0]["id"], f"ev-{self.name}",
                              "花占位：先换花补牌，让手牌回到可计算结构")
        if any(a["kind"] in ("chi", "peng", "ming_gang") for a in actions):
            call = self._best_call(observation)
            if call is not None:
                return call
        if "discard" in by_kind:
            try:
                return self._discard_choice(observation, by_kind["discard"])
            except ValueError:
                first = min(by_kind["discard"], key=lambda a: a["tiles"])
                return Choice(first["id"], f"ev-{self.name}",
                              "EV降级：手牌状态暂不支持（花占位等），按牌名序弃牌")
        if "pass" in by_kind:
            return Choice(by_kind["pass"][0]["id"], f"ev-{self.name}",
                          "v1策略：吃/碰/明杠暂不评估牌权交换，先过")
        first = actions[0]
        return Choice(first["id"], f"ev-{self.name}", "v1策略：其余动作类型按首个合法项")

    def select_flowers(self, observation: dict) -> List[str]:
        """换花批量选择：只换当前合法的花。返回字符串（引擎契约）。"""
        legal = {a["tiles"][0] for a in observation["legal_actions"]
                 if a["kind"] == "flower_kong"}
        held = list(observation["self"]["hand"])
        return [t for t in held if t in legal][:observation.get("wall_count", 1)]
