# Web UI 重设计（v2）——设计文档

> 日期：2026-08-17（修订 2026-08-20，已吸收评审意见：4×P1 + 3×P2）
>
> 状态：v1 评审后修订，待用户复审
>
> 背景：Web UI v1 被"打回重做"。头脑风暴确认四项核心需求：独立摸牌位、我的鸣牌
> 自动检测提示、分析标注在牌上、牌桌视角布局。v1 版 spec 经评审发现后端状态机与
> 事件契约缺失（我的碰/吃/胡无执行接口、放炮胡无法计分、张数校验不支持鸣牌、
> 花牌杠按钮与四张成杠规则冲突、弃牌无稳定标识、摸牌位仅前端、剩余数公式错误），
> 本版全部修正，核心是引入 `GameSession` 最小状态机。

---

## 1. 目标与非目标

**目标**

1. 交互像"点着打牌"：开局点选起手牌、点摸牌位声明摸牌、点任意牌打出。
2. 对手打出一张牌后，系统自动提示我能碰/吃/胡，点击即执行（含完整后端语义）。
3. 引擎分析直接标注在手牌上，右栏保留详表与 AI 建议。
4. 牌桌视角布局，每家面板内嵌动作按钮。
5. 胡牌（自摸/放炮/杠开）由**显式确认动作**进入终局状态，一键算花。
6. 后端持有完整对局状态（阶段、待响应弃牌、摸牌位、胡牌信息），撤销与刷新不丢。

**非目标**

- 不改向听/计分/风险算法；
- 不引入前端框架与构建链；
- 不做对手手牌模拟；
- 不强制回合轮转顺序（对手动作按实际发生自由记录，校验只针对"我"的摸/打/鸣牌）。

## 2. 布局

```text
┌─────────────────────────────────────────────────────┐
│ 上家●(内嵌[打][碰][吃][杠])   对家(…)   下家(…)        │
 │  各家：弃牌河（按打出顺序）+ 明牌 + 已打出张数           │
├──────────────────────────────┬──────────────────────┤
│ [碰][吃…][胡！][过] ←提示条    │ 状态行：阶段+听牌/向听  │
│ 我的花牌区（季节花逐张[杠]；     │ 候选详表（进张+风险%）  │
│   中发白东集满4张才显示[杠]）    │ 杠牌/杠开机会           │
│ 我的明牌区                    │ [问LLM] + 输出          │
│ [暗牌·点击打出] [◌摸牌位]      │ [算花]（胡后）           │
│ 我的弃牌河                    │ [撤销] [新对局]          │
└──────────────────────────────┴──────────────────────┘
```

## 3. 交互流（按打牌节奏，含阶段）

| # | 操作 | 前端行为 | 后端事件 |
|---|---|---|---|
| 1 | 开局 | 全屏牌库点选 13 张（按牌种剩余数禁用）+ 起手花 | `POST /api/new`（副本上限校验） |
| 2 | 我摸牌 | 点摸牌位 → 牌库 → 点那张 → 落入摸牌位高亮 | `摸 X`（阶段须 need_draw） |
| 3 | 我打牌 | 点暗牌或摸牌位任意一张 → 进我的河；摸牌位清空 | `打 X`（阶段须 need_discard） |
| 4 | 对手打牌 | 点那家 [打] → 牌库选牌 → 进其河；**提示条刷新** | `l/r/o + X` → 设置 pending_discard |
| 5 | 我响应 | 提示条显示 [碰]/[吃 <组合>]/[胡！]/[过]，点击即执行 | `我碰 X` / `我吃 A B C` / `胡` / `过` |
| 6 | 对手碰/吃/杠 | 点那家对应按钮选牌（吃选 3 张） | `r碰 X` 等 → 校验并消费 pending |
| 7 | 我的杠 | 手里 4 张同款→浮 [暗杠]；碰后摸回第 4 张→浮 [加杠]；季节花逐张 [杠]；中发白东集满 4 张显示 [杠]（一次杠 4 张） | `an X` / `ka X` / `kg X` |
| 8 | 胡牌 | 状态行"已胡+所胡牌"；[算花] 弹窗显示明细 | `胡`（原子记录，见 §5.4） |

## 4. 分析标注

- 每张暗牌（含摸牌位）上方徽标：打出后向听/进张数；牌边框风险色环（安全绿/中黄/危险红）；
- 候选表第一名加"推荐"角标并在牌上高亮；
- 右栏：状态行（阶段 + 听牌/向听 + 所胡牌 + 全桌剩余）、候选详表（进张种/张、
  吃/碰/炮百分比）、杠牌/杠开机会、[问LLM]（失败折叠 Prompt 预览）、[算花]、[撤销][新对局]。

## 5. 后端状态机与事件契约（新增核心）

