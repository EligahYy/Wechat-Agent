# M2任务3扩展：业务活跃联系人 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans 串行执行；不派发实现代理。步骤使用复选框，云端检查后推main，Mac仅验证。

**Goal:** 在本轮任务3完成业务范围、全量管理入口及有证据的群需求识别，人工移出绝不被自动恢复。

**Architecture:** 全量归档保持稳定ID；范围层结合人工覆盖、真实个人活动和版本化需求信号；设置承担完整联系人管理。分类与档案生成使用不同用途，复用有限模型网关。

**Tech Stack:** Python3.12／FastAPI／SQLite、React／TypeScript、Node24.14.1及现有测试工具。

**Spec:** [已确认范围与设计](../specs/2026-11-13-business-contacts-design.md)。属于[主计划Task3](2026-11-11-m2-customer-profile.md)，不是新增独立产品阶段。

## Global Constraints

- 近90天；已确认身份、人工加入保留。人工移出最高优先，必须人工重新加入。
- 不删归档、不按姓名合并人物、不把群活跃当个人活跃、不自动确认商家。
- 仅已确认商家生成档案；未知身份的群需求分类只产出线索证据。
- 缺模型／覆盖／识别结果不得当作无需求；保守临时候选需要明确理由。
- 原Task3A/B/C及身份菜单改造继续交付；只有本扩展及原门槛通过，才标整个Task3完成。
- 新迁移010及后续，禁止修改001—009。模型真实配置、容量和Mac质量验收独立记录。

## Review Focus

1. 人工移出与迟到分类／新同步／改身份竞争，不能自动回来：Task1、3、5。
2. 群热而本人未发言、裸昵称提及或同名不同ID，不能误纳或合并：Task1、2。
3. 没直接交流的真实潜客不能被规则漏掉；分类未跑不作负面结论：Task3。
4. 搜索、分页、角色数量、全量／业务人数不同范围不可混算：Task2、4。
5. 范围缩小不能缩小发现新潜客所需的来源读取：Task5。

## Task 1：范围数据、人工覆盖与活动证据

**Files:** Create `src/wechat_agent/contacts/{scope,activity}.py`, `storage/migrations/010_business_scope.sql`, `tests/test_business_scope.py`；Modify `storage/db.py`, `source/repository.py`。后端短路径均相对src/wechat_agent。

**Interfaces:** `set_scope(conn, keys:list[ContactKey], included:bool, expected_versions:dict[str,int]) -> ScopeUpdateResult`；`classify_scope(conn,key,now) -> ScopeDecision(included:bool,reasons:list[str],provisional:bool,version:int)`。人工覆盖为include／exclude／无记录；禁止用删除记录表示重新加入。活动物化表按账号、人物、证据类型保存来源及精确UTC时间，带归档代次。

- [ ] Step1：写失败测试。人工exclude＋merchant＋新群需求仍included=False；include超过90天仍True；无人工记录按规则；群最新消息与其他作者不提升本人的last_activity；未核实关系不冒充私聊；90天边界按UTC比较。
- [ ] Step2：运行`.venv/bin/python -m pytest tests/test_business_scope.py -q`。Expected：新模块／表不存在而失败。
- [ ] Step3：实现010迁移和范围服务；归档按受影响人物／会话更新证据，历史首次回填带代次，更新／修订撤销旧证据。私聊可包含我方主动联系；群互动只用可核验引用／结构化ID。已知身份不覆盖人工exclude。批量乐观锁、原子数据库错误回滚、逐人版本冲突。
- [ ] Step4：上述测试绿灯；加测重启、跨账号、系统消息、同名不同编号、修订后失效、批量部分冲突。以现有约2420人／2万消息回放检查性能，不逐人扫描全部消息。
- [ ] Step5：检查后提交`feat: persist business scope and manual precedence`。

## Task 2：范围查询和管理API

**Files:** Modify `contacts/service.py`, `api/contacts.py`；Create `tests/test_business_scope_api.py`。

**Interfaces:** GET `/api/contacts`新增`scope=all|business`，默认all保持旧调用兼容；响应新增scope与scope_totals，total／role_counts始终属于当前scope＋q。每行增加business_scope。PATCH `/api/contacts/scope`接收account_id、included、items[{key,expected_version}]，返回updated／failed，部分冲突409沿用身份接口语义。

- [ ] Step1：失败测试验证全量保留、业务子集、同一快照分页／角色计数、人工移出后仍可在all检索；跨账号批次写入前拒绝。
- [ ] Step2：运行`.venv/bin/python -m pytest tests/test_business_scope_api.py -q`。Expected：参数／路由缺失而失败。
- [ ] Step3：接入Task1服务；全局归档质量统计标明账号全量范围，不冒充当前业务列表质量。未形成业务回填代次时显式返回pending状态，不用0假装没人。
- [ ] Step4：完整测试通过；核对百分号／中文姓名、角色筛选和跨页选择范围，沿用现有姓名搜索语义。
- [ ] Step5：提交`feat: expose scoped business contact management`。

## Task 3：群内需求识别及覆盖

**Files:** Create `discovery/{contracts,context,classifier,repository}.py`, `model/prompts/business-discovery-v1.md`, `tests/test_business_discovery.py`；Modify `context/contracts.py`, `model/gateway.py`及需要的新增迁移。

