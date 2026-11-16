# 同步整理准入、发布保护与记录反馈 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. 沿用已授权的云端串行实施；本文件保留执行步骤；云端交付与实施取舍见验收报告，Mac待实测。

**Goal:** 已知会话完整可读的客户能正常整理，真正的读取缺口仍阻止受影响客户发布；整理记录准确显示客户名、结果、原因及后续动作。

**Architecture:** 一份关联规则、一份按客户评估的覆盖报告、一份前后端共用的任务结果契约。同步原始事实与影响评估分开，模型只消费获准的固定快照，发布保持版本及证据门禁；记录从持久化报告派生，不再靠任意gaps或计数推断成功失败。

**Tech Stack:** Python 3.12、FastAPI/Pydantic、SQLite schema14→15、React/TypeScript、Node 24.14.1、pytest、Vitest、Playwright。wx-cli保持已交付`.2`，不预设再次修改协议。

**Spec:** [整理重设计](../specs/2026-11-16-organize-outcomes-design.md)。测试数据：[45个合成场景](../fixtures/organize-badcases.json)，已接入合成来源／Gateway的真实工作流回放，实测计数见验收报告。

## Global Constraints

- 已知会话失败时该客户不发布；群覆盖未知允许有证据的更新。沿用已批准方案的保守边界，不扩展为任意部分材料发布。
- 不放松账号、角色、业务范围、人工版本、原文修订、worker和元数据代次校验；未知错误默认阻断，不按字符串前缀降级。
- 人工移出优先，模型仅整理业务范围内确认商家；保持90天业务范围规则。
- Python 3.12、Node最低24.14.1；不新增依赖，不改上游技能；真实消息、密钥、本地库及.local证据不提交。
- 原文保留上下文、日历蓝点本人发言、缓存和本地上一条／下一条性能均不得回退。
- 历史完整性仍未验证；不把已知范围完成标成全历史完整。不恢复旧白名单、待办或跟进系统。
- 不吞失败、不清空gaps骗成功、不因新增0就跳过首次整理、不自动重跑旧任务或真实付费模型。
- 云端以合成来源与模型回放验收，Mac只pull/build/运行/实测；两种验收分别记录。

## Review Focus

1. 无关未知群使所有客户被阻断，或相关缺页被错误放行：Task2和Task3的正反对照必须证明边界。
2. 全量共享群失败影响多人，错误只阻断一个或阻断全体：Task3覆盖共享与不共享会话。
3. 覆盖warning／空模型字段导致旧事实、批次或人工值消失：Task4验证成功及拒绝发布后head和证据可访问性。
4. 同名、改名、删除、跨账号和历史缺字段导致记录错人、串数据或伪成功：Task1与Task5验收。
5. 刷新／模型／发布／停止阶段混淆，轮询改变排序，错误文本泄露，重复点击重复付费：Task5与Task6验收。

## 文件职责和接口

| 文件 | 职责 |
| --- | --- |
| 新`source/coverage.py` | `OperationIssue`、`ContactCoverage`、`SyncAssessment`，分类和按客户影响评估；纯评估不发HTTP |
| 新`contacts/conversations.py` | 账号内关联会话统一解析；不改变日历仅本人发言的过滤 |
| `source/sync.py` | 来源读取事实、逐会话结果、统一刷新，产出assessment输入 |
| `operations/contracts.py`、新`operations/reports.py` | OperationReport/ContactOutcome及持久化、最终结果汇总，不包含前端中文文案 |
| 新迁移`015_operation_reports.sql`、`storage/db.py` | 名称快照、版本化报告；旧记录为空，不伪造历史 |
| `operations/worker.py`、`analysis/runner.py` | 刷新→按客户准入→模型→发布→报告的唯一编排 |
| `context/contracts.py`、`context/builder.py`、`profiles/publisher.py` | 固定覆盖结论和安全正向发布，保留旧事实／人工值 |
| 前端新`operationOutcome.ts` | 一个展示映射，列表、横幅、详情消费相同结果 |
| 新`OperationHistory.tsx`及既有OperationDetails/App | 从App拆出记录列表，复用现有Dialog，不新增嵌套弹窗 |
| 新`tests/organize_scenarios.py` | 严格校验45个场景并生成来源／模型回放，不连接真实服务 |

