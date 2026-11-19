# 协作约定

## 主线与上手

太湖麻将网页和微信小程序共用裁判。唯一产品入口：`python -m src.mobile.server --port 8773`。环境与检查见 `docs/development.md`，完整当前映射和目标树见 `docs/architecture.md`。军师深度优化暂停。不要把目标树当成已完成迁移。

## 模块边界

- `src/core/`、`src/simulation/{engine,state,observation,replay}.py`：规则、裁判、脱敏和重放。修改需核对策略与房间调用方，客户端不能代判规则。
- `src/rooms/`、`src/mobile/`：房间、身份、响应仲裁、同步、持久化与HTTP；不重写规则。
- `src/decision/`、`src/players/`：策略、观察适配、军师与可选实验。只使用座位可见信息，不能读取未来墙或他家暗手。
- `clients/miniprogram/`：原生客户端与网页模拟器；shared中共用展示、交互、声音和连接。两端变化都要检查。
- `prototype/`：Block → Flow → App设计；不是正式裁判。`scripts/`为启动、构建与离线实验入口。
- 旧 `src/main.py`、`session.py`、`web.py`、`llm/`、`src/webapp/`及调试桌仍有调用方。不要整包删除，也不要在旧入口新增主线产品功能。退役另开任务。

## 每次修改

一次任务聚焦一个模块。跨模块改动先列调用方与验证范围；不混入无关重命名、格式化或目录迁移。不自动创建日期版设计稿，修订七份主文档或prototype/design.md对应正文。README只保留入口和导航。

验证：`python -m pytest tests/ -q`、`node --test tests/*.test.cjs`；文档变更运行 `python scripts/export_docs.py`。默认离线，不运行付费LLM实验。策略变化另外做确定性反例与同墙对照；界面变化检查实际交互，不能只凭单元测试宣布验收。

私有凭证、牌谱、运行状态、下载视频和生成物不提交。不清除已有runs/var，不占用或终止他人服务。微信真机、正式登录、公网部署尚未验收，不描述为已上线。每个任务提交具体问题、行为和验证结果；不自动推送、部署或联系他人。
