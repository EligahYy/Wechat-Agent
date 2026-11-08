# 历史方案摘要

当前唯一活动设计：[产品方案](../PRODUCT_DESIGN.md)、[系统与 Agent 架构](../SYSTEM_ARCHITECTURE.md)、[验收与实施计划](../ACCEPTANCE_PLAN.md)。当前运行版操作见 [SOP](../DEPLOYMENT_SOP.md)。

| 历史阶段 | 被替代的方向 | 保留位置 |
| --- | --- | --- |
| 早期人工 CRM | 先手建商家／项目、绑定会话、逐条接受待办，用户负担过大 | 早期 Git 历史；旧分散文档已收口 |
| 模型 Harness 增量草案 | 为原分片管线持续增加 Prompt 和规则 | `2cd2e61` 的 `docs/MODEL_HARNESS_DESIGN.md` |
| v0.6 评审与增量实施 | 补身份、范围、源证据与响应回放，但未形成客户完整生命周期 | `34c5145` 的 `docs/MODEL_HARNESS_DESIGN.md` |
| 客户与批次全量重建草案 | 客户文档方向明确，但仍需统一业务边界、媒体、发布顺序和效果验收 | `34c5145` 的 `docs/AI_CRM_DESIGN.md` |

保留的技术资产：wx-cli只读适配、已有密钥迁移、消息修订与历史断点、身份同步、鉴权、模型网络客户端、用量台账和响应缓存。新业务体系不继承旧 AI 客户／待办状态；消息、免跟进规则、明确用户偏好和账单必须保留。

2026-11-08：暂停未发布的文档引擎实施草稿，恢复运行代码基线；本次只交付整体产品、技术和验收方案。旧设计文件保留简短跳转，全文从 Git 查看，不复制多套相互冲突的规范。

本轮开始M0实施；旧AI_CRM_DESIGN、MODEL_HARNESS_DESIGN及UX_REVIEW_PROTOTYPE文件已删除。完整旧内容可从提交a47f99b及以前的Git历史读取。当前实施范围见 [实施状态](../IMPLEMENTATION_STATUS.md)。
