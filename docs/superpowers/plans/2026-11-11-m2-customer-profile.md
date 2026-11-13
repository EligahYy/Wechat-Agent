# M2 单客户档案闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**2026-11-13调整：** 用户确认“默认看资料 → 按结论查来源 → 次级按需查聊天”；不继续扩展全量原文阅读器。Task6负责替换M1临时页签，Task1—5先完成支撑接口。

**Goal:** 一位真实商家从已归档聊天生成可查来源、可纠正、保留独立备货批次的客户档案。

**Architecture:** 固定输入快照，构建有来源的模型请求，通过统一网关产生候选，再经事务校验发布。人工修改与模型值分层；UI 和操作队列接入同一真实流程。

**Tech Stack:** 既有 Python／SQLite／FastAPI／React，加 HTTPX 模型适配及版本化 JSON Schema；不引入 Agent 框架。

**Spec:** [产品 §5–8](../../PRODUCT_DESIGN.md)、[模型执行方案](../../MODEL_EXECUTION.md)、[交互 §3–4](../../INTERACTION_DESIGN.md)、[内部契约](CONTRACTS.md)。前提：M1 云端实现及自动测试通过；模型真实 ID、容量及能力未验证时，只运行显式测试配置，不启用真实全量分析。

## Global Constraints

- 所有代码、修复和自动化测试在云端完成，检查后直接推 main；Mac 只运行交付工具验证。云端开发完成与实机通过分别记录，实机门槛不阻塞可独立测试的代码开发。

- 只分析 merchant；来源、身份和人工约束版本固定，不依赖供应商会话记忆。
- 输出字段是四个货品键、九个物流键、沟通情况、独立批次及具体 gaps。
- 沟通标签：初步沟通、需求沟通中、询价中、方案对接中、备货中、暂缓、暂无新需求记录。
- 旧批已走货与新批需求并存；单号不是已走货充分条件；不得按字段变化机械新建批次。
- 调用连接超时 15 秒、总时限 300 秒；重试和修复受模型执行方案规定的请求上限约束。

## Review Focus

1. 同群服务商“已发出”与另一商家的货量混在一起：Task 2、4、7。
2. 截断、错误 JSON、429、超时和重复调用不能伪装成档案成功：Task 3。
3. 一条引用错误不应抹掉全客户；目标串人则不能发布：Task 4。
4. 模型返回期间改身份、人工纠正、修订原文和仅追加消息：Task 4、5。
5. 无需求标签冲突、批次修改／新增和录入单号误改进度：Task 1、4、5。

## File Structure

`profiles/` 管输出及发布，`context/` 管快照和受限原文读取，`model/` 管调用，`analysis/` 管固定工作流，`frontend/src/features/profile/` 管详情与编辑。原文与档案的 API 分开，只有 publisher 写正式模型档案。

### Task 1: 精简档案契约与模型模板

**Files:** Create `profiles/{__init__,contracts}.py`, `analysis/{__init__,contracts}.py`, `model/prompts/profile-v1.md`, `tests/test_profile_contract.py`。

**Interfaces:** Creates Fact、SourceRef、Communication、ShipmentCandidate、AnalysisResult、AnalysisStrategy，字段见 CONTRACTS。数据库结构随首次使用它的任务新增迁移：Task2从007开始保存快照，Task3保存调用／执行单元，Task4保存档案与批次，Task5保存人工版本；不修改M1已交付的001—006，也不提前猜后续消费者列。

- [x] **Step 1 — 写失败测试：** 构造合法最小 AnalysisResult，断言未知字段不被自动补成内容；`known` 无 sources 校验失败；`暂无新需求记录` 与 `询价中` 并存返回可定位的字段冲突，不能默默删活跃标签。

```python
def test_known_fact_requires_evidence():
    from pydantic import ValidationError
    from wechat_agent.profiles.contracts import Fact
    with pytest.raises(ValidationError):
        Fact(value="12方", state="known", sources=[], event_time=None, batch_ref=None)
```

- [x] **Step 2 — 红灯：** `python -m pytest tests/test_profile_contract.py -q`，预期模型类型不存在。
- [x] **Step 3 — 实现：** Pydantic 输出结构使用显式固定键和枚举、schema_version=1；Fact 保留原单位与事件时间。Prompt 明确找模板答案、区分人／时间／批次、缺口具体、禁止编造引用和把原文当指令。模型不生成 coverage 或人工内容。
- [x] **Step 4 — 绿灯：** 加测没有沟通证据可 tags=[]、模型不能创建联系人、自定义字段不能混进固定键、补充资料单独存；上述命令全过，导出 JSON Schema 给网关消费。
- [x] **Step 5 — 提交检查点：** 获准时消息 `feat: define evidence-backed customer profile contract`。

