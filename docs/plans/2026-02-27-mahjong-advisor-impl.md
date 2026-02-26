# Mahjong Advisor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Mahjong strategy assistant that recommends optimal discards using LLM + probability calculations.

**Architecture:** Hybrid system - Python calculation module for exact probabilities (shanten, remaining tiles, chi/peng risk) + LLM for opponent modeling and natural language advice.

**Tech Stack:** Python 3.11, pytest, anthropic SDK (Claude API)

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `src/core/__init__.py`
- Create: `src/llm/__init__.py`
- Create: `tests/__init__.py`

**Step 1: Create requirements.txt**

```txt
anthropic>=0.40.0
pytest>=8.0.0
```

**Step 2: Create directory structure**

```bash
cd /Users/gump/Work/projects/mahjong-advisor
mkdir -p src/core src/llm tests
touch src/__init__.py src/core/__init__.py src/llm/__init__.py tests/__init__.py
```

**Step 3: Install dependencies**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Step 4: Commit**

```bash
git add requirements.txt src/ tests/
git commit -m "chore: project setup with dependencies"
```

---

## Task 2: Tile Data Structure

**Files:**
- Create: `src/core/tiles.py`
- Create: `tests/test_tiles.py`

**Step 1: Write the failing test**

```python
# tests/test_tiles.py
import pytest
from src.core.tiles import Tile, Suit, create_tile, parse_tile

class TestTile:
    def test_create_wan_tile(self):
        tile = create_tile("万", 3)
        assert tile.suit == "万"
        assert tile.value == 3
        assert tile.is_flower == False

    def test_create_flower_tile(self):
        tile = create_tile("三元", "中")
        assert tile.suit == "三元"
        assert tile.value == "中"
        assert tile.is_flower == True

    def test_dong_feng_is_flower(self):
        tile = create_tile("风", "东")
        assert tile.is_flower == True

    def test_nan_feng_is_not_flower(self):
        tile = create_tile("风", "南")
        assert tile.is_flower == False

    def test_season_is_flower(self):
        tile = create_tile("季节", "春")
        assert tile.is_flower == True

    def test_parse_tile_string(self):
        tile = parse_tile("3万")
        assert tile.suit == "万"
        assert tile.value == 3

    def test_tile_equality(self):
        t1 = create_tile("万", 3)
        t2 = create_tile("万", 3)
        assert t1 == t2

    def test_tile_hash(self):
        t1 = create_tile("万", 3)
        t2 = create_tile("万", 3)
        assert hash(t1) == hash(t2)

    def test_tile_str(self):
        tile = create_tile("万", 3)
        assert str(tile) == "3万"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_tiles.py -v
```
Expected: FAIL with module import error

**Step 3: Write minimal implementation**

```python
# src/core/tiles.py
from dataclasses import dataclass
from typing import Literal, Union

Suit = Literal["万", "饼", "条", "风", "三元", "季节"]

@dataclass(frozen=True)
class Tile:
    suit: Suit
    value: Union[int, str]
    is_flower: bool = False

    def __str__(self) -> str:
        return f"{self.value}{self.suit}"

def create_tile(suit: Suit, value: Union[int, str]) -> Tile:
    """Create a tile with automatic flower detection."""
    is_flower = False

    # 东风是花牌
    if suit == "风" and value == "东":
        is_flower = True
    # 中发白是花牌
    elif suit == "三元":
        is_flower = True
    # 季节花是花牌
    elif suit == "季节":
        is_flower = True

    return Tile(suit=suit, value=value, is_flower=is_flower)

def parse_tile(s: str) -> Tile:
    """Parse tile from string like '3万', '东风', '中'."""
    if len(s) == 2 and s[1] in "万饼条":
        return create_tile(s[1] as Suit, int(s[0]))
    elif s == "东风":
        return create_tile("风", "东")
    elif s == "南风":
        return create_tile("风", "南")
    elif s == "西风":
        return create_tile("风", "西")
    elif s == "北风":
        return create_tile("风", "北")
    elif s in ["中", "发", "白"]:
        return create_tile("三元", s)
    elif s in ["春", "夏", "秋", "冬", "梅", "兰", "竹", "菊"]:
        return create_tile("季节", s)
    else:
        raise ValueError(f"Cannot parse tile: {s}")
```

**Step 4: Run test and fix**

```bash
pytest tests/test_tiles.py -v
```

**Step 5: Commit**

```bash
git add src/core/tiles.py tests/test_tiles.py
git commit -m "feat: add Tile data structure with flower detection"
```

---

## Task 3: GameState Data Structure

