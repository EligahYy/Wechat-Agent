# 首版运行指南（v0.1）

当前已实现 Python 应用、Web 工作台、SQLite 存储、微信只读适配器与 DeepSeek HTTP 客户端。真实微信和真实 DeepSeek 账户尚未联调；测试使用虚构业务数据及 HTTP MockTransport，不是生产连接证明。

## 1. 安装与演示

需要 Python 3.12+ 与 uv。在仓库根目录运行：

```bash
uv sync --frozen
uv run wechat-agent init
uv run wechat-agent demo
uv run wechat-agent token
uv run wechat-agent serve
```

浏览器在本机访问 `http://127.0.0.1:8765`，输入 token 命令显示的本地口令。不要把口令粘贴到聊天或 GitHub。

demo 仅可在空数据库运行，创建一名虚构商家、一批货、一个三方会话和三条消息，默认禁止 DeepSeek 外发，不伪造 AI 结果。运行手工任务、素材、服务商、报价、节点和联系记录不需要 API key。

真实数据与 demo 使用不同目录：

```bash
uv run wechat-agent --data-dir /tmp/wechat-agent-demo demo
uv run wechat-agent --data-dir /tmp/wechat-agent-demo serve
```

默认数据目录：macOS 为 `~/Library/Application Support/Wechat-Agent/`，其他系统为 `~/.local/share/wechat-agent/`。也可用 WECHAT_AGENT_DATA_DIR；所有终端必须选择同一个真实目录。目录应在本机磁盘，不在网盘同步目录。所有进程使用同一用户运行，不需要 sudo。

## 2. 真实微信源

推荐先用新版“微信接入与分析”四步向导；完整步骤见 [1–2 群试点指南](07-wechat-pilot.md)。它支持在页面确认账号，持久保存非机密账号绑定并试采最近 15 分钟，不再必须手工设置账号环境变量。持续采集仍需单独运行 collect。


采集器不会安装、重签或修改微信，不会自动提取密钥。先在 Mac 按已选定 wx-cli 版本的文档验证权限与能力。如果该设备需要不可接受的系统保护变更，就停止真实接入，使用导入模式；不要以降级导入冒充实时采集。

候选上游：pandorafuture/wx-cli，代码契约参考提交 2abe708f55bfe135539a385df856fdc58f97fc74。上游需自行启动到 127.0.0.1:9100；如果启用 token，用 WX_SOURCE_TOKEN 提供给 collector，不写进仓库。上游启动命令、密钥存放和 SIP 条件以所选版本为准。

在本机终端配置非机密账号绑定：

```bash
export WX_SOURCE_URL=http://127.0.0.1:9100
export WX_ACCOUNT_ID=你的源端current_account.wxid
export WX_SELF_ID=同一个微信wxid
uv run wechat-agent source validate
```

validate 检查 `/api/v1/health` 的 ready 和 current_account.wxid；两项本地配置都必须与源端相符，源切号即失败。成功仅证明健康与身份，不证明全文和历史完整。

工作台操作：

1. 创建商家、备货项目、服务商。
2. “微信与分析”中登记 wx_cli、账号和精确私信／群 ID（不能填模糊群名），选择对应项目。
3. 首先保持“仅本地归档”，启动 collector。
4. 查看本地消息，核对全文、方向、发送者及批次；在三方角色表中确认 sender_id 的业务角色。
5. 混合商家或混合批次的群先保持仅本地。本版不自动做消息级多商家归属。

```bash
uv run wechat-agent collect --once
uv run wechat-agent collect
```

每 10 秒扫描，固定窗口、最近重叠回查。每窗口最多 1000 条，超量返回 window_too_large_split_required；本版需手工用更小时间范围回填，不静默丢弃。

按内部会话 UUID 回填：

```bash
uv run wechat-agent collect --conversation 会话UUID --since 起始Unix秒 --until 结束Unix秒
```

单窗口最大 24 小时。窗口失败记录 gap，即使后来成功也不会悄悄抹掉旧告警。本版尚未实现自动清理／核验 gap、周期深历史回查或完整分片对账。`scanned` 不等于历史完整；Mac 休眠时不保证实时接收。

已实现解析 `content.Text`，不会把 snippet 当正文。没有可靠 server_id 时拒绝该窗口；尚未启用分片 local_id 回退。非文本只记占位，不 OCR、转写或发送附件。

## 3. DeepSeek 配置与验证

在本机安全输入 key：

```bash
uv run wechat-agent credentials DEEPSEEK_API_KEY
uv run wechat-agent model validate --fixture tests/fixtures/deepseek-smoke.json
```