路径均相对`src/wechat_agent/`或`frontend/src/`（表中前端项），测试为仓库根目录`tests/`。任务内列出完整路径。

### Task 1：持久化报告与客户名称契约

**Files:** 新`src/wechat_agent/storage/migrations/015_operation_reports.sql`、`src/wechat_agent/operations/reports.py`；改`operations/contracts.py`、`operations/service.py`、`storage/db.py`、`frontend/src/api/types.ts`；新`tests/test_operation_reports.py`。

**Interfaces:**
- 定义Spec中的`OperationReport`、`ContactOutcome`；问题类型来自Task2的`OperationIssue`（本任务先定义在coverage模块，Task2实现评估）。
- `save_report(conn, account_id: str, operation_id: str, report: OperationReport) -> None`；`load_report(...) -> OperationReport | None`。报告表主键(account_id,operation_id)，报告JSON内version固定1，禁止跨账号读取和写入。
- `Operation`新增`contact_name_snapshot: str | None = None`、`report: OperationReport | None = None`。operations新增可空名称列，另表`operation_reports(account_id,operation_id,report_json)`；不改RunState值域。

- [x] Step1 写失败测试：新建任务保存当时名称；改名后snapshot不变；历史null回退当前同账号名称；删除后可读；同名不同ID不合并；跨账号报告不可读；schema14升级保留原任务状态。测试`test_report_roundtrip_is_account_scoped`断言load错误账号不能返回报告。
- [x] Step2 运行`.venv/bin/python -m pytest tests/test_operation_reports.py -q`，确认因新契约／迁移缺失FAIL。
- [x] Step3 实现迁移、契约及读写。创建接口仍即时返回，不请求来源／模型。列表通过JOIN批量取名称与report，禁止每记录查一次联系人。旧记录回退带`legacy`说明，不回填成“当时名称”。
- [x] Step4 同一命令PASS；追加`tests/test_sync_operations.py`和`tests/test_profile_interface.py`，断言API兼容与账号隔离。
- [x] Step5 提交`feat: persist scoped operation outcomes and contact names`。

### Task 2：统一关联集合与按客户覆盖判断

**Files:** 新`src/wechat_agent/contacts/conversations.py`、`src/wechat_agent/source/coverage.py`；改`source/sync.py`、`context/builder.py`、`messages/queries.py`；新`tests/test_source_coverage.py`，改`tests/test_message_source_scope.py`。

**Interfaces:**
- `resolve_contact_conversations(conn, key: ContactKey) -> set[str]`：仅账号内已有私聊会话、有效成员关联、本人历史发言证明的群；不制造来源不存在的私聊。同步时与当前available相交读取；已有归档关联但本次来源消失的会话须显式结果，不能静默移出required。
- `OperationIssue(code, stage, severity, scope, contact_id=None, conversation_id=None, suggested_action='none')`，值域见Spec。
- `ContactCoverage(contact_id, required_conversation_ids, completed_conversation_ids, failed_conversation_ids, can_analyze, issues)`。
- `assess_sync(conn, account_id: str, contact_ids: set[str], result: SyncResult) -> SyncAssessment`。`SyncAssessment`含`global_blocked: bool`、`contacts: dict[str, ContactCoverage]`、`issues: list[OperationIssue]`。实施取舍：`SyncResult`新增逐会话conversation_gaps事实，由Assessment统一生成结构化issues；旧gaps保留诊断兼容，不作为worker唯一准入条件。