**Files:**
- Modify: `src/core/tiles.py`
- Create: `tests/test_game_state.py`

**Step 1: Write the failing test**

```python
# tests/test_game_state.py
import pytest
from src.core.tiles import Tile, create_tile, GameState, Meld, MeldType

class TestGameState:
    def test_create_game_state(self):
        state = GameState(my_hand=[])
        assert state.my_hand == []
        assert state.discards == {"left": [], "right": [], "opposite": []}

    def test_add_discard(self):
        state = GameState(my_hand=[])
        state.discards["left"].append(create_tile("万", 3))
        assert len(state.discards["left"]) == 1

    def test_meld_creation(self):
        meld = Meld(type="peng", tiles=[create_tile("万", 3)] * 3)
        assert meld.type == "peng"
        assert len(meld.tiles) == 3
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_game_state.py -v
```

**Step 3: Add to tiles.py**

```python
# Add to src/core/tiles.py
from typing import Literal, Union, Dict, List

MeldType = Literal["chi", "peng", "ming_gang", "an_gang"]

@dataclass
class Meld:
    type: MeldType
    tiles: List['Tile']

@dataclass
class GameState:
    my_hand: List['Tile']
    discards: Dict[str, List['Tile']] = None
    melds: Dict[str, List['Meld']] = None
    flowers_in_hand: List['Tile'] = None
    konged_flowers: List['Tile'] = None
    current_turn: Literal["me", "left", "right", "opposite"] = "me"

    def __post_init__(self):
        if self.discards is None:
            self.discards = {"left": [], "right": [], "opposite": []}
        if self.melds is None:
            self.melds = {"left": [], "right": [], "opposite": []}
        if self.flowers_in_hand is None:
            self.flowers_in_hand = []
        if self.konged_flowers is None:
            self.konged_flowers = []
```

**Step 4: Run test**

```bash
pytest tests/test_game_state.py -v
```

**Step 5: Commit**

```bash
git add src/core/tiles.py tests/test_game_state.py
git commit -m "feat: add GameState and Meld data structures"
```

---

## Task 4: Tile Counter (Remaining Tiles)

**Files:**
- Create: `src/core/probability.py`
- Create: `tests/test_probability.py`

**Step 1: Write the failing test**

```python
# tests/test_probability.py
import pytest
from src.core.tiles import create_tile, GameState
from src.core.probability import count_remaining_tiles, TileCounter

class TestTileCounter:
    def test_initial_count(self):
        counter = TileCounter()
        # 万饼条各36张
        assert counter.get_count(create_tile("万", 3)) == 4
        # 风牌各4张
        assert counter.get_count(create_tile("风", "南")) == 4
        # 三元各4张
        assert counter.get_count(create_tile("三元", "中")) == 4

    def test_remove_from_hand(self):
        counter = TileCounter()
        counter.remove(create_tile("万", 3), 2)
        assert counter.get_count(create_tile("万", 3)) == 2

    def test_count_remaining_from_state(self):
        hand = [create_tile("万", i) for i in range(1, 5)]  # 1-4万
        state = GameState(my_hand=hand)
        state.discards["left"] = [create_tile("万", 5)]

        remaining = count_remaining_tiles(state)
        assert remaining[create_tile("万", 1)] == 3  # 手牌有1张，剩3张
        assert remaining[create_tile("万", 5)] == 3  # 弃牌有1张，剩3张
```

**Step 2: Run test**

```bash
pytest tests/test_probability.py -v
```

**Step 3: Write implementation**

```python
# src/core/probability.py
from collections import defaultdict
from typing import Dict
from .tiles import Tile, create_tile, GameState

class TileCounter:
    """Tracks count of each tile type."""

    def __init__(self):
        self._counts: Dict[Tile, int] = defaultdict(int)
        self._initialize()

    def _initialize(self):
        # 万饼条各36张 (1-9各4张)
        for suit in ["万", "饼", "条"]:
            for value in range(1, 10):
                self._counts[create_tile(suit, value)] = 4
        # 风牌各4张
        for value in ["东", "南", "西", "北"]:
            self._counts[create_tile("风", value)] = 4
        # 三元各4张
        for value in ["中", "发", "白"]:
            self._counts[create_tile("三元", value)] = 4
        # 季节花各1张
        for value in ["春", "夏", "秋", "冬", "梅", "兰", "竹", "菊"]:
            self._counts[create_tile("季节", value)] = 1

    def get_count(self, tile: Tile) -> int:
        return self._counts.get(tile, 0)

    def remove(self, tile: Tile, count: int = 1):
        self._counts[tile] = max(0, self._counts[tile] - count)

def count_remaining_tiles(state: GameState) -> Dict[Tile, int]:
    """Calculate remaining tiles given game state."""
    counter = TileCounter()

    # Remove tiles from my hand
    for tile in state.my_hand:
        counter.remove(tile)

    # Remove tiles from my flowers
    for tile in state.flowers_in_hand:
        counter.remove(tile)
    for tile in state.konged_flowers:
        counter.remove(tile)

    # Remove tiles from discards
    for player_discards in state.discards.values():
        for tile in player_discards:
            counter.remove(tile)

    # Remove tiles from melds
    for player_melds in state.melds.values():
        for meld in player_melds:
            for tile in meld.tiles:
                counter.remove(tile)

    return dict(counter._counts)
```

