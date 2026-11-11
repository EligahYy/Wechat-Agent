# 阶段之间的内部契约

这些是待实现的内部接口，由各计划标注的任务创建。名称改变必须同步消费者和测试；不要求 wx-cli 或 DeepSeek 原生返回这些结构。业务字段与展示规则仍以有效产品方案为准。

## M0 创建：来源、能力与证据

`src/wechat_agent/source/contracts.py` 使用 Pydantic：

- `ContactKey(account_id: str, contact_id: str)`；所有客户读写以二者限定，不用显示姓名作键。
- `ContactRecord(key: ContactKey, remark: str | None, nickname: str | None, is_self: bool)`。
- `ConversationRecord(account_id: str, conversation_id: str, kind: Literal['private','group'], title: str | None, member_ids: list[str])`。
- `MessageRecord(account_id: str, conversation_id: str, message_id: str, sender_id: str | None, sent_at: datetime, kind: str, body: str, reply_to: str | None, attachment_ids: list[str], source_revision: str, raw: dict)`；时间需带时区，修订由源字段或经验证的同消息版本摘要映射。只有来源明确识别的 system／revoke 事件允许 sender_id=None；保留内容、时间和原始来源，已有真实发送人则保留。普通聊天仍要求非空稳定发送人，不按名称或方向推断。
- 此处 message_id 是保留来源命名空间／会话的规范化稳定身份，避免不同会话的本地 ID 相撞；原始源标识另存在 raw。数据库自增修订 revision 与源端 source_revision 的映射由归档层维护。
- `SourcePage(account_id: str, conversation_id: str, records: list[MessageRecord], next_cursor: str | None, complete: bool, gaps: list[str], conversation_kind: Literal['private','group'] | None=None, issues: list[SourceIssue]=[])`；列表使用default_factory。空页也能保存明确会话的游标，records的账号／会话必须一致；complete与游标／缺口不能矛盾。
- `SourceIssue(code: Literal['message_sender_missing','source_message_id_unavailable','message_contract_invalid'], message_id: str | None, raw: dict)`；归属不足的原文单独保存，不能强行插入正常消息或静默丢弃。已知稳定消息ID只按身份和版本去重问题记录；没有稳定ID时保留各次观察，不按正文合并。修复后重读可标记旧问题已解决，旧原文仍保留。
- `SourceAdapter` Protocol：只读属性`account_id: str`；`check() -> CapabilityReport`；`contacts() -> list[ContactRecord]`；`conversations() -> list[ConversationRecord]`；`messages(conversation_id: str, cursor: str | None, limit: int) -> SourcePage`；`fetch_attachment(attachment_id: str) -> AttachmentFetch`。方法均为async；账号固定在适配器实例中。
- `AttachmentFetch(attachment_id: str, state: Literal['original','thumbnail','missing','unavailable','failed'], content: bytes | None, mime: str | None, reason: str | None)`。
- `CapabilityReport(component: str, status: Literal['passed','failed','pending','unsupported'], facts: dict, gaps: list[str], checked_at: datetime)`；未实际调用不得 passed。

`src/wechat_agent/model/contracts.py` 创建 `ModelCapabilities(model_id: str, context_tokens: int, max_output_tokens: int, structured_output: bool, vision: bool, verified_at: datetime)`。运行时实际值来自 M0 证据，不提供假 Pro 默认值。

## M1 创建：归档、API 与最小操作