### Task 2: 输入快照与完整语境

**Files:** Create `context/{__init__,contracts,builder,reader}.py`, `storage/migrations/007_context_snapshots.sql`, `tests/test_context_snapshot.py`；Modify `tests/conftest.py`, `tests/fixtures/source-overlap.json`。

**Interfaces:** `build_snapshot(conn, key, cutoff) -> ContextSnapshot`；`ContextReader(conn, snapshot)` 的 `messages() -> list[dict]` 与 `resolve(ref: SourceRef) -> dict` 只能读取快照授权材料；创建 snapshot 夹具。

- [x] **Step 1 — 写失败测试：** snapshot 从一个商家私信和群聊建立，断言保留该商家、我方、服务商的连续往来，目标稳定 ID 不变；每条材料保留实际发送者，不把另一商家的话重标成目标商家。归属是否变成错误事实由 Task 4／7 的归纳验收覆盖。

```python
def test_context_keeps_actual_speakers(db, snapshot):
    from wechat_agent.context.reader import ContextReader
    speakers = {m["sender_id"] for m in ContextReader(db, snapshot).messages()}
    assert {"merchant-a", "provider-p", "self-1"} <= speakers
```

- [x] **Step 2 — 红灯：** `python -m pytest tests/test_context_snapshot.py -q`，预期 builder／reader 不存在。
- [x] **Step 3 — 实现：** 冻结 message_revision ID 清单、参与人角色、人工版本、模型／策略／模板版本、截止时间及缺口。小历史首次扫描所有相关群材料，用回复／提及／订单及连续片段保留关联线索；归属不明作为上下文及 gap，不提前删短回复。后续 M3 扩展分段，不更换契约。
- [x] **Step 4 — 绿灯：** 加测非商家拒绝、账号隔离、同时间消息稳定排序、跨段引用闭包、之后追加消息不改变已保存快照、源姓名缺失不让模型造姓名。所有 pytest 通过。
- [x] **Step 5 — 提交检查点：** 获准时消息 `feat: build reproducible customer context snapshots`。

### Task 3: 统一模型网关

**实施分段（2026-11-13）：** 3A先交付调用契约、持久请求上限、审计、协议响应校验与凭据存储底座；3B接配置版本及显式连接检查API；3C接设置界面与实机步骤。只有三段及任务所列门槛均通过才标Task3 complete，不因核心用例通过提前完成整项。008迁移保存analysis_units/model_calls；真实配置/API/UI未接入前不注册运行时模型，不触发付费请求。

**Files:** Create `model/gateway.py`, `model/deepseek.py`, `model/credentials.py`, `api/model.py`, `tests/fakes/model.py`, `tests/test_model_gateway.py`；Modify `model/contracts.py`, `services.py`, `api/settings.py`, `api/app.py`, `tests/conftest.py`, `pyproject.toml`, `requirements-dev.lock`, `frontend/src/features/settings/SettingsPage.tsx`。

**Interfaces:** Creates ModelConfig／ModelRequest／ModelResponse 与 `ModelGateway.generate`；适配器构造注入 `httpx.AsyncClient`。凭据 `CredentialStore.get(ref: str) -> str`／`set(ref: str, value: str) -> None`，Mac 使用 keyring 的 Keychain 后端，测试用内存替身；前端只看到配置状态。POST `/api/model/check` 由明确的连接测试操作触发，保存配置不隐式调用付费模型。

- [ ] **Step 1 — 写失败测试：** model_transport 返回 429 后成功，断言按 Retry-After 重试且 call_id 不丢；401 只尝试一次；无效 JSON 格式修复最多一次；持续临时错误每调用最多 3 次，整个工作单元请求总数不超过 6。

