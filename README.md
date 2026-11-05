# 微信客户助手 · Wechat-Agent

**聊天自动整理成客户档案、跟进计划和今日行动。** 面向跨境电商平台产品／运营，接入个人工作微信的私信与普通群聊，通过 DeepSeek 理解需求、顾虑和承诺。

无需先建商家／项目或逐条接受 AI 建议。工作台仅保留今日跟进、客户、待确认、设置四个入口。自动结果附消息证据；发送微信仍由用户核对并操作。

## 启动

已完成 wx-cli 与有效密钥接入的用户：

```bash
git pull origin main
uv sync --frozen
# wx-cli 已运行则跳过
~/.local/bin/wx-cli server run --host 127.0.0.1 --port 9100
uv run wechat-agent start
```

访问 http://127.0.0.1:8765，登录口令通过 `uv run wechat-agent token` 查看。在设置确认工作账号、配置 DeepSeek key 和预算、开启自动整理即可。不要同时运行旧的 collect／worker；start 已统一管理后台。

首次接入和故障排查见 [部署与使用 SOP](docs/DEPLOYMENT_SOP.md)。旧数据保留，数据库升级至 v6 前自动备份；不需要重新导入现有记录。

## 当前能力与边界

- 自动发现工作私信与群聊，增量采集和历史断点补齐；授权后分批分析，近期优先。
- 按稳定联系人身份贯通私信与群聊，生成需求事实、机会与计划；自动新增／更新／等待／关闭事项。
- 今日到期行动、原文证据、按需话术、人工结果记录、改期保护、暂停联系和少量关键确认。
- 消息保守过滤空文本和简短寒暄／确认，可切回全部；原文与模型上下文不删除。
- 仅一个备用文件导入入口，支持标准 CSV／JSON／JSONL；不再维护旧导出项目格式转换。图片按需本地读取，未实现 OCR。

本机存储并不等于内容不外发：授权的脱敏文本经 HTTPS 发往 DeepSeek。密钥、整库和图片原件不外发。不自动发送微信、加好友或建群。

本版为自动 CRM 文本闭环；公司主体合并、OCR／价卡理解、素材驱动历史激活及更细的任务策略尚未全部交付。真实 Mac／DeepSeek 效果需按 SOP 验收，模拟测试不代替真实验证。

[完整目标设计与交付状态](docs/AI_CRM_DESIGN.md) · [文档导航](docs/README.md)

开发检查：`uv run pytest -q`、`uv run ruff check src tests`。浏览器测试使用隔离虚构数据，见 tests/browser_server.py 和 tests/browser/smoke.cjs。
