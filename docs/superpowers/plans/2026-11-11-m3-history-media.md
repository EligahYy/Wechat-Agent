# M3 长历史与附件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持超窗口历史及图片／PDF／CSV／Excel 资料，证明实际处理范围，并能恢复失败分段。

**Architecture:** 获取原件、解析和模型整理分层；把长历史拆成有来源的分段事实，再按字段／批次归纳。解析结果、覆盖和检查点全部持久化，复用只限输入版本一致的单元。

**Tech Stack:** 既有栈；按 M0 样本验证后添加 Pillow、pypdf、openpyxl、pypdfium2 和本地 Tesseract，CSV 使用标准库。库版本实际解析进锁文件。

**Spec:** [产品 §4、8](../../PRODUCT_DESIGN.md)、[模型执行 §2–5](../../MODEL_EXECUTION.md)、[内部契约](CONTRACTS.md)。前提：M2 云端端到端回放通过；真实客户闭环仍保留实机验收项。

## Global Constraints

- 所有代码、修复和自动化测试在云端完成，检查后直接推 main；Mac 只运行交付工具验证。云端开发完成与实机通过分别记录，实机门槛不阻塞可独立测试的代码开发。

- 原件／缩略图／获取失败／未解析／解析失败是不同状态。
- 首次相关历史完整扫描，不以 Top-K 或反复压缩摘要代替。
- 输出预留及安全余量纳入容量；安全余量初始为窗口的 10%。
- 每个归纳单元最多两轮补读，失败请求仍受每工作单元最多 6 次上限。
- 一个附件或分段失败保留其他已核对事实；处理覆盖由程序计算，不能当成模型理解正确率。

## Review Focus

1. 原件不在本机、只有缩略图、权限不足和损坏文件：Task 1、2。
2. 扫描 PDF、Excel 多工作表、货量单位及表格单元格来源：Task 2。
3. 单段话题比窗口长、引用跨段、事实总量仍超窗：Task 3、4。
4. 附件重新解析、原文修订及人工约束变化让缓存失效：Task 4。
5. 部分失败看起来像全部完成、重试重复模型用量：Task 4、5。

## File Structure

`attachments/` 管获取、文件存储、解析与定位；`context/chunks.py` 管容量和切分；`analysis/` 增加事实账本、覆盖及检查点。前端扩展现有来源面板，不新增统计侧栏。

### Task 1: 可恢复的附件获取

**Files:** Create `attachments/store.py`, `attachments/fetch.py`, `tests/test_attachment_fetch.py`, `storage/migrations/003_media_chunks.sql`；Modify source adapter、api/messages.py、tests/conftest.py。

**Interfaces:** `fetch_and_store(conn, source: SourceAdapter, attachment_id: str, root: Path) -> AttachmentFetch`（async）；内部文件按哈希存储，外部只暴露附件 ID。此任务创建 media_source fixture：在 db 注册 image-missing 及其消息，回放源取该附件返回 missing。

- [ ] **Step 1 — 写失败测试：** 源返回 missing 和 thumbnail 分别保存真实状态，原文仍可读；相同文件重取不重复写；写文件中断不标 original；跨账号附件请求无法读到文件。