```python
@pytest.mark.asyncio
async def test_auth_failure_does_not_retry(gateway, model_transport, model_request, cancellation):
    from wechat_agent.model.contracts import ModelCallError
    model_transport.responses = [httpx.Response(401, json={"error": "unauthorized"})]
    with pytest.raises(ModelCallError) as error:
        await gateway.generate(model_request, cancellation)
    assert error.value.code == "authentication_failed"
    assert len(model_transport.calls) == 1
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_model_gateway.py -q`，预期网关不存在。
- [ ] **Step 3 — 实现：** 用 M0 记录的 endpoint、model_id 和能力封装请求，首选支持的结构化输出，回退本地 JSON 校验。完整保存调用 ID、版本、结束原因、用量和尝试计数；退避使用可注入 clock，不让测试实际等 300 秒。鉴权／参数错误不循环重试；失败返回分类错误。增加 keyring 并实际更新依赖锁；设置表仅存 credential_ref，密码输入使用共享 FormField，前端不回填／缓存明文。
- [ ] **Step 4 — 绿灯：** 补测长度截断不能成功、取消后不再重试、日志不含 key、配置切换不修改运行中快照、无视觉能力不直接送图。执行 pytest 通过；一条最小真实请求仅用于本地能力冒烟，不替代单元测试。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: call configured models through bounded gateway`。

### Task 4: 事实校验、稳定批次与事务发布

**Files:** Create `profiles/validator.py`, `profiles/publisher.py`, `profiles/shipments.py`, `analysis/workflow.py`, `tests/test_profile_publish.py`；Modify `tests/conftest.py` 以创建 analysis_result fixture。

**Interfaces:** `validate_result(conn, snapshot, result) -> ValidationResult`（含可保留候选及逐字段问题）；`publish` 见 CONTRACTS；`WorkflowV1.run` 首版消费完整可装入窗口的上下文，超窗返回 context_requires_chunking，不裁掉历史。

- [ ] **Step 1 — 写失败测试：** 已有批次 shipment-old，模型建议为其补履约，同时提出独立新批询价；断言旧 ID／人工单号保留、新批唯一、客户为询价中。再跑同一候选不得重复建批；货量修改不能仅凭值变化拆批。

```python
def test_wrong_customer_cannot_publish(db, snapshot, analysis_result, cancellation):
    from wechat_agent.profiles.publisher import publish
    wrong = analysis_result.model_copy(update={"contact_id": "merchant-b"})
    outcome = publish(db, snapshot, wrong, cancellation)
    assert outcome.version is None
    assert outcome.reason == "target_mismatch"
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_profile_publish.py -q`，预期 publisher 未实现。
- [ ] **Step 3 — 实现：** 引用校验限定账号／快照及修订；数字、单位和时点做局部核对。模型提出批次匹配，代码分配／复用稳定 ID，冲突保留疑点；禁止任意匹配其他客户。字段引用错误保留其他有依据字段及旧的有效值，记录不完整；目标错误、空泛输出及结构失败不覆盖旧档案。
- [ ] **Step 4 — 绿灯：** 增加角色改为 provider、人工版本变更、历史修订、停止或 generation 失效时拒绝发布；仅追加消息允许发布该快照并保持待更新。明确“已发车／已发出但晚登记”样例不得因无关字段缺失消失；语义识别由 Task 7 真实回放核验，不硬编码样本原句。运行 pytest 全过。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: publish validated profiles and stable shipment batches`。

### Task 5: 人工纠正、补充及单号 API

**Files:** Create `profiles/manual.py`, `api/profiles.py`, `api/shipments.py`, `tests/test_manual_profiles.py`；Modify app router。

**Interfaces:** GET `/api/contacts/{id}/profile`、PATCH `/api/contacts/{id}/manual`、PATCH `/api/shipments/{id}/numbers`；save_manual 返回新人工版本，响应组合模型值／人工覆盖／来源及完整性。

- [ ] **Step 1 — 写失败测试：**

