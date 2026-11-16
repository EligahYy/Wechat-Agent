# M3 文本长历史与恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking. 已授权云端串行开发、最终一次整体CR、测试后非强制推main。

**Goal:** 已确认商家的长文本历史能在模型窗口内分段处理，记录范围与进度，失败重试复用有效结果。

**Architecture:** 统一模型真实请求形状的容量核算；会话内有序分段与单消息片段保留原始引用；schema16持久化计划和内容寻址检查点；分段提取→紧凑事实归纳，最后沿用现有校验和事务发布。完整范围由程序计算，不接受模型自报覆盖。

**Tech Stack:** Python3.12、SQLite、Pydantic、既有OpenAI兼容网关、React/TypeScript、pytest/Vitest/Playwright；无新增tokenizer依赖，不猜DeepSeek分词器。

**Spec:** [产品方案](../../PRODUCT_DESIGN.md)、[模型执行](../../MODEL_EXECUTION.md)、[内部契约](CONTRACTS.md)、[原M3计划](2026-11-11-m3-history-media.md) Task3—4。本轮聚焦文本，附件Task1—2／5后续。

## Global Constraints

- 保留完整原文与说话人；覆盖以原文修订与片段范围核对，不Top-K丢弃或递归摘要压缩。
- 容量包含模板、JSON Schema、消息、输出、10%余量和修复请求空间。可注入精确分词器；未接入真实模型分词器时明确UTF8保守上界，不伪称已支持某型号。
- 分段结果需先校验来源属于该段；归纳不引入新引用。归纳过大按字段／批次拆单元，单字段仍无法容纳则显式失败并保留检查点，不截断或伪完整。
- 来源未完成、人工覆盖、身份／业务范围、停止、资料版本、引用修订等发布保护继续生效。分段失败保留检查点和旧档案，全部所需单元成功才发布新档案。
- 复用键包含账号／客户、当前材料及修订、必要相邻／引用语境、人工版本、角色／范围、模型配置、模板及策略；无关时间戳／操作ID不纳入。每逻辑单元网络请求最多6次，跨新任务不重置；成功单元不再发请求。
- 沿用统一同步整理任务和重新同步入口，不新增绕开来源与授权的执行入口。小历史直接路径兼容旧WorkflowV1，生产切到WorkflowV2并明确一次策略升级重算。
- 分段发现与附件解析不属于本轮；云端合成回放不代表真实模型质量。

## Task 1: 统一容量与有证据范围的分段

**Files:** 新建context/tokens.py、context/chunks.py、tests/test_context_chunks.py；修改model/gateway.py。

- [x] Step1 写失败测试：请求计量、输出与余量、schema与转义、Unicode；会话顺序、相邻与远端回复、超长单条、固定提示超窗、片段完整无漏、稳定缓存键。
- [x] Step2 运行pytest定向并观察红灯。
- [x] Step3 实现单一预算函数供网关和规划共用；纯规划器可在线程运行避免阻塞事件循环。
- [x] Step4 定向绿灯并回归网关与旧工作流；提交容量与规划检查点。

## Task 2: 检查点、提取与有界归纳

**Files:** schema016_history_checkpoints.sql、analysis/checkpoints.py、analysis/history.py、analysis/facts.py、model/prompts/history-v1.md；model/contracts.py、gateway.py、storage/db.py及测试。

- [x] Step1 写失败测试：三段中段失败仍完成其余段，重试只补失败；持久化重开；修订／角色／人工／配置变更正确失效；单消息分片、伪造引用、无关空结果、归纳失败／超大字段、停止及跨账号；6次预算跨操作持久化。
- [x] Step2 运行定向红灯。
- [x] Step3 实现schema16和内容寻址缓存；阶段输入／校验／结果持久化、程序覆盖和归纳；未知错误不缓存成成功。
- [x] Step4 定向绿灯和迁移／发布回归；提交后端检查点。

## Task 3: 生产接线与用户进度

**Files:** analysis/runtime.py、runner.py、operations/reports.py；CustomerSyncStatus.tsx、OperationDetails.tsx、operationOutcome.ts、tests/webserver.py及生产／浏览器测试。

- [x] Step1 失败测试覆盖超窗真实网关任务成功发布、失败复用、在途进度、重试不重复成功段、来源与分析状态分开、人工修改阻止旧结果。
- [x] Step2 生产启用WorkflowV2；操作counts保存分段／归纳／复用／消息覆盖；现有任务终态更新保留这些计数。
- [x] Step3 卡片就近显示分段进度与复用，失败原因提供重新同步并解释保留检查点；单元用完次数明确提示，不无穷重复付费。
- [x] Step4 定向API、单元、浏览器和构建通过；提交生产UI检查点。

## Task 4: 整体验收、CR与架构文档

- [x] Step1 完整Python、前端unit/build、相关浏览器回归；独立小窗口大历史合成输入，核对所有修订与片段覆盖、原文证据、缓存及安全边界。
- [x] Step2 一次最终独立只读CR：容量与实际HTTP一致、成功缓存不越权、失败恢复预算不重置、空／无效模型输出不误报成功、最后发布保护、计划性能与SQL事务。
- [x] Step3 重要问题一次修复，失败回归→绿灯；不重复派CR。
- [x] Step4 更新STATUS、计划索引、MODEL_EXECUTION、MAC_SETUP与验收报告；wheel资源、迁移、静态服务及diff检查，非强制推main。

## Pre-flight

Task1请求计量与Task2提取、归纳必须使用同一请求形状；通过统一ModelRequest预算函数消除双重估算。Task2新schema独立016，原计划003已被operations占用，不覆盖历史迁移。Task2缓存不依赖操作ID，网关unit授权依赖操作ID；新增checkpoint_key做持久预算，单次unit仍绑定当前操作／快照。Task3需刷新runner局部counts，防止进度在最终写入时丢失。
