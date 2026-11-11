# M5 质量、升级与 Mac 交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用真实样本证明一期档案价值，验证版本重算与恢复，交付可在 Mac 稳定运行的本地应用。

**Architecture:** 质量评估与产品数据分开，升级通过同输入回放及显式重算完成。部署为一个本地同源应用，备份保留原文、派生版本与人工资料，真实凭据仍留本机受控存储。

**Tech Stack:** 既有栈；pytest、Vitest、Playwright Chromium／WebKit、SQLite online backup、SHA-256 清单；不在本期引入 Agent 平台。

**Spec:** [产品 §9](../../PRODUCT_DESIGN.md)、[模型执行 §6–7](../../MODEL_EXECUTION.md)、[交互验收](../../INTERACTION_DESIGN.md)、[内部契约](CONTRACTS.md)。前提：M4 运行回归通过。

## Global Constraints

- 约 10 位代表性真实商家首轮样本，另留独立复测集，不能以合成演示冒充。
- 关键回归零错、引用全部可定位且抽查支持结论、人工内容不丢失，再扩大批量。
- 模型／模板／策略升级不自动全量重算；失败不替换旧结果，回退不删除人工内容。
- 只有桌面工作台／设置，无详情侧栏、白名单或待办扩展。
- 生产同源、绑定 127.0.0.1，默认端口 8000；应用关闭时不承诺自动执行。

## Review Focus

1. 模型隐藏错误字段获得漂亮正确率、未知被计为漏提或反之：Task 1。
2. 新模型 JSON 合法但串批、来源不支持结论、旧人工值被覆盖：Task 1、2。
3. SQLite WAL 中有未 checkpoint 数据、备份缺附件或恢复覆盖当前库：Task 3。
4. 深色宿主、矮窗口、多层弹窗焦点、快速动画和所有输入框：Task 4。
5. 新 Mac 的路径含空格、端口占用、Keychain 未配置及依赖不一致：Task 3、5。

## File Structure

`evaluation/` 放评估器与报告结构；`maintenance/` 放重算、版本切换及备份恢复；`scripts/` 放安装／启动／检查。真实评估材料在本地；仓库只存可审查的脱敏样本及汇总。

### Task 1: 可复现质量评估

**Files:** Create `evaluation/{__init__,contracts,runner,metrics}.py`, `tests/test_evaluation_metrics.py`, `tests/fixtures/evaluation/critical-cases.json`, `docs/verification/profile-quality.md`。

**Interfaces:** `evaluate(expected: list[ExpectedFact], actual: AnalysisResult) -> EvaluationReport`；ExpectedFact 含 contact_key、field、value／unit、event_time、batch_ref、allowed_sources、critical；报告含正确／错提／漏提／未知／错归／混批／引用／人工保持及调用成本耗时，以及 ready_for_acceptance。空标注集、关键失败或尚未复核语义不能使 ready_for_acceptance 为真，不用单一总分隐藏缺陷。

- [ ] **Step 1 — 写失败测试：** 隐藏错误字段会降低召回而非让所有指标提升；真正无资料的字段不算漏提；已提供却未读到的信息算遗漏；源 ID 存在但结论无支撑不能算已通过语义复核。精度与召回分母写进报告。

```python
def test_missing_gold_data_cannot_pass(analysis_result):
    from wechat_agent.evaluation.metrics import evaluate
    report = evaluate([], analysis_result)
    assert report.ready_for_acceptance is False
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_evaluation_metrics.py -q`，预期评估模块不存在。
- [ ] **Step 3 — 实现：** 支持固定输入版本和模型／策略版本回放，机器只计算可确定匹配，语义等价与来源支撑保留人工 reviewed／unreviewed。首轮约10位，独立复测集至少3位作为实施默认；覆盖跨群、服务商回复、附件、新旧批、字段修改、已发出但晚登记、卡航＋海运等情况。
- [ ] **Step 4 — 验证：** 单元测试通过；在 Mac 运行 `python -m wechat_agent.evaluation.runner --dataset .local/evaluation/heldout.json --strategy workflow_v1 --output .local/evaluation/report.json`。CLI 默认回放已有候选，不自动重发付费请求；显式 `--live` 才运行模型。人工复核真实样本，profile-quality.md 列出所有错误和未复核项；有关键错误则修链路并重跑，不能勾过。
- [ ] **Step 5 — 提交检查点：** 获准时提交评估代码、合成关键回归及脱敏报告，消息 `test: evaluate factual profile quality on held-out cases`。

