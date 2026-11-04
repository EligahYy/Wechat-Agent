# 本地技术实现设计

状态：拟实现契约；没有已运行服务。部署目标：Apple Silicon Mac，单用户、本地访问。本期不依赖云端服务。

## 1. 技术选择

| 部分 | 一期选择 | 理由 |
| --- | --- | --- |
| 运行时 | Python 3.12，uv 管理依赖与锁文件 | 一套语言完成导入、任务处理与页面 |
| Web | FastAPI + Jinja2，少量 HTMX／原生 JS | 避免额外前端构建链 |
| 存储 | SQLite，WAL，外键，Alembic 迁移 | 单用户足够；保持迁移与备份能力 |
| 数据访问 | SQLAlchemy 2 + Pydantic | 数据模型与输入契约明确 |
| 后台处理 | 独立 Python worker，SQLite 持久化任务队列 | 模型耗时不阻塞页面；无需 Redis |
| 分析 | 规则基线；可选本机 Ollama 模型 | 无模型也能验证业务流程 |
| 验证 | pytest，HTTP 集成测试，人工验收 | 覆盖重复处理、状态与故障恢复 |

模型不作为应用启动依赖。规则模式仅识别明确日期／关键词候选，不能宣称具备完整语义理解；语义提取与草稿质量需单独验收。本机模型性能按 Mac 可用内存实测，不预先保证速度。

## 2. 模块与进程

```text
src/wechat_agent/
  adapters/       # fixture、JSONL、wx-cli 接入隔离层
  ingestion/      # 校验、白名单、去重、游标及本地发送队列
  crm/            # 商家、身份关联、事实与触达限制
  followups/      # 任务状态机、联系记录、下一步
  analysis/       # 上下文构建、规则、本机模型、结果校验
  opportunities/  # 业务机会匹配与激活候选
  jobs/           # 持久化任务及 worker
  web/            # 页面、接口、模板
  cli.py          # 导入、服务、worker、备份、诊断
tests/fixtures/   # 仅虚构数据
```

API 监听 127.0.0.1，worker 独立运行；采集器作为可选第三进程。worker 不持有长时间数据库事务调用模型。客户端先持久化数据，再排分析任务。

## 3. 数据模型

所有主键使用应用生成的 UUID；原始来源 ID 作为文本保存，避免长整数转换丢失精度。时间保存 UTC，并在界面按业务时区展示；原始时间和时区信息单独保留。

| 表 | 关键字段／约束 |
| --- | --- |
| merchants | name、stage、owner_note、created_at |
| contacts | account_id、source_contact_id、display_name；来源身份唯一 |
| merchant_contacts | merchant_id、contact_id、role、confirmed_at；多对多 |
| conversations | account_id、source_conversation_id、kind、title、allowlisted |
| conversation_merchants | conversation_id、merchant_id、association_type；群关联不等于所有消息归属 |
| messages | account_id、conversation_id、source_id、sender_id、direction、event_time、ingested_at、type、text、coverage_flags |
| message_revisions | message_id、revision_hash、revision_type、content；记录可观察到的修订／撤回 |
| message_merchants | message_id、merchant_id、confirmed_by；支持消息级归属 |
| merchant_facts | merchant_id、field、value、evidence_ids、review_status、user_locked |
| analysis_runs | input_hash、input_message_ids、context_version、engine_version、prompt_version、status、error_code |
| suggestions | run_id、kind、payload、evidence_ids、review_status、dedup_key |
| followup_tasks | merchant_id、kind、state、due_at、due_text、due_precision、origin_suggestion_id、version |
| task_events | task_id、actor、action、before、after、created_at |
| touchpoints | merchant_id、channel、contacted_at、outcome、next_action；人工确认 |
| opportunities | description、eligibility、limitations、starts_at、ends_at |
| outreach_preferences | merchant_id、do_not_contact、paused_until、cooldown_days |
| sync_checkpoints | source、account_id、conversation_id、cursor_json、last_success、coverage_start、gap_status |
| jobs | type、payload、dedup_key、status、attempts、lease_until、available_at、last_error |

