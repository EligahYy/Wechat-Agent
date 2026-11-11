# 阶段之间的内部契约

这些是待实现的内部接口，由各计划标注的任务创建。名称改变必须同步消费者和测试；不要求 wx-cli 或 DeepSeek 原生返回这些结构。业务字段与展示规则仍以有效产品方案为准。

## M0 创建：来源、能力与证据

`src/wechat_agent/source/contracts.py` 使用 Pydantic：

- `ContactKey(account_id: str, contact_id: str)`；所有客户读写以二者限定，不用显示姓名作键。
- `ContactRecord(key: ContactKey, remark: str | None, nickname: str | None, is_self: bool)`。
- `ConversationRecord(account_id: str, conversation_id: str, kind: Literal['private','group'], title: str | None, member_ids: list[str])`。
- `MessageRecord(account_id: str, conversation_id: str, message_id: str, sender_id: str, sent_at: datetime, kind: str, body: str, reply_to: str | None, attachment_ids: list[str], source_revision: str, raw: dict)`；时间需带时区，修订由源字段或经验证的同消息版本摘要映射。
- 此处 message_id 是保留来源命名空间／会话的规范化稳定身份，避免不同会话的本地 ID 相撞；原始源标识另存在 raw。数据库自增修订 revision 与源端 source_revision 的映射由归档层维护。
- `SourcePage(account_id: str, conversation_id: str, records: list[MessageRecord], next_cursor: str | None, complete: bool, gaps: list[str])`；空页也能保存明确会话的游标，records 的账号／会话必须一致。
- `SourceAdapter` Protocol：`check() -> CapabilityReport`；`contacts() -> list[ContactRecord]`；`conversations() -> list[ConversationRecord]`；`messages(conversation_id: str, cursor: str | None, limit: int) -> SourcePage`；`fetch_attachment(attachment_id: str) -> AttachmentFetch`。均为 async；账号固定在适配器实例中。
- `AttachmentFetch(attachment_id: str, state: Literal['original','thumbnail','missing','unavailable','failed'], content: bytes | None, mime: str | None, reason: str | None)`。
- `CapabilityReport(component: str, status: Literal['passed','failed','pending','unsupported'], facts: dict, gaps: list[str], checked_at: datetime)`；未实际调用不得 passed。

`src/wechat_agent/model/contracts.py` 创建 `ModelCapabilities(model_id: str, context_tokens: int, max_output_tokens: int, structured_output: bool, vision: bool, verified_at: datetime)`。运行时实际值来自 M0 证据，不提供假 Pro 默认值。

## M1 创建：归档、API 与最小操作

- `storage/db.py: open_db(path: Path) -> sqlite3.Connection`，启用外键、WAL、有限 busy timeout；`migrate(conn) -> None` 按版本迁移。
- `source/repository.py: archive_page(conn, page: SourcePage) -> ArchiveDelta`，返回 `inserted: int, revised: int, unchanged: int`，同一事务保存消息及游标。
- `contacts/service.py: set_roles(conn, keys: list[ContactKey], role: str, expected_versions: dict[str,int]) -> RoleUpdateResult`；角色值 `merchant / provider / platform / unknown`，禁止修改本人为商家。
- `source/sync.py: sync_scope(conn, source: SourceAdapter, scope: OperationScope, cancellation: CancellationToken) -> SyncResult`；后者含成功会话、失败会话、变化数量及 gaps。
- `operations/contracts.py`：`OperationScope(account_id: str, contact_id: str | None)`；`CancellationToken(operation_id: str, generation: int)`；`RunState = queued | running | stop_requested | stopped | succeeded | failed`。
- `Operation(id: str, scope: OperationScope, state: RunState, phase: str='queued', generation: int=1, remaining: int=0, counts: dict[str,int]={})`，可用动作在响应时计算；counts 使用 default_factory，不共享可变默认值。
- `operations/service.py: create_operation(conn, action: str, scope: OperationScope, idempotency_key: str) -> Operation`；`operations/worker.py: run_next(conn, services: Services) -> Operation | None`。M1 只执行同步，不支持的分析能力返回 `capability_not_ready`，不返回假档案。
- `run_next` 与 `sync_scope` 都是 async；数据库事务本身同步，事务里不 await 网络。POST `/api/operations` 创建 body 为 `{action, scope, idempotency_key}`；控制 body 为 `{action, operation_id, target_item_ids?}`，不允许控制请求伪造账号范围。
- `api/app.py: create_app(settings: Settings, services: Services | None = None) -> FastAPI`；测试以依赖注入提供回放源。`Services` 在 `services.py` 定义，先含 `source: SourceAdapter | None`，以后增加 model／strategy，不更换调用入口。
- HTTP 日期为 ISO 8601（含偏移）；错误为 `{code, message, details}`，冲突 409、无效输入 422、源服务失败 502；错误不含密钥。
- 联系人／档案／原文／单号路由均显式携带 account_id，并由服务端验证当前账号权限；不能只凭裸 contact_id 读写。
- 联系人响应 `{items, total, page, page_size}`，最大 20；每行含稳定 `key`、`display_name`、`role`、`role_version`、`sources` 和资料状态。
- M2 扩展联系人行的 `goods_route`、`communication`、`last_business_at`、`profile_updated_at`，不另写一份虚构商家列表；商家视图按 last_business_at，未整理回退最近归档消息时间。
- `frontend/src/api/types.ts` 随后端契约保持一致；`api/client.ts: request<T>(path: string, init?: RequestInit): Promise<T>` 只访问同源 `/api`。

