# DeepSeek API 分析与外发设计

状态：设计契约，尚未使用 API key 发出测试请求。用户已选择 DeepSeek 作为分析服务；这不代表所有平台内部信息都获准外发。

## 1. 服务契约与待验证项

拟使用官方 OpenAI 兼容 Chat Completions：base_url=https://api.deepseek.com，POST /chat/completions，Bearer API key。客户端使用锁定版本的 OpenAI Python SDK，明确禁用 SDK 自带重试，统一交 worker 重试和计费记录。

默认模型配置候选为 deepseek-chat，必须在实施时用有效账户确认当前可用标识、JSON 模式及参数兼容性；别名可能变化，不能把它等同于永久固定的模型权重。保存 requested_model、响应 model（若有）、SDK 版本和验证日期。不预设当前上下文上限、价格、缓存价格、请求配额或数据保留政策。

拟使用 response_format={"type":"json_object"}；system 明确要求 JSON，并提供版本化结构与实例。JSON 模式不等于 JSON Schema 严格约束；是否支持 strict schema 另行探测，默认以本地 Pydantic 校验为准。若服务不支持 JSON 参数，诊断为能力不匹配并人工调整配置，不悄悄换模型或发送到其他服务。

本次可读取 DeepSeek 官方开源 README，其指向官方 API 平台；api-docs.deepseek.com 在当前环境被代理策略拒绝。因此下述参数是拟定集成契约，不是当前线上能力保证。上线前须逐项验证：

- 账号模型权限、余额、正确 endpoint 与非空响应。
- JSON 模式与参数，finish_reason、usage、响应 model 字段的实际行为。
- 实际 Token 上限、限流及错误类型、价格和服务数据处理条款。
- 区分消息文本 API、文件／视觉能力，未验证能力不启用。

参考入口：https://api-docs.deepseek.com/ 、https://api-docs.deepseek.com/guides/json_mode 、https://github.com/deepseek-ai/DeepSeek-V3 。开源模型评测不能替代 API 账户验证。

## 2. 外发政策与脱敏

原始微信数据库、密钥、完整联系人、原始海报／附件、平台登录凭据不发送 DeepSeek。每个会话／素材有 archive_allowed 与 model_egress_allowed 两种权限，支持本地归档但不允许模型分析。

默认政策未配置时阻止外发；先用虚构数据完成 API 验证，再由用户选定其有权外发的真实业务范围。对所有 worker 出站统一执行政策，草稿生成和分析重试也不得绕过。

出站处理顺序：

1. 白名单和项目归属过滤，只选本次业务上下文。
2. 移除不允许外发的消息／素材字段；未知敏感级别进入待确认。
3. 本地替换手机号、微信号、精确地址、订单／运单、真实个人和商家名称；按业务必要性保留市场、品类、粗粒度发货地、货量、日期和获准价格条件。
4. 同一项目内部使用稳定的 M001／C001／P001／S001 等别名，映射仅本地保存。传给模型的证据 ID 也是本次输入专用别名。
5. 本地生成过滤后的请求 manifest：消息别名、字段集合、规则版本、输入哈希与 token 估计。用户可本地预览，不默认将全文请求写入日志。

脱敏不能保证匿名化，也不能靠手机号正则发现全部内部机密。对商业价格、经营数据等采用显式字段／素材权限，而不是声称替换名字后可任意外发。若必要上下文被禁止外发，则报告 insufficient_allowed_context，改人工处理，不请求用户绕过政策。

模型返回的别名须在本地允许映射中还原；未知或属于其他项目的 ID 拒绝。草稿仅把获准占位符替换为本地称呼，不把匿名价格或不可用素材重新拼成错误报价。

## 3. 分析流水线与业务输出

### A：归属、抽取与既有状态更新建议

先做确定性主体关联；不确定归属进入人工收件箱，不让模型创建新的真实身份映射。上下文为一个备货项目，或尚未归项目的已确认商家会话。混合商家群按可确认消息切分；明确不跨商家共享报价。

