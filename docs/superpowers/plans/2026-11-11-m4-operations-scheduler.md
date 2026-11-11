# M4 批量、控制与每日更新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全局、单客户和每日更新复用一套持久化执行控制，支持真实进度、优先、停止、恢复与用量。

**Architecture:** 扩展 M1 的同一操作服务，以数据库租约、执行令牌和客户级去重防止并发发布。调度器只创建操作，worker 调用已验证的同步、解析和模型链路。

**Tech Stack:** 既有栈；SQLite 队列／租约、asyncio 后台 worker、zoneinfo、可注入时钟；不增加 Redis。

**Spec:** [产品 §7–8](../../PRODUCT_DESIGN.md)、[实施 §7–8](../../IMPLEMENTATION_PLAN.md)、[模型执行 §5](../../MODEL_EXECUTION.md)、[内部契约](CONTRACTS.md)。前提：M3 通过。

## Global Constraints

- 所有代码、修复和自动化测试在云端完成，检查后直接推 main；Mac 只运行交付工具验证。云端开发完成与实机通过分别记录，实机门槛不阻塞可独立测试的代码开发。

- 状态为 queued／running／stop_requested／stopped／succeeded／failed，操作以 available_actions 为准。
- 同客户不并发分析，单客户优先到下一个可执行位置，不强行中断其他客户的已发请求。
- 每日默认 08:30，时区 Asia/Shanghai；应用未运行不承诺唤醒。
- 停止后不发布迟到结果，保留已归档消息及已完成客户；无未完成工作不显示继续。
- 无每日 Token 硬上限，但单次重试和补读有界，用量如实记录。

## Review Focus

1. 双击主按钮、全局与单客户重叠、应用热重载双 worker：Task 1。
2. 排队停止、请求中停止、停止后改身份与迟到响应：Task 2。
3. 睡眠数天、跨午夜、主机时区变化和改计划时间：Task 3。
4. 部分失败、重试被成功去重吞掉、完成后幽灵继续：Task 2、4。
5. 网络超时仍计费、用量未知、无新增但仍有未完成分段：Task 4、5。

## File Structure

仍使用 `operations/service.py`、`worker.py`，新增 leases／scheduler；设置持久化在 `settings/`，前端的进度和记录复用 `features/operations/`。不创建另一套单客户任务或定时任务 UI。

### Task 1: 原子领取、去重和单客户优先

**Files:** Create `operations/leases.py`, `storage/migrations/004_execution.sql`, `tests/test_operation_leases.py`；Modify service.py、worker.py、api/app.py。

**Interfaces:** `claim_next(conn, worker_id: str, now: datetime) -> Lease | None`；`Lease(operation_id: str, item_id: str, generation: int, expires_at: datetime)`；`available_actions(operation: Operation) -> list[str]`。续租间隔 10 秒、租约 30 秒，时间通过可注入 clock 提供。

- [ ] **Step 1 — 写失败测试：** 两个 SQLite 连接同时领取同项只能一人获得；同客户的全局项与单客户请求复用活跃项；指定排队客户提高优先级，已运行客户返回当前进度；不同账号相同 contact_id 不冲突。

