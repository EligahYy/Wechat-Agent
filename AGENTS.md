# 本项目开发约定

## 产品依据

只采用清空仓库后重新讨论的方案，以 `docs/README.md` 指向的有效文档为准。用户后续明确调整优先。当前产品只建设有价值的客户资料，不能顺带恢复旧白名单、待办或跟进系统。

## Superpowers

用户要求后续开发使用 [obra/superpowers](https://github.com/obra/superpowers)。本仓库采用项目级技能安装，固定版本及恢复命令见 `docs/DEVELOPMENT_WORKFLOW.md`。

每次开始本项目工作，先读取 `.agents/skills/superpowers-using-superpowers/SKILL.md` 及其 Codex 工具说明，再按任务读取适用技能。若文件缺失，先执行 `bash scripts/install-superpowers.sh`；网络不通时说明实际缺失，不假装技能已加载。

- 设计以已完成的用户讨论为上下文；审查批注用 `receiving-code-review`，修复用 `systematic-debugging`。
- 实施前把当前阶段拆成可执行任务；开发使用 `test-driven-development`，结束前使用 `verification-before-completion`。
- 不修改上游技能正文。工具名称、权限与并发能力以当前会话为准；是否委派遵循当前会话约束。
- 用户明确要求的范围和权限优先于技能默认动作。当前保持本地修改，未经用户后续指示不提交、不推送、不发布；不因技能默认提交或分支流程打断已授权的审查工作。

Superpowers 是开发助手的工作流程，与产品运行时调用 DeepSeek 的模型链路分开。
