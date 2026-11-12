# 开发工作流与技能安装

更新：2026-11-11（北京时间）。本文件约束开发过程，不增加产品功能。

## 项目级 Superpowers

- 来源：[obra/superpowers](https://github.com/obra/superpowers)，MIT 许可。
- 安装版本：7.0.2，固定提交 `22f0b463e7a5e579904dd6211a520321035526f7`。
- 上游存放于 `.agents/vendor/superpowers`，各技能通过相对符号链接放在 `.agents/skills/superpowers-*`。这些依赖目录不提交到本仓库。
- 项目启动入口为 [AGENTS.md](../AGENTS.md)：先读取 `using-superpowers`，再按任务读取适用技能，不依赖当前聊天临时记忆。
- 这是本仓库技能文件与入口配置；未修改客户端的全局插件注册，也不宣称已验证插件市场的会话启动钩子。官方 Codex App 全局安装入口为 Plugins → Superpowers。

新环境恢复：

```bash
bash scripts/install-superpowers.sh
```

脚本固定上游提交、拒绝覆盖已有不同技能及脏依赖；再次运行不重复安装。更新需先审阅上游变更，再修改固定提交及本文版本，不自动跟随 main。

## 使用顺序

1. 读取有效产品方案和当前阶段；已有讨论作为设计输入，避免从零重复询问。
2. 有批注先用 `receiving-code-review` 核实问题；发现运行故障用 `systematic-debugging` 定位原因。
3. 实施阶段用 `writing-plans` 拆解文件、数据迁移、测试与完成条件，再执行对应任务。
4. 业务代码使用 `test-driven-development`；静态文档修订只做相应一致性、链接和格式核对。
5. 结束前用 `verification-before-completion` 获取当前验证证据，区分检查通过、尚未实现和未能验证。

当前用户指示：所有开发在云端逐任务串行完成，检查后直接提交并推送 main；Mac 只 pull 和运行验证，问题回到云端修复。实机未验证状态独立保留，不阻塞可独立开发模块。是否使用子代理依用户最新指示和当前会话约束执行；开发任务仍串行。本轮用户明确请求技能内代码审查，按requesting-code-review使用单个只读独立审查代理，不并行修改文件；历史报告中的作者自审记录保留。Superpowers 负责开发过程，产品的上下文、Agent 演进和 DeepSeek 调用仍按模型执行方案实现。
