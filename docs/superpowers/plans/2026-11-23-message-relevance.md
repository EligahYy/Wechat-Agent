# 按档案字段筛选沟通原文开发计划

> **执行方式**　使用 Superpowers executing-plans 串行执行，按任务先写回归用例，再实现、验证和提交。

**目标**　让本地筛选覆盖已授权的归档历史，模型集中提取与客户档案相关的事实，减少首次及增量整理的请求量。

**架构**　沿用快照、整理队列、模型网关和证据发布。快照后生成按消息修订记录的分级清单，给现有分段器提供高价值主材料、允许的上下文和证据白名单。筛选、提取和发布分别保存可核对的结果。

**技术栈**　Python 3.12、SQLite、FastAPI、React、Node 24.14.1、pytest、Vitest、Playwright。

**依据**　[分级设计](../specs/2026-11-23-message-relevance-design.md) · [产品资料状态](../../PRODUCT_DESIGN.md#7-同步整理与资料状态) · [现有模型执行](../../MODEL_EXECUTION.md)

**状态**　待开发。基线 `67fa941`、workflow-v4、schema 19。下文文件名和接口为计划契约。

## 全局约束

- 规则复用现有档案货品、物流、沟通和备货字段。按账号、客户、消息修订核验权限和证据。保留原文、冻结引用、人工编辑与历史版本。
- 规则分级和离线预览均为零模型调用。输出覆盖以校验过的原文区间和有效检查点证明。分段遵守供应商实际容量、现有 20 次请求或 10 分钟的执行预算、单工作单元重试上限。
- 同一条消息的分级随客户及相关依赖变化。等级可因规则、对话引用或人工复核更新。模型提议补证时，由程序重新核验，并受一次局部提取和现有预算约束。
- 按已知范围读取的来源缺口、附件待解析和事实待核对继续如实展示。相关性改造沿用现有业务范围及商家准入。
- 先做离线对照，再以单客户明确选用方式启用。记录真实微信和供应商的实测结果，通过质量和性能门槛后另行确定扩大范围。

## 文件与职责

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| 规则 | `src/wechat_agent/context/relevance.py`，新增 | 字段线索、归属、升级理由与确定性分级 |
| 持久化 | `src/wechat_agent/analysis/relevance.py`，新增 | 筛选清单、受影响依赖、复核记录、受检输入版本 |
| 运行 | `analysis/{runner,runtime,history,coverage,checkpoints}.py`、`context/assembler.py` | 策略选择、按级取材、继续与覆盖证明 |
| 档案与记录 | `profiles/{publisher,status,manual}.py`、`operations/{contracts,reports,service}.py` | 更新准入、零调用结果、状态与原因 |
| 工作台与核对 | `api/operations.py`、`frontend/src/components/{HistoryProgress,OperationDetails}.tsx`、`frontend/src/app/App.tsx`、`frontend/src/app/useOperations.ts` | 分级进度、复核与单客户启用 |
| 样本与验证 | `tests/fixtures/relevance/`，新增 | 固定输入、人工事实期望和配对基准 |

## 重点回归

1. 同群两个客户与同名说话人，报价只有明确归属时才能入选或发布。
2. 「改成 12」「先别发」和跨月引用能改变旧批次，规则缺词时仍可根据关联升级。
3. 唯一旧证据被撤回或修订后，无法通过新增闲聊的零调用路径将档案标为已更新。
4. 局部补证因超时暂停，续跑继承策略与分级版本并复用成功工作，覆盖分母动态增加一次。
5. 仅有附件、无匹配业务原文、真正模型空结果是三个可区分的结果。

## 任务 1　分级规则和离线对照

**文件**　新增 `src/wechat_agent/context/relevance.py`、`tests/test_message_relevance.py` 和 `tests/fixtures/relevance/`。

**接口**　`classify_messages(snapshot, rows, actors, conversations, *, known_batches, reviewed_refs) -> RelevanceManifest`。清单项含 `message_id`、`revision`、`level`、`field_paths`、`reason_codes`、`dependencies` 和 `needs_review`。输出附规则版本，不携带重复正文。输入来自授权快照，分类函数不访问外部服务。

- [ ] 写 `test_two_customers_and_cross_month_correction`，断言目标客户的「15 方」及跨月「改成 12，先别发」为高，另一客户已明确独立的报价为低，无法归属的报价为中且待核对。
- [ ] 写 `test_noise_unusual_business_and_attachment_only`，断言寒暄为低，未命中词表的疑似业务改动为中，纯附件保留解析缺口，数字或相似单号单独出现不升级。验证清单逐修订完全覆盖，分类重复运行结果一致。
- [ ] 运行 `.venv/bin/python -m pytest -q tests/test_message_relevance.py`，看到接口缺失或期望不符后实现分级规则、报价否定等短句及可验证的对话归属。
- [ ] 重跑分类用例通过。对已有冻结快照运行本地预览，输出脱敏的分级数量和命中原因，确认模型调用数为 0。提交规则与样本。

## 任务 2　持久化分级清单和证据依赖

**文件**　新增 `src/wechat_agent/analysis/relevance.py`、`src/wechat_agent/storage/migrations/020_message_relevance.sql`、`tests/test_relevance_storage.py`，修改 `storage/db.py`。

**接口**　`save_relevance(conn, snapshot, token, manifest)`、`load_relevance(conn, account_id, snapshot_id)`。清单按账号、快照、客户及规则版本索引，依赖索引记录消息编号和修订。复核记录按账号、客户、消息修订保存。写入使用现有事务与操作代次校验。

- [ ] 写 `test_relevance_manifest_persists_and_rejects_stale_or_foreign_refs`，断言重启后清单完整，相同请求幂等，跨账号证据及取消后的写入被拒绝。写 `test_schema19_upgrade_preserves_history`，验证已有快照、档案、检查点和整理记录可读。
- [ ] 运行 `.venv/bin/python -m pytest -q tests/test_relevance_storage.py`，确认失败点后实现迁移、读写及反查索引。原文正文仍通过现有快照读取。
- [ ] 重跑存储及旧库回归，通过后提交迁移和存储。

## 任务 3　高价值提取、补证与恢复

**文件**　修改 `src/wechat_agent/analysis/{runner,runtime,history,coverage,checkpoints}.py`、`context/assembler.py` 和 `operations/{contracts,service}.py`，新增 `tests/test_relevance_workflow.py`。

**接口**　`SyncOptions.text_strategy` 接受 `full` 或 `relevance`，缺省为 `full`。单客户整理可选 `relevance`，服务端校验任务类型和客户范围。分级路径使用独立的 `workflow-v5` 策略。分段输入分别声明主材料、上下文、可用证据及固定字段。相同任务的恢复继承策略，沿用持久预算和幂等键。

- [ ] 写 `test_extracts_only_high_primary_and_rejects_low_or_foreign_citations`，模拟模型引用中、低级及其他客户原文。仅经程序核验并提升的高价值证据可支持发布。
- [ ] 写 `test_promotion_and_resume_preserve_exact_coverage`，断言补证新增覆盖分母只计算一次。模拟输出截断与重启，已验证分段不再付费调用。另验 1 万条原文中最后一条为唯一关键事实时仍会入选。
- [ ] 运行 `.venv/bin/python -m pytest -q tests/test_relevance_workflow.py`，确认失败后接通分级路径。使用现有字符分片、预算检查和候选归纳；中级用于解释，确认提供业务事实时先提升再追加一次局部提取。保留双层覆盖，旧模式沿用现有语义。
- [ ] 重跑新链路、现行工作流及引用校验回归，通过后提交。此时仍通过测试／回放入口验证。

## 任务 4　增量核对、零调用和资料状态

**文件**　修改 `src/wechat_agent/analysis/{runner,relevance}.py`、`profiles/{publisher,status,manual}.py`、`operations/reports.py`，新增 `tests/test_relevance_incremental.py`。

**接口**　`reassess_changes(conn, snapshot, prior_manifest) -> RelevanceManifest` 重算新增、修订、撤回及其依赖。最近一次无实质变化的核对结果绑定已发布档案版本、完整材料修订指纹、人工约束、身份、范围和策略。只有当前已发布内容已覆盖旧高价值材料，且本次没有受影响的事实、失效证据或待核对项，才记录零调用结果。`ContactOutcome.reason=no_relevant_material` 表示本地筛选未发现可整理业务信息。首次存在原文、筛选完成且无待核对项时复用资料枚举 `no_findings`，按原因显示「未发现可整理的业务原文」。模型空结果保留 `empty_result`。

- [ ] 写 `test_low_only_append_has_zero_calls_and_keeps_published_version`，断言新增闲聊完成核对后模型调用为 0，旧档案引用与版本相同，资料恢复为原先已更新或整理不完整的状态。
- [ ] 写 `test_revoked_sole_source_blocks_unchanged`，同时加入闲聊和撤回事件，断言旧值待核对并重新计算对应字段或批次。另测同样输入、人工版本变化、同名群成员变化逻辑。
- [ ] 写 `test_no_relevant_material_differs_from_empty_result_and_pending_attachment`，首次无高价值内容、模型空输出、附件待核对均返回各自原因。
- [ ] 运行 `.venv/bin/python -m pytest -q tests/test_relevance_incremental.py`，确认失败后接入依赖反查、核对结果和资料状态。失败或零调用均保留历史证据快照，独立成功字段继续遵守人工覆盖。
- [ ] 重跑增量、资料状态、发布冲突及操作记录回归，通过后提交。

## 任务 5　分级进度与按范围复核

**文件**　修改 `src/wechat_agent/api/operations.py`、`operations/{contracts,reports,service}.py`、`frontend/src/api/types.ts`、`frontend/src/components/{HistoryProgress,OperationDetails}.tsx`、`frontend/src/app/App.tsx`、`frontend/src/app/useOperations.ts`。新增 `tests/test_relevance_review_api.py`、`frontend/e2e/message-relevance.spec.ts`。

**接口**　`GET /api/operations/{operation_id}/relevance` 分页读取当前账号、当前任务的等级和原因，可按日期、会话和等级筛选。进度计数包括 `relevance_total`、`relevance_high`、`relevance_medium`、`relevance_low`、`relevance_context_used`，整合现有提取与复用进度。单客户明确选用分级策略。复核提交沿用 `POST /api/operations` 的单客户整理入口，使用 `SyncOptions.relevance_review_refs` 接收选中的 `message_id/revision`。日期和会话用于选取范围，真正纳入复核的是明确选中的原文修订。创建任务时校验现行账号、客户、业务范围和消息修订，worker 在冻结快照时再次核验。重启继续继承复核范围，重复提交沿用幂等键。

- [ ] 写 `test_review_is_scoped_versioned_and_idempotent`，覆盖跨账号、失效修订、重启及重复提交。复核权限只允许把相关原文纳入提取；局部更新保持现有人工资料。
- [ ] 写浏览器回放确认「已筛选 339 条 · 高 48 · 中 67 · 低 224」与「已整理高价值原文 18 / 48」受实际计数驱动，按范围找到漏判原文并加入复核。旧记录可正常查看。
- [ ] 先跑后端回归与浏览器用例验证失败，再接通接口、提示和单客户入口，保留明确的「全量复核」路径供对照和回退。
- [ ] 重跑 `.venv/bin/python -m pytest -q tests/test_relevance_review_api.py` 和前端指定回放，通过后提交。

## 任务 6　配对性能及实机验收

**文件**　新增 `tests/test_relevance_benchmark.py`，更新 `docs/STATUS.md`、`docs/MAC_SETUP.md` 和验收记录。

- [ ] 对同一份固定快照分别运行全量和分级路径，固定模型配置与测试数据，首次对照两边都使用各自的冷缓存，续跑和增量分别在各自的检查点基础上测。请求次数含归纳、补证及重试。原文字节按真实模型请求中带入的正文计算，重复发送的上下文重复计入。报告正确、错归、漏提、待核对、请求次数、用量与阶段耗时。
- [ ] 用合成样本验证 339 条混合原文、事实密集对话、跨月改量，以及 1 万条末尾只有一条业务消息的场景。确认两层覆盖独立且合法归属的关键事实均保留。
- [ ] 跑完整后端、前端单元、相关浏览器用例、生产构建和 schema 19 升级。整体代码审查聚焦证据权限、漏提、零调用捷径、恢复和人工资料保留。
- [ ] 在 Mac 对至少 5 个真实短历史和 3 个长历史做脱敏配对实测。普通混合文本的多请求首轮样本以模型收到的原文字节和实际请求次数各减少至少 50% 为目标。现行路径只用一次请求即可完成的短样本应保持请求次数，另核对用量和耗时。200–500 条普通文本另核对一轮完成、通常 6–8 次请求以内与 P95 三分钟候选目标。事实密集样本单列。
- [ ] 只有已标注的关键事实完整保留、错归为零、发布引用均可定位时才扩大范围。样本少时保留各次结果供核对。达不到目标时保留单客户试用和全量复核入口，按漏提或耗时来源逐项修正。记录云端及实机验收结果并更新阶段状态。