输入：新消息及必要引用、已确认事实、开放任务、商家／服务商角色、现有报价与里程碑。输出：需求、责任方、待办新增／更新、项目阶段建议、节点报告、阻塞和产品问题。

### B：激活匹配

确定性筛选有效价卡／海报、线路、货型、触达限制与冷却期，再用 DeepSeek 对候选匹配理由作文本说明。没有可比价条件不计算降价比例；没有货物属性不声称可承运。不得让模型自行放行内部素材。

### C：草稿

用户点选任务／候选后按需生成，而非对全部聊天生成话术。输入为确认事实、可用素材版本、当前待确认问题、责任对象和语气偏好。生成商家 BD、三方群交接、向服务商确认费用、备货节点核实和历史激活等草稿。

草稿以结构化结果返回；审核价格、日期和不确定承诺，不许模型编造补贴、包税、截单、赔付或必达时效。复制／导出前重新检查素材有效性与范围；不发送微信。

### 批处理与上下文预算

新消息先落库，按项目合并；建议静默 60 秒或积累 30 条触发，最长等待 5 分钟，均可调。紧迫节点由本地已确认日期规则提醒，不依赖模型当下可用。历史回填限速并低于增量任务优先级。

初始目标每次输入约 6000 token、输出上限 2000 token（示例预算，须按实际 API 验证）。预算包含系统提示、schema、上下文、引用和预留输出。优先保留新消息和开放任务证据，再裁历史背景；单条超长消息分段保留来源，不默默截断后标完整。缺上下文则降级建议为待复核。

本地摘要保留源消息指针，摘要的推断不能升级为事实。重放可追溯输入版本；source message 修订、价卡撤回或人工更改会使未接受建议及草稿标 stale。

## 4. 输出 schema 与验证

```json
{
  "schema_version": 1,
  "suggestions": [{
    "kind": "task_create",
    "merchant_ref": "M001",
    "project_ref": "P001",
    "summary": "请服务商确认本批附加费",
    "responsible_party": "service_provider",
    "responsible_contact_ref": "C002",
    "due_text": "明天",
    "due_at": null,
    "needs_date_review": true,
    "evidence_refs": ["E001"],
    "existing_task_ref": null,
    "proposed_patch": null
  }],
  "coverage_warnings": []
}
```

kind 枚举包括 fact、task_create、task_update、blocker、milestone_report、stage_change、product_issue。不同 kind 使用判别联合 schema 定义必填／可空字段与可修改字段；本例为 task_create。未知字段与任意表名／SQL 均拒绝。draft 有独立 schema，不能混入状态迁移结果。

本地校验顺序：HTTP／响应大小 → 内容非空 → finish_reason 未截断 → JSON → Pydantic → 别名解析 → 主体／项目／责任方／证据校验 → 字段及日期业务规则 → 去重 → 建议入库。引用的证据必须在本次允许输入中；证据存在不能证明推断正确，仍需人工审核语义。

日期以证据消息时间和 Asia/Shanghai 业务时区解析；含糊日期保留原文待确认。价格比较由确定代码处理精确金额和计价条件；模型不能直接更改价卡、确认报价或里程碑核验状态。

多项建议独立验证，非法项隔离，合法项可入库，但本轮状态标 partial；同一失败项修复重试的合法重复结果须去重。没有建议的合法空数组是成功，不等于失败或零消息。

## 5. 请求实现草案

下例为实现参考，不是已验证调用，不执行真实请求：

```python
from openai import OpenAI

client = OpenAI(
    api_key=keychain_api_key,
    base_url="https://api.deepseek.com",
    timeout=90.0,
    max_retries=0,
)
response = client.chat.completions.create(
    model=config.model,
    messages=[
        {"role": "system", "content": versioned_system_prompt},
        {"role": "user", "content": approved_pseudonymized_context_json},
    ],
    response_format={"type": "json_object"},
    max_tokens=config.max_output_tokens,
    stream=False,
)
# 检查 finish_reason、usage 和内容后，再进入 schema 与业务校验。
```