- [x] Step1 写正反失败用例：无关未知群+3/3完成→can_analyze=true；已知群缺页→false；只有作者历史消息且成员未知→关联该群且上下文含其他人发言；无成员无发言无私聊→空集合；旧已知群本次消失→blocker；未知码→global_blocked=true。不能用仅删除字符串的实现通过。
- [x] Step2 运行`.venv/bin/python -m pytest tests/test_source_coverage.py tests/test_message_source_scope.py -q`并观察FAIL。
- [x] Step3 实现统一集合及分类。来源metadata读取部分失败若不能确定影响范围，默认全局阻断；明确只是无关名称未知才作warning。不移除现有代次／身份保护。快照读取关联群完整语境，不扩大为账号全部群。
- [x] Step4 同一命令PASS；再运行`tests/test_source_sync.py tests/test_source_identity_protocol.py tests/test_context_snapshot.py`。回归日历只标本人及原文权限。
- [x] Step5 提交`fix: evaluate synchronization coverage per contact`。

### Task 3：以覆盖结论编排整理与全量部分成功

**Files:** 改`src/wechat_agent/operations/worker.py`、`analysis/runner.py`、`operations/reports.py`；新`tests/test_organize_admission.py`；改`tests/test_single_customer_flow.py`。

**Interfaces:**
- `assess_sync`替代`elif result.gaps`的一刀切分支；已有角色和业务范围筛选继续生效。
- `analyze(conn, operation, owner, session, targets, *, coverage: dict[str, ContactCoverage] | None = None)`。coverage为None仅供旧内部调用兼容，生产编排必须显式传入且缺少目标项即拒绝。
- `finalize_report(conn, account_id: str, operation_id: str) -> OperationReport`从持久化读取与整理项汇总；总任务在部分失败时底层state=failed，report标partial，不重置成功项或抹掉警告。

- [x] Step1 写失败测试：45场景中unknown_unrelated_group、known_room_timeout、mixed_account_batch、shared_failed_room、first_profile_zero_insertions、unchanged_inputs、stop_before_source。断言模型调用次数、目标ID、head是否变化、每客户原因及总报告；不是只断言任务state。
- [x] Step2 运行`.venv/bin/python -m pytest tests/test_organize_admission.py -q`，确认现有全局gaps门禁导致期望失败。
- [x] Step3 实现：全局blocker停止新模型调用；会话blocker只阻断依赖它的客户；覆盖warning不阻断。身份发现失败不得继续静默吞错，保存classification_failed，待识别身份保留，不假装已完成档案整理；资料刷新任务不读取消息、不调用模型。模型未配置时保存source=completed、analysis=failed及原因，不倒写成来源失败。没有可整理材料显示not_applicable/no_material；非商家与人工移出保留各自原因。
- [x] Step4 运行Task3测试及`tests/test_contact_refresh.py tests/test_sync_operations.py tests/test_profile_workflow.py`，全部PASS。验证单客户与全量对同一客户产生相同准入结论。
- [x] Step5 提交`feat: organize eligible contacts with explicit partial outcomes`。

### Task 4：覆盖入快照与保护旧资料发布

**Files:** 改`src/wechat_agent/context/contracts.py`、`context/builder.py`、`analysis/runner.py`、`profiles/publisher.py`；新`tests/test_profile_coverage_publication.py`；改`tests/test_profile_publish.py`。

**Interfaces:**
- 新`ContextCoverage`含`required_conversation_ids: tuple[str,...]`、`completed_conversation_ids: tuple[str,...]`、`warning_codes: tuple[str,...]`、`policy_version: Literal['known-scope-v1']`；构造时排序去重。`ContextSnapshot.coverage: ContextCoverage | None = None`兼容历史。
- `build_snapshot(..., coverage: ContextCoverage | None = None)`；runner仅允许can_analyze=true的coverage构建；包含coverage的manifest参与持久化和unchanged稳定比较，任务ID、时间、显示名不参与。
- `publish`保留原接口；候选无值且旧值仍有当前快照授权证据时保留旧值；无法安全保留则返回`PublishResult(reason='retained_evidence_unavailable')`且事务不动head和批次。不得绕过validator复制无效证据。