**Step 4: Run test**

```bash
pytest tests/test_probability.py -v
```

**Step 5: Commit**

```bash
git add src/core/probability.py tests/test_probability.py
git commit -m "feat: add TileCounter for remaining tile calculation"
```

---

## Task 5: Shanten Calculator (Basic)

**Files:**
- Create: `src/core/hand_analyzer.py`
- Create: `tests/test_hand_analyzer.py`

**Step 1: Write the failing test**

```python
# tests/test_hand_analyzer.py
import pytest
from src.core.tiles import create_tile
from src.core.hand_analyzer import calculate_shanten, is_tenpai

class TestShanten:
    def test_complete_hand_shanten_zero(self):
        # 已经胡的牌型：123万 456饼 789条 中中中 发发
        hand = (
            [create_tile("万", i) for i in [1,2,3]] +
            [create_tile("饼", i) for i in [4,5,6]] +
            [create_tile("条", i) for i in [7,8,9]] +
            [create_tile("三元", "中")] * 3 +
            [create_tile("三元", "发")] * 2
        )
        assert calculate_shanten(hand) == 0

    def test_tenpai_shanten_zero(self):
        # 听牌：缺一张
        hand = (
            [create_tile("万", i) for i in [1,2,3]] +
            [create_tile("饼", i) for i in [4,5,6]] +
            [create_tile("条", i) for i in [7,8]] +  # 差一张
            [create_tile("三元", "中")] * 3 +
            [create_tile("三元", "发")] * 2
        )
        assert calculate_shanten(hand) == 0
        assert is_tenpai(hand) == True

    def test_one_shanten(self):
        # 一向听
        hand = (
            [create_tile("万", i) for i in [1,2,3]] +
            [create_tile("饼", i) for i in [4,5]] +  # 差两张
            [create_tile("条", i) for i in [7,8,9]] +
            [create_tile("三元", "中")] * 3 +
            [create_tile("三元", "发")] * 2
        )
        assert calculate_shanten(hand) == 1
```

**Step 2: Run test**

```bash
pytest tests/test_hand_analyzer.py -v
```

**Step 3: Write implementation (simplified shanten)**

```python
# src/core/hand_analyzer.py
from typing import List
from .tiles import Tile

def calculate_shanten(hand: List[Tile]) -> int:
    """
    Calculate shanten (向听数) - steps needed to reach tenpai.
    Simplified implementation for MVP.
    """
    # 过滤掉花牌
    non_flowers = [t for t in hand if not t.is_flower]
    n = len(non_flowers)

    # 简化算法：计算需要的面子数和对子
    # 标准胡牌需要 4个面子 + 1个对子 = 14张

    if n < 14:
        # 牌不够，返回最小向听
        return 8 - (14 - n) // 3

    # TODO: 实现完整的向听数算法
    # MVP阶段使用简化版本
    return _simple_shanten(non_flowers)

def _simple_shanten(hand: List[Tile]) -> int:
    """Simplified shanten calculation."""
    # 统计每种牌的数量
    tile_counts = {}
    for tile in hand:
        key = (tile.suit, tile.value)
        tile_counts[key] = tile_counts.get(key, 0) + 1

    # 计算对子数
    pairs = sum(1 for c in tile_counts.values() if c >= 2)

    # 计算刻子候选
    pungs = sum(1 for c in tile_counts.values() if c >= 3)

    # 简化：向听数 = 8 - 2*pairs - pungs (非常粗略的估计)
    shanten = max(0, 8 - pairs - pungs * 2)
    return min(shanten, 6)  # 最多6向听

def is_tenpai(hand: List[Tile]) -> bool:
    """Check if hand is tenpai (听牌)."""
    return calculate_shanten(hand) == 0

def get_ukeire(hand: List[Tile]) -> List[Tile]:
    """Get tiles that would improve the hand."""
    # MVP: 返回手牌中已有1-2张的牌
    tile_counts = {}
    for tile in hand:
        key = (tile.suit, tile.value)
        tile_counts[key] = tile_counts.get(key, 0) + 1

    ukeire = []
    for (suit, value), count in tile_counts.items():
        if 1 <= count <= 2 and count < 4:
            from .tiles import create_tile
            ukeire.append(create_tile(suit, value))

    return ukeire
```

