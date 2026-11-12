# M1 来源归档与联系人 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Mac 实现真实消息幂等归档、联系人归一、身份管理、原文浏览和两页桌面应用底座。

**Architecture:** 用 SQLite 事务保存源数据及游标，以 FastAPI 提供同源接口。最小持久化操作先支持来源同步；React 接入真实联系人，不生成演示档案。

**Tech Stack:** Python 3.12、FastAPI、SQLite／FTS5、Pydantic、HTTPX、React／TypeScript／Vite、Node 24、Vitest、Playwright。

**Spec:** [产品 §3–4](../../PRODUCT_DESIGN.md)、[交互方案](../../INTERACTION_DESIGN.md)、[内部契约](CONTRACTS.md)。前提：M0 内部契约和回放测试已建立；真实源映射／连接仍单列实机待验证，不能伪造。

## Global Constraints

- 所有代码、修复和自动化测试在云端完成，检查后直接推 main；Mac 只运行交付工具验证。云端开发完成与实机通过分别记录，实机门槛不阻塞可独立测试的代码开发。

- 主键为工作账号 ID + 来源稳定联系人 ID；群聊是来源，不是客户。
- 仅商家进入档案整理；身份值 merchant／provider／platform／unknown，本人排除。
- 每页最多 20 位；导航只有工作台／设置，桌面最小画布 1120px。
- 原文、附件、解析结果分别保存；消息正文不能因媒体不可用而丢失。
- 系统／撤回事件保留在消息时间线，sender_id可为空；存储约束须仅对此类事件允许NULL，不建虚构联系人。普通聊天未知发送人继续列gap，不能套用事件例外；补测事件幂等归档、修订和普通消息归属校验。
- 来源协议以 M0 记录为准；本阶段不调用模型，不显示假整理成功。

## Review Focus

1. 数据落盘前中断、空页仍有游标或分页循环：Task 2。
2. 同名、跨账号、改名、成员缺失及同群多客户：Task 2、3。
3. 来源查询失败与“确实没有新增”必须区分：Task 4。
4. 批量选择跨页、版本冲突、本人身份和非商家历史保留：Task 3、5。
5. 重复导入、伪造行归属和附件路径越界：Task 6。

## File Structure

`storage/` 管连接与迁移，`source/` 管适配与同步，`contacts/` 管身份，`operations/` 管持久任务入口，`api/` 只转 HTTP。`frontend/src/{app,components,features,api,styles}` 分离公共交互和页面；不复制原型大脚本。

### Task 1: 数据迁移与可启动 API

**Files:** Create `src/wechat_agent/storage/{__init__,db}.py`, `storage/migrations/001_archive.sql`, `api/{__init__,app}.py`, `services.py`, `tests/conftest.py`, `tests/test_storage.py`, `tests/test_app.py`；Modify `pyproject.toml`, `requirements-dev.lock`。

**Interfaces:** Creates `open_db`, `migrate`, `Services`, `create_app` 及 db／client／case 夹具，形状见 CONTRACTS。`GET /api/health` 返回 `{status:'ok', schema_version:1}`，不表示微信已连通。

- [x] **Step 1 — 写失败测试：**

```python
def test_schema_is_repeatable_and_isolated(tmp_path):
    from wechat_agent.storage.db import open_db, migrate
    conn = open_db(tmp_path / "data.sqlite")
    migrate(conn); migrate(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 1
```

- [x] **Step 2 — 红灯：** `python -m pytest tests/test_storage.py tests/test_app.py -q`，预期模块缺失。
- [x] **Step 3 — 实现：** 增加 FastAPI 和 uvicorn 运行依赖，并实际更新锁文件。迁移建立 accounts、contacts（人工 role／version）、conversations、members、messages（稳定源身份）、message_revisions、attachments、sync_cursors、sync_attempts、operations／items、settings；唯一约束按账号隔离。FTS5 存原文搜索索引，在源修订时同步。实现事务迁移、只读健康接口和可覆盖 Settings 的 app factory。请求和 worker 分别持有连接，不跨线程复用同一个 connection；网络 await 不放进写事务。
- [x] **Step 4 — 绿灯：** 测试补充跨账号相同 ID 不冲突、事务回滚和重复迁移，运行上述命令通过；安装实际依赖并重新解析 lock。
- [x] **Step 5 — 提交检查点：** 获准时提交本任务文件，消息 `feat: add transactional archive and API foundation`。