```python
@pytest.mark.asyncio
async def test_missing_original_remains_missing(db, media_source, tmp_path):
    from wechat_agent.attachments.fetch import fetch_and_store
    result = await fetch_and_store(db, media_source, "image-missing", tmp_path)
    assert result.state == "missing"
    assert result.content is None
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_attachment_fetch.py -q`，预期 fetch/store 尚无实现。
- [ ] **Step 3 — 实现：** 源返回 bytes 后临时文件写入、哈希核对、原子改名，再提交数据库状态；单独记录获取与解析版本／错误。读取必须校验附件归属，限制为工作目录中的已登记文件；失败可重试，不改写消息正文。
- [ ] **Step 4 — 绿灯：** 上述测试通过；补测无后缀 MIME、损坏零字节、重复重试和断点恢复，运行命令相同。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: archive attachments with explicit acquisition states`。

### Task 2: 图片与文档解析

**Files:** Create `attachments/{contracts,parser,ocr,pdf,spreadsheet}.py`, `tests/test_media_parsers.py`, `tests/fixtures/media/`；Modify requirements lock。

**Interfaces:** Creates ParseResult 和 `parse_attachment(path, mime)`，fragments 各含 text、locator、质量标记；locator 固定为 page:n、sheet:name/cell:A1 等可回定位字符串。

- [ ] **Step 1 — 写失败测试：** 文本 PDF 保留页码；扫描页 OCR 保留 page；XLSX 两工作表同坐标必须区分；CSV 引号／换行单元格不打散；损坏文件返回 failed 而非空文本成功，未支持格式为 unsupported。

```python
def test_csv_volume_preserves_unit(tmp_path):
    from wechat_agent.attachments.parser import parse_attachment
    path = tmp_path / "pack.csv"
    path.write_text("货品,货量\n收纳盒,12方\n", encoding="utf-8")
    result = parse_attachment(path, "text/csv")
    assert result.state == "parsed"
    assert any("12方" in fragment.text for fragment in result.fragments)
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_media_parsers.py -q`，预期解析器不存在。
- [ ] **Step 3 — 实现：** pypdf 提文本，扫描页用 pypdfium2 渲染后交 OCR；图片 OCR 保留片段位置；Excel 用 openpyxl 读取，不执行公式，缓存值缺失明确标 gap。Tesseract 调用用参数数组，测试注入可控 OCR 输出；Mac 实机单独安装并核验语言包，缺引擎为 unavailable，不伪解析。旧 XLS 等未支持格式保留原件并报明格式。同步解析器通过 `asyncio.to_thread` 执行，不阻塞 worker 心跳；线程中不持有 SQLite 连接。
- [ ] **Step 4 — 绿灯与实测：** pytest 全过并对 M0 的真实图片／价卡／PDF／装箱表核对文字、数值、单位和位置；记录 OCR 漏字，不能把低质量文字标确定事实。更新实际 lock 及支持格式表。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: parse logistics media with source locators`。

### Task 3: 容量核算与历史分段

**Files:** Create `context/tokens.py`, `context/chunks.py`, `tests/test_context_chunks.py`；Modify context/contracts.py。

**Interfaces:** `estimate_tokens(material: str, model_id: str) -> int`；`plan_chunks(snapshot, capabilities) -> list[ContextChunk]`；ContextChunk 含 id、refs、overlap_refs、input_tokens、output_tokens、cache_key，存入 003 迁移的 chunks 表。

- [ ] **Step 1 — 写失败测试：** 使用固定 tokenizer 替身和窗口 1000，安全余量 100；断言每段规则／约束／材料／输出／余量之和不超 1000，所有原始 refs 都被覆盖；跨段引用不丢，同条重叠不会生成两条来源事实。