### 5.1 GameSession（`src/session.py` 新增类）

```python
@dataclass
class GameSession:
    state: GameState            # 现有局面（手牌/河/明牌/花牌）
    phase: str                  # "need_draw" | "need_discard" | "won"
    discard_seq: int            # 弃牌单调计数器
    pending: Optional[dict]     # {"id", "player", "tile"} 最新一张待响应弃牌；可为 None
    drawn_tile: Optional[Tile]  # 摸牌位（后端持有，随快照撤销/刷新恢复）
    win: Optional[dict]         # {"method","tile","source"}；见 5.4
    konged_this_turn: bool      # 本回合是否杠过（杠开判定用）：杠事件置 True，我打出后清零
    history: list               # GameSession 整体 deepcopy 快照栈
```

- 撤销 = 弹出快照恢复**整个 GameSession**（含 pending/drawn_tile/win），刷新安全；
- CLI `run_session` 同步迁移到 GameSession（原有事件语法不变，新增 §5.2 事件）。

### 5.2 期望暗牌数与阶段校验

```text
base(N) = 13 − 3×N     其中 N = len(my_melds)
合法暗牌数：base（=need_draw，等摸牌）或 base+1（=need_discard，须打一张）
```

- `摸 X` 仅当 `len(hand)==base`；`打 X` 仅当 `len(hand)==base+1`；
- 碰/吃后：N+1、手牌 −2 → 恰为 `base(N+1)+1` → 自动进入 need_discard（**不摸牌直接打**）；
- 暗杠：N+1、手牌 −4 → `base(N+1)` → need_draw（补牌）；
- 加杠：N 不变、手牌 −1 → `base` → need_draw（补牌）；
- 杠花：手牌不变 → 阶段不变（need_draw 时杠花后仍补牌；need_discard 时杠花后直接打）；
- 对手动作不改变我的阶段（自由记录），但会更新 pending。

### 5.3 事件全集（parse_event 扩展）

| 事件 | 语法 | 语义与校验 |
|---|---|---|
| 我摸牌 | `摸 X` | need_draw；`remaining(X)>0`（防第 5 张）；花牌入 flowers_in_hand；drawn_tile=X |
| 我打牌 | `打 X` | need_discard；X 在手且非花；入我的河；drawn_tile 清空；设 pending（我打的牌对手也可响应） |
| 我碰 | `我碰 X` / `me碰 X` | pending 活跃且 X==pending.tile 且 can_peng；手牌移 2 张 X；**按 pending.id 精确取走那张河牌**；my_melds+=peng；阶段→need_discard |
| 我吃 | `我吃 A B C` | pending 活跃、pending.player==left、pending.tile∈{A,B,C} 且 can_chi 对应组合；手牌移除另两张；按 id 取河牌；my_melds+=chi；→need_discard |
| 过 | `过` / `pass` | 仅清 pending（记录该 id 已过），不改其他状态 |
| 我胡 | `胡` | 见 5.4 |
| 对家打 | `l X` 等 | `remaining(X)>0`；入河；设 pending={id,player,tile} |
| 对家碰/吃/杠 | `r碰 X` 等 | **校验 X==pending.tile**；按 id 精确取走 pending 那张（不再全河反查）；入其 melds；清 pending |
| 对家暗杠 | `l暗杠 X` | 无河牌交互，4 张入 melds（罕见场景补齐） |
| 杠花 | `kg X` | 季节花：移 1 张；**中发白东：要求 flowers_in_hand 中该款恰 4 张，一次移 4 张**，否则报错 |
| 暗杠/加杠 | `an X` / `ka X` | 现有校验不变；an/ka 后阶段→need_draw（补牌） |
| 新对局 | `POST /api/new` | 起手牌逐种校验不超副本上限（普通牌/中发白东≤4，季节花≤1） |

### 5.4 胡牌（原子终局事件）

`win = {"method": "zimo"|"dianpao"|"gangkai", "tile": Tile, "source": player|None}`

- **放炮（ron）**：pending 活跃且 `can_ron(hand + pending.tile, fuuro)`；点 [胡！] →
  记录 `{dianpao, tile=pending.tile, source=pending.player}`；**该牌留在对方河中不动**
  （计分时构造 `my_hand + [tile]`）；阶段→won；
- **自摸**：need_discard 且 `shanten(hand)==-1` → UI 出 [胡·自摸]；确认记录
  `{zimo, tile=drawn_tile, source=None}`；→won；
- **杠开**：`konged_this_turn == True` 且摸补牌后成胡 → [胡·杠开]；
  记录 `{gangkai, tile=drawn_tile}`；→won；
- won 后除 撤销/新对局 外事件全部拒绝；不允许仅凭 `shanten==-1` 自动进入 won，
  必须显式确认。

### 5.5 撤销