### Task 2: 显式重算、版本切换与回退

**Files:** Create `maintenance/{__init__,contracts,reanalysis}.py`, `analysis/registry.py`, `tests/test_reanalysis.py`, `frontend/src/features/settings/ReanalysisDialog.tsx`, `frontend/e2e/reanalysis.spec.ts`；Modify operations API、worker、settings API。

**Interfaces:** `plan_reanalysis(conn, keys, strategy_version) -> ReanalysisPlan`，返回范围／版本／数量，不调用源或模型；开始后创建 reanalyze 操作，复用队列。registry 只注册代码内已审核策略，不执行客户端任意模块路径。

- [ ] **Step 1 — 写失败测试：** 切换模型配置本身不增加任务；显式选2个商家重算只调模型、不重新读源；失败保留旧 profile_version；新结果不覆盖 manual；选非商家拒绝分析，运行时改身份不得发布。

```python
def test_reanalysis_preview_does_not_start_work(db):
    from tests.factories import seed_case
    from wechat_agent.source.contracts import ContactKey
    from wechat_agent.maintenance.reanalysis import plan_reanalysis
    seed_case(db, "source-overlap")
    before = db.execute("SELECT count(*) FROM operations").fetchone()[0]
    plan = plan_reanalysis(db, [ContactKey(account_id="acct-1", contact_id="merchant-a")], "workflow_v1")
    assert plan.count == 1
    assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == before
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_reanalysis.py -q`，预期维护服务缺失。
- [ ] **Step 3 — 实现：** 设置维护入口预览范围和版本后开始；保存输入、模型、模板、策略、解析器和 schema 版本。兼容结果保持可读，切回旧策略不删除新旧记录；选择展示的有效版本时仍叠加最新人工修订。首版只有 workflow_v1，候选策略仅在测试／回放验证，不引入真正多 Agent 架构。
- [ ] **Step 4 — 绿灯：** 加测停止／继续、同客户幂等、已改模板待显式重算、回退不丢单号、重算期间新消息仍待更新。Python 及 `npm run test:e2e -- reanalysis.spec.ts` 通过；保存一次真实版本切换／失败回退记录。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: reanalyze selected merchants with versioned rollback`。

### Task 3: 一致性备份与独立恢复

**Files:** Create `maintenance/backup.py`, `tests/test_backup_restore.py`, `docs/BACKUP_RESTORE.md`；Modify `maintenance/contracts.py` 及迁移入口。

**Interfaces:** `create_backup(conn, destination) -> BackupManifest`、`restore_backup(manifest, destination) -> None`；manifest 含 schema_version、数据库及附件哈希、生成时间。恢复目标必须为新目录。

- [ ] **Step 1 — 写失败测试：** WAL 仍有事务提交时备份，恢复后消息、人工修改、批次和单号都存在；附件缺失／哈希错误拒绝完整成功；非空目标目录拒绝覆盖；schema 太新明确失败。

```python
def test_restore_does_not_overwrite_existing_directory(db, tmp_path):
    from wechat_agent.maintenance.backup import create_backup, restore_backup
    backup = create_backup(db, tmp_path / "backup")
    occupied = tmp_path / "existing"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        restore_backup(backup.manifest_path, occupied)
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "keep"
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_backup_restore.py -q`，预期维护模块缺失。
- [ ] **Step 3 — 实现：** 用 SQLite backup API 获取一致数据库，再按该快照引用复制不可变附件并验证清单；迁移前自动备份。恢复到独立目录并跑完整性／外键检查；运行中旧任务恢复为中断，不自动重发请求。Keychain 凭据不导出进备份，换机器需重新配置。
- [ ] **Step 4 — 绿灯及实测：** pytest 全过；在 Mac 新目录做一次恢复，打开档案核对来源、人工覆盖、单号及媒体。原库保持可用，不以复制一个 `.sqlite` 文件冒充 WAL 一致性备份。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: back up and restore complete local application data`。

### Task 4: 桌面字体、控件、动效与浏览器验收

**Files:** Create `frontend/e2e/{desktop,controls,motion}.spec.ts`, `docs/verification/desktop-acceptance.md`；Modify已有组件与 tokens。