明确区分消息入库、成功分析与人工确认。消息提交成功后才能推进采集游标；不等待模型完成。任务与事件在同一事务更新；页面使用 version 字段检测并发修改。

## 4. 标准导入协议

一期以 UTF-8 JSONL 为统一入口，每行一条消息。例如（虚构）：

```json
{"schema_version":1,"source":"manual","account_id":"demo-account","conversation_id":"demo-chat-1","conversation_type":"private","source_id":"demo-msg-001","sender_id":"demo-customer-1","direction":"incoming","event_time":"2026-11-04T09:00:00+08:00","message_type":"text","text":"请周五前把试用安排发给我"}
```

- 必填：版本、来源、账号、会话、来源 ID、方向、带时区时间、消息类型；文本消息要求 text。
- direction 为 incoming／outgoing／unknown；不能根据昵称猜方向。
- 导入前预览来源、数量、日期、会话；未批准会话不保存正文，返回被排除计数。
- 返回新增、重复、修订、拒绝及隔离条数和逐行错误码。格式失败不推进整批源游标。
- 一批数据事务性入库；建议批量上限初始设为 1000 条，并限制文件大小。
- 对有可靠 source_id 的来源，按来源命名空间、账号、会话、source_id 唯一。
- 人工数据须分配稳定 ID；重复导入同一文件复用 ID。缺失稳定 ID 时隔离并提示，不能仅靠文本哈希把两条真实重复发言误合并。
- 非文本、解码失败、仅摘要、缺失上下文以 coverage_flags 表示。图片／语音一期只保存占位与可用元数据，不宣称完成转写或全文归档。

## 5. 微信适配器：独立的验证关口

候选为 pandorafuture/wx-cli；前期调研提交为 2abe708f55bfe135539a385df856fdc58f97fc74，不保证最新版本或当前 Mac 兼容。记录 macOS、芯片、微信、工具版本和取得权限的方式。

不将关闭 SIP、修改微信签名或规避终端防护作为自动安装步骤。若候选工具在实际设备上要求这些变更，暂停该接入路径，单独评估；业务闭环继续使用标准导入。仅在授权范围内读取本机业务数据。

优先让工具仅监听回环地址，由适配器读取，不对公网或公司网络暴露 API。白名单在适配器／导入层强制执行，不依赖上游“隐藏联系人”功能。

已核实候选版本的 timeline 要求 since 和 until，同时支持 limit／offset，返回分页和分片警告；数据结构使用 snippet，正文是否完整必须实测。若不能取得完整正文，保存为 partial，不用于需要完整证据的正式提取。

同步策略：

1. 按固定时间窗口查询，固定 until，升序完整分页；窗口内结果暂存。
2. 检查 has_more、skipped、分片警告、正文完整性及分页稳定性。
3. 幂等保存结果，推进“已扫描窗口”，记录数据质量与覆盖缺口。
4. 近期窗口重叠回查，定期核对更早窗口；延迟补录可能早于重叠窗口，不能承诺绝不漏数。
5. SSE 仅提示有新消息，不能替代持久化进度和回查。

固定窗口并不提供数据库快照隔离；出现分页期间变动时须回查。无法确认完整的窗口保留 gap 状态，不能用最后一条消息时间冒充完整同步水位。缺失本地记录、已清理历史和无法解码分片需明确提示。

## 6. 分析流程

上下文按商家／会话及话题组织，包含本批消息、必要引用、已确认事实、开放任务、近期联系记录和业务配置。以 Token 预算限长；历史摘要只作背景，不替代原始证据。跨商家数据不混入上下文。

确定性任务键包含输入消息及修订、身份映射、业务配置、开放任务版本、分析器和提示词版本。相同输入不重复分析，相关状态变化则允许重算。规则先做触达限制与基础候选；可选本机模型提取语义。

输出采用版本化 JSON Schema：

