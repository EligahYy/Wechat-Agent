# 半托管欧区备货用户助手

从本机微信私信与群聊归档资料，管理业务联系人，并逐步生成有来源、可纠正的商家档案。

**当前：M1云端完成；M2任务1—3及业务范围、日历消息浏览完成；下一步为M2任务4「事实校验与事务发布」。** 当前schema11。真实档案闭环、附件获取／解析及每日自动执行尚未完成，不能把来源同步或连接检查当作模型整理成功。

已实现工作台／设置、业务活跃联系人、设置中的全量联系人管理、身份与人工范围覆盖、按日日历原文、搜索／来源筛选、本人发言定位、CSV／JSON导入，以及安全模型配置和主动连接检查。最新云端基线为Python417、前端31单元／49浏览器及构建通过；Mac证据另记。

开发在云端串行完成，检查后直接推送main；Mac只pull、build、重启并验证。运行入口是项目根目录构建的`frontend/`和同源后端，详见[Mac更新与验证](docs/MAC_SETUP.md)。

- [当前进度与待验证事项](docs/STATUS.md)
- [文档索引](docs/README.md)
- [产品方案](docs/PRODUCT_DESIGN.md) · [交互方案](docs/INTERACTION_DESIGN.md)
- [实施与验收](docs/IMPLEMENTATION_PLAN.md) · [模型调用与上下文](docs/MODEL_EXECUTION.md)
- [正在执行的开发计划](docs/superpowers/plans/README.md) · [开发工作流与Superpowers](docs/DEVELOPMENT_WORKFLOW.md)

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