**Interfaces:** `build_discovery_snapshot(conn,key,cutoff,versions) -> DiscoverySnapshot`；与商家快照分离用途，保留实际说话人和版本化材料。`DiscoveryStrategy.classify(snapshot,cancellation) -> DiscoveryResult(contact_id,intent,sources,gaps)`；intent限定request／advertisement／forwarded／other／uncertain。`publish_discovery(conn,snapshot,result,cancellation) -> DiscoveryPublishResult`再次核对范围、作者、引用修订及人工覆盖。

- [ ] Step1：失败回放：未私聊过的群内本人询价进入业务；服务商揽客和转发不能冒认自有需求；引用其他人的货量、同名发送人、错账号／修订拒绝；人工移出期间迟到结果不可加回。
- [ ] Step2：运行`.venv/bin/python -m pytest tests/test_business_discovery.py -q`。Expected：分类用途模块缺失而失败。
- [ ] Step3：只识别90天实际发言及必要前后文，按有编号单元批处理，不逐消息调用；共享网关3次调用／6次单元限额与取消屏障。新增明确discovery输入用途，不能放宽商家build_snapshot／publisher的merchant限制。分类仅引用既有作者ID，不创造联系人、不改变role。缺模型、缺覆盖或不确定时保守保留近期实际群发言临时候选并记录原因；明确负面结果仅在对应窗口覆盖充分且材料未变化时生效。
- [ ] Step4：上述测试和错误JSON／超窗／停止／重复处理／覆盖代次回归通过；能力未验证不得实调。人工标注夹具报告误纳、漏纳和不确定，不以JSON正确代替语义验收。
- [ ] Step5：提交`feat: identify evidence-backed group demand candidates`。

## Task 4：工作台业务列表与设置管理

**Files:** Create `frontend/src/features/settings/ContactManager.tsx`, `frontend/e2e/business-contacts.spec.ts`；Modify `ContactsPage.tsx`, `SettingsPage.tsx`, `api/{client,types}.ts`及测试服务器夹具。

**Interfaces:** 工作台请求scope=business，设置“联系人管理”请求scope=all；消费Task2批量结果，版本冲突保留失败项。业务范围与四种身份分开。

- [ ] Step1：写失败E2E：工作台页签改“业务活跃联系人”；设置可打开全量管理、姓名检索、跨页选择、单个／批量加入移出；完成后两个列表人数正确，资料不删除；移出者再次同步不回来。
- [ ] Step2：运行`npm --prefix frontend run test:e2e -- business-contacts.spec.ts`。Expected：入口／范围操作缺失而失败。
- [ ] Step3：复用表格、菜单、输入与动效，不复制第二套身份规则。管理入口在设置，非第三个主导航。显示简短纳入理由及识别覆盖pending提示；管理中可按在范围内／未在范围内筛选。主工作台隐藏全量归档噪声，商家档案默认以业务范围内merchant为目标，历史档案仍可从全量详情打开。
- [ ] Step4：E2E、unit、Node24.14.1 build通过；验证键盘、深浅色、空列表、409与选择栏平滑变化。现有20/8分页夹具按真实业务证据调整，不把所有合成人物强制标已确认以绕过新规则。
- [ ] Step5：提交`feat: manage active business contacts from workspace and settings`。

## Task 5：同步整合、消费者门槛与交付

**Files:** Modify `operations/worker.py`, `tests/test_sync_operations.py`、`tests/test_business_scope_flow.py`, `docs/{PRODUCT_DESIGN,INTERACTION_DESIGN,STATUS,MAC_SETUP}.md`, `docs/verification/m2-profile-review.md`；同步M2 Task4／7消费者条目。

**Interfaces:** 普通同步仍读取发现潜客所需会话；同步后活动更新→可执行的需求识别→范围刷新→仅业务范围内merchant分析规划。`business_scope_allows_analysis(conn,key)`在领取／后续发布前复核人工exclude，不靠UI隐藏决定执行权限。

- [ ] Step1：失败集成测试：全局不分析已移出商家；目标移出后单客户操作明确提示重新加入；仍读取必要群原文；新群需求可纳入候选但不自动生成商家档案；停止／失败保留覆盖未完成；不调用模型时不得报识别完成。
- [ ] Step2：运行`.venv/bin/python -m pytest tests/test_business_scope_flow.py -q`。Expected：worker尚未接范围而失败。
- [ ] Step3：接入范围与识别阶段；用户手动加入／移出不清除身份、档案和原文。M2 Task4／7发布端必须消费本门槛，当前未实现的发布仍明确capability_not_ready，不冒充闭环。处理旧库回填及新入群数据，不因隐藏联系人停止发现新需求。
- [ ] Step4：全部Python、前端unit／E2E／build、wheel和生产HTTP检查通过；一次最终独立只读审查，重要问题失败回归后修复；Mac核验90天、手动覆盖与真实群需求样本，未实测标待验证。
- [ ] Step5：更新状态、验证报告、Mac步骤并提交`feat: integrate business scope into source and analysis planning`，非强制推main。

## Task3扩展退出条件

- [ ] 原3A/B/C、模型配置／主动检查与按钮附近身份菜单完成回归。
- [ ] 本文Tasks1—5完成云端实现；身份、范围、原始归档相互独立，旧资料完整。
- [ ] 人工移出不被任何自动流程恢复；自动期限及公开群需求纳入有可定位依据。
- [ ] 未配置模型／缺覆盖仍不会静默漏掉近期群发言潜客；临时候选与确定业务理由区别展示。
- [ ] 整项Task3仅在上述门槛全过后打勾；真实模型识别质量与Mac验收独立保留。
