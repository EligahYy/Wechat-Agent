# 本项目开发约定

## 产品依据

只采用清空仓库后重新讨论的方案，以 `docs/README.md` 指向的有效文档为准。用户后续明确调整优先。当前产品只建设有价值的客户资料，不能顺带恢复旧白名单、待办或跟进系统。

## Superpowers

用户要求后续开发使用 [obra/superpowers](https://github.com/obra/superpowers)。本仓库采用项目级技能安装，固定版本及恢复命令见 `docs/DEVELOPMENT_WORKFLOW.md`。

每次开始本项目工作，先读取 `.agents/skills/superpowers-using-superpowers/SKILL.md` 及其 Codex 工具说明，再按任务读取适用技能。若文件缺失，先执行 `bash scripts/install-superpowers.sh`；网络不通时说明实际缺失，不假装技能已加载。

- 设计以已完成的用户讨论为上下文；审查批注用 `receiving-code-review`，修复用 `systematic-debugging`。
- 实施前把当前阶段拆成可执行任务；开发使用 `test-driven-development`，结束前使用 `verification-before-completion`。
- 不修改上游技能正文。工具名称、权限与并发能力以当前会话为准；是否委派遵循当前会话约束。
- 用户明确要求的范围和权限优先于技能默认动作。当前已授权在云端按任务串行开发、检查后直接提交并推送到 `main`，无需再询问分支／推送许可；不强制创建开发分支或 worktree，不强推或覆盖远程变更。

## 云端开发与本地验证

- 所有编码、修复、计划维护和自动化测试在云端完成，使用 `executing-plans` 逐个任务推进；不把开发工作交给用户 Mac。
- 用户 Mac 只从 `main` pull 项目、安装运行依赖并验证真实微信、模型、附件和系统行为；云端提供可复制的验证命令及明确结果说明。
- 分别记录云端开发状态和本地实机验证状态。缺少 Mac 实测不阻塞可独立测试的后续模块开发，但不能宣称真实接入、质量验收或无人值守已经通过。
- 源端命令、模型 ID 或字段未知时，保留显式配置与未支持状态；用已定义契约及回放测试开发，依据用户提供的验证结果修正，不能编造成功。
- 前端最低兼容基线是Node 24.14.1；更改依赖锁时，在云端用该版本执行`npm ci --engine-strict`、前端测试和构建，不能只用云端较新的Node判断兼容。
- 不要求用户修改代码排错；收集必要的版本、脱敏报告和错误后，在云端修复，再推送 `main` 供用户 pull 复验。

Superpowers 是开发助手的工作流程，与产品运行时调用 DeepSeek 的模型链路分开。