任何事件前压栈 `deepcopy(GameSession)`；[撤销] 弹栈整体恢复——pending、
drawn_tile、win、阶段随快照一致恢复，天然解决"撤销打牌后摸牌位丢失"。

## 6. 引擎新增（`src/core/hand_analyzer.py`，纯函数 + 单测）

```python
can_peng(hand, tile) -> bool
can_chi(hand, tile) -> list[list[Tile]]   # 全部吃法（含边张/嵌张）：
    # tile=3万 且手里有 1,2 / 2,4 / 4,5 万 → [[1万,2万],[2万,4万],[4万,5万]]
    # 纯手牌判断；"只有上家能吃"由调用方（状态机）控制
can_ron(hand, tile, fuuro=0) -> bool       # calculate_shanten(hand+[tile],fuuro)==-1
```

## 7. Web 接口（`src/web.py`）

| 接口 | 入参 | 出参 |
|---|---|---|
| `POST /api/new` | `{hand, flowers}` | ok/错误（副本上限校验） |
| `POST /api/event` | `{line}` | 事件语法见 §5.3；错误返回可读中文 |
| `GET /api/state` | — | `{state, analysis, flow}`；`flow = {phase, drawn_tile, pending:{id,player,tile}, win, remaining_by_tile}` |
| `GET /api/legal` | — | **基于当前 pending 计算**（无需前端传牌）：`{pending:{id,player,tile}, peng, chi:[[..]], ron}`；无 pending 时全空 |
| `POST /api/score` | `{win_method?}` | 有 win 记录用之（放炮构造 `hand+[tile]`），否则用入参做假设计分；返回 `{hua, flowers, breakdown}` |
| `POST /api/advice` | — | 现有逻辑不变 |

- `remaining_by_tile`：**按牌种**的剩余（普通牌/中发白东上限 4，季节花上限 1，减已见），
  供牌库点选禁用；全桌总数另给（`analysis.remaining_total`）。

## 8. 状态归属

| 状态 | 归属 |
|---|---|
| 局面（手牌/河/明牌/花牌） | 后端 GameState |
| 阶段 / pending(含 id) / drawn_tile / win | 后端 GameSession（随快照撤销） |
| 出牌候选/风险/杠开机会/分种剩余 | 后端 analyze + flow |
| 我的可碰/吃/胡 | 后端 /api/legal（按 pending 实时算） |
| "已过"的提示 | 后端（过=消费该 pending id；同牌再次被打会生成**新 id** 重新提示） |
| 界面临时态（弹层开合等） | 前端 |

## 9. 边界与防错

| 场景 | 处理 |
|---|---|
| 张数阶段 | 按 §5.2 以 `len(my_melds)` 计算；碰/吃后直接进入打牌；杠后进入补牌 |
| 副本上限 | 开局/摸牌/对手弃牌/对手明牌录入时逐种校验（>上限直接报错），杜绝静默钳 0 |
| 单张"中"点杠 | kg 对中发白东要求 4 张成杠，一次移 4；季节花才允许逐张 |
| 弃牌误取旧牌 | 一切取河牌动作按 pending.id 精确执行，不再按牌名反查 |
| 同名牌二次打出 | 每次弃牌新 id；过只消费当前 id |
| 摸牌位丢失 | 后端持有 drawn_tile，刷新/撤销一致恢复 |
| 提示与手动操作 | 提示条不阻塞输入；其它操作默认视为过（pending 被新事件覆盖时自然失效） |
| 任何输错 | [撤销] 整快照回退 |

## 10. 测试

- 引擎：can_chi（边/嵌/多组合/字牌不可吃）、can_peng、can_ron（含 fuuro）；
- GameSession：阶段流转（摸→打、碰后直接打、杠后补牌）、我碰/我吃的扣牌与按 id 取河、
  过与新 id、放炮/自摸/杠开 win 记录、kg 的季节花 vs 四张成杠、副本上限校验、撤销整体恢复；
- Web：/api/legal 基于_pending（上家吃/非上家不吃、能胡）、/api/score 用 win 记录
  （放炮构造胡牌张）、/api/state.flow 完整性；模式沿用线程起服 + urllib；
- 前端：无框架不上自动化 UI 测试，API 测试 + 用户上手验收。

## 11. 文件变化

- **重写**：`src/webapp/index.html`（前端 v2）；
- **大改**：`src/session.py`（新增 GameSession 状态机、事件扩展、校验；CLI run_session 迁移）；
- **修改**：`src/web.py`（/api/legal 重定义、/api/score、/api/state.flow）、
  `src/core/hand_analyzer.py`（+3 函数）；
- **不变**：向听/计分/风险算法、CLI 一次性模式、AI 建议链路与 Prompt、
  `src/core/tiles.py`、`src/core/scoring.py`、`src/core/probability.py`。
