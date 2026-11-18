# 整理效率与长历史可靠性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 缩短短历史整理等待，使长历史可分段、可暂停恢复，并准确区分质量问题与普通信息缺失。

**Architecture:** 先测量与分类，再引入有界稀疏提取、引用映射、覆盖账本归纳与分层缓存。保留快照权限和原子发布边界，按任务串行实施。

**Tech Stack:** Python3.12 / FastAPI / SQLite / Pydantic / React / TypeScript / Node24.14.1。

**Spec:** [审查与设计](../specs/2026-11-18-organize-reliability-design.md)。基线d4300d7；下方记录已实施的首批修复，其余任务按复选框追踪。

## Global Constraints

不修改原文、不跨联系人引用、不覆盖人工值、不编造模型能力。迁移从当前schema17顺序增加，保留旧记录可读。新增版本策略使用workflow-v3，旧检查点只读保留，不能误复用。未经核实不发送供应商思考参数。不新增依赖除非确有必要。

## Review Focus

- 撤回或角色变化发生在模型等待期间：发布必须拒绝（任务4、7）。
- 小窗口但单条引用前文巨大：显式暂停/错误，不能丢语境（任务3）。
- 失败后重启、同一操作重复继续：不能重复发布或绕过预算（任务6）。
- 一个字段包含千条互相冲突的报价：归纳不能任意选值或丢来源（任务5）。
- 老记录只有字符串缺口：界面兼容且未知错误不隐藏（任务2）。

### Task 1: 耗时归因与基准

**Files:** 修改 `src/wechat_agent/model/gateway.py`、`src/wechat_agent/analysis/runner.py`、`src/wechat_agent/analysis/checkpoints.py`、`src/wechat_agent/operations/reports.py`；新增 `tests/test_analysis_timing.py`；其余新模块在实现步骤指定。

**Interfaces:** 新增analysis/telemetry.py：record_stage(conn, operation_id: str, stage: str, elapsed_ms: int, metrics: dict) -> None；新增迁移保存阶段/请求耗时，使用单调时钟计算。记录网络尝试、重试、缓存与实际消息量，不保存原文或密钥。

- [ ] 写失败用例：test_timing_attributes_retry：fake clock下两次请求分别计时，准备与模型耗时不重复累计；test_unchanged_has_zero_calls：沿用runner.unchanged，无变化模型0次。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_analysis_timing.py -q`，确认因目标行为缺失失败。
- [ ] 按上述接口实现最小变更，保持设计中的预算与失败语义；新增持久字段配套升级及旧库读取测试。
- [ ] 重跑该测试为PASS，并运行受影响现有模块测试；前端涉及状态时增加对应Vitest用例。
- [ ] 检查diff，独立提交该任务代码、测试及迁移；不把未完成任务标记完成。

### Task 2: 问题分类与局部校验

**Files:** 修改 `src/wechat_agent/profiles/validator.py`、`src/wechat_agent/profiles/publisher.py`、`src/wechat_agent/operations/reports.py`、`frontend/src/features/profile/ProfileOverview.tsx`；新增 `tests/test_profile_issue_policy.py`；其余新模块在实现步骤指定。

**Interfaces:** 新增profiles/issues.py：ProfileIssue(code: str, severity: str, field_path: str | None, count: int)；classify_issues(legacy: list[str]) -> list[ProfileIssue]。validator保留number_not_supported/unit_not_supported/event_date_not_supported等精确原因；发布状态依据结构化严重度。API新增issues_detail，保留issues兼容。

- [ ] 写失败用例：test_optional_unknown_is_success；test_attachments_grouped：4附件显示1条提示count=4；test_summary_error_deduplicated：连带标签只有1条；test_wrong_number_preserves_old_field；test_unknown_legacy_issue_visible。不要把单位换算默认为合法，新增有明确等价规则的回归后才支持。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_profile_issue_policy.py -q`，确认因目标行为缺失失败。
- [ ] 按上述接口实现最小变更，保持设计中的预算与失败语义；新增持久字段配套升级及旧库读取测试。
- [ ] 重跑该测试为PASS，并运行受影响现有模块测试；前端涉及状态时增加对应Vitest用例。
- [ ] 检查diff，独立提交该任务代码、测试及迁移；不把未完成任务标记完成。

### Task 3: 动态上下文与稀疏提取

**Files:** 修改 `src/wechat_agent/analysis/history.py`、`src/wechat_agent/context/chunks.py`、`src/wechat_agent/model/prompts/history-v1.md`、`src/wechat_agent/analysis/runtime.py`；新增 `tests/test_workload_planning.py`；其余新模块在实现步骤指定。

