# 太湖麻将

网页与微信小程序共用裁判的四人太湖麻将产品。访客联机开发版已支持1～4位真人同桌、机器人补位、准备开局与结算；微信真机、正式登录与上线仍待验收，军师深入优化暂停。

## 开始使用

```sh
.venv/bin/python -m src.mobile.server --port 8773
```

打开 <http://127.0.0.1:8773/>，开好友桌或输入6位房间号加入；真人准备、房主补齐机器人后明确开局。原生小程序连接同一服务地址即可同桌。默认EV机器人无需模型API。环境、调试入口及验证见[开发说明](docs/development.md)。

## 唯一文档入口

| 要了解什么 | 文档 |
| --- | --- |
| 产品范围与用户流程 | [产品](docs/product.md) |
| 模块、接口、现状与目标树 | [架构](docs/architecture.md) |
| 完整太湖麻将玩法 | [规则](docs/rules.md) |
| 自身优化、动态读牌、攻守、军师 | [策略](docs/strategy.md) |
| 运行、测试、评测、资料与HTML导出 | [开发](docs/development.md) |
| 当前进度与下一步 | [路线图](docs/roadmap.md) |
| 重要取舍与教训 | [决策](docs/decisions.md) |
| 页面、牌桌、空态和交互 | [原型规范](prototype/design.md) · [桌面原型](prototype/index.html) · [微信小程序原型](prototype/miniprogram/index.html) |

每个主题维护同一正文，修订交给Git。原型遵循Block→Flow→App；生成的HTML位于`artifacts/docs/`，运行时知识从主文档生成。现有代码目录保持原位，未来代码树是渐进迁移目标。

跨端同桌与手机试打：`python3 -m src.mobile.server --port 8773` → <http://127.0.0.1:8773/>。原生微信工程与导入步骤见 [小程序开发说明](clients/miniprogram/README.md)。

## 参与开发

先按[开发说明](docs/development.md)创建环境，再阅读[协作边界](AGENTS.md)。推荐 Python 3.11、Node.js 22+；默认运行不需要模型密钥。主入口是8773跨端服务，旧网页和LLM链仅作兼容／研究，不在其中新增产品功能。
