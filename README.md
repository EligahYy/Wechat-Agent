# Wechat-Agent

Use agent to manage Wechat

跨境电商平台商家备货与头程物流协同助手：接入个人微信私信与普通微信群，以商家和备货批次管理价卡／海报 BD、头程服务商三方对接、备货节点和历史商家激活。对外消息与建群均由用户人工确认并操作。

当前为架构设计交付，尚未实现可运行应用。以下接口、配置与 CLI 为拟实现契约，不代表已接通真实微信或 DeepSeek。

## 确定架构

**Mac 微信 → 本地只读采集适配器 → SQLite 消息与业务库 → 本地外发过滤 → DeepSeek API → 结构校验 → 人工审核 → 跟进工作台。**

本地部署采集器、API、数据库、分析 worker 和页面，不需要先购买服务器或部署 Tailscale。本地运行不等于数据不出本机：获准的脱敏业务上下文会经 HTTPS 发往 DeepSeek，微信密钥、整库和原始素材默认不外发。

- [业务工作流](docs/01-workflow.md)：BD、备货项目、三方责任、价卡与履约节点。
- [完整采集与业务架构](docs/02-local-implementation.md)：真实接入、协议、数据、进程、同步与恢复。
- [实施与验收计划](docs/03-local-validation.md)：先验证采集与 API，再实现端到端业务闭环。
- [DeepSeek 分析设计](docs/04-deepseek-analysis.md)：调用契约、外发边界、输出校验、重试与预算。

真实采集必须在 Apple Silicon Mac 上验证准确的微信／macOS／工具版本及权限；Linux 云环境不能代替这一验证。采集失败时保留数据导入和业务操作，但必须显示降级，不宣称微信实时采集成功。