macOS 使用系统钥匙串；开发环境也支持 DEEPSEEK_API_KEY 环境变量。不要把值写入命令历史、仓库、文档或聊天。不自动切换 API 供应商，endpoint 固定为官方 api.deepseek.com；DEEPSEEK_MODEL 可指定账户已验证模型，默认候选 deepseek-chat。

首次验证只传仓库虚构样例，会产生实际 API 请求及费用；无 key 时报告 blocked_credentials。检查成功后并不等于真实业务文本已获准外发。

确认有权外发的会话才开启 egress。该授权覆盖当前会话的全部文本，不能细分内部机密；正则脱敏仅是辅助。先看“本地消息”，确认范围后再开外发并查看“脱敏请求预览”。一旦授权，worker 可自动分析新消息；本版没有逐请求人工批准开关。

```bash
uv run wechat-agent worker --engine deepseek --once
uv run wechat-agent worker --engine deepseek
```

请求输出 JSON，校验现有证据别名，所有待办先进入审核箱；日期保留原文，由用户设置具体跟进时间。点击“确认建任务”才形成正式任务。角色、归属或原文变化会使未审核建议失效，已确认任务保持人工状态。

初版按每批最多 30 条新／修订消息排 job；上下文最多 16000 字符，超限明确 blocked_context_limit，不截断当全文。页面整个会话预览／草稿暂限 80 条，超过时等待后续分页上下文能力。没有自动摘要或语义任务合并，因此需要人工审查重复语义。

每次调用预留输入估计与最大输出预算；usage 缺失／超时保守计入预留。默认每日 100000 token、输出 2000、每任务最多 3 次调用，初版通过 Settings 修改。没有最新单价时不显示虚假的精确金额。

阻塞后可在会话卡点击“安排分析”，只重置可恢复阻塞／失败任务。错误页只显示类型，不暴露服务器响应、key 或消息正文。

## 4. 日常业务操作

- 手工待办或接受建议；任务显示责任方，平台用户负责内部协调。
- 暂缓任务时输入含时区时间。取消／完成保留变更事件；旧版本更新被拒绝。
- 素材以新版本新增，关键价格条件人工核对；过期、待审、内部或撤回素材不能用于新报价引用。
- 项目具体报价是快照，后续价卡变化不覆盖历史。
- 复制草稿／记录联系不代表已备货；`stocking_result` 节点需人工记录核验口径，项目才允许完成。
- 历史激活首版仅做市场＋有效素材匹配，检查拒绝联系及 14 天触达冷却，不自动断言更便宜或商家有货。
- 商家触达限制目前通过 POST /api/merchants/{id}/preferences 设置 do_not_contact；页面完整偏好编辑后续补齐。

## 5. 备份与开发验证

```bash
uv run wechat-agent backup /本机新文件路径/backup.sqlite3
uv run pytest -q
```

备份使用 SQLite Backup API，目标必须不存在；本版未导入二进制素材文件，因此无需打包素材。恢复时停止本应用进程，将备份复制为新私有目录下 agent.sqlite3，再用 --data-dir 启动并核对消息和任务；登录口令会在新目录生成。请保留原目录，不覆盖唯一副本。

本版数据库使用 sqlite3 和 PRAGMA user_version 事务迁移，已有 v1 自动升级 v2，拒绝比当前更高的版本；暂未引入 SQLAlchemy／Alembic。未来改变存储层时继续保持兼容迁移。

## 6. 当前未交付的设计项

用户级 launchd、自适应历史回填与 gap 对账、多商家消息级归属、完整联系人导入、任务编辑／语义合并、素材文件／OCR、自动产品问题分类、完整平台数据接口、自动定时通知、DeepSeek 流式／复杂 schema 和费用币种换算尚未实现。设计文档是目标架构，不能作为这些能力已可用的证据。

本版不自动发送、不自动拉群，也不改变系统路由或关闭任何安全保护。


## 7. 页面显示 cross_site

这是浏览器从其他网站打开本地页面时带上 Sec-Fetch-Site: cross-site，旧版把顶层导航也一并拦截导致的。修复版仅允许 GET / 的 document 顶层导航；跨站 API 读取、写入和 iframe 仍然禁止，Origin、登录与 CSRF 校验继续保留。

请使用独立浏览器标签页，手工在地址栏输入 `http://127.0.0.1:8765`，不要放在其他网站的 iframe 内。更新代码后停止旧后端并重启。不需要重新 init 或 demo，原有数据库保留。

如果本地口令曾贴入聊天或日志，可在相同数据目录运行 `uv run wechat-agent token --rotate`；命令输出新口令供本机登录，旧 Cookie 和旧 Bearer 会话在下一次请求失效。不要分享新口令。