```python
def test_chunks_fit_capacity(snapshot, capabilities):
    from wechat_agent.context.chunks import plan_chunks
    caps = capabilities.model_copy(update={"context_tokens": 1000, "max_output_tokens": 128})
    chunks = plan_chunks(snapshot, caps)
    assert chunks
    assert all(c.input_tokens + c.output_tokens + 100 <= 1000 for c in chunks)
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_context_chunks.py -q`，预期分段器不存在。
- [ ] **Step 3 — 实现：** 使用 M0 真实容量，不提供未知容量默认。按会话和连续话题切分，超长话题继续拆并保留相邻上下文；固定规则本身已超窗时明确失败。优先实际 tokenizer，无对应实现时记录保守估算方法；不得自动截掉最早材料。
- [ ] **Step 4 — 绿灯：** 增加极长单条、同时间排序、Unicode／表格、所有内容都短但规则占满、不同模型窗口的边界测试；pytest 全过，覆盖率等于清单范围而非模型自报。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: partition complete customer history within model capacity`。

### Task 4: 分段事实、覆盖与检查点复用

**Files:** Create `analysis/{facts,coverage,checkpoints}.py`, `model/prompts/facts-v1.md`, `tests/test_chunk_workflow.py`；Modify analysis/workflow.py、profiles/publisher.py。

**Interfaces:** `extract_chunk(chunk: ContextChunk, snapshot, cancellation) -> list[Fact]`（async）；`compute_coverage`、`load_checkpoint` 见 CONTRACTS；WorkflowV1 在 direct／chunked 路径产生同一 AnalysisResult。

- [ ] **Step 1 — 写失败测试：** 三段中第二段调用失败，断言第一和第三段事实保留、第二段 failed、客户不宣称完整；恢复时只补失败段；修订第二段后只有其及依赖归纳失效，模型／模板／人工版本变动按缓存键失效。

```python
def test_unprocessed_snapshot_is_not_complete(db, snapshot):
    from wechat_agent.analysis.coverage import compute_coverage
    coverage = compute_coverage(db, snapshot.id)
    assert coverage.pending
    assert coverage.complete is False
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_chunk_workflow.py -q`，预期尚不支持分段工作流。
- [ ] **Step 3 — 实现：** 持久化“看过无关”和有效事实；按来源去重，保留归属、事件时间、单位及批次。全部事实仍超窗时按字段／批次／事件分单元归纳并保留原文引用，不靠摘要递归丢事实。冲突最多两轮补读；记录每轮和工作单元 ID，不重置重试预算。
- [ ] **Step 4 — 绿灯：** 增加附件后来成功解析、服务商回复跨段、单字段超窗、停止后恢复不重发成功调用、模型伪称 coverage=100 被忽略等测试；pytest 全过。无可安全归纳的部分明确未完成，不硬裁历史。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: resume evidence extraction with verified coverage`。

### Task 5: 附件定位、局部缺口及重试交互

**Files:** Modify `src/wechat_agent/api/attachments.py`, `src/wechat_agent/api/profiles.py`, `frontend/src/features/profile/EvidencePanel.tsx`, `frontend/src/features/messages/MessageTimeline.tsx`, `src/wechat_agent/operations/service.py`, `src/wechat_agent/operations/worker.py`, `tests/webserver.py`；Create `frontend/src/features/messages/AttachmentViewer.tsx`, `frontend/e2e/media.spec.ts`, `tests/test_media_retry.py`, `tests/fixtures/media-mixed.json`。

**Interfaces:** GET `/api/attachments/{id}?view=original|parsed`；重试通过统一 operations 的指定未完成 item，不发明第二套任务；响应含 acquisition／parse／coverage 分层结果。

- [ ] **Step 1 — 写失败测试：** 图片原文定位和 PDF 页码／Excel 单元格可跳转；缺失原件不显示“已解析”；分段 failed 时资料行显示不完整且仍可查看已有档案，重试只触发对应 item。

```ts
test("missing original is shown honestly", async ({ page }) => {
  await page.request.post("/api/__test__/reset", {
    data: { case: "media-mixed" },
  });
  await page.goto("/");
  await page.getByRole("button", { name: "商家甲", exact: true }).click();
  await page.getByRole("tab", { name: "沟通原文" }).click();
  await expect(page.getByText("本机缺失", { exact: true })).toBeVisible();
});
```

- [ ] **Step 2 — 红灯：** `python -m pytest tests/test_media_retry.py -q` 与 `cd frontend && npm run test:e2e -- media.spec.ts`，预期能力未实现。
- [ ] **Step 3 — 实现：** 文件查看使用受控 ID；原件、解析文本及具体问题就近展示，标明人工／模型结论差异。工作流反馈完整性，不恢复已删除的侧栏数量统计或通用说明堆叠。
- [ ] **Step 4 — 绿灯：** 两组测试及前端 build 通过；在 Mac 长历史＋混合附件样本逐项核对覆盖与定位，将阶段结果写 `docs/verification/m3-media-history.md`。
- [ ] **Step 5 — 提交检查点：** 获准时消息 `feat: expose media evidence and targeted retry`。

## 退出条件

- [ ] 确实超窗口的历史可以处理；覆盖清单可核对，模型漏提另行统计。
- [ ] 目标四类附件有实测结果，不支持／缺失透明降级；已有文本事实不丢。
- [ ] 断点恢复、版本失效和局部重试通过，成功单元不重复计费请求。
- [ ] Python 全测、前端相关 E2E／unit／build 通过；完整性与资料状态一致。