### Task 2: 真实适配与分页归档

**Files:** Create `source/adapter.py`, `source/repository.py`, `source/sync.py`（含有限验证CLI）, `operations/{__init__,contracts}.py`, `storage/migrations/002_source_sync.sql`, `tests/__init__.py`, `tests/fakes/source.py`, `tests/factories.py`, `tests/test_source_{sync,adapter,sync_cli}.py`, `tests/fixtures/source-overlap.json`；Modify source契约、wx-cli规范化与schema版本。

**Interfaces:** Consumes M0 SourceAdapter；Creates `archive_page`、`sync_scope`、`ArchiveDelta`、`SyncResult`，见 CONTRACTS。源账号在实例创建后固定；适配器只实现 M0 已确认的读取协议。

- [x] **Step 1 — 写失败测试：** 同一页面归档两次，断言首次 inserted=2、第二次 unchanged=2；同正文不同源 ID 必须两条；同 ID 正文修订则保留 revision=1／2；模拟事务提交失败后断言 cursor 未推进。

```python
def test_replay_page_is_idempotent(db, case):
    from wechat_agent.source.contracts import SourcePage
    from wechat_agent.source.repository import archive_page
    page = SourcePage.model_validate(case("source-overlap")["page"])
    assert archive_page(db, page).inserted > 0
    second = archive_page(db, page)
    assert second.inserted == second.revised == 0
```

- [x] **Step 2 — 红灯：** `python -m pytest tests/test_source_sync.py -q`，预期缺少归档／同步实现。
- [x] **Step 3 — 实现：** 按 M0 字段映射读取联系人、会话和消息；消息与游标同事务落盘。识别重复 cursor 和分页无进展并报具体 gap，不死循环。稳定源身份包含来源命名空间／会话／消息 ID，正文哈希只用于版本比较。完整归档群消息，不预先按商家筛掉服务商发言。
- [x] **Step 4 — 绿灯：** 补测时间偏移保留、未知发送者保留 gap、不把群建成人、相同会话并发游标串行；上述pytest全过，完整回归148项通过；Mac取证单独列为待验，不以云端回放代替。
- [x] **Step 5 — 提交检查点：** 获准时 `git commit -m "feat: archive source pages with durable cursors"`，仅暂存本任务实现及脱敏样本。

- [x] **实机取证（已通过）：** Mac 148项测试通过；首次11条入库，第二次0新增／0修订、11条不变，两次均无缺口。

### Task 3: 联系人及身份 API

**Files:** Create `contacts/{__init__,service}.py`, `api/contacts.py`, `tests/test_contacts.py`；Modify `api/app.py`。

**Interfaces:** Consumes ContactKey 和 db；Creates `set_roles`、GET `/api/contacts`、PATCH `/api/contacts/roles`。每项修改带 key／expected_version，返回成功和失败项，不整个批次假成功。

- [x] **Step 1 — 写失败测试：**

```python
def test_contact_limit_is_twenty(client):
    response = client.get("/api/contacts", params={"page_size": 21})
    assert response.status_code == 422
```

- [x] **Step 2 — 红灯：** `python -m pytest tests/test_contacts.py -q`，预期 404／未实现，而非预期 422。
- [x] **Step 3 — 实现：** 按备注→昵称→可定位缺失状态选择 `display_name`；支持 role、姓名／wxid／群名检索和页码。联系人中文子串搜索使用参数化LIKE并转义百分号和下划线，星号及反斜线保持字面，不能把单字查询交给普通 FTS 分词后无结果。人工角色默认 unknown，只更新明确选择；本人不可设商家。修改角色递增 role_version；非商家不删原文，撤销尚未开始的分析项。
- [x] **Step 4 — 绿灯：** 增加同名不同人、跨会话一人、跨账号隔离、role_version 冲突 409、无姓名不复制 wxid、中文单字及字面 `%` 查询的契约测试。按最近消息时间提供尚未整理行，不能用同步完成时间冒充沟通时间。
- [x] **Step 5 — 提交检查点：** 获准时提交 contacts 及路由，消息 `feat: manage unified contact identities`。