- [x] Step1 写失败测试：warning不清空旧货品／物流／沟通；备货批次不因未返回而删除；人工值优先；旧证据修订变化不能复用；非法跨客户／账号引用不发布；失败保留head；同材料但覆盖warning集合变化不误判unchanged；人工、身份、范围、修订变化及停止仍拒绝过期发布。
- [x] Step2 运行`.venv/bin/python -m pytest tests/test_profile_coverage_publication.py -q`观察FAIL。
- [x] Step3 实现固定覆盖和保守发布；本轮不增加“根据没提到推断取消需求”操作。保留历史版本证据入口及权限。history_complete_unverified是范围提示，不能单独使UI显示整理失败。
- [x] Step4 运行Task4测试及`tests/test_profile_publish.py tests/test_manual_profiles.py tests/test_profile_interface.py`全部PASS。先前保留批次来源回归必须继续通过。
- [x] Step5 提交`fix: preserve evidence-backed facts during scoped organization`。

### Task 5：记录、客户横幅统一展示结果与动作

**Files:** 新`frontend/src/app/operationOutcome.ts`、`frontend/src/components/OperationHistory.tsx`；改`frontend/src/app/App.tsx`、`app/useOperations.ts`、`components/OperationDetails.tsx`、`api/types.ts`及既有样式；新`frontend/src/app/operationOutcome.test.ts`，改`components/OperationDetails.test.tsx`。

**Interfaces:**
- `presentOperation(operation: Operation): OperationPresentation`，结果含`title`、`scopeLabel`、`tone: 'neutral'|'success'|'warning'|'error'`、`sourceText`、`analysisText`、`reasonText`、`impactText`、`action`和`diagnostics`。
- `action: 'retry_sync'|'open_model_settings'|'review_contact'|null`映射既有创建任务／设置入口；无自动重试，不向来源发送聊天。
- `OperationHistory({operations, selectedId, onSelect, onAction})`复用Dialog中的列表；按created_at稳定排序，进行中updated_at轮询不改变任务先后。名称直接消费后端快照，不依赖当前联系人分页。

- [x] Step1 用版本化报告构造失败单测：completed+coverage warning显示“整理完成／有范围提示”；source completed+model failed显示“消息已同步，模型整理未完成”；source partial显示完成2/3及会话原因；停止不显示失败；旧记录3/3+failed仍解释旧记录原因缺失，不伪造成功；重名、改名、删除名称正确；英文码只在诊断详情中。
- [x] Step2 运行`cd frontend && npm run test:unit -- --run src/app/operationOutcome.test.ts src/components/OperationDetails.test.tsx`观察FAIL，使用Node24.14.1环境。
- [x] Step3 实现统一展示；主详情最多两行阶段结果、一项主原因、一项下一步，多个问题汇总数量并可展开。不展示供应商原始错误；所有名称和文本按React文本渲染，禁止dangerouslySetInnerHTML。旧记录不展示不存在的时长或完成时间。测试跨午夜created_at排序、轮询不跳序、极长／HTML字符姓名、未知错误码的安全展示。
- [x] Step4 同一命令PASS；键盘展开、诊断折叠、错误动作、长名称和窄窗口无溢出；点击不同记录展开不同内容。客户页横幅与记录详情标题一致。
- [x] Step5 提交`feat: explain organization results with customer-specific history`。

### Task 6：45场景数据驱动回归与端到端验收

**Files:** 新`tests/organize_scenarios.py`、`tests/test_organize_scenarios.py`、`tests/fixtures/organize-scenarios.json`；改`tests/webserver.py`、`frontend/e2e/operation-history.spec.ts`、`frontend/e2e/profile.spec.ts`；新`docs/verification/organize-outcomes-report.md`。

**Interfaces:**
- 将设计JSON复制到tests/fixtures，替换status为实际测试fixture声明；`load_cases(path) -> list[Scenario]`严格校验未知given字段，不能静默忽略开关。`seed_scenario(conn, case)`建立真实SQLite账号、联系人、群、消息修订和旧档案；`run_scenario(case) -> ScenarioObservation`记录操作HTTP结果、来源请求、模型请求、发布版本、保留资料和最终报告。
- ScenarioObservation至少含设计JSON的expect字段。创建拒绝及历史记录only场景单独走HTTP／repository验证，不假造它们执行过pipeline。invalid_evidence等归一展示码映射实际validator错误，原始固定码保留在diagnostics。

