# 开发计划索引

更新：2026-11-16（北京时间）。[STATUS](../../STATUS.md)是唯一执行位置：M1与M2任务1—7代码及审查修复完成；真实业务质量待Mac验证。Mac实机结果单列，不把能力检查或来源同步当作档案质量验收。

| 状态 | 计划 | 交付 |
| --- | --- | --- |
| 云端实施及整体CR完成 | [整理准入与结果反馈](2026-11-16-organize-outcomes.md) | 按已知范围整理、客户结果隔离、准确记录；45个回放场景已运行，589后端／36单元／71浏览器通过；Mac待实测 |
| 本轮维护完成 | [原文查询性能](2026-11-15-message-query-optimization.md) | 来源／日期统一、索引、缓存和本地导航；0b42eac已交付，回到M2主线 |
| 主线：M2实机验收待核对 | [M2单客户档案](2026-11-11-m2-customer-profile.md) | 任务1—7云端代码及重要审查项已完成，云端／实机验收分别记录 |
| 文本子阶段云端完成 | [M3文本长历史与恢复](2026-11-16-m3-text-history.md) | 分段、字段／批次归纳、持久检查点和进度；实机待核对 |
| 附件下一步 | [M3长历史与附件](2026-11-11-m3-history-media.md) | 来源获取／解析及附件证据；M3不整体标完成 |
| 待开始 | [M4控制与日调度](2026-11-11-m4-operations-scheduler.md) | 批量、继续／重试、每日运行 |
| 待开始 | [M5质量与交付](2026-11-11-m5-quality-delivery.md) | 真实样本、重算、升级恢复与Mac交付 |
| 已归档维护 | [仓库收敛](../../archive/plans/2026-11-15-repository-consolidation.md) | 归档、最新入口和同轮原文反馈已验收 |

**编号按各自计划区分：原文性能计划的Task4已完成，只表示该维护验收完成；M2主计划Task4—6也已交付，任务7云端代码已验收，实机门槛保留。** M3文本子阶段已优先交付，继续附件与实机核对，再推进M4调度、M5质量交付。

已完成M0／M1、联系人修复、业务范围、发言导航与日历计划在[归档索引](../../archive/README.md)。归档计划保留当时的命令与测试，不作为当前状态。

共同依据：[产品](../../PRODUCT_DESIGN.md)、[交互](../../INTERACTION_DESIGN.md)、[模型执行](../../MODEL_EXECUTION.md)、[实施架构](../../IMPLEMENTATION_PLAN.md)、[内部接口](CONTRACTS.md)。有效补充为[业务范围](../specs/2026-11-13-business-contacts-design.md)、[日历双栏](../specs/2026-11-15-timeline-calendar-design.md)与[原文统一查询](../specs/2026-11-15-message-query-optimization-design.md)。

代码位于src/wechat_agent与frontend，测试为tests与frontend单元／E2E，安装脚本位于scripts；归档原型不参与运行或开发门槛。Python3.12、Node最低24.14.1及hash锁文件保持；原始聊天、凭据、运行库及.local证据不入Git。

按用户选择用executing-plans串行完成，TDD后验证，重要变更结束前一次独立只读审查。检查后直接非强制推main；Mac只pull、build、运行和验证。源端命令、真实模型和容量未知时显式待验证，不猜协议或伪造成功。
