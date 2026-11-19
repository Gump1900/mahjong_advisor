# 开发与验证

项目入口见[README](../README.md)，模块与迁移边界见[架构](architecture.md)。以下均在项目根目录执行，默认使用虚拟环境。命令的职责和付费边界分别说明，不把调试桌当正式多人服务。

## 环境与配置

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

`config/local.example.toml` 是模板；实际凭证用本机 `config/local.toml` 或对应环境变量，不提交。默认EV机器人与军师不需要模型API。历史LLM实验仍有独立配置与共享预算，只有显式授权才运行付费模式；本说明的验证命令不调用付费模型。

## 运行入口

```sh
# 跨端产品入口：好友房、访客同桌、服务器机器人
.venv/bin/python -m src.mobile.server --port 8773

# 旧大厅单人调试入口（保留）
.venv/bin/python -I scripts/lobby.py --port 8765 --table-port 8766

# 开发调试直达：会跳过大厅直接建立试打局
.venv/bin/python -I scripts/ev_table.py --port 8767

# 终端陪打：分别为开局、查看、执行明确动作
.venv/bin/python -I scripts/play_vs_bots.py new 42
.venv/bin/python -I scripts/play_vs_bots.py
.venv/bin/python -I scripts/play_vs_bots.py move '<动作id>'

# 原型浏览：打开 http://127.0.0.1:8878/prototype/
.venv/bin/python -m http.server 8878 --bind 127.0.0.1
```

主入口访问`http://127.0.0.1:8773/`；旧大厅为8765，旧牌桌8766只在明确开局后启用。调试与原型端口可改，不终止用户已有服务来抢端口。原型、真实裁判桌、正式联机是不同验证对象。

备用 `scripts/play_web.py` 是通过HTTP读取牌桌的军师侧栏；旧 `src/main.py`、`src/web.py` 等与可选LLM实验链仍保留兼容，非正式主入口。删除它们前核对调用方、替代能力与测试；不能为得到全绿而删除旧测试。

## 验证命令

```sh
.venv/bin/python -m pytest tests/ -q
node --test tests/*.test.cjs
.venv/bin/python scripts/ev_selfcheck.py 40
.venv/bin/python scripts/ev_reading_audit.py 2
.venv/bin/python scripts/taatsu_quiz.py --samples 64 --sample-prolog 300
.venv/bin/python scripts/self_play.py --hands 1
```

全量测试核对规则、接口和运行；自战检查结构、降级、异常及耗时；reading audit在冻结观察上比较历史／仅牌河，不能当胜率试验；quiz区分教学、牌谱、合成题；self_play默认离线代码机器人，只有显式`--llm`才进入付费实验。

策略变更用确定性反例及同墙轮换，分别报告策略／规则版本、样本范围、净得分、点炮、有效喂牌、耗时和波动。重复同牌墙的座位轮换按同一分组隔离训练／验证。题库分数与接口成功率不等于真人棋力；少数局完成不等于算法变强。

## 数据与证据

- `data/banks/taatsu-bank-v1.jsonl`：教学题；`taatsu-bank-prolog.jsonl`：牌谱来源题；`taatsu-bank-synthetic.jsonl`：合成完整性题。三类答案含义不同，不混作人类最优标签。
- `data/banks/taihu-history-v1.sources.json`：历史练习来源清单；`scripts/strategy_casebook.py`只导出座位当时可见问题，审阅者材料单独保存。先验推断与事后真值分别处理。
- `data/knowledge/experience.md`：24张经验卡与教学素材来源；`data/sources/`：可保存的字幕、摘录、视频素材。不再把题库放在docs。禁止再分发的外部牌谱不搬进仓库。
- `artifacts/evaluations/`：实验结果、文档迁移来源与历史原始说明；这是生成／证据数据，不是另一套规范。原实验目录和私有牌谱仍位于runs，既有代码与续局不做目录迁移。
- 任何测试数字都绑定具体命令、时间、代码指纹和范围；旧快照不当当前基线。保留失败原文及拒绝原因，不重写成已通过，不自动追加付费请求。

## 规范导出与运行时知识

```sh
.venv/bin/python -m pip install 'Markdown>=3.7,<4'
.venv/bin/python scripts/export_docs.py
```

