# 历史回归观察

从本机历史练习题库 taihu-history-v1-20261025 的 public 目录提取20份 case_id 与 input，供协议、事实和168个合法分支回归。只保留对应座位当时可见观察；不包含裁判牌墙、访问凭证、其他座位暗手或模型原始响应。这些是项目机器人实验局面，不是专家最优标签，也不是训练／胜率成绩。来源分类见 data/banks/taihu-history-v1.sources.json。

相邻 flower-speed-observation.json 提取自历史 rejected-seat-2 的 observation，仅用于未知补牌速度的解释回归；未保留模型响应和运行日志。测试不得依赖本机 runs 目录。
