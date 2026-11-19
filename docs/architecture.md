# 架构

这是目标边界与当前映射，不能把目标树当作已完成的物理迁移。本次文档整理不迁移 `src/`、不重命名包、不移动运行数据。

## 模块与依赖

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| 规则／引擎 | 牌、合法动作、摸打与响应、计分、观察脱敏、事件与重放 | 选择打法、连接和页面 |
| 房间／联机 | 身份、座位、准备、开局、同步、重连、机器人任务调度 | 重写吃碰杠胡与计分 |
| 策略 | 向听进张、对手推断、动作评估、风格与策略版本 | 直接修改牌局或读取他家真值 |
| 客户端 | 大厅、房间、牌桌、结算、交互与展示状态 | 最终裁定动作和分数 |
| 军师／复盘 | 建议编排、理由、候选、当时信息与事后真值分开回看 | 为已选动作编理由、阻塞对局 |
| 实验室 | 数据采集、回归、自战、对比、校准 | 在正式对局中静默训练或升级权重 |

网页／小程序 → 房间与连接层 → 引擎。引擎生成座位观察 → 策略；机器人建议由房间层校验时效后提交。军师消费相同观察与分析，展示层不回写计算结果。初期可在一个服务和仓库中保持这些边界。

## 当前代码归属

| 当前路径 | 职责与后续去向 |
| --- | --- |
| `src/core/tiles.py`、`round_rules.py`、`scoring.py` | rules模型、合法性、结算 |
| `src/core/hand_analyzer.py`、`probability.py` | 共用规则计算／策略分析；先补引用核对，拆职责时不改行为 |
| `src/core/math_core.py`、`src/decision/ev.py` | strategy分析与评估 |
| `src/decision/belief.py`、`reading.py`、`dynamic_reading.py` | strategy推断与采样 |
| `src/decision/call_pressure.py`、`call_decision.py`、`ev_bot.py` | 动作比较、策略和观察适配 |
| `src/decision/ev_coach.py`、`receipts.py`、`replay_review.py` | coaching建议、回执、复盘 |
| `src/simulation/engine.py`、`state.py`、`observation.py`、`replay.py` | rules引擎、完整状态、座位观察、重放 |
| `src/simulation/hidden_world.py` | 另一条物理采样路径；与belief的职责整合要单独验证 |
| `src/simulation/web.py`、`webapp/`、`src/webapp/table_ui_patch.py` | 当前调试桌服务、界面与注入层；正式客户端拆出前继续复用 |
| `clients/miniprogram/`、`src/mobile/server.py` | 原生WXML客户端＋浏览器设备模拟器，共用展示模型和交互控制器；独立陪练与跨端访客同桌入口；非正式公网服务 |
| `src/rooms/network.py` | 共用RoomService／规则引擎的跨端访客房间：座位授权、冻结响应窗口、服务端机器人、状态同步与原子存档 |
| `src/rooms/`其余模块、`scripts/lobby.py` | 房间生命周期与旧大厅入口；旧8765/8766路径保留独立调试，不作为跨端入口 |
| `src/players/base.py`、`analysis.py`、`solo_search.py`、`search_player.py` | 玩家契约、分析和搜索复用；不能当作整包遗留删除 |
| `src/players/llm.py`及grounded／table协议族、`src/llm/`、根main/session/web | 可选／兼容实验与旧入口，仍有调用方；退役需先确认替代能力 |
| `scripts/play_web.py` | 备用军师侧栏，通过HTTP访问牌桌，不依赖旧src/web.py |
| `scripts/`、`src/simulation/runner.py`、`experiment.py` | 保留薄入口；离线编排后续归lab |

旧 `decision/models.py`、`service.py`、`risk.py` 仍被旧会话／Web／LLM链和测试引用；不因主线改用EV就认定无人使用。`players/config.py` 是凭证配置读取，非训练脚本。材料和数据移动时必须同步消费者，不能只改文件树。

## 稳定接口与不变量

| 接口 | 当前入口 | 约束／尚缺内容 |
| --- | --- | --- |
| 动作执行 | `Table.apply(seat, action_id, controller, reason)` | 引擎校验合法动作；HTTP的version校验和身份认证由上层负责；非法动作不偷偷修正 |
| 合法动作 | `observe(table, seat)["legal_actions"]` | discard、chi、peng、ming_gang、an_gang、add_gang、flower_kong、pass、win、ron；仅提供当前可执行项 |
| 座位观察 | `src/simulation/observation.py: observe` | 只有本人暗手；他家暗杠／摸牌脱敏；策略唯一输入，未来墙和裁判真值不外泄 |
| 策略 | `EVBot.choose(obs)`、`rank_candidates(state)` | 输出当前合法action_id与依据；异步任务须核对局面版本，过期结果丢弃 |
| 军师 | `EVCoach.explain(payload)` | 返回strategy-v2、summary、explanation、verification_note，可含brief／reading；首屏用brief，详细分析折叠 |
| 牌谱／回执 | `replay(json)`、`save_receipt`、`load_receipts` | 裁判真值与用户可见回放分开；实验记录策略／规则版本；重放确定性 |

