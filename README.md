# 麻将策略助手（Mahjong Advisor）

基于"计算引擎 + LLM 推理"的混合架构，像麻将老手一样读牌、给出出牌建议。

> **Phase 1（核心引擎）+ Phase 2（LLM 顾问 + 命令行）已完成。** 引擎算出确定性事实（向听/进张/听牌/出牌候选/剩余张数/风险），LLM 负责读牌推理与出牌建议；命令行可交互使用。计分（花数/杠开）仍待做。

## 规则基线

- **144 张牌**：万饼条各 36 张 + 东南西北 16 张 + 中发白 12 张 + 季节花 8 张。
- **可组牌**（参与"4 组面子 + 1 对"的胡牌结构）= 万饼条 1-9 + 风牌 **南/西/北**，共 30 种。
  - 数字牌可顺子/刻子；南西北是字牌，只能刻子/对子，无顺子。
- **花牌**（不参与结构，不可打出，可留着杠开）= **东风 + 中发白 + 春夏秋冬梅兰竹菊**。
- **胡牌形态**：
  1. 标准形：4 组面子（顺子或刻子）+ 1 对；
  2. 七对：7 个对子（门清）。
  - 听牌形式（单吊/边张/嵌张/两面/双碰等）由向听算法自动检测，无需单独配置。

## Phase 1 能力（`src/core/`）

| 模块 | 说明 |
|------|------|
| `tiles.py` | 牌的数据结构、创建/解析、花牌判定、30 种可组牌索引。 |
| `hand_analyzer.py` | 向听数（标准形 + 七对取最小，**支持明牌后按 4−N 组面子算**）、听牌、进张、出牌候选排序。 |
| `probability.py` | 全 144 张计数器；剩余张数；`discard_risk` 三档标签；`estimate_discard_risks` 给被吃/被碰/点炮的启发式概率估计。 |
| `scoring.py` | 花数计分：实现设计文档已列的规则（4明刻=5花/4暗刻=10花/杠开=8花不封顶）+ 每张花牌1花；其余番型是显式扩展点 `PATTERN_TABLE`。 |

向听约定：**胡牌 = -1，听牌 = 0**。听牌/进张会枚举所有合法拆法并取并集——例如：

```
手牌 23456 (配两组完成面子)  -> 听 1,4,7
手牌 2345666                 -> 听 1,2,4,5,7（两种拆法并集）
```

### 数据模型约定

`GameState` 中 `my_hand` 放**可组牌**，持有的花牌放 `flowers_in_hand`（已杠的放 `konged_flowers`）。**不要把同一张花牌同时放进 `my_hand` 和 `flowers_in_hand`**，否则剩余牌统计会重复扣减。

## Phase 2 能力（`src/llm/` + `src/main.py`）

| 模块 | 说明 |
|------|------|
| `advisor.py` | `analyze(state)` 编排引擎产出结构化结果；`build_prompt` 按模板拼局面；`get_advice` 调 Claude 给读牌建议。 |
| `probability.py` 的 `discard_risk` | 启发式点炮风险（安全/中/危险，非精确概率）。 |
| `main.py` | 交互式命令行。 |

**混合架构**：引擎负责确定性数字（向听数、进张、听牌、剩余张数、出牌候选排序、风险标签），**绝不**让 LLM 算这些；LLM 只做读牌、风险评估解释、出牌综合建议。

## 使用

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 运行测试
python -m pytest -v
```

> 注意：本仓库的 `.venv/bin/pytest` 入口指向一个旧路径（shebang 失效），请用 `python -m pytest` 调用。

### 命令行助手

```bash
export ANTHROPIC_API_KEY=your_key      # 或先 ant auth login
python -m src.main
# 可选：换更省更快模型（默认 claude-opus-5）
export MAHJONG_ADVISOR_MODEL=claude-sonnet-5
```

分步输入手牌（暗牌）→ 花牌 → 自己的明牌 → 上家/下家/对家弃牌，先打印【分析结果】（向听/听牌/进张/出牌候选/剩余张数/风险估计），再请求【AI建议】。**没有 API key 或网络不通时不会崩溃**，会退化为只展示分析结果 + 给模型的 Prompt 预览。

明牌写法：`peng 5饼`、`chi 3万 4万 5万`、`ming_gang 9条`、`an_gang 南风`，多组用空格或逗号分隔（全角逗号也行）。碰过之后手牌只输剩下的暗牌，向听会按"还差 4−明牌数 组面子"计算。

计分（作为库）：

```python
from src.core.scoring import score_hand
from src.core.tiles import create_tile, Meld

result = score_hand(
    hand=[create_tile("万", i) for i in (1, 2, 3, 4, 5, 6)],  # 暗牌
    my_melds=[Meld("peng", [create_tile("饼", 5)] * 3)],
    flowers=["中"],          # 持有的花牌名
    win_method="gangkai",    # zimo / dianpao / gangkai
)
print(result.hua, result.breakdown)
```

> **计分口径（待你校准）**：目前只实现了设计文档列出的三条（4明刻=5花、4暗刻=10花、杠开=8花上不封顶）+ 约定的"每张花牌 1 花"。其他番型（对对胡/清一色/七对…）在 `src/core/scoring.py` 的 `PATTERN_TABLE` 留了扩展点，补上完整花数表即可。风险估计同理是透明启发式（公式写在 `estimate_discard_risks` 的 docstring 里），不是精确概率。

### 作为库

```python
from src.core.tiles import create_tile
from src.core.hand_analyzer import calculate_shanten, get_waiting_tiles, rank_discards

hand = [create_tile("万", i) for i in (2, 3, 4, 5, 6)] \
     + [create_tile("饼", 1)] * 3 + [create_tile("条", 2)] * 3 \
     + [create_tile("风", "南"), create_tile("风", "南")]
print(calculate_shanten(hand))          # 0  (听牌)
print(get_waiting_tiles(hand))          # [1万, 4万, 7万]
```

## 后续路线图

- 补全花数表（对对胡/清一色/字一色/七对…）——填 `PATTERN_TABLE` 即可。
- 风险估计从透明启发式升级（结合对手听牌推断）。
- Web UI / 拍照识别 / 语音输入（设计文档 Phase 3-5）。
