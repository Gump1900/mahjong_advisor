"""LLM advisor: orchestrate the engine into a prompt and call Claude.

Hybrid architecture: the engine computes deterministic facts (shanten, ukeire,
waiting tiles, discard ranking, remaining counts, risk labels) and the LLM
does the judgment layer — reading opponents, weighing risk vs. payoff, and
explaining the recommendation in natural language. The LLM never computes
shanten or tile counts.
"""
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..core.hand_analyzer import (
    calculate_shanten,
    get_ukeire,
    get_waiting_tiles,
    rank_discards,
)
from ..core.probability import (
    count_remaining_tiles,
    discard_risk,
    estimate_discard_risks,
)
from ..core.scoring import HELD_FLOWER_TIERS, kong_value
from ..core.tiles import GameState, Meld, Tile

# Default model per the claude-api skill (override via MAHJONG_ADVISOR_MODEL).
DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = (
    "你是麻将策略助手。下面的【计算结果】由确定性引擎给出（向听数、进张、听牌、"
    "剩余张数、出牌风险），请直接采信，不要重新计算或质疑这些数字。你的职责是读牌"
    "推理、权衡每张牌的风险与收益、并给出有理由的出牌建议。这套玩法一胡即终局"
    "（不是血流成河）：任意一家胡牌本局立即结束——把快胡的累积收益计入权衡，"
    "速度通常比牌型大小更重要。用通俗中文，不要用日式麻将术语（如两面/嵌张/雀头）。"
)


@dataclass
class AnalysisBundle:
    """Deterministic analysis of a game state, fed to the prompt and the UI."""

    shanten: int
    is_tenpai: bool
    ukeire: List[Tile]
    waiting: List[Tile]
    discards_ranked: List[Tuple[Tile, int]]
    risks: Dict[Tile, str]                    # coarse label, kept for the UI
    risk_estimates: Dict[Tile, Dict[str, float]]  # {chi, peng, ron, label}
    remaining: Dict[Tile, int]
    remaining_total: int
    kong_opportunities: List[Dict] = field(default_factory=list)
    discard_speed: Dict[Tile, Dict[str, int]] = field(default_factory=dict)  # 进张 per discard


def find_kong_opportunities(state: GameState) -> List[Dict]:
    """Kong-able assets the player can TIME (留花/择时杠 for the 杠开 shot).

    - 暗杠: 4 identical playable tiles concealed in hand
    - 加杠: a peng meld plus the drawn 4th copy in hand
    - 花牌自杠: 4 identical 中发白东 held un-konged (12花 vs 6花 held), and
      EVERY held season flower (春夏秋冬梅兰竹菊) — seasons score 1花 konged
      or held alike, so their kong value is purely the timing: kong at
      tenpai and win on the replacement draw = 杠开.
    """
    opps: List[Dict] = []
    hand_counts = Counter(t for t in state.my_hand if not t.is_flower)

    for tile, n in hand_counts.items():
        if n == 4:
            opps.append({
                "tile": tile, "kind": "暗杠", "hua": kong_value("an_gang", tile),
                "note": "4张在手，可留到听牌时再暗杠",
            })

    for m in state.my_melds:
        if m.type == "peng" and m.tiles and hand_counts.get(m.tiles[0], 0) >= 1:
            tile = m.tiles[0]
            opps.append({
                "tile": tile, "kind": "加杠", "hua": kong_value("ming_gang", tile),
                "note": f"碰{tile}后又摸到一张，可加杠（风刻+1升级为杠分）",
            })

    flower_counts = Counter(state.flowers_in_hand)
    for tile, n in flower_counts.items():
        if tile.suit == "三元" or (tile.suit == "风" and tile.value == "东"):
            if n >= 4:
                held = HELD_FLOWER_TIERS[4]
                opps.append({
                    "tile": tile, "kind": "花牌自杠", "hua": kong_value("an_gang", tile),
                    "note": f"留4张={held}花 / 杠=12花（暗杠后不算花）；留到听牌杠搏杠开",
                })
        elif tile.suit == "季节":
            opps.append({
                "tile": tile, "kind": "花牌自杠", "hua": 1,
                "note": "季节花杠/留都是1花，价值在时机：留到听牌杠搏杠开",
            })
    return opps