真实消息结构将在 `contracts/` 建立机器可验证的单一来源；当前没有完整联机JSON Schema，不用本表代替协议实现。observer标识、对局版本、请求标识和动作id用途分别明确，不能用昵称或房号授权控制座位。

动作流程：识别身份与座位 → 校验对局／请求版本与幂等 → 引擎执行并完成响应仲裁 → 追加事件 → 逐座位生成可见更新 → 客户端呈现 → 仅在新决策时调度机器人／军师。GET不创建对局或触发付费。

## 随机性与信息存储

当前引擎基于显式种子的伪随机洗牌；网页默认种子来自系统随机源，测试可复现。重放保存初始牌墙，不重新洗牌。这个检查不等于正式联机随机性已验收。

正式对局目标为服务端不可由玩家指定的随机性，不向客户端暴露种子、完整牌墙或未来牌序，不按输赢、身份或牌力定向配牌。随机算法和部署选型另行验证；开发实验仍可注入种子／牌墙。

当前私有续局和日志继续位于 `runs/`，不因目录规划擅自移动。目标var存私有运行数据，artifacts存实验和生成物；公开样例仅放脱敏data。凭证模板可入库，config/local.toml与实际密钥不入库。

## 目标文件树

下面是逐步迁移的终态；未开工的客户端、契约、部署目录无需预先创建空壳。

```text
mahjong_advisor/
├── README.md                         # 当前主线、启动方式、文档入口
├── pyproject.toml                    # Python 项目与检查配置
├── .gitignore
├── .env.example                      # 配置项示例，无真实密钥
│
├── backend/                          # 服务端与可离线复用的领域代码
│   ├── pyproject.toml                 # 后端包、依赖与运行配置（迁移时统一）
│   └── src/mahjong/
│       ├── __init__.py
│       ├── app.py                    # 组装服务、路由与依赖的启动入口
│       ├── rules/                    # ① 规则与对局引擎
│       │   ├── models/               # 牌、手牌、副露、动作、座位
│       │   ├── legality/             # 胡牌、吃碰杠、资格与限制
│       │   ├── engine/               # 状态、发牌、摸打、响应与终局
│       │   ├── scoring/              # 分项计分与支付结算
│       │   ├── visibility/           # 座位观察与信息脱敏
│       │   ├── replay/               # 事件、牌谱、恢复与版本兼容
│       │   └── versions/             # 明确支持的规则版本配置
│       ├── rooms/                    # ② 房间与联机的业务逻辑
│       │   ├── identity.py           # 玩家身份抽象
│       │   ├── room.py               # 房间、座位、准备与生命周期
│       │   ├── service.py            # 创建、加入、开局与动作调度
│       │   ├── sessions.py           # 在线状态与重连
│       │   └── bot_scheduler.py      # 补位、托管与机器人任务
│       ├── strategy/                 # ③ 机器人与策略
│       │   ├── interfaces.py         # 观察与合法动作 → 决策
│       │   ├── analysis/             # 向听、进张、牌形与通用分析
│       │   ├── inference/            # 对手推断与概率模型
│       │   ├── evaluation/           # 收益、风险与动作评估
│       │   ├── policies/             # 基础、数学、搜索等策略实现
│       │   ├── profiles/             # 版本、风格与难度配置
│       │   └── adapters/             # 引擎观察与动作适配
│       ├── coaching/                 # ⑤ 军师与复盘
│       │   ├── advice.py             # 实时建议编排
│       │   ├── explanation.py        # 依据、解释与候选比较
│       │   ├── review.py             # 关键决策复盘
│       │   └── playback.py           # 面向用户的回放查询
│       ├── transport/                # ② 的网络接入实现
│       │   ├── http/                 # 请求入口，具体方式待选型
│       │   ├── realtime/             # 实时消息连接与推送
│       │   ├── auth/                 # 网页与微信身份接入适配
│       │   └── schemas/              # 消息校验与协议转换
│       └── storage/                  # ②⑤ 的持久化适配
│           ├── repositories/         # 房间、对局、牌谱等存取接口
│           └── migrations/           # 选定数据库后的结构变更
│
├── clients/                          # ④ 客户端与交互设计
│   ├── web/                          # 正式网页客户端
│   │   ├── src/
│   │   │   ├── pages/                # 大厅、房间、牌桌、结算与复盘
│   │   │   ├── components/           # 麻将牌、手牌、副露、操作面板
│   │   │   ├── game/                 # 本地展示状态与动画编排
│   │   │   ├── network/              # 请求、订阅、重连与确认
│   │   │   └── assets/               # 网页专用资源
│   │   └── tests/
│   ├── miniprogram/                  # 微信小程序，已有原生开发版
│   │   ├── pages/
│   │   ├── components/
│   │   ├── services/                 # 登录、网络与状态同步
│   │   ├── assets/
│   │   └── tests/
│   └── shared/                       # 实际可复用时再建立共享代码
│       ├── protocol/                 # 生成的协议类型与消息辅助
│       └── presentation/             # 与框架无关的展示映射
│
├── contracts/                        # 模块边界上的公共契约
│   ├── protocol/                     # 客户端消息定义、错误码和版本
│   └── examples/                     # 脱敏的消息与状态示例
├── lab/                              # ⑥ 离线实验，不进入正式业务链
│   ├── self_play/                    # 零真人四机器人批量对抗
│   ├── evaluation/                   # 同墙轮换、基线对比与统计
│   ├── training/                     # 参数拟合与独立模型训练
│   ├── casebooks/                    # 题库构建、判卷与回归
│   ├── audits/                       # 历史牌局与解释审计
│   └── debug_table/                  # 开发专用调试牌桌
├── tests/                            # 跨后端模块和端到端验证
│   ├── rules/
│   ├── rooms/
│   ├── strategy/
│   ├── coaching/
│   ├── contracts/
│   ├── integration/
│   └── fixtures/
├── data/
│   ├── banks/                        # 版本化题库与来源说明
│   └── samples/                      # 可公开的脱敏样例牌谱
├── artifacts/                        # 实验输出和候选模型，默认忽略
├── var/                              # 本地运行数据与私有牌谱，默认忽略
├── assets/                           # 有授权的共用素材与来源记录
├── scripts/                          # 薄启动入口、构建与迁移工具
├── config/                           # 配置模板；本机配置不提交
├── deploy/                           # 服务部署与环境配置
├── prototype/                       # Block → Flow → App，规范见design.md
└── docs/                            # 七份主文档，入口见根README
    ├── product.md
    ├── architecture.md
    ├── rules.md
    ├── strategy.md
    ├── development.md
    ├── roadmap.md
    └── decisions.md
```

