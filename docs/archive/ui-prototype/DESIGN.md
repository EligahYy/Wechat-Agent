# 桌面交互原型

> 归档原型：仅保留历史演示和许可来源，不作为当前产品规则或功能验收。正式入口见[仓库说明](../../../README.md)。

产品：半托管欧区备货用户助手。更新：2026-11-11（北京时间）。

最终产品与交互规则已经收敛到 [产品方案](../../PRODUCT_DESIGN.md) 和 [交互方案](../../INTERACTION_DESIGN.md)，本文件不再累积中间修订记录。

## 原型范围

工作台与设置两页；商家／全部联系人；批量身份；无侧栏的客户详情；资料来源、编辑、人工补充、备货单号、沟通原文；同步入口与演示进度；深浅色和减少动态效果。

人物、对话、模型运行及同步均为示例。真实服务、数据库与调度尚未接入。原型结果不作为模型业务质量验收。

## 设计来源

- [Taste Skill](https://github.com/Leonxlnx/taste-skill)，本机安装版本 2.5.1。
- [Apple DESIGN.md](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/apple/DESIGN.md)。

采用系统字体、统一组件、克制玻璃与连续动效。用户要求的是实际工作台，官网 hero、整屏营销段落、插图与滚动场景不适用。具体尺寸、颜色和控件规则以正式交互方案为准。

## 查看与导出

```bash
python3 -m http.server 8765 --directory ui-prototype
python3 ui-prototype/build-preview.py
```

浏览 http://localhost:8765 ，或打开 `preview.html`。导出包含本地样式、脚本和示例附件，无外部资源依赖。

原型浏览器检查使用本环境的 Playwright 与 Chromium；各 `check-*.cjs` 只验证示例交互，需运行本地 8765 预览服务。检查范围见 [REVIEW.md](REVIEW.md)。