**Interfaces:** 只消费已有 API；Playwright webServer 启动隔离测试后端与前端，不使用真实数据库；覆盖 Chromium 和 WebKit，先在 frontend 执行 `npx playwright install chromium webkit`，Safari 实机单列。

- [ ] **Step 1 — 写失败回归：** 1180／1280／1440／1920 桌面及 720px 高度；所有搜索、资料单行／多行、单号、时间的实际背景／边框／48px／12px／14px／焦点一致；深色在白色宿主里仍无白底。新增断言必须先在存在缺陷的组件上验证失败，已有正确行为不制造虚假红灯。

```ts
test("search uses the common field dimensions", async ({ page }) => {
  await page.goto("/");
  const input = page.getByRole("searchbox").first();
  await expect(input).toHaveCSS("font-size", "14px");
  await expect(input).toHaveCSS("border-radius", "12px");
  await expect(input).toHaveCSS("height", "48px");
});
```

- [ ] **Step 2 — 红灯：** `cd frontend && npm run test:e2e -- desktop.spec.ts controls.spec.ts motion.spec.ts`；记录具体失败，若新回归直接通过则保留保护，不宣称复现了 bug。
- [ ] **Step 3 — 修复：** 统一 token／控件，不为各弹窗叠加单独覆盖。按交互方案修页签指示器、导航、来源双向收起、勾选栏、搜索／筛选稳定行、按钮 hover 和 reduced-motion。时间区只保留一个组件，时区在浮层内；资料正文实色、交互层玻璃。
- [ ] **Step 4 — 绿灯及人工核对：** 前端全部 unit／E2E／build、Python 全测通过；Mac Safari 实机检查键盘焦点、Escape、多层弹窗、时间选择、字体和滚动。用 desktop-acceptance.md 记录实机版本、截图及未通过项，不用 Chromium 截图代替 Safari 通过。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `test: verify desktop controls typography and motion`。

### Task 5: Mac 单应用启动与最终交付

**Files:** Create `scripts/{setup-mac,start-app,check-release}.sh`, `tests/test_release_layout.py`, `docs/RUNBOOK.md`；Modify `api/app.py`, `docs/MAC_SETUP.md`, `README.md`。

**Interfaces:** `bash scripts/setup-mac.sh` 安装锁定依赖和构建前端；`bash scripts/start-app.sh` 同源启动 127.0.0.1:8000；环境变量 `WECHAT_AGENT_DATA_DIR` 允许显式选择数据目录，不改系统 HOME。脚本不重新安装未知 wx-cli、不自动发模型请求。

- [ ] **Step 1 — 写失败测试：** 已构建前端入口可由 FastAPI 提供，合法 GET 不被同源检查误拦；跨站写请求拒绝；API 不回明文密钥；脚本路径含空格可启动；端口占用清晰失败且不改绑公网地址。

```python
def test_local_frontend_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert client.get("/api/health").status_code == 200
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_release_layout.py -q`，预期尚无单应用发布布局。
- [ ] **Step 3 — 实现：** 服务静态构建、API 和受控附件同源；setup 用已有锁文件与 `npm ci`，不漂移升级版本；start 只启动一个拥有租约的 worker。RUNBOOK 写首次配置、手动同步／整理、停止／恢复、日计划、未知用量、备份恢复及升级。`.env`／运行数据不入 Git。
- [ ] **Step 4 — 验证：** 在 Mac 的全新 clone 路径按说明执行 setup、check-release、start，完成来源检测→身份→商家档案→纠正→单号→重启→恢复。`check-release.sh` 运行 Python 全测、前端 unit／build／E2E，不自动进入真实付费模型回放。将 M0–M5 证据、依赖锁及已知限制一起核对。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: deliver reproducible local Mac application`；提交后推送／发版按当时用户指示执行。

## 退出条件

- [ ] 真实首轮样本和独立复测完成，关键回归无错；完整报告错误与遗漏，未知不是遮羞布。
- [ ] 模型切换、显式重算、失败回退不丢人工值、原文和稳定批次。
- [ ] 备份在新目录恢复通过；Mac 全新 clone 可以按 RUNBOOK 启动。
- [ ] 桌面回归和 Safari 实机验收完成，所有未实现／不支持能力有明确边界；到此一期完成，不顺带加入待办或 Agent 平台。