**Step 4: Run test**

```bash
pytest tests/test_hand_analyzer.py -v
```

**Step 5: Commit**

```bash
git add src/core/hand_analyzer.py tests/test_hand_analyzer.py
git commit -m "feat: add basic shanten calculator"
```

---

## Task 6: LLM Advisor

**Files:**
- Create: `src/llm/advisor.py`
- Create: `tests/test_advisor.py`

**Step 1: Write the failing test**

```python
# tests/test_advisor.py
import pytest
from src.core.tiles import create_tile, GameState
from src.llm.advisor import build_prompt

class TestAdvisor:
    def test_build_prompt_includes_hand(self):
        hand = [create_tile("万", i) for i in [1,2,3]]
        state = GameState(my_hand=hand)
        prompt = build_prompt(state, shanten=2, ukeire=[])
        assert "1万" in prompt
        assert "2万" in prompt
        assert "3万" in prompt

    def test_build_prompt_includes_shanten(self):
        state = GameState(my_hand=[])
        prompt = build_prompt(state, shanten=2, ukeire=[])
        assert "向听数" in prompt
        assert "2" in prompt
```

**Step 2: Run test**

```bash
pytest tests/test_advisor.py -v
```

**Step 3: Write implementation**

```python
# src/llm/advisor.py
import os
from typing import List, Dict
from ..core.tiles import Tile, GameState

def build_prompt(state: GameState, shanten: int, ukeire: List[Tile]) -> str:
    """Build the LLM prompt with game state."""

    hand_str = ", ".join(str(t) for t in state.my_hand) or "无"
    flowers_str = ", ".join(str(t) for t in state.flowers_in_hand) or "无"
    ukeire_str = ", ".join(str(t) for t in ukeire) or "无"

    prompt = f"""你是一位麻将大师，请根据以下局面给出出牌建议。

【规则】
- 144张牌：万饼条各36张 + 风牌16张 + 中发白12张 + 季节花8张
- 花牌（东风、中发白、春夏秋冬梅兰竹菊）可留着杠开，不能打出
- 吃只能上家（left），碰三家都可以
- 有番就能胡

【当前局面】
我的手牌：[{hand_str}]
我的花牌（未杠）：[{flowers_str}]

上家（left）弃牌：[{', '.join(str(t) for t in state.discards['left']) or '无'}]
下家（right）弃牌：[{', '.join(str(t) for t in state.discards['right']) or '无'}]
对家（opposite）弃牌：[{', '.join(str(t) for t in state.discards['opposite']) or '无'}]

【计算结果】
向听数：{shanten}
进张牌：[{ukeire_str}]

请分析：
1. 推断各对手可能在做什么牌型
2. 给出3-5个出牌建议，每个包含：
   - 打哪张牌
   - 被吃/碰概率评估
   - 点炮风险
   - 简短理由
3. 如果有花牌，给出杠牌建议
"""
    return prompt

async def get_advice(state: GameState, shanten: int, ukeire: List[Tile]) -> str:
    """Get advice from LLM."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    prompt = build_prompt(state, shanten, ukeire)

    message = client.messages.create(
        model="claude-sonnet-4-6-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text
```

**Step 4: Run test**

```bash
pytest tests/test_advisor.py -v
```

**Step 5: Commit**

```bash
git add src/llm/advisor.py tests/test_advisor.py
git commit -m "feat: add LLM advisor with prompt builder"
```

---

## Task 7: Main Entry Point

**Files:**
- Create: `src/main.py`

**Step 1: Write main.py**

