# Wechat-Agent

面向跨境电商平台产品／运营人员的个人工作微信客户管理助手。

目标链路：**导入聊天 → DeepSeek 识别客户与需求 → 自动建立有证据的客户档案 → 自动维护跟进计划与待办 → 今天该联系谁。** 发送微信、加好友和建群仍由用户操作。

## 正在确认改造方案

**请先审阅 [AI 客户管理助手完整改造设计](docs/AI_CRM_DESIGN.md)。当前仅完成设计整理，尚未实施该方案。**

方案取消手工建立商家、项目和逐群关联的前置条件；常规建档与跟进自动生效，仅处理少量关键确认。工作台简化为今日跟进、客户、待确认和设置。设计包含页面、身份归属、档案字段、计划与任务规则、历史初始化、DeepSeek 流水线、媒体边界、迁移、验收与待确认决策。

用户确认设计后再改业务代码。**现有版本尚不能自动生成完整客户档案和跟进计划**，不能把旧的联系人发言汇总当作已完成 AI CRM。

## 现有版本的部署与数据接入

当前可运行版本的唯一部署入口：[从零部署与真实微信接入 SOP](docs/DEPLOYMENT_SOP.md)。包含 wx-cli、已有密钥迁移、本地启动、历史初始化、增量采集、手动文件导入和故障排查。

已实现：私信／群聊可见会话发现、可续跑历史归档、CSV／JSON／JSONL／旧导出文件导入、消息与联系人时间线、本地工作台、DeepSeek 调用及证据校验基础、图片按需读取。现有分析仍需手工业务关联，正是本次改造对象。数据库当前为 v5。

已运行源服务的用户，在仓库目录归档数据：

```bash
uv run wechat-agent archive discover --account 你的基础wxid
uv run wechat-agent archive init-all --account 你的基础wxid
uv run wechat-agent archive status
# 中断后恢复
uv run wechat-agent archive resume
```

保留手动入口，不要求继续运行旧导出项目：

```bash
uv run wechat-agent import /路径/all_messages.csv --account 你的基础wxid --preview
uv run wechat-agent import /路径/all_messages.csv --account 你的基础wxid
```

当前导入默认只在本机归档，不自动分析全部历史。范围仅限当前账号、当前 Mac 的源端可见可读数据；未同步／已删除记录无法保证覆盖，媒体原件不默认批量下载。用户已报告解密与归档成功；真实 DeepSeek 效果、图片完整性和新方案仍需独立验收。

应用继续本地部署，仅获准的业务上下文经 HTTPS 发往 DeepSeek。本地部署不等于聊天内容不出本机；微信密钥与整库不外发。不需要先部署云服务器。

文档导航见 [docs/README.md](docs/README.md)；早期方案已压缩为 [历史摘要](docs/archive/README.md)，完整旧稿可由 Git 历史查看。

现有代码测试：`uv run pytest -q`。本次文档改动不代表新功能测试通过。
