# 联系人来源与名称修复 Implementation Plan

> 历史归档：保留当时方案、命令和验证结果，不代表当前实现。当前入口见[实施状态](../../STATUS.md)。

> **For agentic workers:** Use superpowers:executing-plans，按R1—R4串行执行，采用TDD；最后进行一次独立只读审查。

**Goal:** 修复错误发送人、名称丢失和来源范围不透明，提供只刷新联系人元数据的入口与可复制验证工具。

**Architecture:** 固定wx-cli 7bed9e767a55d86ac2b9142a49ca078f95623c8b，以可识别补丁交付；本项目通过明确能力契约读取带状态的名称及群成员证据。名称候选按人物／会话作用域落库，元数据更新独立于消息同步；旧原文和人工身份不删除。

**Tech Stack:** Python3.12／FastAPI／SQLite、React／TypeScript、Rust及固定wx-cli Cargo.lock。

**Spec:** [审查与验收](../verification/2026-11-12-contact-names-review.md)、[产品方案](../../PRODUCT_DESIGN.md)、[内部契约](../../superpowers/plans/CONTRACTS.md)。

## Global Constraints

- 云端串行开发、检查后推main；Mac仅安装／运行／验证，不编写修复代码。
- 不清库、按昵称合并人、猜好友关系或静默改旧消息作者；群名片保留作用域。
- 真实空值与unreadable分开；来源不确定时保留证据和缺口，不伪装补名成功。
- 诊断仅GET源元数据和只读应用库，不建操作、不读消息正文；只导出计数与技术状态。
- 新来源补丁须显式版本／能力识别，原版0.7.4仅用于有限诊断，不继续信任其无来源依据的群消息归属。
- Node24.14.1／npm11.11.0为前端验证基线；不修改已发布001—004迁移。

## Review Focus

1. 不同账号／worker／metadata代次混读，必须中止并保留先前归档。
2. 源端读取失败不能变成用户删除备注；真实清空应更新而不是COALESCE保留。
3. URL、XML、空前缀与旧ID／openim；信任有来源依据的发送人，完整正文不丢失。
4. 无好友卡群成员、多群名片、历史人物；显示来源与复制名称一致，不假称当前好友。
5. 元数据刷新中断、重复和部分失败，不触发聊天／模型，不误改身份或旧消息作者。

### Task 1: R1 只读来源诊断

**Files:** Create contacts/check.py、tests/test_contact_diagnostics.py；Modify source契约／adapter的技术信息输出。

- [x] 写失败测试：无个人字段、无消息请求／写操作；固定账号与协议失败；来源与归档人物差异、缺名／坏名分类；输出不能覆盖数据库／配置。
- [x] 运行观察失败，再实现`python -m wechat_agent.contacts.check --account ... --output ...`；原版不伪造解码错误／刷新时间，明确unknown或需补丁。
- [x] 验证并提交R1。

### Task 2: R2 wx-cli固定补丁

**Files:** Create patches/wx-cli/{manifest.json,*.patch,README.md}、scripts/install-wx-cli.sh；在.local固定上游源码开发并导出patch。

- [x] Rust失败回放覆盖URL／XML不替换真实fallback，匹配可信前缀才剥离，缺身份保留正文与空归属。
- [x] 来源名称读取区分known／empty／unreadable并正确统计行错误；只读结构化群成员HTTP及元数据能力／刷新状态。
- [x] resolver随成功数据库刷新替换；显式元数据刷新能够刷新缓存、返回真实成功／失败代次。
- [x] Rust相关测试及完整可执行测试、补丁可从干净固定commit应用；安装器校验基线／patch，不覆盖原工具，运行合成数据HTTP验证后提交R2。

### Task 3: R3 名称候选及刷新状态归档

**Files:** Create storage/migrations/005_contact_names.sql、source/names.py、tests/test_contact_names.py；Modify source契约／adapter／repository、contacts/service、db版本和诊断。

- [x] 失败测试覆盖状态明确清空／失败保留、已标识session发送人名、群作用域与冲突、真实备注优先、旧库升级／回滚、跨账号。
- [x] `NameEvidence`保存origin／conversation／value／state／observed_at；成功元数据记录来源版本与代次、最后观察时间。只消费核验能力，原版保留显式未验证状态。
- [x] 全部读取名称字段统一质量规则；群／会话名不冒充全局昵称，复制微信名称仅用于可确认的全局名称；保留原文／人工身份。
- [x] 验证并提交R3。

### Task 4: R4 独立刷新入口与旧数据回补

**Files:** Modify operations契约／service／worker、sync、api、React页面／types／OperationDetails；Create刷新操作及浏览器回归。

- [x] 失败测试：refresh_contacts仅刷新来源元数据／名称，0消息请求／0模型请求；重复／停止／部分失败可追踪；旧人物只补名不删人、不改作者。
- [x] 工作台顶部提供刷新联系人入口，进度与历史用真实操作；列表标明群／会话／历史名称来源和人物范围，缺名称原因可判断。
- [x] Python全套、前端unit／build／浏览器、wheel及合成来源真实HTTP验证；一次独立只读审查并修复重要发现。
- [x] 更新STATUS、源协议、Mac安装和验证说明，提交推main；未有Mac证据不声称已恢复真实姓名。