def analyze(state: GameState) -> AnalysisBundle:
    """Run the engine over the state and collect every fact the advisor needs."""
    hand = state.my_hand
    fuuro = len(state.my_melds)  # each called meld is a finished mentsu
    shanten = calculate_shanten(hand, fuuro)
    is_tenpai = shanten == 0
    discards_ranked = rank_discards(hand, fuuro)
    remaining = count_remaining_tiles(state)

    # 一胡即终局 -> 速度优先：同向听时，打出后进张（种数/活张数）多的排前面
    discard_speed: Dict[Tile, Dict[str, int]] = {}
    for tile, _after in discards_ranked:
        remaining_hand = list(hand)
        remaining_hand.remove(tile)
        ukeire = get_ukeire(remaining_hand, fuuro)
        discard_speed[tile] = {
            "types": len(ukeire),
            "tiles": sum(remaining.get(u, 0) for u in ukeire),
        }
    discards_ranked.sort(
        key=lambda x: (x[1], -discard_speed[x[0]]["tiles"], str(x[0]))
    )

    risks = {tile: discard_risk(tile, state) for tile, _ in discards_ranked}
    risk_estimates = {
        tile: estimate_discard_risks(tile, state) for tile, _ in discards_ranked
    }
    return AnalysisBundle(
        shanten=shanten,
        is_tenpai=is_tenpai,
        ukeire=get_ukeire(hand, fuuro),
        waiting=get_waiting_tiles(hand, fuuro) if is_tenpai else [],
        discards_ranked=discards_ranked,
        risks=risks,
        risk_estimates=risk_estimates,
        remaining=remaining,
        remaining_total=sum(remaining.values()),
        kong_opportunities=find_kong_opportunities(state),
        discard_speed=discard_speed,
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
        f"- 打 {tile}：打出后向听数 {after}；"
        f"进张 {a.discard_speed[tile]['types']}种/{a.discard_speed[tile]['tiles']}张（速度）；"
        f"点炮风险 {a.risks[tile]}"
        f"（被吃 {a.risk_estimates[tile]['chi']:.0%} / 被碰 {a.risk_estimates[tile]['peng']:.0%}"
        f" / 点炮 {a.risk_estimates[tile]['ron']:.0%}，启发式估计）；"
        f"该牌剩余 {a.remaining.get(tile, 0)} 张"
        for tile, after in a.discards_ranked[:6]
    ) or "- （没有可打牌）"

    kong_section = ""
    if a.kong_opportunities:
        kong_lines = [
            f"- {op['kind']} {op['tile']}：杠分 {op['hua']}花；{op['note']}"
            for op in a.kong_opportunities
        ]
        if a.is_tenpai:
            kong_lines.append(
                "（当前已听牌：现在杠任意一组，补牌成胡即杠开——底分8花替代2/4，"
                "且与番型/杠分/花全部叠加，上不封顶）"
            )
        kong_section = "【杠牌/杠开机会】\n" + "\n".join(kong_lines) + "\n\n"

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
- 本玩法一胡即终局（不是血流成河/血战到底）：任意一家胡牌本局立即结束、
  直接下一把——先胡先得，快胡的累积进账常常优于憋大牌，速度很重要

【当前局面】
我的手牌：[{_tiles(state.my_hand)}]
我的明牌：[{_melds(state.my_melds)}]
我的花牌（未杠）：[{_tiles(state.flowers_in_hand)}]
{chr(10).join(sections)}
全桌剩余牌：{a.remaining_total} 张

【计算结果】（由确定性引擎给出，请直接采信，不要重新计算）
向听数：{shanten_desc}
进张牌：[{_tiles(a.ukeire)}]
{waiting_line}
候选出牌（按"打出后向听数"从小到大排序，越小越该保留进张）：
{candidates}

{kong_section}请分析：
1. 推断各对手可能在做什么牌型（结合他们的弃牌与明牌）
2. 评估每个候选出牌的风险和收益；一胡即终局，把"快听快胡"的累积收益计入权衡
3. 结合【杠牌/杠开机会】：哪些杠该留到听牌时再开（搏杠开8花），哪些该现在开
4. 给出最终推荐（3-5个选项）及简短理由
"""


def get_advice(
    state: GameState,
    analysis: AnalysisBundle,
    *,
    client=None,
    model: str = None,
) -> str:
    """Ask Claude for discard advice. `client` is injectable for testing.

    Defaults to a real ``anthropic.Anthropic()`` (resolved from the environment)
    and ``claude-opus-5`` (overridable via ``model`` or MAHJONG_ADVISOR_MODEL).
    """
    import anthropic  # imported lazily so the module loads without the SDK

    if client is None:
        client = anthropic.Anthropic()
    model = model or os.environ.get("MAHJONG_ADVISOR_MODEL", DEFAULT_MODEL)

    response = client.messages.create(
        model=model,
        max_tokens=8192,  # headroom for adaptive thinking + the advice
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(state, analysis)}],
    )

    if response.stop_reason == "refusal":
        raise ValueError("模型因安全策略拒绝了这个请求，请换种问法或换一个模型。")

    text = "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    )
    return text.strip() or "（模型未返回文本）"