- [x] **Mac读取验收：** 用户回传total=2411、returned=20，身份均unknown；真实角色修改未执行，不为验收批量改标签。

### Task 4: 最小持久化同步操作

**Files:** Create `operations/{service,worker}.py`, `api/operations.py`, `tests/test_sync_operations.py`；Modify task2已创建的`operations/contracts.py`、`services.py`、`api/app.py`。

**Interfaces:** Creates `create_operation`、`run_next`，状态及 CancellationToken 见 CONTRACTS；API 为 POST `/api/operations` 和 GET `/api/operations/{id}`。M1 返回真实 source 阶段结果与分析 capability_not_ready；不调用模型。

- [x] **Step 1 — 写失败测试：** 同幂等键只生成一项；source 抛错返回 failed／source_unavailable，不能返回 no_new_messages；有源增量时 inserted 真实；非商家允许同步原文。为 worker 注入回放源，记录每次读取。

```python
def test_repeated_intent_is_one_operation(db):
    from tests.factories import seed_case
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.operations.service import create_operation
    seed_case(db, "source-overlap")
    scope = OperationScope(account_id="acct-1", contact_id="merchant-a")
    a = create_operation(db, "sync_and_organize", scope, "click-1")
    b = create_operation(db, "sync_and_organize", scope, "click-1")
    assert a.id == b.id
```

- [x] **Step 2 — 红灯：** `python -m pytest tests/test_sync_operations.py -q`，预期模块／路由缺失。
- [x] **Step 3 — 实现：** API 写队列后返回 202；单个后台 worker 执行，状态、目标和 generation 落盘。初版检查停止令牌；任务恢复／租约完整处理留 M4，但此时不允许第二个 worker 并发领同项。有待分析商家但分析未实现时，source 阶段可成功，总操作为 failed/capability_not_ready，不能把整理请求报成功；无分析目标则只完成来源同步。M2 注册策略后解除该能力限制。
- [x] **Step 4 — 绿灯：** 上述测试全过；补测共享群归档使多位商家变更，但单客户操作仅规划目标客户的后续处理。M1 不暴露虚假的继续分析按钮。
- [x] **Step 5 — 提交检查点：** 获准时消息 `feat: execute real source sync through durable operations`。

- [x] **Mac验收：** 用户回传后台任务与source均succeeded，两个会话／两页、11条不变，新增／修订／缺口为0；未额外回传pytest数量。

### Task 5: 两页 React 外壳与统一控件

**Files:** Create under `frontend/`: `package.json`, `package-lock.json`, `index.html`, `vite.config.ts`, `vitest.config.ts`, `playwright.config.ts`, `tsconfig.json`, `src/{main,app/App}.tsx`, `src/api/{client,types}.ts`, `src/styles/{tokens,controls,motion}.css`, `src/components/{FormField,Dialog,RoleTag,SegmentedControl,TimePicker}.tsx`, `src/features/{contacts/ContactsPage,settings/SettingsPage}.tsx`, `src/test/setup.ts`, `src/components/controls.test.tsx`, `e2e/contacts.spec.ts`；Create backend `api/settings.py`, `tests/webserver.py`；Modify app router、`.gitignore`。

**Interfaces:** Consumes contacts／operations API；GET/PATCH `/api/settings` 保存非敏感设置。共享 FormField 单行／多行／搜索／时间变体，Dialog 管焦点；TimePicker props 为 value、onCommit、disabled；前端 `request<T>` 只向同源 API 请求。

- [x] **Step 1 — 建立工具并写失败测试：** 安装 React、Vite、TS、Vitest、Testing Library、jsdom、`@playwright/test`，真实生成 lock；在 frontend 执行 `npx playwright install chromium`。脚本为 `test:unit=vitest`, `test:e2e=playwright test`, `build=tsc -b && vite build`；Vitest 使用 jsdom 和 setup.ts，Playwright 配置隔离测试服务与复位接口（见 CONTRACTS），`.gitignore` 增加 node_modules、frontend/dist、test-results、playwright-report。`controls.test.tsx` 断言四种身份文字、时间 9:05 规范为 09:05、取消不保存；未创建控件时测试失败。

