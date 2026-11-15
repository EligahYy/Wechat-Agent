# 历史归档索引

更新：2026-11-15。只归档本仓库重建后已完成或被替代的资料；重建前实现不恢复。归档不参与正式应用，不是另一套有效产品方案。当前入口见[文档索引](../README.md)和[STATUS](../STATUS.md)。

| 目录 | 内容与归档原因 |
| --- | --- |
| [ui-prototype](ui-prototype/DESIGN.md) | 被正式React页面替代的静态演示、样例资产及原型检查脚本；保留内部资源和许可证，不作为默认入口 |
| [plans](plans/2026-11-11-m1-source-contacts.md) | 完成的M0／M1、联系人修复、业务范围、发言导航、日历计划；M2主计划仍活跃 |
| [specs](specs/2026-11-15-contact-speech-navigation-design.md) | 被按日日历替代的全历史发言导航设计 |
| [verification](verification/m1-report.md) | M0／M1、早期M2检查点、联系人审查、旧Mac步骤及逐阶段回传；保留当时测试事实 |
| [history](history/status-before-consolidation-2026-11-15.md) | 收敛前累计状态／修复流水，便于追溯，不与STATUS并行维护 |

最新业务范围设计、日历设计、M2任务3和日历验收、能力证据及Mac回传仍在有效目录。源码、测试、10份SQL迁移、依赖锁、wx-cli补丁和安装脚本未作为“无引用文件”归档。

原型若需查看，仅静态启动：`python3 -m http.server 8765 --directory docs/archive/ui-prototype --bind 127.0.0.1`。其旧检查脚本和本地artifacts是当时工具／产物，不作为当前CI或真实功能门槛；未随仓库保存的证据路径只记文本，不提供失效链接。

逐文件迁移见[归档清单](INVENTORY.md)。

本轮维护计划：[仓库收敛](plans/2026-11-15-repository-consolidation.md)。