- [x] Step1 为JSON逐例参数化断言，关联Task1—5已记录的RED→GREEN证据；每个given开关必须有观测验证，新增边界先补独立失败测试再修复；模型调用只检查真实FakeGateway请求，不以手工返回次数充数。
- [x] Step2 在`.venv/bin/python -m pytest tests/test_organize_scenarios.py -q`验证尚未实现的fixture builder失败；实现严格加载、真实数据库种子和来源/模型回放。已有Task1—5测试继续独立存在，不以同一个纯展示函数验证整条管线。
- [x] Step3 增加负向控制：关闭coverage警告时结果不变；把同一群从无关改为已知失败时必须由允许变阻断；A/B共享群与独立群对照；重跑同幂等键只建一个任务且模型不重复调用；明确新任务相同输入可跳过。来源用httpx.MockTransport至少回放一次完整v2 health→refresh→metadata→messages协议，不能所有来源只使用FakeSource。
- [x] Step4 E2E覆盖四条完整路径：范围warning仍生成首次档案、消息成功但模型失败后跳转设置、全量部分成功定位具体客户、旧失败记录及切换记录。再验证日历、身份修改、复制提示层级及证据跳转。测试文字以中文产品文案为准，技术码验证限诊断展开。
- [x] Step5 运行全量Python、前端unit、全部E2E、Node24.14.1构建、wheel打包与资源校验；Playwright串行执行，不同时启动多个测试服务。预期所有受支持测试通过；不得预填通过数量，记录实际输出和失败理由。使用`npm run test:unit -- --run`、`npm run test:e2e`、`npm run build`及`.venv/bin/python -m pytest -q`；wheel运行`.venv/bin/python -m pip wheel . --no-deps -w /tmp/organize-outcomes-wheel`，检查schema15和前端资源打包且与源码逐字节一致。
- [x] Step6 执行一次独立只读整体审查；Important/Critical逐项RED→GREEN修复并重跑相关及全量，Minor明确记录。检查真实模型没有被测试调用、原文密钥没有入Git。
- [x] Step7 更新STATUS、计划索引、MAC_SETUP与验收报告，先提交回归与修复，再非强制推main。Mac验收选择至少一位有旧档案、一位无档案、一位有已知来源缺口的客户，核对消息、模型调用、证据与旧资料保留；未有真实样本时明确待测，不能用合成样本宣称质量已验收。

## 测试数据覆盖与完工标准

45个场景不是全部靠一条E2E跑完。source/coverage纯评估负责范围组合，真实数据库集成负责资料与事务，HTTP回放负责接入契约，浏览器负责结果可理解及交互；同一个场景可以跨层验证。另落实Spec浏览器及性能补充矩阵：报告列表无N+1、无读取全部正文、加载记录不调用来源／模型，旧请求不覆盖新选择，连点重试不产生重复有效任务。数据文件内reason是期望归一报告码，真实底层码需保留并在实现中显式映射，禁止虚构来源协议。

本轮必须证明：3/3已读完+无关未知群不阻断；2/3已读完不能为该客户发布；全量只影响确实依赖失败会话的客户；历史未知范围不会被宣称完整；0新增不等于0模型调用；模型和发布失败不误称来源失败；记录始终能回答“谁、做到哪、哪里失败、旧资料是否保留、下一步是什么”。

## 自审与交接

方案覆盖→Task1契约、Task2范围、Task3编排、Task4发布、Task5反馈、Task6数据与验收。五项Review Focus各有显式测试。新增API字段可空，旧快照coverage可空，旧记录不回填成功；未知严重问题默认阻断。source与model的“完成”不再混用，任务控制state与展示outcome分开。

已按既定executing-plans串行实施全部云端任务。接口共享的Task1—4及后端回归以原子后端提交交付，Task5前端与Task6文档／验收分别提交；不伪造逐步骤独立提交。按已知范围完整读取的保守边界执行，实际文件与接口取舍见验收报告。本轮不声称M2真实质量已通过，Mac验收清单保持待测。
