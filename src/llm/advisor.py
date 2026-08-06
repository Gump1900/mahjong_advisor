"""LLM advisor: orchestrate the engine into a prompt and call Claude.

Hybrid architecture: the engine computes deterministic facts (shanten, ukeire,
waiting tiles, discard ranking, remaining counts, risk labels) and the LLM
does the judgment layer — reading opponents, weighing risk vs. payoff, and
explaining the recommendation in natural language. The LLM never computes
shanten or tile counts.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..core.hand_analyzer import (
    calculate_shanten,
    get_ukeire,
    get_waiting_tiles,
    rank_discards,
)
from ..core.probability import count_remaining_tiles, discard_risk
from ..core.tiles import GameState, Meld, Tile

# Default model per the claude-api skill (override via MAHJONG_ADVISOR_MODEL).
DEFAULT_MODEL = "claude-opus-5"


@dataclass
class AnalysisBundle:
    """Deterministic analysis of a game state, fed to the prompt and the UI."""

    shanten: int
    is_tenpai: bool
    ukeire: List[Tile]
    waiting: List[Tile]
    discards_ranked: List[Tuple[Tile, int]]
    risks: Dict[Tile, str]
    remaining: Dict[Tile, int]
    remaining_total: int


def analyze(state: GameState) -> AnalysisBundle:
    """Run the engine over the state and collect every fact the advisor needs."""
    hand = state.my_hand
    shanten = calculate_shanten(hand)
    is_tenpai = shanten == 0
    discards_ranked = rank_discards(hand)
    risks = {tile: discard_risk(tile, state) for tile, _ in discards_ranked}
    remaining = count_remaining_tiles(state)
    return AnalysisBundle(
        shanten=shanten,
        is_tenpai=is_tenpai,
        ukeire=get_ukeire(hand),
        waiting=get_waiting_tiles(hand) if is_tenpai else [],
        discards_ranked=discards_ranked,
        risks=risks,
        remaining=remaining,
        remaining_total=sum(remaining.values()),
    )


# --- prompt construction ---------------------------------------------------
def _tiles(tiles: List[Tile]) -> str:
    return " ".join(str(t) for t in tiles) or "无"


def _melds(melds: List[Meld]) -> str:
    if not melds:
        return "无"
    return ", ".join(
        f"{m.type}[{_tiles(m.tiles)}]" for m in melds
    )


def build_prompt(state: GameState, analysis: AnalysisBundle) -> str:
    """Build the LLM prompt: rules, table state, and the engine's computed facts."""
    a = analysis
    players = [("上家", "left"), ("下家", "right"), ("对家", "opposite")]

    if a.shanten == -1:
        shanten_desc = "-1（已经胡了）"
    elif a.shanten == 0:
        shanten_desc = "0（听牌）"
    else:
        shanten_desc = f"{a.shanten}（还差 {a.shanten} 步听牌）"

    candidates = "\n".join(
        f"- 打 {tile}：打出后向听数 {after}；点炮风险 {a.risks[tile]}；该牌剩余 {a.remaining.get(tile, 0)} 张"
        for tile, after in a.discards_ranked[:6]
    ) or "- （没有可打牌）"

    waiting_line = ""
    if a.is_tenpai:
        waiting_line = (
            f"听牌（胡这些牌）：{_tiles(a.waiting)}；"
            f"各听牌剩余张数：{ {str(t): a.remaining.get(t, 0) for t in a.waiting} }\n"
        )

    sections = []
    for label, key in players:
        sections.append(f"{label}（{key}）弃牌：[{_tiles(state.discards.get(key, []))}]")
        sections.append(f"{label}（{key}）明牌：[{_melds(state.melds.get(key, []))}]")

    return f"""你是一位麻将大师，请根据以下局面给出出牌建议。

【规则】
- 144张牌：万饼条各36张 + 东南西北16张 + 中发白12张 + 季节花8张
- 花牌（东风、中发白、春夏秋冬梅兰竹菊）不能打出，可留着杠开，不参与胡牌结构
- 吃只能上家（left），碰三家都可以
- 胡牌：4组面子（顺子或刻子）+ 1对，或七对

【当前局面】
我的手牌：[{_tiles(state.my_hand)}]
我的花牌（未杠）：[{_tiles(state.flowers_in_hand)}]
{chr(10).join(sections)}
全桌剩余牌：{a.remaining_total} 张

【计算结果】（由确定性引擎给出，请直接采信，不要重新计算）
向听数：{shanten_desc}
进张牌：[{_tiles(a.ukeire)}]
{waiting_line}
候选出牌（按"打出后向听数"从小到大排序，越小越该保留进张）：
{candidates}

请分析：
1. 推断各对手可能在做什么牌型（结合他们的弃牌与明牌）
2. 评估每个候选出牌的风险和收益
3. 如果我有花牌，给出杠牌建议（是否该等听牌时杠开）
4. 给出最终推荐（3-5个选项）及简短理由
"""