**Interfaces:** 新增analysis/planning.py：WorkPolicy(seed_messages=80, seed_input_target=24000)；plan_work(rows: list[dict], request_factory, config, policy: WorkPolicy) -> list[ContextChunk]，只规划首批并持久化边界，后续批次由反馈调度。新增analysis/extraction.py定义ExtractedFacts，仅含有证据事实、事件、问题；显式schema版本，最终仍转换AnalysisResult。新增context/assembler.py的ContextPack与assemble_context(snapshot, primary_spans, task, facts) -> ContextPack；新增analysis/adaptive.py的observe_attempt(state, observation) -> state，采用设计中的两次低负载增长25%和超时/length减半规则。完整wire预算硬校验；80/24000只是冷启动参考。

- [ ] 写失败用例：test_same_count_different_density_changes_pack；test_million_window_still_bounded；test_single_unit_no_merge；test_oversized_reply_not_dropped；test_unicode_spans_cover_exactly。新增test_feedback_grows_and_shrinks、test_rate_limit_does_not_shrink、test_old_reply_dependency_loaded、test_last_message_not_omitted、test_plan_boundaries_stable_after_restart；超长单条、空消息及仅附件都覆盖。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_workload_planning.py -q`，确认因目标行为缺失失败。
- [ ] 按上述接口实现最小变更，保持设计中的预算与失败语义；新增持久字段配套升级及旧库读取测试。
- [ ] 重跑该测试为PASS，并运行受影响现有模块测试；前端涉及状态时增加对应Vitest用例。
- [ ] 检查diff，独立提交该任务代码、测试及迁移；不把未完成任务标记完成。

### Task 4: 短引用与字段隔离

**Files:** 修改 `src/wechat_agent/analysis/history.py`、`src/wechat_agent/analysis/facts.py`、`src/wechat_agent/context/reader.py`；新增 `tests/test_citation_aliases.py`；其余新模块在实现步骤指定。

**Interfaces:** 新增analysis/citations.py：build_aliases(rows: list[dict]) -> dict[str, dict]；resolve_aliases(payload: dict, aliases: dict[str, dict]) -> dict。别名s1等按unit稳定顺序生成，恢复精确原ID/revision，片段只允许已读范围。最多一次局部修复；修复只发送相关字段、合法材料及明确原因。

- [ ] 写失败用例：test_alias_roundtrip；test_other_unit_alias_rejected；test_unknown_alias_isolates_field；test_cross_contact_blocks；test_revoked_during_call_blocks_publish；test_invalid_field_keeps_valid_siblings。非法引用绝不以模糊匹配替换。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_citation_aliases.py -q`，确认因目标行为缺失失败。
- [ ] 按上述接口实现最小变更，保持设计中的预算与失败语义；新增持久字段配套升级及旧库读取测试。
- [ ] 重跑该测试为PASS，并运行受影响现有模块测试；前端涉及状态时增加对应Vitest用例。
- [ ] 检查diff，独立提交该任务代码、测试及迁移；不把未完成任务标记完成。

### Task 5: 有覆盖证明的分层归纳

**Files:** 修改 `src/wechat_agent/analysis/facts.py`、`src/wechat_agent/analysis/history.py`、`src/wechat_agent/analysis/checkpoints.py`、`src/wechat_agent/analysis/coverage.py`；新增 `tests/test_hierarchical_reduction.py`；其余新模块在实现步骤指定。

**Interfaces:** 新增analysis/reduction.py：ReductionNode(input_ids: list[str], outputs: list[dict], dispositions: dict[str,str])；validate_reduction(node: ReductionNode, inputs: dict[str,dict]) -> None。每层32候选/24000估算为初始软目标，由任务3反馈调度，必须满足真实窗口；按字段/事件分桶，多层输出必须缩小候选或明确冲突聚合，否则暂停归纳不收敛。本地去重、单候选直通，最终本地装配。

