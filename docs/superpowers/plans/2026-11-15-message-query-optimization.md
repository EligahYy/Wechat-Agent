# 联系人原文性能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans。按用户授权在main串行实施，最后一次独立只读审查。

**Goal:** 统一联系人原文筛选和查询，修复首屏、切日和每次定位刷新。

**Architecture:** 本人发言索引产生日期／群会话范围，有效私聊单独兼容；单页及导航共享范围，前端就地定位和有界缓存。

**Tech Stack:** Python3.12 / SQLite / FastAPI / React / TypeScript / Node24.14.1。

**Spec:** [设计与影响审查](../specs/2026-11-15-message-query-optimization-design.md)。

## Global Constraints

不清库，不改源协议／模型选材／业务范围；只蓝点本人日期；保留他人上下文、有效私聊、账号授权、稳定游标和安全附件。

## Review Focus

仅我方私聊仍可落点；修订撤销旧日期；搜索不改变本人会话依据；缓存不串人；本地定位后跨窗口仍能正确找邻居。

### Task 1: 来源、日期、索引与影响回归

Files: `messages/queries.py`, `messages/calendar.py`, `api/messages.py`, `storage/db.py`, `storage/migrations/011_message_query_indexes.sql`, `tests/test_message_query_performance.py`, 现有日历／来源／storage测试。

Interfaces: `timeline_sources(conn,account,contact,conversation_id=None)`返回来源；`message_scope(...,sources,day)`返回一次解析的where/params；read_calendar返回本人days及轻量首末日期。

- [x] 写两群跨日、纯上下文日期撤销、作者修订、私聊落点和SQLite工作量上限测试，运行看失败。
- [x] 实施来源直查、日内会话范围、schema11表达式／附件／revision索引和批取附件。
- [x] 更新受最新蓝点规则影响的旧断言，跑消息、导入、snapshot、discovery和业务范围回归。

### Task 2: 窗口定位元数据与本地跳转

Files: `api/messages.py`, `api/types.ts`, `MessageTimeline.tsx`, `frontend/e2e/message-navigation.spec.ts`。

Interfaces: speech.positions每个位置有current_id/index/previous_id/next_id；分页合并positions；jump命中窗口直接设置speech。

- [x] 写浏览器测试：已加载定位不发HTTP、不丢计数、不替换DOM；窗口外定位失败仍留原消息。
- [x] 先验证失败，再补定位元数据、本地jump、稳定列表key及轻量忙态。
- [x] 测跨窗口、搜索、滚动补页后定位和旧游标。

### Task 3: 月份与窗口缓存

Files: `MessageBrowser.tsx`, `MessageCalendar.tsx`, `MessageTimeline.tsx`, `frontend/e2e/message-calendar.spec.ts`及缓存用例。

Interfaces: 组件内缓存按完整读取条件及revision隔离，最多6项，30秒有效。

- [x] 写缓存命中／revision失效、仅蓝点、切月不拉正文及切换竞态测试，观察失败。
- [x] 实施有界缓存、只本人蓝点、首屏当月优先及有效私聊回退；保留日历可达和布局。
- [x] 回归窄屏、页签切换、读取失败不显示旧日期数据。

### Task 4: 全面验收与收敛

Files: 文档索引／STATUS／日历规范／verification报告，独立审查记录。

- [x] 完整pytest、前端单元／E2E、Node24.14.1构建。
- [x] 相同150000条、802会话数据重测，记录查询计划和耗时。
- [x] 独立只读最终审查，必要问题按红绿测试修复，更新影响报告及当前说明。
- [x] 检查diff后提交并非强制推送main，提供Mac pull/build/restart验证步骤。