M1 创建 `tests/conftest.py` 的 `db`（临时 SQLite）、`client`（隔离 FastAPI TestClient）、`case(name)`（读取 `tests/fixtures/<name>.json`）夹具。回放源在 `tests/fakes/source.py` 实现 SourceAdapter，保留实际调用清单；fixture 均为合成或脱敏材料。

`source-overlap.json` 的规范样本使用 acct-1、merchant-a、merchant-b、provider-p、self-1 和 dm-a／group-1，另补合成联系人到28位可管理联系人（不含本人），供20/8分页测试；page 键是可被 SourcePage 验证的一页消息。M1 Task 2 创建 `seed_case(conn, name) -> None` 测试帮助函数，填入该样本对应的账号、联系人、角色、会话和原文；不出现在生产代码中。

商家甲是 merchant-a 的合成显示名。M1 Task 5 创建 `tests/webserver.py`，仅这个隔离测试服务注册 `/api/__test__/reset`，按 case 重置测试数据库；生产 app 不注册该路由。前端 E2E 使用同源 `/api`，测试端口18001／18002、workers=1，默认 `beforeEach` 复位 source-overlap；后续阶段加对应 case，不把合成数据塞入生产包。

## M2 创建：档案、模型与发布

- `profiles/contracts.py`：`Fact(value: str | None, state: known | uncertain | not_mentioned, sources: list[SourceRef], event_time: datetime | None, batch_ref: str | None)`；`SourceRef(message_id: str, revision: int, attachment_id: str | None, locator: str | None)`，查询时始终加账号和快照权限。
- 固定键：`goods.category / products / special_attributes / volume`；`logistics.origins / destinations / warehouse_postcode / transport / clearance_tax / timing / price / pickup_lastmile / concerns`。
- `Communication(summary: Fact, tags: list[str], last_business_at: datetime | None)`；`ShipmentCandidate(existing_id: str | None, candidate_key: str, goods: list[Fact], logistics: list[Fact], stage: str, numbers: list[str], sources: list[SourceRef])`。
- `AnalysisResult(contact_id: str, goods: dict[str,Fact], logistics: dict[str,Fact], communication: Communication, shipments: list[ShipmentCandidate], gaps: list[str])`；`coverage` 不由模型返回。输出结构 `schema_version=1`。
- `context/contracts.py: ContextSnapshot(id: str, key: ContactKey, cutoff: datetime, material_refs: list[SourceRef], role_version: int, manual_version: int, versions: dict[str,str], gaps: list[str])`。
- `context/builder.py: build_snapshot(conn, key: ContactKey, cutoff: datetime) -> ContextSnapshot`；拒绝非商家。
- `model/gateway.py: ModelGateway.generate(request: ModelRequest, cancellation: CancellationToken) -> ModelResponse`（async）；构造器注入 HTTPX client、凭据存储和模型配置，Services 增加可空 model。请求含 call_id、unit_id、snapshot_id、phase、model_config_version、messages、output_schema、output_tokens；响应含 payload、finish_reason、usage、model_id。类型放 `model/contracts.py`，不依赖全局可变 client。
- `ModelConfig(version: str, endpoint: str, model_id: str, credential_ref: str, capabilities: ModelCapabilities)`，不内嵌明文密钥；保存设置时的临时凭据输入交给后端 CredentialStore，响应只返回配置状态。
- `analysis/contracts.py: AnalysisStrategy.run(snapshot: ContextSnapshot, checkpoint: dict | None, cancellation: CancellationToken) -> AnalysisResult`（async）；`analysis/workflow.py: WorkflowV1` 为首版实现。
- `profiles/publisher.py: publish(conn, snapshot: ContextSnapshot, result: AnalysisResult, cancellation: CancellationToken) -> PublishResult`，返回 version、完整性、拒绝原因。
- `PublishResult(version: int | None, complete: bool, reason: str | None)`；目标错配 reason 为 target_mismatch，version=None。
- `profiles/manual.py: save_manual(conn, key: ContactKey, patch: dict, expected_version: int) -> int`；人工来源与模型值分开。

