# Calendar Message Browser Implementation Plan

> 历史归档：保留当时方案、命令和验证结果，不代表当前实现。当前入口见[实施状态](../../STATUS.md)。

> **For agentic workers:** Use superpowers:executing-plans 串行TDD，一次最终独立只读审查。云端main提交推送已授权。

**Goal:** 左日历右当日原文，完整上下文、本人定位和连续阅读。
**Architecture:** 时间线新增北京时间day范围及最新消息定位；独立月历元数据只返回有记录日期/计数和最新日期。React日历与日内时间线复用原文组件，独立滚动、边缘自动分页，复用账号权限／菜单／主题。
**Tech Stack:** FastAPI/SQLite，React/TypeScript，现有SelectField与motion。
**Spec:** ../specs/2026-11-15-timeline-calendar-design.md

### Task 1: 月历和日内接口
- [x] RED：UTC+8跨午夜、月日期计数、来源范围、最新日期、空日、跨账号、日内本人计数与游标绑定。
- [x] GREEN：calendar endpoint及day/date_latest日内查询，保留默认旧接口兼容。全部Python通过。
### Task 2: 日历双栏与连续阅读
- [x] RED：选日展开、日期蓝点、来源和日内搜索、回到最新、本人定位、自动补页不重复／不跳位置、无分页按钮。
- [x] GREEN：响应式日历组件、双栏浏览器、消息独立滚动，保留本轮浮条／柔和高亮改动。Node24.14.1构建、unit、浏览器回归通过。
### Task 3: 审查与交付
- [x] 一次独立只读审查；重要问题以失败测试修复。记录云端与Mac边界、更新状态和交互方案，检查后非强制推main。

完成：Python405、前端29单元／41浏览器及Node24.14.1构建通过。一次独立审查4项重要问题全部修复；窄屏显式焦点移交为延后小项。详见[验收记录](../../verification/calendar-message-browser-report.md)。
