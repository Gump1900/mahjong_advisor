"""Interactive CLI for the mahjong advisor.

Run with:  python -m src.main
Set ANTHROPIC_API_KEY (or run `ant auth login`) for live AI advice; without it
the tool prints the engine analysis and a prompt preview instead of crashing.
"""
from .core.tiles import GameState, parse_tile
from .llm.advisor import analyze, build_prompt, get_advice


def _join(tiles) -> str:
    return " ".join(str(t) for t in tiles)


def _input_tiles(prompt: str):
    line = input(prompt).strip()
    if not line:
        return []
    return [parse_tile(s) for s in line.split()]


def _print_analysis(a) -> None:
    print("\n【分析结果】")
    if a.shanten == -1:
        print("已经胡了！")
    elif a.shanten == 0:
        print(f"听牌！胡：{_join(a.waiting) or '（无）'}")
    else:
        print(f"向听数：{a.shanten}（还差 {a.shanten} 步听牌）")
        print(f"进张牌：{_join(a.ukeire) or '无'}")
    print(f"全桌剩余牌：{a.remaining_total} 张")
    print("出牌候选（按打出后向听数排序，越小越值得保留进张）：")
    for tile, after in a.discards_ranked[:6]:
        print(
            f"  - 打 {tile}：打出后向听数 {after}；"
            f"点炮风险 {a.risks[tile]}（该牌剩余 {a.remaining.get(tile, 0)} 张）"
        )


def main() -> None:
    print("=== 麻将策略助手 ===\n")
    print("牌的写法：3万 / 9条 / 1饼 / 东风 / 南风 / 中 / 春 等，用空格分隔。")
    print("（东风、中发白、春夏秋冬梅兰竹菊是花牌，写在“花牌”那行，不要写进手牌）\n")

    hand = _input_tiles(
        "请输入你的手牌（如：2万 3万 4万 5万 6万 6万 6万 1饼 1饼 1饼 2条 2条 2条）:\n> "
    )
    flowers = _input_tiles("请输入你手里的花牌（未杠，直接回车跳过）:\n> ")

    state = GameState(my_hand=hand, flowers_in_hand=flowers)
    for label, key in (
        ("上家(left)", "left"),
        ("下家(right)", "right"),
        ("对家(opposite)", "opposite"),
    ):
        state.discards[key] = _input_tiles(f"请输入{label}的弃牌（直接回车跳过）:\n> ")

    analysis = analyze(state)
    _print_analysis(analysis)

    print("\n正在获取 AI 建议...")
    try:
        advice = get_advice(state, analysis)
        print(f"\n【AI建议】\n{advice}")
    except Exception as e:  # noqa: BLE001 - surface any failure, then fall back
        print(f"\n获取 AI 建议失败：{e}")
        print("（设置 ANTHROPIC_API_KEY 或 `ant auth login` 后可获取 AI 建议；")
        print(" 下面是给模型的 Prompt 预览，可自行复制使用。）\n")
        print("【Prompt 预览】")
        print(build_prompt(state, analysis))


if __name__ == "__main__":
    main()