M2 添加 `snapshot` 夹具（源自跨私信／群样本的已确认商家快照），`model_transport` 夹具（HTTPX MockTransport，记录请求及次数）。测试会显式导入需要断言的服务，不以真实 API 网络调用充当单元测试。

M2 Task 3 的测试网关 fixture 为 gateway；model_transport 提供 `responses: list[httpx.Response]` 脚本队列和 `calls: list[httpx.Request]`，用自定义 AsyncBaseTransport 实现；model_request、cancellation、capabilities 都在该任务的 conftest 中创建，分别指向合法快照、已落盘运行项和合成已核验窗口。M2 Task 4 增加 analysis_result fixture，用该 snapshot 的真实引用构造合法候选；类型或字段变化同步这些测试帮助函数。

模型失败统一为 `ModelCallError(code: str, message: str)`，鉴权失败 code=authentication_failed，实际 token 不进入 message。M2 Task 7 的 services fixture 组合回放源、gateway 和 WorkflowV1；model_calls 按 account_id、contact_id、snapshot_id 记录，便于核验范围。

## M3–M5 增量扩展

- M3 `context/chunks.py: plan_chunks(snapshot, capabilities) -> list[ContextChunk]`；段标识稳定、包含来源及重叠；`attachments/parser.py: parse_attachment(path: Path, mime: str) -> ParseResult`，返回 `state, fragments, gaps, parser_version`，片段含 text、locator。
- M3 `analysis/coverage.py: compute_coverage(conn, snapshot_id: str) -> Coverage`，列出 processed／failed／pending 的来源和段；`analysis/checkpoints.py: load_checkpoint(conn, snapshot_id: str, unit_id: str, cache_key: str) -> dict | None`。
- `Coverage(processed: list[str], failed: list[str], pending: list[str], complete: bool)`；ContextChunk.input_tokens 包括规则／模板／人工约束／材料，output_tokens 单列，二者加安全余量核算。
- M4 扩展原 operations 服务，添加 `control_operation(conn, operation_id: str, action: str) -> Operation`；`settings/repository.py: save_schedule(conn, account_id: str, enabled: bool, time: str, timezone: str) -> Schedule`；`operations/scheduler.py: tick(conn, now: datetime) -> list[str]`，返回本次创建的操作 ID 列表（每账号每日最多一个）。
- M5 `maintenance/backup.py: create_backup(conn, destination: Path) -> BackupManifest`；`restore_backup(manifest: Path, destination: Path) -> None`；`maintenance/reanalysis.py: plan_reanalysis(conn, keys: list[ContactKey], strategy_version: str) -> ReanalysisPlan`。类型定义在相邻 `contracts.py`。
- BackupManifest 返回 `manifest_path: Path` 和已写入的版本／哈希清单；非空恢复目标抛 FileExistsError。ReanalysisPlan 含 `keys: list[ContactKey]`、`strategy_version: str`、`count: int`，规划不创建操作。

这些签名是计划基线。未知的上游参数不通过“待填字符串”进入代码；M0 之后若发现需要变更，先改此文件、相关计划和契约测试，再执行消费者任务。