- `storage/db.py: open_db(path: Path) -> sqlite3.Connection`，启用外键、WAL、有限 busy timeout；`migrate(conn) -> None` 按版本迁移。
- `open_existing_db(path: Path, *, readonly: bool=False)`供运行时请求使用，URI模式为ro／rw，缺失数据库直接失败；只有显式初始化／迁移入口可创建数据库。联系人GET只读，单次查询的计数与行使用同一读事务。
- 数据库路径为Settings.data_dir下的archive.sqlite3；已交付迁移不原地修改，后续表结构变更新增版本。FTS搜索必须关联messages并按account_id限定，不能把全库索引结果直接返回给联系人接口。设置按账号保存，应用级偏好若需要持久化另加迁移。
- `source/repository.py: archive_page(conn, page: SourcePage) -> ArchiveDelta`，返回 `inserted: int, revised: int, unchanged: int`，同一事务保存消息及游标。
- `archive_metadata(conn, account_id, contacts, conversations) -> None`保存真实来源名称、会话与成员，不覆盖人工role／role_version。archive_page在写入前重验页内范围，缺口页保存有效消息和原始问题但不推进游标；修订保留原时间偏移和raw，后续跨偏移排序须按真实时间值换算，不能直接比较ISO字符串。
- `contacts/service.py: set_roles(conn, keys: list[ContactKey], role: str, expected_versions: dict[str,int]) -> RoleUpdateResult`；角色值 `merchant / provider / platform / unknown`，禁止修改本人为商家。
- 身份批次只含同一账号，expected_versions以contact_id为键。PATCH `/api/contacts/roles`接收`{account_id, role, items:[{key:{account_id,contact_id},expected_version}]}`，最多500项，重复联系人为422。实际变更才递增role_version，同角色为不改版本的成功项；本人业务身份锁定。
- `RoleUpdateResult(status:'succeeded'|'partial'|'failed', updated:[{key,role,role_version,changed,cancelled_analysis_items,cancelled_operations}], failed:[{key,code,current_version}])`。全部通过返回200；有逻辑冲突返回409，错误details中保留完整结果。合法项已提交，前端必须应用updated的新版本、仅保留失败选择，不能把整个409当成全部回滚或盲目重试旧版本。数据库执行失败则整批回滚、返回503，不回显底层错误。
- 撤销仅作用于排队的`phase='analysis'`项及目标明确的排队分析操作，保留原文、来源同步、其他联系人和正在运行的项。分析工作单元统一使用此phase；内部模型调用的extract／merge等阶段独立记录。M2发布仍须核对merchant身份和snapshot.role_version，不能因请求已发出就发布非商家结果。
- `source/sync.py: sync_scope(conn, source: SourceAdapter, scope: OperationScope, cancellation: CancellationToken | None, *, conversation_ids: list[str] | None=None, page_size: int=200, max_pages: int=1000, from_start: bool=False, sample: bool=False, on_progress=None) -> SyncResult`；结果含total_conversations、successful_conversations、failed_conversations、incomplete_conversations、inserted／revised／unchanged、pages_processed、gaps、stopped及history_complete=False。限量未扫完与真正失败分开。None仅供独立验证CLI；正式操作传持久化取消令牌，提交前再次检查状态和generation。进度回调在选择目标、每页提交后和每个会话结束后执行，回调不位于归档写事务内。
- 原子提交同时校验已有cursor和数据库租约；不同连接／进程不能同时推进同一会话。租约有效120秒，逐页续租，等锁最多5秒，过期所有者不得提交。网络请求不持写事务。账号／会话错配拒绝归档，跳行、分片错误及异常行保留具体缺口。SQLite schema2新增source_issues和sync_leases，不修改schema1迁移。
- `operations/contracts.py`：`OperationScope(account_id: str, contact_id: str | None)`；`CancellationToken(operation_id: str, generation: int)`；`RunState = queued | running | stop_requested | stopped | succeeded | failed`。
- `Operation`包含id、scope、action、state、phase、generation、remaining、counts、error_code、source_state、options、history_complete=False、items、created_at、updated_at和available_actions。items含各项state／phase／counts／gaps／error_code及分析目标的role_version；不返回内部checkpoint。可变字段使用default_factory。M1仅queued／running支持stop，其余可用动作为空。
- `SyncOptions(sample: bool=False, from_start: bool=False, page_size: int=200, max_pages: int=1000, conversation_ids: list[str] | None=None)`。sample自动收窄默认值到每页20条、每会话2页，并最多选择一个私信和一个群；显式超限拒绝。实际选择参数持久化且可查询，样本扫描完成不等于全历史完整。
- `operations/service.py: create_operation(conn, action: str, scope: OperationScope, idempotency_key: str, *, options: SyncOptions | None=None) -> Operation`；`control_operation(conn, account_id, operation_id, action)`；`operations/worker.py: run_next(conn, services: Services, *, account_id=None, on_claim=None) -> Operation | None`为async。同账号幂等键对应同一不可变意图，改变action／scope／options返回409；不同键重复提交同一活动范围也返回409及已有operation_id。
- POST `/api/operations`创建body为`{action:'sync'|'sync_and_organize', scope, idempotency_key, options?}`，落盘后返回202，表示接受而非完成。控制body为`{action:'stop', account_id, operation_id}`，返回200；服务端先验证账号，不接受伪造范围。GET `/api/operations/{id}?account_id=...`返回详情，GET `/api/operations?account_id=...&page=1&page_size=20`返回`{items,total,page,page_size}`，历史行省略items。读事务保证快照一致。
- M1执行真实来源同步，不调用模型。sync完成即可成功；sync_and_organize针对当前merchant且有已归档材料的目标生成分析项，即使本次无新消息也不能跳过首次整理。分析尚未实现时source_state可为succeeded，总操作为failed／capability_not_ready；无分析目标才只完成来源同步。单客户操作可归档共享群上下文，但只规划该客户的分析项。源端不可用为source_unavailable，页数上限或材料缺口为source_incomplete，不能解释成没有新消息。
- SQLite schema3通过迁移003增加请求选项、worker所有权、项进度和role_version，保留001／002原文。领取用事务限定每账号一个运行操作；停止先落盘generation屏障，再取消本进程请求，迟到页不能提交。正常退出停止活动项；确认所有者进程已退出的遗留任务记为interrupted／stopped，不自动重放。PID复用、完整租约恢复及继续／重试由M4完成。
- `api/app.py: create_app(settings: Settings, services: Services | None = None) -> FastAPI`；`Services`含`source: SourceAdapter | None`、`source_factory: Callable[[str], AbstractAsyncContextManager] | None`及`auto_run: bool=True`。应用lifespan拥有worker；未注入Services时按配置延迟构造固定账号WXCLIAdapter，每个操作关闭自己的连接。注入source由调用方管理，factory上下文按操作关闭。空队列启动不读取微信。测试通常用auto_run=False手动驱动，生命周期用例例外；以后增加model／strategy而不更换入口。
- HTTP 日期为 ISO 8601（含偏移）；错误为 `{code, message, details}`，冲突 409、无效输入 422、源服务失败 502；错误不含密钥。
- 联系人／档案／原文／单号路由均显式携带 account_id，并由服务端验证当前账号权限；不能只凭裸 contact_id 读写。
- 联系人API按服务端source_config.expected_account_id或注入source.account_id限定；配置冲突返回503。无绑定时仅允许读取唯一的已归档账号，多账号须明确配置，否则409/account_binding_required；请求不能自行选择其他账号，越界403，混入其他账号的批次写入前整体拒绝。
- 联系人响应 `{items, total, page, page_size}`，最大 20；每行含稳定 `key`、`display_name`、`role`、`role_version`、`sources` 和资料状态。
- GET `/api/contacts` 查询参数为 `account_id`、`q`、`role`（all／四类身份）、`page`、`page_size`。响应另含 `role_counts`（搜索结果的身份分布，不随身份筛选改变）；来源用 `{conversation_id,kind,title}`。每行包含 `display_name_source`、`copy_name`、`last_message_at`、`last_business_at`、`profile_status`、`profile_updated_at` 及 `source_gaps`。名称按真实备注→昵称选择，缺失则明确标记，`copy_name=None`，不能复制wxid替代；中文子串、百分号、下划线、星号和反斜线按字面检索。
- M1按相关归档材料的原消息时间排序（含时区换算），不是同步或模型处理时间，也不是已确认业务时间；last_business_at、profile_updated_at暂为None。商家有材料为pending，无材料为no_data；非商家profile_status=None。M2接入实际档案后再更新业务字段；不能先生成演示摘要。
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
- 输入完整性必须检查相关未解决source_issues和未读完的sync_cursors，将具体缺口写入snapshot.gaps；不能把未读取或归属不足的内容当成模型已确认“未提及”。
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
- M4扩展现有`control_operation(conn, account_id, operation_id, action)`，保留账号校验并增加受条件限制的继续／重试；`settings/repository.py: save_schedule(conn, account_id: str, enabled: bool, time: str, timezone: str) -> Schedule`；`operations/scheduler.py: tick(conn, now: datetime) -> list[str]`，返回本次创建的操作ID列表（每账号每日最多一个）。
- M5 `maintenance/backup.py: create_backup(conn, destination: Path) -> BackupManifest`；`restore_backup(manifest: Path, destination: Path) -> None`；`maintenance/reanalysis.py: plan_reanalysis(conn, keys: list[ContactKey], strategy_version: str) -> ReanalysisPlan`。类型定义在相邻 `contracts.py`。
- BackupManifest 返回 `manifest_path: Path` 和已写入的版本／哈希清单；非空恢复目标抛 FileExistsError。ReanalysisPlan 含 `keys: list[ContactKey]`、`strategy_version: str`、`count: int`，规划不创建操作。

这些签名是计划基线。未知的上游参数不通过“待填字符串”进入代码；M0 之后若发现需要变更，先改此文件、相关计划和契约测试，再执行消费者任务。
