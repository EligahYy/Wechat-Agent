# 半托管欧区备货用户助手

从个人工作微信的私信和群聊，整理商家资料、备货批次和有原文依据的下一步。使用本机 wx-cli 与 DeepSeek API，微信由用户人工发送。

**当前 v0.8.0：M1 技术试点。** 新工作台已连接真实本地归档和独立的客户文档引擎；全量自动重建、媒体识别和真实模型业务验收尚未完成。原工作台保留。[准确交付范围](docs/IMPLEMENTATION_STATUS.md)。

## 更新和启动

先停止旧start／serve／worker，再执行：

```bash
git pull origin main
uv sync --frozen
# 源服务已运行则跳过
~/.local/bin/wx-cli server run --host 127.0.0.1 --port 9100
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent start --pilot
```

打开 http://127.0.0.1:8765，使用 `uv run wechat-agent token` 显示的口令登录。在原工作台设置确认工作账号、模型key、文本分析授权和预算，维护会话／人物免跟进名单。已有配置可复用。

点击 **新工作台试点**（`/workspace`）→ **试点与进度** → 选择一位消息量较少的联系人 → **分析此联系人**。此操作会请求DeepSeek；先试1–2位，再核对客户、批次、角色和证据。

`--pilot`保留采集，暂停旧模型后台，仅执行手动试点。新增来源之后需要再次分析该联系人。schema v10升级先备份旧库，原聊天、名单、用量和旧业务数据保留。不带`--pilot`仍运行旧模型后台。

可选CLI：

```bash
uv run wechat-agent rebuild inspect
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent rebuild analyze --contact '来源联系人ID'
```

inspect仅统计归档缺口，不调用模型。完整新装、已有密钥迁移、备用文件导入和异常恢复见 [部署与使用SOP](docs/DEPLOYMENT_SOP.md)。

## 当前试点能力

同一联系人跨会话维护一个客户文档；资料、批次、行动和确认带证据，修改有版本记录。人物排除、范围变更和原文修订会影响展示资格。人工完成、暂停、角色决定受到保护；新进展未分析或上下文不完整时不强推今日建议。

模型最多3次请求、1次限定范围检索；共用预算台账，保存响应供重放，同一联系人使用进程锁防并发重复请求。姓名从源端读取。只处理授权文本，图片／复杂长历史会明确标记覆盖不足；不会把HTTP成功或合法JSON当成业务正确的证明。

## 文档

- [部署与日常使用](docs/DEPLOYMENT_SOP.md)：当前版本怎么运行。
- [实施状态](docs/IMPLEMENTATION_STATUS.md)：已实现和仍待交付。
- [产品方案](docs/PRODUCT_DESIGN.md) · [技术架构](docs/SYSTEM_ARCHITECTURE.md) · [验收计划](docs/ACCEPTANCE_PLAN.md)：完整目标。
- [UI规范](docs/UI_DESIGN.md) · [独立交互原型](docs/UI_PROTOTYPE.html)：目标交互，原型为虚构数据，不代表全部已接入。
- [文档导航](docs/README.md)：历史说明和阅读入口。

开发检查：`uv run pytest -q`、`uv run ruff check src tests`。新工作台浏览器测试使用独立目录、虚构聊天和模拟模型：`tests/workspace_browser_server.py`、`tests/browser/workspace.cjs`。测试不会访问真实微信或DeepSeek，不代替真实业务样本验收。
