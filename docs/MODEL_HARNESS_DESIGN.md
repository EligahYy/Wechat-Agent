# 旧模型 Harness 评审：已归档

2026-11-08：此前基于 v0.5.4 的增量改造方案不再作为活动开发文档。完整旧稿见 Git 提交 `34c5145` 的本文件；它包含 v0.6.0 已交付能力及当时尚未实现的计划。

新的 [系统与 Agent 架构](SYSTEM_ARCHITECTURE.md) 统一定义单 Agent 执行、身份与范围、工具检索、客户文档、结构化变更、回放和预算。产品语义以 [产品方案](PRODUCT_DESIGN.md) 为准，是否可用以 [验收计划](ACCEPTANCE_PLAN.md) 为准。

继续采用本机 Python、SQLite、DeepSeek API 的轻量方向。一个 Agent 并不意味着任意改写 Markdown，也不意味着所有身份／业务规则都交给模型。运行方式见 [当前版本 SOP](DEPLOYMENT_SOP.md)。
