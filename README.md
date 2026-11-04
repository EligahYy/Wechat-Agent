# Wechat-Agent

Use agent to manage Wechat

跨境电商平台商家备货与头程物流协同助手：接入个人微信私信与普通微信群，以商家和备货批次管理价卡／海报 BD、头程服务商三方对接、备货节点和历史商家激活。对外消息与建群均由用户人工确认并操作。

当前已实现工作私信／群聊全量会话发现、可续跑历史初始化、CSV／JSON／旧导出文件手动导入、消息档案与客户跨会话时间线，以及本地工作台、DeepSeek 客户端和图片按需读取。用户已报告旧密钥导入和 21 库解密成功、试点链路打通；图片实机及真实 DeepSeek 分析需独立验收。

## 部署入口

**只按这一份操作：[从零部署、真实微信接入与验收 SOP](docs/DEPLOYMENT_SOP.md)。**

覆盖 Git／uv 安装、wx-cli 下载校验、已有密钥复用、服务启动、双群试采、图片检查、DeepSeek、备份与故障排查。没有有效密钥时的阻塞条件明确列出，不要求为试点关闭 SIP。

已有用户更新后重启 serve／collect／worker，无需重新 init、demo 或删除数据；数据库自动升级到 v4。图片消息点击“读取本机图片”，仅在本机获取缓存，尚无 OCR。

## 全量接入与手动入口

源端健康运行后，在仓库目录：

```bash
uv run wechat-agent archive discover --account 你的基础wxid
uv run wechat-agent archive init-all --account 你的基础wxid
uv run wechat-agent archive status
# 中断后恢复
uv run wechat-agent archive resume
```

不需要旧 wechat-export 或中间导出文件；手动入口仍保留：

```bash
uv run wechat-agent import /路径/all_messages.csv --account 你的基础wxid --preview
uv run wechat-agent import /路径/all_messages.csv --account 你的基础wxid
```

默认只在本机归档，不自动分析全历史。全量范围是当前 Mac、当前账号、源端可见且可读取的私信与群聊，不包含未同步／已删除数据，媒体原件不默认批量下载。界面提供全量消息搜索、历史翻页、联系人跨私信／群聊时间线；详见 SOP 第 6A–6C 节。

测试：`uv run pytest -q`。演示请使用 SOP 中的独立数据目录。

## 确定架构

**Mac 微信 → 本地只读采集适配器 → SQLite 消息与业务库 → 本地外发过滤 → DeepSeek API → 结构校验 → 人工审核 → 跟进工作台。**

本地部署采集器、API、数据库、分析 worker 和页面，不需要先购买服务器或部署 Tailscale。本地运行不等于数据不出本机：获准的脱敏业务上下文会经 HTTPS 发往 DeepSeek，微信密钥、整库和原始素材默认不外发。

历史设计已移入 [docs/archive](docs/archive/)，不是额外部署步骤。下一阶段优先级见 SOP 第 11 节：先验证图片／价卡识别与真实 DeepSeek 闭环，再完善任务更新、多批次归属和常驻稳定性。