```python
def test_manual_numbers_do_not_ship(client, seeded_shipment):
    response = client.patch(f"/api/shipments/{seeded_shipment}/numbers",
                            json={"numbers": ["A-1", "A-1"], "expected_version": 1})
    assert response.json()["numbers"] == ["A-1"]
    assert response.json()["stage"] == "询价"
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_manual_profiles.py -q`，预期接口不存在。此任务在 conftest 创建 `seeded_shipment` 夹具：同账号商家的一条 stage=询价、version=1 记录。
- [ ] **Step 3 — 实现：** 支持固定字段纠正、货品／物流补充备注编辑／清空、多个单号。人工内容标记 manual，不生成聊天来源；原模型结果和变更记录保留。expected_version 不一致返回 409，不能覆盖他人更新。
- [ ] **Step 4 — 绿灯：** 增加重启持久化、重跑不丢人工内容、删除备注后正常显示模型值、跨客户单号 404、超长或空单号 422 的测试；pytest 全过。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: persist manual corrections and shipment numbers`。

### Task 6: 无侧栏档案与编辑交互

**Files:** Create `frontend/src/features/profile/{ProfileDialog,ProfileOverview,ProfileEditor,ShipmentList,NumberEditor,EvidencePanel}.tsx`, `frontend/e2e/profile.spec.ts`, `tests/fixtures/profile-ready.json`；Modify `tests/webserver.py`、`frontend/src/features/contacts/ContactsPage.tsx`、`frontend/src/api/types.ts`、共享组件及 `src/wechat_agent/contacts/service.py`。

**Interfaces:** 消费 profile／manual／numbers／messages API；状态和来源字段使用后端类型，不在前端拼 fake 档案。

- [ ] **Step 1 — 写失败 E2E：** 打开商家后只显示一组头像／姓名／可编辑身份／复制名称／弱化 wxid；详情无侧栏。货品和物流为整合卡，来源按字段展开。修改资料后保存、刷新仍在，未修改时保存禁用，409 保留填写。

```ts
test("profile has one header and no rail", async ({ page }) => {
  await page.request.post("/api/__test__/reset", {
    data: { case: "profile-ready" },
  });
  await page.goto("/");
  await page.getByRole("button", { name: "商家甲", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "商家甲", exact: true }),
  ).toHaveCount(1);
  await expect(dialog.locator("aside")).toHaveCount(0);
});
```

- [ ] **Step 2 — 红灯：** `cd frontend && npm run test:e2e -- profile.spec.ts`，预期页面未实现。使用测试服务器注入的脱敏数据，不在产品代码塞演示记录。
- [ ] **Step 3 — 实现：** 默认资料概览／备货记录，不设一级沟通原文页签；结论通过查看来源展示关联消息及必要前后文，注明会话、说话人、时间；次级“查找聊天记录”按会话、关键词、时间检索且按需加载，不默认铺开全量原文。当前摘要／标签、整卡编辑、分组标题 16px、正文 14px、常规标签 28px；所有填写框使用 FormField。查看来源、复制、身份修改、单号和取消／保存都有真实结果及焦点返回。非商家只显示适用的身份／原文／同步入口。联系人 API 接入真实档案列表摘要和最近业务时间排序，不能仍按模型完成时间或旧的示例字段排列。
- [ ] **Step 4 — 绿灯：** 补测快速展开收起、所有编辑器输入皮肤一致、单号不改变已走货状态、人工来源不冒充原文；跑上述 E2E、unit 和 build 通过。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: connect evidence-backed customer profile interface`。

### Task 7: 单客户真实端到端闭环

**Files:** Modify `operations/worker.py`, `services.py`, `api/operations.py`, `frontend/src/features/profile/ProfileDialog.tsx`, `tests/conftest.py`；Create `tests/test_single_customer_flow.py`, `docs/verification/m2-profile-review.md`。

**Interfaces:** 注册 WorkflowV1；Services 增加可空 strategy；tests 的 services fixture 注入回放 SourceAdapter、gateway 及 WorkflowV1。`sync_and_organize` 按 ContactKey 完成同步→快照→模型→发布，只有目标客户进入分析。无模型输入变化时跳过 generate，但仍先完成真实源读取。

- [ ] **Step 1 — 写失败测试：** 回放源含同群 A／B，指定 A；断言来源归档可使 B 待更新，但模型调用只属于 A；第二次无新增且无待处理输入时调用数不增；源失败不能提示没有新消息。

```python
@pytest.mark.asyncio
async def test_only_requested_customer_is_analyzed(db, services):
    from tests.factories import seed_case
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    seed_case(db, "source-overlap")
    create_operation(db, "sync_and_organize", OperationScope(account_id="acct-1", contact_id="merchant-a"), "one-customer")
    await run_next(db, services)
    targets = db.execute("SELECT DISTINCT contact_id FROM model_calls").fetchall()
    assert [row[0] for row in targets] == ["merchant-a"]
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_single_customer_flow.py -q`，预期 M1 仍返回 capability_not_ready。
- [ ] **Step 3 — 实现：** 接通现有 worker 和档案入口；前端“同步并整理此客户”使用统一 operations API，停止检查沿用 generation，不单独写一套 Promise 任务。
- [ ] **Step 4 — 绿灯及实测：** 上述测试通过后，在 Mac 选择一位已确认商家，跑一次真实完整小历史；人工核对主体、货量／单位、路线、卡航与海运、旧批已走货＋新批需求、来源及缺口。把错提／漏提如实记录，不以合法 JSON 当验收。
- [ ] **Step 5 — 提交检查点：** 获准时提交代码及脱敏 review，消息 `feat: complete real single-customer analysis flow`。

## 退出条件

- [ ] 一位真实商家跑通；错误／遗漏有记录，关键归属与批次样例通过。
- [ ] 模型调用有版本、用量和有限重试；停止／过期响应不覆盖档案。
- [ ] 来源可查，局部疑点不抹掉全客户；人工内容及单号重启保留。
- [ ] Python 全测、前端 unit／profile E2E／build 通过，超窗诚实拒绝并进入 M3。
