# 实施文档

更新：2026-11-11（北京时间）。以仓库清空后重新讨论的产品和最新交互为基线，不沿用重建前方案。

1. [产品方案](PRODUCT_DESIGN.md)：范围、身份、档案模板、批次、同步与资料状态。
2. [交互方案](INTERACTION_DESIGN.md)：两页导航、无侧栏档案、公共控件、动效和时间选择。
3. [实施方案](IMPLEMENTATION_PLAN.md)：技术底座、模型链路、统一操作、接口及 M0–M5 验收。
4. [模型执行方案](MODEL_EXECUTION.md)：实际请求组织、上下文快照、长历史、失败恢复及模型／Agent 升级。
5. [开发工作流](DEVELOPMENT_WORKFLOW.md)：Superpowers 项目级安装、固定版本与开发使用约定。
6. [Mac 初始化](MAC_SETUP.md)：拉取仓库、恢复技能及运行现有原型。
7. [M0–M5 开发计划](superpowers/plans/README.md)：六份逐任务计划及共享接口；M0采样与M1分页归档幂等已在Mac通过，联系人读取已在Mac通过；持久化同步操作已在Mac通过；正式React页面与统一控件云端完成、实机待验，下一项为原文浏览及导入。

[交互原型](../ui-prototype/preview.html)提供效果参照，只有示例数据，尚未连接真实服务。

冲突处理：用户后续明确调整优先，先同步有效文档再实现。不要从历史实现、旧截图、原型计时器或过期中间稿推导业务规则。

[归档概要](archive/README.md)只记录删除及替代情况，不保存另一份旧产品方案。

[M0开发与验证报告](verification/m0-report.md) · [M1开发与验证报告](verification/m1-report.md) · [Mac验证记录](verification/mac-validation.md)