`clients/shared` 仅在存在明确可复用代码时建立。前端框架、实时传输、数据库与部署尚待选型，不为目录命名提前做决定。

## 渐进迁移

文档与资料整理 → 原位梳理共用分析职责 → 逐模块迁移strategy／coaching → 正式网页与联机边界 → 实验工具归lab。每次只处理一类职责，列受影响调用方，验证结果相对基线无新增失败；不强制先做完所有改名才推进产品。当前大厅／房间基础保持使用。

## 跨端开发版协议

统一入口为 `src.mobile.server`（推荐8773）；网页与原生WXML客户端共用 `/api/rooms/`。单人适配测试仍使用 `/api/session` 路径，互不控制；旧8766／8767桌也不自动并入共享房间。

| 入口 | 用途与权限 |
| --- | --- |
| POST identity；GET profile | 显式创建访客、检查已有凭证；昵称不授权 |
| POST create／join；GET state | 开房／6位房号入座／读取当前成员视角；GET不建局不推进 |
| POST bots／ready／start | 房主补空位、各自准备、房主明确开局；下一局重新准备 |
| POST action／flowers | X-Session映射到固定座位；当前version＋action_id＋request_id校验；不接受客户端指定裁判座位 |
| POST leave／retry | 主动离桌中止当前局；机器人异常可重试，旧窗口任务结果丢弃 |

当前以约700ms只读轮询同步；机器人由服务端后台推进，不依赖客户端step。响应窗口中的玩家选择先私下收集，直到本窗口需要的座位均已响应才原子应用；同一窗口的版本不因另一玩家先响应而失效。机器人用窗口入口冻结的脱敏观察决策。客户端不会收到其他座位选择或暗手；终局后才允许摊牌。

共享房间、访客凭证、牌谱、待响应选择与有界幂等记录原子写入 `runs/shared-rooms/state.json`，权限600；进程文件锁防止两个服务写同一存档。离桌／换局前的全知牌谱归档到同目录archives，不能作为公开素材。两端旧凭证可以在服务重启后恢复原房间、座位与手牌。短暂断网只显示离线，不自动中止或接管；开发版明确离桌才中止，房主离开由仍在房中的第一位真人接任。正式超时、托管、房间回收与房主转让政策仍待产品验收。