```json
{
  "schema_version": 1,
  "suggestions": [{
    "kind": "task_create",
    "merchant_id": "demo-merchant-1",
    "summary": "发送试用安排",
    "responsible_party": "self",
    "due_at": null,
    "due_text": "周五前",
    "due_precision": "ambiguous",
    "evidence_message_ids": ["stored-message-uuid"],
    "existing_task_id": null,
    "needs_review": true
  }]
}
```

示例中的相对日期保留待确认；解析器仅在规则明确时结合原消息时间和业务时区归一化，绝不按分析当天解释历史消息。歧义和节假日规则交给用户确认。

校验内容：结构、字段枚举、证据存在、证据属于本批允许上下文、商家归属、关联任务权限及日期。失败最多重试两次，仍失败进入人工处理；不把失败输出写成事实。

建议去重用消息证据、动作类型和目标任务共同约束；跨批语义相似仅提示合并，不直接吞掉事项。接受同一建议必须幂等。用户已确认内容受锁定和版本控制保护。

草稿使用已确认事实生成，不得虚构优惠、报价、客户兴趣或完成状态；缺失价格时保留显式待填写项。聊天内容为不可信数据，模型没有 shell、浏览器、文件遍历或微信操作工具。

## 7. 本地接口与页面

拟实现入口：

| 接口 | 用途 |
| --- | --- |
| GET /health | 数据库与 worker 心跳状态；不返回正文 |
| POST /api/imports | 提交标准消息批次 |
| GET /api/merchants | 商家列表／搜索 |
| POST /api/associations | 人工关联联系人、会话、消息与商家 |
| POST /api/analysis-runs | 对选定范围排分析任务 |
| GET /api/suggestions | 待审核建议 |
| POST /api/suggestions/{id}/accept | 幂等接受建议，事务创建／更新任务 |
| POST /api/tasks/{id}/transition | 检查版本及状态迁移，追加事件 |
| POST /api/touchpoints | 确认联系记录与下次任务 |
| POST /api/opportunities | 录入业务机会 |
| POST /api/drafts | 生成草稿，不发送 |
| GET /api/sync-status | 覆盖范围、缺口、最后成功时间 |

页面：今日工作台、建议收件箱、商家详情／时间线、机会与激活、导入与运行状态。状态变更均使用 POST，不能通过 GET 触发。

默认不设计“发送微信”接口。复制按钮只复制草稿；没有发送成功回执。

## 8. 可靠性与本地保护

- SQLite 队列使用短事务领取任务与租约；worker 崩溃后可重新领取。重试采用退避，超过阈值进入 failed，可人工重放。
- SQLite 忙超时、单 worker 和有限分析并发，模型调用期间释放数据库锁。
- 程序只监听 127.0.0.1；使用本机会话认证、CSRF 防护和 Origin／Host 校验，防止其他网页调用本机变更接口。
- 页面转义消息文本；一期不渲染聊天中的原始 HTML，不自动访问链接或加载远程图片。
- 敏感配置和密钥不进入仓库；数据目录仅当前用户可访问。FileVault 是磁盘保护，不等同于 SQLite 自带加密。
- 日志仅记录内部 ID、计数、状态和错误码，默认不记录消息正文、密钥和完整模型输入输出。
- 本机模型绑定回环地址；运行时不回退外部 API。首次下载模型文件与运行期数据外发是两件事，分别说明。
- 使用 SQLite Backup API 创建一致性备份，不直接只复制正在写入的主 DB 文件。恢复到新目录验证消息、任务、事件和关联关系。
- 提供按商家／来源清理数据的设计；删除须覆盖衍生建议、模型缓存和导出文件。备份保留期限单独管理，不宣称删除主库即清除所有副本。

## 9. 后续扩展边界

本期不设置云端脚本、Tailscale 或外部模型凭据。未来是否迁移，由实际采集稳定性、Mac 常驻条件、模型速度、数据许可和多设备需求决定。

保留标准导入协议、服务层、任务队列和数据库迁移能力即可；不提前建设分布式系统。将来同步的是获准的数据与事件，不上传微信密钥或整库。