```python
def test_one_item_has_one_lease(db):
    from datetime import datetime, timezone
    from tests.factories import seed_case
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.leases import claim_next
    seed_case(db, "source-overlap")
    create_operation(db, "sync_and_organize", OperationScope(account_id="acct-1", contact_id="merchant-a"), "lease-case")
    now = datetime.now(timezone.utc)
    assert claim_next(db, "worker-a", now) is not None
    assert claim_next(db, "worker-b", now) is None
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_operation_leases.py -q`，预期租约与优先队列未实现。
- [ ] **Step 3 — 实现：** 事务领取、唯一活跃客户约束、账号级单 worker 租约；heartbeat 续租，发布检查 lease／generation。应用 lifespan 只启动一个拥有租约的 worker，热重载新进程没有租约就不执行。scope/idempotency 由服务器验证，不能信任客户端传任意账号。
- [ ] **Step 4 — 绿灯：** 加测租约过期、旧 worker 响应、源会话游标锁及重复幂等键，pytest 全过；旧响应仍可记真实用量，但不得发布档案。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: serialize durable operations with fenced leases`。

### Task 2: 停止、继续、失败重试与重启

**Files:** Modify operations/service.py、worker.py、profiles/publisher.py、api/operations.py；Create `operations/recovery.py`, `tests/test_operation_controls.py`。

**Interfaces:** `control_operation(conn, operation_id, action) -> Operation`；`recover_expired(conn, now: datetime) -> list[str]`。动作 stop／resume／retry 只对合法状态与未完成项有效。

- [ ] **Step 1 — 写失败测试：**

```python
def test_completed_has_no_resume():
    from wechat_agent.operations.service import available_actions
    from wechat_agent.operations.contracts import Operation
    from wechat_agent.operations.contracts import OperationScope
    operation = Operation(id="op-1", scope=OperationScope(account_id="acct-1", contact_id="merchant-a"),
                          state="succeeded", remaining=0)
    assert "resume" not in available_actions(operation)
```

另测 queued 停止零请求、running 停止后迟到结果不写、stopped 有剩余才可 resume、failed retry 只选失败目标。

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_operation_controls.py -q`，预期完整控制缺失，不得通过未定义测试帮助函数制造红灯。
- [ ] **Step 3 — 实现：** stop 立即阻止新请求并使执行令牌失效，尽可能取消 HTTP；完成客户不回滚。resume 使用新 generation 和兼容检查点；人工／身份／源修订变化重建受影响输入。重启将过期运行项标 stopped 并说明 interrupted，必须明确继续，不自动重发旧模型请求。
- [ ] **Step 4 — 绿灯：** 测试覆盖停止后切为非商家、修订人工内容、部分成功后 retry、无剩余不能 resume、旧 heartbeat 无法复活任务；pytest 全过。可恢复与失败使用同一进度接口。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: stop and resume operations from real checkpoints`。

### Task 3: 北京时间每日计划

**Files:** Create `settings/{__init__,repository}.py`, `operations/scheduler.py`, `tests/test_scheduler.py`；Modify settings API、app lifespan。

**Interfaces:** `save_schedule(conn, account_id, enabled, time, timezone) -> Schedule`；`tick(conn, now) -> list[str]`；计划唯一键为 account_id＋稳定 schedule_id＋北京时间日期，不以每次配置版本产生额外日任务。

- [ ] **Step 1 — 写失败测试：** `2026-11-11T00:29:00Z` 不触发，`00:30:00Z` 只触发一次；同日再 tick 不触发。睡眠三天到计划后只补当前一次检查；关闭计划不停止已运行任务；主机时区为 UTC 也按上海计算。

```python
def test_daily_due_time_is_shanghai(db):
    from datetime import datetime
    from tests.factories import seed_case
    from wechat_agent.settings.repository import save_schedule
    from wechat_agent.operations.scheduler import tick
    seed_case(db, "source-overlap")
    save_schedule(db, account_id="acct-1", enabled=True, time="08:30", timezone="Asia/Shanghai")
    assert tick(db, datetime.fromisoformat("2026-11-11T00:29:00+00:00")) == []
    assert len(tick(db, datetime.fromisoformat("2026-11-11T00:30:00+00:00"))) == 1
    assert tick(db, datetime.fromisoformat("2026-11-11T00:31:00+00:00")) == []
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_scheduler.py -q`，预期调度器缺失。
- [ ] **Step 3 — 实现：** 存 `Asia/Shanghai`、规范 HH:mm、启用状态与最后计划日期。tick 只创建统一 sync_and_organize，不直接调用模型。保存时间校验 24 小时，已执行当天修改时间不重复自动创建；用户手动同步仍可发起。没有待处理输入时跳过 generate，不能跳过真实源检查。
- [ ] **Step 4 — 绿灯：** 加测重启、跨北京时间午夜、09:05／25:00、并发两个 tick、首次启用计划前／后的行为，pytest 全过。首次启动当日已过时间补一次，未到时间等待，关闭则不补。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: schedule daily Shanghai-time source updates`。

