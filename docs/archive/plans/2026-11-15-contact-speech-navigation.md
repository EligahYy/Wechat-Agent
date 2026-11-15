# Contact Speech Navigation Implementation Plan

> 历史归档：保留当时方案、命令和验证结果，不代表当前实现。当前入口见[实施状态](../../STATUS.md)。

> **For agentic workers:** Use superpowers:executing-plans 串行实施，TDD，一次最终独立只读审查。用户授权main云端提交推送。

**Goal:** 保留其他人上下文，稳定ID高亮本人，跨分页前后定位。
**Architecture:** 复用时间线只读权限和筛选SQL，增加focus_id／latest和导航元数据；有界前后文窗口、前向／后向游标；React导航状态和sticky工具条。
**Tech Stack:** SQLite/FastAPI，React/TypeScript，现有主题和动效。
**Spec:** ../specs/2026-11-15-contact-speech-navigation-design.md

### Task 1: 有界定位与导航接口
- [x] 写失败测试：跨页本人计数／前后ID、同名不算、来源和搜索作用域、非法目标、上下文保留、首尾边界。
- [x] 在api/messages.py复用过滤条件实现focus_id及focus_latest，响应speech导航；保持原有游标。Expected:目标前后文有界且账号隔离，pytest通过。
### Task 2: 原文高亮与导航
- [x] 浏览器失败测试后实现本人高亮、当前条强调、吸顶导航、加载／空状态和定位滚动；同一客户页签保留时间线挂载。
- [x] 定位跨页不要求全量加载；分页提供更早和更晚上下文。Expected:键盘按钮、减少动效、搜索／来源及既有原文回归通过。
### Task 3: 验收与交付
- [x] 完整Python，相关浏览器，单元及Node24.14.1构建；一次独立只读审查，重要问题RED→GREEN修复；更新STATUS和报告，提交并非强制推main。

完成：Python400、前端29单元／35浏览器、Node24.14.1构建通过。一次最终独立审查后的修复及延期项见[验收报告](../verification/speech-navigation-report.md)。
