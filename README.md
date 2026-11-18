# 半托管欧区备货用户助手

从本机微信私信与群聊归档资料，管理业务联系人，并逐步生成有来源、可纠正的商家档案。

**当前主线为 M3 附件获取与解析。** M3 文本 workflow-v4 云端修复已交付，数据库自动升级至 schema 19。真实商家质量与时延待 Mac 核对。[整理链路验收](docs/verification/organize-review-followup.md)

最新反馈修复见[单次额度与引用纠正](docs/verification/output-allocation.md)，避免把1M上下文直接当作单次输出。

此前[输出截断恢复与程序组装](docs/verification/output-recovery.md)：多次完整结构化回复经校验后合并，失败保留检查点。

本轮[文本长历史与恢复验收](docs/verification/m3-text-history.md)说明处理范围、重试预算与实测边界。

已补充[整理链路、结果反馈与架构审查](docs/verification/organize-outcomes-report.md)：已知范围完整即可整理，真实会话缺口按客户阻断；记录显示客户名、原因和动作。

已实现同步归档、业务联系人与全量管理、身份与人工范围覆盖、日历原文、来源／搜索／本人定位、导入，以及真实资料卡／备货／人工编辑／单号／来源证据。模型连接检查与独立文档预算核对完成后可执行单客户文本整理，无变化跳过模型，停止或版本冲突不发布旧结果。已支持文本超窗分段、按字段／批次归纳和有效检查点复用；实际附件解析与每日调度尚未交付。最新结果和Mac边界见[实施状态](docs/STATUS.md)。

开发在云端串行完成，检查后直接推送main；Mac只pull、build、重启并验证。运行入口是项目根目录构建的`frontend/`和同源后端，详见[Mac更新与验证](docs/MAC_SETUP.md)。

- [当前进度与待验证事项](docs/STATUS.md)
- [文档索引](docs/README.md)
- [产品方案](docs/PRODUCT_DESIGN.md) · [交互方案](docs/INTERACTION_DESIGN.md)
- [实施与验收](docs/IMPLEMENTATION_PLAN.md) · [模型调用与上下文](docs/MODEL_EXECUTION.md)
- [M2主线与后续开发计划](docs/superpowers/plans/README.md) · [开发工作流与Superpowers](docs/DEVELOPMENT_WORKFLOW.md)

仓库目录：

| 目录 | 用途 |
| --- | --- |
| `src/wechat_agent/` | 本机API、来源归档、范围、上下文和模型模块 |
| `frontend/` | 正式React工作台与设置、单元和浏览器测试 |
| `tests/` | 合成数据、后端回归及测试专用服务 |
| `scripts/`、`patches/wx-cli/` | 技能恢复、补丁版wx-cli安装及补丁来源 |
| `docs/` | 当前方案、进度、计划与有效验证记录 |
| `docs/archive/` | 已完成计划、历史记录和被正式页面替代的静态原型 |

旧原型已退出默认入口，仅用于历史对照；不从演示数据或计时器推导产品规则。没有自动发微信、待办或复杂Agent产品流。原始聊天、凭据、数据库、临时证据和构建产物不提交仓库。
