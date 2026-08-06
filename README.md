# 麻将策略助手（Mahjong Advisor）

基于"计算引擎 + LLM 推理"的混合架构，像麻将老手一样读牌、给出出牌建议。

> 当前为 **Phase 1：核心引擎**。手牌分析（向听数、进张、听牌、出牌候选）与剩余牌统计已可用；LLM 读牌推理与命令行界面在 Phase 2。

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
| `hand_analyzer.py` | 向听数（标准形 + 七对取最小）、听牌、进张、出牌候选排序。 |
| `probability.py` | 全 144 张计数器；按局面统计各牌剩余张数。 |

向听约定：**胡牌 = -1，听牌 = 0**。听牌/进张会枚举所有合法拆法并取并集——例如：

```
手牌 23456 (配两组完成面子)  -> 听 1,4,7
手牌 2345666                 -> 听 1,2,4,5,7（两种拆法并集）
```

### 数据模型约定

`GameState` 中 `my_hand` 放**可组牌**，持有的花牌放 `flowers_in_hand`（已杠的放 `konged_flowers`）。**不要把同一张花牌同时放进 `my_hand` 和 `flowers_in_hand`**，否则剩余牌统计会重复扣减。

## 使用

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 运行测试
python -m pytest -v
```

> 注意：本仓库的 `.venv/bin/pytest` 入口指向一个旧路径（shebang 失效），请用 `python -m pytest` 调用。

```python
from src.core.tiles import create_tile
from src.core.hand_analyzer import calculate_shanten, get_waiting_tiles, rank_discards

hand = [create_tile("万", i) for i in (2, 3, 4, 5, 6)] \
     + [create_tile("饼", 1)] * 3 + [create_tile("条", 2)] * 3 \
     + [create_tile("风", "南"), create_tile("风", "南")]
print(calculate_shanten(hand))          # 0  (听牌)
print(get_waiting_tiles(hand))          # [1万, 4万, 7万]
```

## Phase 2 路线图

- `src/llm/advisor.py`：构建局面 prompt + 调用 Claude API，给出读牌推理与出牌建议。
- `src/main.py`：命令行交互（输入手牌/弃牌/明牌 → 输出建议）。
- 概率风险启发式：被吃/被碰/点炮概率（结合剩余牌统计与对手弃牌）。
- 计分（花数、杠开）。
