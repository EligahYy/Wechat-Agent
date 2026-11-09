# 半托管欧区备货用户助手

从个人工作微信的私信和群聊，整理商家资料、备货批次和有原文依据的下一步。使用本机 wx-cli 与 DeepSeek API，微信由用户人工发送。

**当前 v0.11.1：完整客户资料、统一工作台与人工跟进闭环。** 自动队列、证据档案、批次判断、跟进记录、行动草稿、白名单和图片文字核对已接入。[交付范围与限制](docs/IMPLEMENTATION_STATUS.md)。

## 更新和启动

先停止旧start／serve／worker，再执行：

```bash
git pull origin main
uv sync --frozen
# 源服务已运行则跳过
~/.local/bin/wx-cli server run --host 127.0.0.1 --port 9100
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent start
```

打开 http://127.0.0.1:8765，使用 `uv run wechat-agent token` 显示的口令登录。在“设置与接入”确认工作账号、模型key、文本分析授权和预算，维护会话／人物免跟进名单。已有配置可复用。

登录后默认进入客户工作台。打开 **整理与进度 → 开启自动整理**，系统优先整理近15天活跃联系人，每人从完整历史开始；分册完成后汇总档案和行动。首次升级需开启一次，之后按账号记住状态。已有聊天无需重导。

默认 `start` 运行新客户后台；`--pilot` 仅供手动分析，`--legacy` 才运行旧后台。schema v13升级先备份原库，原聊天、分册、名单和用量保留。设置、白名单与监控已统一进入新版；旧界面仅显式 `/legacy` 兼容。

可选CLI：

```bash
uv run wechat-agent rebuild inspect
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent rebuild analyze --contact '来源联系人ID'
```

inspect仅统计归档缺口，不调用模型。完整新装、已有密钥迁移、备用文件导入和异常恢复见 [部署与使用SOP](docs/DEPLOYMENT_SOP.md)。

## 当前能力

同一联系人跨会话维护一个客户文档；资料、批次、行动和确认带证据，修改有版本记录。人物排除、范围变更和原文修订会影响展示资格。人工完成、暂停、角色决定受到保护；新进展未分析或上下文不完整时不强推今日建议。

按客户读取全部已授权归档，先分册整理再总结；不按价值过滤消息。一次操作最多新增12次模型请求，达到次数上限由后台自动继续，预算不足次日自动续跑；调高预算也会恢复，已完成分册复用。原文、分册与进度可在新工作台查看。图片可本机预览、本地识别，核对文本确认后才进入下一轮；原图不发送给DeepSeek。模型业务准确性及Mac Vision识别质量仍需真实样本验收。

客户详情分为资料概览、批次与行动、完整时间线和人工跟进。可核对证据、确认阶段、生成编辑草稿；微信发送后记录实际结果，并更新待办或下次日期。生成草稿不等于已联系，记录已联系不等于已发货。

## 文档

- [部署与日常使用](docs/DEPLOYMENT_SOP.md)：当前版本怎么运行。
- [实施状态](docs/IMPLEMENTATION_STATUS.md)：已实现和仍待交付。
- [产品方案](docs/PRODUCT_DESIGN.md) · [技术架构](docs/SYSTEM_ARCHITECTURE.md) · [验收计划](docs/ACCEPTANCE_PLAN.md)：完整目标。
- [UI规范](docs/UI_DESIGN.md) · [独立交互原型](docs/UI_PROTOTYPE.html)：目标交互，原型为虚构数据，不代表全部已接入。
- [文档导航](docs/README.md)：历史说明和阅读入口。

开发检查：`uv run pytest -q`、`uv run ruff check src tests`。新工作台浏览器测试使用独立目录、虚构聊天和模拟模型：`tests/workspace_browser_server.py`、`tests/browser/workspace.cjs`、`tests/browser/workspace-reviews.cjs`（每套使用新的数据目录）。测试不会访问真实微信或DeepSeek，不代替真实业务样本验收。