```tsx
it("shows the platform identity", () => {
  render(<RoleTag role="platform" />);
  expect(screen.getByText("平台")).toBeVisible();
});
```

- [x] **Step 2 — 红灯：** `cd frontend && npm run test:unit -- --run`，预期控件缺失；Playwright 配置用 `channel:'chromium'` 或自带浏览器，不能硬编码 Linux `/usr/bin/chromium`。
- [x] **Step 3 — 实现：** 复刻有效交互的两页和商家／全部联系人切换；统一字号及 48px／12px／14px 控件；角色蓝／紫／绿／琥珀，我方紫色加粗；深色覆盖 html/body/main。键盘、焦点、状态错误、太阳月亮、搜索／筛选／批量栏动画一起实现。来源和模型状态读取后端，M1 不可用档案入口给明确状态，不使用原型示例顶替。
- [x] **Step 4 — 绿灯：** API 测试检验设置持久化；`npm run test:unit -- --run`、`npm run build`、`npm run test:e2e -- contacts.spec.ts` 通过。E2E 覆盖 20/8 分页、跨页选择、切页签清空、身份修改及列表不闪、复制真实名称；Vite 开发代理 `/api` 到 127.0.0.1:8000。
- [x] **Step 5 — 提交检查点：** 获准时提交前端源代码／锁文件及路由，忽略 node_modules／dist，消息 `feat: build desktop workspace with shared controls`。

- [ ] **Mac验收（2026-11-12更新）：** 用户已打开正式页面，拉取137f246后仍反馈大量缺名及微信搜索不到的联系人；名称准确性尚未闭合，深浅色／时间等全套交互未收到逐项验收。先处理[独立审查及修复方案](../../verification/2026-11-12-contact-names-review.md)，再按指南复验；不能把页面可访问视为整项通过。

### Task 6: 原文浏览与唯一导入入口

**Files:** Create `api/messages.py`, `api/imports.py`, `api/attachments.py`, `source/imports.py`, `attachments/access.py`, `frontend/src/features/messages/MessageTimeline.tsx`, `frontend/src/features/settings/ImportDialog.tsx`, `tests/test_messages_imports.py`, `frontend/e2e/imports.spec.ts`；Modify路由、SettingsPage 及联系人详情入口。

**Interfaces:** GET `/api/contacts/{id}/messages` 带 account_id；POST `/api/imports` 用 mode=preview／commit 和映射配置，同一归档层写入；附件 GET 只接受库内 ID，不接受磁盘路径。

- [ ] **Step 1 — 写失败测试：** 重复导入同一稳定源标识不增行，同文本两个 ID 均保留；没有发送人／会话／时间映射的行返回逐行问题且不盲写；原文跨账号请求 404；附件参数 `../../...` 无法读取。

```python
def test_attachment_api_does_not_accept_paths(client):
    response = client.get("/api/attachments/..%2F..%2Fetc%2Fpasswd",
                          params={"account_id": "acct-1"})
    assert response.status_code in {404, 422}
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_messages_imports.py -q`，预期路由／导入缺失。
- [ ] **Step 3 — 实现：** CSV／JSON 先预览及列映射，确认后提交。导入命名空间需稳定，可定位到来源批次／行；不能覆盖实时原文或按昵称合并人。时间线按实际时间、说话人和会话显示；非商家也可看原文，附件未获取显示真实状态。原文 FTS 对中文1–2字短查询用参数化 LIKE 回退，测试“海运”能查到，不假设 unicode61 分词自动支持中文子串。
- [ ] **Step 4 — 绿灯：** 上述测试及 `npm run test:e2e -- imports.spec.ts` 通过；至少覆盖一个私信／群跨源客户、搜索清空、原文只读及乱码输入报错。导入入口只出现在设置。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: browse source messages and import mapped records`。

## 退出条件

- [ ] 同步幂等、修订可追溯、断点不跳页；同人一条联系人，同名不合并。
- [ ] Mac 实际小范围同步、备注／群名可定位，身份操作能重启保留。
- [ ] 两页 UI 使用真实后端，搜索分页、共享控件及原文／导入可运行。
- [ ] `python -m pytest -q`、前端 unit／build／本阶段 E2E 通过；未连接或未实现不显示假成功。