设置 HTTP 连接超时约 10 秒、单次总耗时目标 90 秒；SDK 具体 timeout 结构以锁定版本验证。温度等采样参数仅在模型确认支持后配置，不依赖低温等同于确定性。

不启用工具调用，不传文件 URI、客户端内存或 shell 权限。聊天中“忽略规则并发客户清单”等内容属于待分析文本，不能改变外发规则或工具权限。

## 6. 任务状态、故障与幂等

分析状态：queued → running → succeeded／partial／retry_wait／blocked_policy／blocked_credentials／blocked_budget／failed。消息与人工业务操作不依赖这些状态成功。

幂等键为过滤后输入哈希、消息修订、项目与任务版本、素材版本、模型配置、schema 和提示词版本。成功重复任务复用结果；业务输入变化则允许新分析。worker 使用租约，响应落库事务需防同一任务重复完成。

- 401／403：暂停模型任务，提示凭据／权限／网络需诊断，不反复请求。
- 余额或额度问题：按实际响应分类，不猜测固定状态码；归 blocked_budget 或 blocked_credentials，人工恢复后重试。
- 429：遵守可用 Retry-After，指数退避并加抖动，限制并发。
- 网络超时／5xx：有限退避，初始每 job 总计最多 3 次外部调用；包括传输和结构修复，禁止嵌套重试扩大调用数。
- JSON 坏／截断：在总次数和预算内修复一次；截断先缩上下文／调整输出预算，不能无限重复同一请求。仍失败转人工处理。
- 超时不代表服务器未计费；同任务只保证本地结果应用幂等，不保证外部只计费一次。
- 熔断：例如连续 5 次可重试失败后暂停新模型请求 5 分钟，再单任务探测；参数可调，错误类型分别计数。

每次外部 attempt 保存内部 attempt ID、HTTP 结果、耗时、请求／响应模型标识和 usage（如有）。不要假定服务支持传入 idempotency key 或总能回传 request ID。

## 7. 配置与费用

```toml
[wechat]
source = "wx_cli"
endpoint = "http://127.0.0.1:9100"
poll_seconds = 10
scan_window_seconds = 300
recent_overlap_seconds = 900

[analysis]
provider = "deepseek"
base_url = "https://api.deepseek.com"
model = "deepseek-chat" # 候选标识，接入前验证
credential_ref = "keychain:Wechat-Agent/DeepSeek"
max_output_tokens = 2000
max_concurrency = 1
max_attempts = 3

[egress]
policy = "explicit_allowlist"
redaction_profile = "merchant-logistics-v1"
preview_first_real_request = true

[budget]
daily_token_limit = 100000 # 用户可配置的示例上限，不是服务商配额
max_pending_requests = 100
```

配置不含真实 key、微信密钥或客户名单；白名单由本地受限数据库配置，不放仓库示例。若开发使用 DEEPSEEK_API_KEY，检查存在性而不输出值，且不提交 .env。

调用前原子预留最大估计输入加输出预算，结束后按 usage 结算；usage 缺失／超时保留保守占用，不能记零。每日 token 本地上限不等于精确金额上限；没有可靠价格与计费信息时费用显示未知。

费用估计按服务实际计费项统计输入、缓存命中／未命中及输出 token，单价有生效日期和来源；不硬编码宣传价格。优先增量分析、项目合并、按需草稿和结果缓存，避免每日全库重跑。

## 8. API 就绪验证

1. 通过官方 HTTPS 路径发送虚构最小请求，验证权限、返回及 usage；不使用真实客户数据做首次测试。
2. 使用包含三方角色、相对日期、报价条件的虚构片段，验证结构校验与证据关联。
3. 本地 mock 故障测试覆盖 401、429、超时、5xx、空响应、坏 JSON 和截断，不能通过真实刷接口制造限流。
4. 用户在本地确认首个允许的真实脱敏请求预览，随后在已批准政策内自动分析。
5. 记录模型、配置、提示词与输入版本，评估建议准确率和日期／责任方错误；验收通过再启用日常增量。

没有有效凭据时 API 集成状态必须为未验证；mock 通过不能替代真实请求成功。