```python
# src/main.py
import asyncio
from .core.tiles import create_tile, parse_tile, GameState
from .core.hand_analyzer import calculate_shanten, get_ukeire
from .core.probability import count_remaining_tiles
from .llm.advisor import build_prompt, get_advice

def input_hand() -> list:
    """Input hand tiles from user."""
    print("请输入你的手牌（用空格分隔，如：1万 2万 3万 4饼 5饼）:")
    line = input().strip()
    if not line:
        return []
    return [parse_tile(s.strip()) for s in line.split()]

def input_discards(player: str) -> list:
    """Input discard tiles for a player."""
    print(f"请输入{player}的弃牌（用空格分隔，直接回车跳过）:")
    line = input().strip()
    if not line:
        return []
    return [parse_tile(s.strip()) for s in line.split()]

def main():
    print("=== 麻将策略助手 ===\n")

    # 输入手牌
    hand = input_hand()

    # 输入花牌
    print("请输入你手里的花牌（用空格分隔，直接回车跳过）:")
    flowers_line = input().strip()
    flowers = [parse_tile(s.strip()) for s in flowers_line.split()] if flowers_line else []

    # 创建游戏状态
    state = GameState(my_hand=hand, flowers_in_hand=flowers)

    # 输入各家弃牌
    state.discards["left"] = input_discards("上家(left)")
    state.discards["right"] = input_discards("下家(right)")
    state.discards["opposite"] = input_discards("对家(opposite)")

    # 计算向听数和进张
    shanten = calculate_shanten(hand)
    ukeire = get_ukeire(hand)

    print(f"\n【分析结果】")
    print(f"向听数：{shanten}")
    print(f"进张牌：{', '.join(str(t) for t in ukeire) if ukeire else '无'}")

    # 获取LLM建议
    print("\n正在获取AI建议...")
    try:
        advice = asyncio.run(get_advice(state, shanten, ukeire))
        print(f"\n【AI建议】\n{advice}")
    except Exception as e:
        print(f"获取建议失败: {e}")
        print("\n【Prompt预览】")
        print(build_prompt(state, shanten, ukeire))

if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add src/main.py
git commit -m "feat: add CLI main entry point"
```

---

## Task 8: Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

```python
# tests/test_integration.py
import pytest
from src.core.tiles import create_tile, GameState
from src.core.hand_analyzer import calculate_shanten, get_ukeire
from src.core.probability import count_remaining_tiles
from src.llm.advisor import build_prompt

class TestIntegration:
    def test_full_analysis_flow(self):
        # 模拟一局游戏
        hand = [
            create_tile("万", 1), create_tile("万", 2), create_tile("万", 3),
            create_tile("饼", 4), create_tile("饼", 5),
            create_tile("条", 7), create_tile("条", 8), create_tile("条", 9),
            create_tile("风", "南"), create_tile("风", "南"),
            create_tile("三元", "中"), create_tile("三元", "中"), create_tile("三元", "中"),
        ]

        state = GameState(my_hand=hand)
        state.discards["left"] = [create_tile("万", 9), create_tile("饼", 1)]

        # 分析
        shanten = calculate_shanten(hand)
        ukeire = get_ukeire(hand)
        remaining = count_remaining_tiles(state)

        # 构建prompt
        prompt = build_prompt(state, shanten, ukeire)

        assert "1万" in prompt
        assert shanten >= 0
        assert len(remaining) > 0
```

**Step 2: Run test**

```bash
pytest tests/test_integration.py -v
```

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration test"
```

---

## Task 9: README and Final Polish

**Files:**
- Create: `README.md`
- Create: `docs/rules.md`

**Step 1: Write README**

```markdown
# 麻将策略助手

基于 LLM + 概率计算的麻将出牌建议工具。

## 功能

- 手牌分析：计算向听数、进张牌
- 概率计算：剩余牌统计、吃碰概率
- AI建议：像麻将老手一样给出出牌建议

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 使用

```bash
export ANTHROPIC_API_KEY=your_key
python -m src.main
```

## 规则

详见 [docs/rules.md](docs/rules.md)

## 开发

```bash
pytest tests/ -v
```
```

**Step 2: Write rules.md**

```markdown
# 麻将规则

## 牌的构成（144张）

| 类型 | 张数 | 说明 |
|------|------|------|
| 万饼条 | 108张 | 各36张 |
| 东南西北 | 16张 | 东风是花牌 |
| 中发白 | 12张 | 花牌 |
| 春夏秋冬梅兰竹菊 | 8张 | 花牌 |

## 花牌规则

- 东风、中发白、季节花 = 花牌（共24张）
- 花牌不能打出，可留着杠开
- 杠开 = 8花

## 胡牌条件

- 四组一对
- 有番就能胡
```

**Step 3: Final commit**

```bash
git add README.md docs/rules.md
git commit -m "docs: add README and rules"
```

---

## Summary

9 tasks, TDD approach, each with clear steps:
1. Project setup
2. Tile data structure
3. GameState data structure
4. Tile counter
5. Shanten calculator
6. LLM advisor
7. Main entry point
8. Integration test
9. Documentation