### Task 4: 统一进度、记录与状态条

**Files:** Create `frontend/src/features/operations/{OperationBanner,OperationPanel,OperationHistory}.tsx`, `frontend/e2e/operations.spec.ts`, `tests/test_operation_views.py`, `tests/fixtures/completed-operation.json`；Modify工作台、ProfileDialog、SettingsPage、操作 API、tests/webserver.py。

**Interfaces:** GET operation 响应含 state／phase／counts／items／available_actions／error／usage_summary；记录查询 `GET /api/operations?account_id=...&page=...` 最大20；列表与详情共享 operation ID。

- [ ] **Step 1 — 写失败测试：** 全局和详情显示同一个正在执行的目标；completed 不显示继续；部分失败显示完成数和失败项重试。已无新消息但仍有待处理分段，不显示“无需整理”。API 服务端决定动作，前端不推断。

```ts
test("finished operation has no continue", async ({ page }) => {
  await page.request.post("/api/__test__/reset", {
    data: { case: "completed-operation" },
  });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "继续本次", exact: true }),
  ).toHaveCount(0);
});
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_operation_views.py -q` 和 `cd frontend && npm run test:e2e -- operations.spec.ts`，预期新进度未实现。
- [ ] **Step 3 — 实现：** 轮询统一接口，页面卸载取消旧轮询；phase 区分同步／解析／整理／发布。停止请求期间显示实际状态，恢复中断需明确点击。工作台同步并整理、详情同步此客户、设置开关和记录均使用该服务；不新增导航页。
- [ ] **Step 4 — 绿灯：** 补测错误 toast、不连源不提示无新增、单客户优先、连续点击不双发、停止／恢复快速切换、配置开关不假停止，相关测试通过；前端 unit／build 通过。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: unify sync and analysis progress across workspace`。

### Task 5: 用量与真实运行回归

**Files:** Create `operations/usage.py`, `tests/test_usage_recovery.py`, `docs/verification/m4-runtime.md`；Modify model/gateway.py、OperationPanel.tsx、tests/conftest.py。

**Interfaces:** `summarize_usage(conn, operation_id: str) -> dict` 返回 requests、input_tokens、output_tokens、unknown_calls、cost、阶段耗时及可选核验价格版本。超时无响应的用量为 unknown，不填零；timed_out_operation 测试 fixture 创建两次调用，一次超时用量未知、一次成功用量已知，不附核验价格。

- [ ] **Step 1 — 写失败测试：** 模型首次超时后重试成功，两次都入账且一次 usage unknown；恢复成功段不增加真实调用；不设置每日 token 硬拦截；价目未验证时不展示虚构金额。

```python
def test_timeout_usage_is_not_hidden(db, timed_out_operation):
    from wechat_agent.operations.usage import summarize_usage
    usage = summarize_usage(db, timed_out_operation)
    assert usage["requests"] == 2
    assert usage["unknown_calls"] == 1
    assert usage["cost"] is None
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_usage_recovery.py -q`，预期汇总／恢复统计缺失。
- [ ] **Step 3 — 实现：** 从 model_calls 而非前端动画汇总；按同步／解析／模型分别计时，保留错误原因。真实 Mac 依次验证断网、睡眠、退出、重启、停止后改身份、重复手动点击，记录结果和未通过项。
- [ ] **Step 4 — 绿灯：** 上述测试、Python 全测和 operations E2E 通过；观察至少一次计划到点与一次睡眠补检查，形成 m4-runtime.md，不能用修改电脑时间代替所有时间边界测试。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: report actual operation usage and recovery evidence`。

## 退出条件

- [ ] 全局、单客户、每日计划复用队列，去重和优先生效。
- [ ] 无幽灵运行、停止后无迟到发布、成功后无继续；部分失败可以局部重试。
- [ ] 每天仅一次自动检查、错过合并一次；无变化不重发模型。
- [ ] 自动测试和 Mac 生命周期实测记录均通过；失败未闭合时不启用无人值守批量。