七份主文档和原型规范只人工维护Markdown；HTML导出至`artifacts/docs/`，入口`index.html`。导出文件不手改、不提交。原型HTML是交互实现，仍在prototype维护。

可选LLM调用从`src/players/knowledge.py: load_knowledge()`即时读取规则、取舍原则、信息边界和复盘核对章节；不会优先读过期生成物。需落盘时`export_knowledge()`生成`artifacts/context/knowledge.md`供哈希／审计，规则变更自动失效重建。章节标题是该导出器的显式契约，修改时同步导出映射与回归。自定义知识与运行时选入的经验附录仍由compact_rules保留；线上数据不能修改职责和规则。

## 一次任务与提交

每次专注一个模块或问题。列明受影响调用方；规则、策略、表达、联机分别验证。提交写具体问题、改变后的行为和检查范围，不把“曾经试过什么”变成新设计文件。普通修复直接改对应正文，进度只改roadmap。

纯文档／资料整理与代码搬家分别进行。先保存未跟踪文件和工作区快照，再合并、更新消费者、核对链接，最后清理旧稿。私有快照位于忽略的var，生成物位于忽略的artifacts；协作交接基线单独提交；后续不把不同任务积累成混合工作区。

## 交互检查

组件状态 → Flow分支 → App完整路径；真实网页检查空态、加载失败、响应仲裁、重复／过期动作、等待、听牌常驻、军师折叠、结算和重连。长牌河与花牌极限是区域容量测试，不伪装成合法的同时144张牌谱。网络或客户端更改不得泄露暗手、种子或未来墙。

## 跨端房间、手机模拟器与小程序

运行 `python3 -m src.mobile.server --port 8773`，打开 <http://127.0.0.1:8773/>；小程序“连接设置”填写相同地址。开好友桌、把6位房间号交给另一端加入，各自准备，房主补齐机器人并明确开局。支持1～4位真人；每位玩家需要独立访客凭证，网页测试可使用不同浏览器资料／无痕环境。默认没有军师，无LLM费用。原生WXML工程、局域网配对和平台验收边界见[客户端说明](../clients/miniprogram/README.md)。

共享桌通过服务端后台推进、客户端只读轮询同步；没有客户端“暂停整桌／下一步”。单人“手机适配测试桌”保留尺寸、安全区、场景、暂停和逐步调试。两种模式的凭证和桌不混用；旧8766／8767调试桌不并入共享桌。

共享存档默认 `runs/shared-rooms/state.json`，包含私有凭证和全知牌谱，权限600；同路径只允许一个服务持有文件锁。开发隔离测试可用 `--rooms-state <另一个私有路径>`，两端仍必须指向同一实例。普通断线后重连或刷新继续；服务重启后保留房间、座位、待响应与各自暗手。不要清除本地访客记录来模拟断线。主动离开会中止正在进行的这一局，并保留私有归档；正常结算后返回房间重新准备。

已验证双网页独立身份同桌、微信开发者工具原生客户端同桌双向动作，以及服务实际停止／重启后两端旧凭证与手牌一致。手机真机、微信正式登录与公网部署尚未验收。

## 协作交接

先读根目录 [AGENTS.md](../AGENTS.md) 的模块边界，再读本模块对应正文。建议 Python 3.11、Node.js 22 及以上；Node 使用内置测试运行器，无需 npm install。默认运行与测试不需要 API 密钥。GitHub Actions 执行 Python 全量回归、客户端测试和规范 HTML 导出。

首次启动会自行创建 runs、var 等本机目录；这些目录、config/local.toml、微信 project.private.config.json 都不随仓库交接。不要拷贝原开发者访客凭证或私有牌谱。data/banks/taihu-history-v1.sources.json 是来源索引，其引用的旧 runs 日志属于可选研究输入，干净克隆不附带这些私有材料。回归必需的20份座位可见观察已单独收录 tests/fixtures/history，测试不依赖本机历史日志。下载视频位于忽略的 data/sources/video，不是启动依赖。

功能分支从交接基线创建，一次 PR 聚焦一个模块；涉及公共观察、动作、计分或协议时，同时标明调用方。提交前运行上面的 Python 和 Node 检查；界面改动额外走入口→房间→牌桌→结算流程。现有预期失败用 pytest 原因跟踪，不通过删测试或泛化忽略来消除。正式真机、登录与公网部署仍未验收。
