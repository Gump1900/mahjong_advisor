"""Legacy offline analysis exports. Unchecked paid prose is disabled."""
from typing import List
from ..core.tiles import GameState, Meld, Tile
# Compatibility exports for existing library callers.
from ..decision.models import AnalysisBundle
from ..decision.service import analyze, find_kong_opportunities

# Compatibility constant only; get_advice no longer constructs a paid client.
DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = (
    "你是麻将策略助手。下面的向听数、进张、听牌、未见张数由确定性引擎计算。"
    "出牌风险数值只是未经实战校准的启发式指标，不是确定事实或精确概率。你的职责是读牌"
    "推理、权衡每张牌的风险与收益、并给出有理由的出牌建议。这套玩法一胡即终局"
    "（不是血流成河）：任意一家胡牌本局立即结束——把快胡的累积收益计入权衡，"
    "速度通常比牌型大小更重要。用通俗中文，不要用日式麻将术语（如两面/嵌张/雀头）。"
    "回答保持简洁：推理点到为止，最终建议用列表呈现。"
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
        f"（未经校准的启发式标签，不是概率）；"
        f"该牌未见 {a.remaining.get(tile, 0)} 张"
        for tile, after in a.discards_ranked[:6]
    ) or "- （没有可打牌）"

    kong_section = ""
    if a.kong_opportunities:
        kong_lines = [
            f"- {op['kind']} {op['tile']}："
            f"{'本次花分增量' if op.get('hua_basis') == 'flower_score_delta' else '杠分'} "
            f"{op['hua']}花；{op['note']}"
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
        sections.append(f"{label}已知花牌：[{_tiles(state.opponent_flowers.get(key, []))}]；"
                        f"已杠花牌：[{_tiles(state.opponent_konged_flowers.get(key, []))}]；"
                        "花牌记录可能不完整，未记录不代表无花")

    return f"""你是一位麻将大师，请根据以下局面给出出牌建议。

【规则】
- 144张牌：万饼条各36张 + 东南西北16张 + 中发白12张 + 季节花8张
- 花牌（东风、中发白、春夏秋冬梅兰竹菊）不能打出，可留着杠开，不参与胡牌结构
- 吃只能上家（left），碰三家都可以
- 胡牌：4组面子（顺子或刻子）+ 1对，或七对；无花不能接炮，只能自摸
- 接炮资格看花牌、南西北风刻和杠分；清一色、碰碰胡等加分项不提供接炮资格
- 无花普通自摸每家固定6点，再加适用牌型分；有花自摸底4、放炮底2、杠开底8替代
- 中发白东可以单张杠，同款持有和单张杠合并按1/2/4/6计分；四张一起暗杠12点
- 本玩法一胡即终局（不是血流成河/血战到底）：任意一家胡牌本局立即结束、
  直接下一把——先胡先得，快胡的累积进账常常优于憋大牌，速度很重要
- 同一张弃牌可一炮多响，放炮者分别向所有胡牌者付钱；自摸由其余三家支付
- 杠分只有自己最终胡牌才结算；黄庄所有人收入为零
- 对手已知花牌影响其胡牌价值和放炮损失，花多不代表已经听牌

【当前局面】
我的手牌：[{_tiles(state.my_hand)}]
我的明牌：[{_melds(state.my_melds)}]
我的花牌（未杠）：[{_tiles(state.flowers_in_hand)}]
{chr(10).join(sections)}
剩余未见牌：{a.remaining_total} 张（包含对手暗牌，不是牌墙长度）

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
    """Fail before client construction, authentication or any request.

    GameState lacks the complete referee observation needed by strategy-v2.
    Do not invent missing state or preserve an unguarded billing escape hatch.
    Offline analyze/build_prompt exports remain for existing callers.
    """
    raise ValueError("旧版自由文字LLM接口已关闭，未产生API调用；离线计算仍可用。请使用桌面strategy-v2受约束军师。")
