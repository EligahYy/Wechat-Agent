# 半托管欧区备货用户助手

当前位于 **M1：来源归档与联系人**。任务1—5代码已交付，联系人来源／名称问题仍在修复；任务6原文浏览与导入未开始，M2—M5未实施。云端验证与Mac验收分开记录，详见[当前实施状态](docs/STATUS.md)及[联系人审查](docs/verification/2026-11-12-contact-names-review.md)。

开发在云端逐任务完成，检查后直接推送 `main`；Mac 只 pull 和运行验证，问题由云端修复。云端开发完成与本地实机通过分别记录。

**工作微信资料 → 统一联系人 → 确认身份 → 自动整理商家档案与备货记录 → 每日／按需更新。**

本期只做好有来源、可纠正的客户资料。仅分析商家；服务商、平台的相关答复作为上下文保留。待办、跟进建议、白名单及复杂 Agent 不在本期。

有效文档：

- [产品方案](docs/PRODUCT_DESIGN.md)
- [交互与视觉方案](docs/INTERACTION_DESIGN.md)
- [实施阶段与验收](docs/IMPLEMENTATION_PLAN.md)
- [模型调用、上下文与升级](docs/MODEL_EXECUTION.md)
- [开发工作流与 Superpowers](docs/DEVELOPMENT_WORKFLOW.md)

仅使用清空仓库后重新讨论的方案与最新交互，不恢复重建前实现。

[在 Mac 初始化项目](docs/MAC_SETUP.md) · [M0–M5 开发计划](docs/superpowers/plans/README.md)

## 查看原型

```bash
python3 -m http.server 8765 --directory ui-prototype
```

打开 http://localhost:8765 ，或查看 [单文件原型](ui-prototype/preview.html)。无需安装前端依赖；其中人物、消息和运行均为演示。

[原型说明](ui-prototype/DESIGN.md) · [原型核查记录](ui-prototype/REVIEW.md) · [文档索引](docs/README.md)
