# 原型设计系统

[总入口](index.html) · [微信小程序原型](miniprogram/index.html) · [组件](blocks/index.html) · [产品流程地图](flows/product.html) · [牌桌流程](flows/index.html) · [完整App](app/index.html) · [唯一设计规范](design.md)

Block→Flow→App复用同一实现；Git保存修订，不复制日期或版本稿。

| 调整内容 | 文件 |
| --- | --- |
| 手机组件／流程／App | blocks/mobile.js；flows/miniprogram.js；app/miniprogram.js |
| 手机评审画板样式 | shared/miniprogram.css |
| 牌、同排副露、听牌、军师等基础组件 | blocks/ui.js；catalog.js检验状态 |
| 动作／取消／确认与桌内流程 | flows/table-interactions.js；definitions.js |
| 房间、准备、开局、离开权限 | flows/product-flow.js |
| 大厅／房间／牌桌页面组合 | app/navigation.js |
| 场景、右侧说明 | shared/scenarios.js；annotations.js |
| 画板、样式、素材 | shared/ |

在项目根目录运行 `python3 -m http.server 8878`，打开 `http://127.0.0.1:8878/prototype/`；也可直接打开静态HTML。场景目录以可交互页面为准，未知情况与原型边界见design。

原型是本地演示，不是实际多人服务。正式启动、调试与测试见[开发说明](../docs/development.md)，玩法见[规则](../docs/rules.md)。


小程序稿采用390×844竖屏入口／房间／结算、844×390横屏牌桌；这是一种待评审的横竖屏方案，不调用真实微信接口或设备方向API。页面内的“纯净预览”隐藏评审工具；通过左侧场景和右侧说明审查状态，主流程也可以从首页逐步点击。当前小程序稿不包含军师，原有桌面原型不受影响。

真实试打另见[手机模拟器与原生小程序](../clients/miniprogram/README.md)，运行于8770端口；本目录继续保存设计样例，不将样例分数或假动作当作裁判结果。