- [ ] 写失败用例：test_thousand_quotes_reduces；test_missing_candidate_disposition_rejected；test_conflicting_prices_preserved；test_single_batch_too_large_recovers；test_no_progress_pauses；test_merge_cannot_introduce_sources。增加test_duplicate_page_idempotent、test_forged_processed_ids_rejected、test_truncated_page_preserves_prior_pages；所有叶子有合法归属账本才允许最终发布。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_hierarchical_reduction.py -q`，确认因目标行为缺失失败。
- [ ] 按上述接口实现最小变更，保持设计中的预算与失败语义；新增持久字段配套升级及旧库读取测试。
- [ ] 重跑该测试为PASS，并运行受影响现有模块测试；前端涉及状态时增加对应Vitest用例。
- [ ] 检查diff，独立提交该任务代码、测试及迁移；不把未完成任务标记完成。

### Task 6: 暂停恢复与提取缓存

**Files:** 修改 `src/wechat_agent/analysis/checkpoints.py`、`src/wechat_agent/model/gateway.py`、`src/wechat_agent/analysis/runner.py`、`src/wechat_agent/operations/service.py`、`src/wechat_agent/operations/worker.py`；新增 `tests/test_analysis_resume.py`；其余新模块在实现步骤指定。

**Interfaces:** 新增analysis/execution.py：ExecutionBudget(max_calls=20, max_elapsed_seconds=600)；can_start_unit(state, budget: ExecutionBudget) -> bool。迁移保存剩余工作与暂停原因，继续沿用持久尝试计数。新增持久事实/事件/引用依赖索引，覆盖所有主消息或合法缓存；提取key移除不相关profile_version但显式纳入实际读取依赖；归纳key包含旧档案。单请求总120秒/read90/connect15；超时一次重试后缩段，剩余预算不足暂停。

- [ ] 写失败用例：test_budget_pause_and_resume；test_restart_does_not_reset_attempts；test_duplicate_resume_no_duplicate_publish；test_append_reuses_closed_chunks；test_edit_invalidates_dependent_chunks；test_manual_role_changes_invalidate；test_old_event_update_invalidates_dependents；test_model_change_resets_feedback；test_auth_error_no_retry；test_cancel_inflight。不要共享SQLite连接并发写。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_analysis_resume.py -q`，确认因目标行为缺失失败。
- [ ] 按上述接口实现最小变更，保持设计中的预算与失败语义；新增持久字段配套升级及旧库读取测试。
- [ ] 重跑该测试为PASS，并运行受影响现有模块测试；前端涉及状态时增加对应Vitest用例。
- [ ] 检查diff，独立提交该任务代码、测试及迁移；不把未完成任务标记完成。

### Task 7: 交互与整体验收

**Files:** 修改 `frontend/src/components/OperationDetails.tsx`、`frontend/src/features/profile/ProfileOverview.tsx`、`frontend/src/api/types.ts`、`docs/STATUS.md`、`docs/MODEL_EXECUTION.md`；新增 `tests/test_analysis_acceptance.py`；其余新模块在实现步骤指定。

**Interfaces:** API暴露阶段耗时/暂停与继续动作；界面区分已更新、需核对、已暂停、失败，缺口按设计分类。增加frontend/e2e/analysis-reliability.spec.ts；更新Mac验证说明与策略版本迁移说明。

- [ ] 写失败用例：test_fixture_matrix：1/80/81/1000/10000条含重复、编辑、撤回、四附件、冲突、已走货旧批、无业务内容；分别断言覆盖、请求次数、恢复与旧值保护。浏览器检查中文提示、暂停继续和历史字符串兼容。
- [ ] 运行 `.venv/bin/python -m pytest tests/test_analysis_acceptance.py -q`，确认因目标行为缺失失败。
- [ ] 按上述接口实现最小变更，保持设计中的预算与失败语义；新增持久字段配套升级及旧库读取测试。
- [ ] 重跑该测试为PASS，并运行受影响现有模块测试；前端涉及状态时增加对应Vitest用例。
- [ ] 检查diff，独立提交该任务代码、测试及迁移；不把未完成任务标记完成。

## 最终验证与交付

- [ ] `.venv/bin/python -m pytest -q` 全量后端通过。
- [ ] Node24.14.1下在frontend运行 `npm run test:unit -- --run`、`npm run build`、`npm run test:e2e`；浏览器串行，避免端口冲突。
- [ ] 验证schema17旧库升级、新库、wheel资源及生产静态入口；不清库。
- [ ] 记录固定数据集请求数/耗时、取消与失败恢复结果；真实供应商测试单列待验，质量不以请求成功代替。
- [ ] 整体CR聚焦证据权限、字段保留、归纳覆盖与缓存失效，修复重要问题后非强制推main。

自审：设计1—2由任务2/4负责，3—4由任务3/4负责，5由任务5负责，6—7由任务1/6负责，8由任务6负责；展示和实机验收由任务7负责。并发执行及附件解析明确不在本次范围。

动态组装补充自审：任务3负责上下文选择及反馈，任务4负责引用，任务5负责完整页幂等组装与归纳，任务6负责依赖失效和恢复。供应商硬容量仍保留，禁止将软调度目标变成全历史处理上限。


## 2026-11-18 首批实施

优先落地任务3的请求预分批和按材料分配初始输出，以及任务5的单一事实本地组装。以完整请求的24000 UTF-8估算作为初始软目标。设置中的上下文与最大输出用于供应商容量校验，长消息按字符拆分，必需的回复前文可在供应商窗口内扩大该次请求。聚合超过软目标改走字段归纳。结果已在各分段按既有检查点持久化。

短引用映射、持续反馈调整、复杂冲突的多层归纳、操作级暂停继续、缺口分类及真实模型耗时采样尚待推进。现有任务复选框只在整项验收后勾选。
