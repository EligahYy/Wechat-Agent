# 半托管欧区备货用户助手

当前阶段：产品与交互方案收敛，准备实施。已具备桌面交互原型；真实微信、模型、数据库和调度尚未接入。

**工作微信资料 → 统一联系人 → 确认身份 → 自动整理商家档案与备货记录 → 每日／按需更新。**

本期只做好有来源、可纠正的客户资料。仅分析商家；服务商、平台的相关答复作为上下文保留。待办、跟进建议、白名单及复杂 Agent 不在本期。

有效文档：

- [产品方案](docs/PRODUCT_DESIGN.md)
- [交互与视觉方案](docs/INTERACTION_DESIGN.md)
- [实施阶段与验收](docs/IMPLEMENTATION_PLAN.md)
- [模型调用、上下文与升级](docs/MODEL_EXECUTION.md)
- [开发工作流与 Superpowers](docs/DEVELOPMENT_WORKFLOW.md)

仅使用清空仓库后重新讨论的方案与最新交互，不恢复重建前实现。

## 查看原型

```bash
python3 -m http.server 8765 --directory ui-prototype
```

打开 http://localhost:8765 ，或查看 [单文件原型](ui-prototype/preview.html)。无需安装前端依赖；其中人物、消息和运行均为演示。

[原型说明](ui-prototype/DESIGN.md) · [原型核查记录](ui-prototype/REVIEW.md) · [文档索引](docs/README.md)
