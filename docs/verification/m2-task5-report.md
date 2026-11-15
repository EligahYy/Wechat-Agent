# M2任务5：人工纠正、补充及单号API

2026-11-15（北京时间），基线e807eec。新增schema013；云端API完成，界面消费属于任务6，真实模型／worker接线属于任务7。

## 交付

- GET `/api/contacts/{id}/profile?account_id=...`：返回模型原值、人工覆盖、有效展示值、来源、单号、版本、完整性和待更新状态；模型值与人工值有差异时保留两者及模型来源。
- PATCH `/api/contacts/{id}/manual`：body含account_id、expected_version、fields、notes。fields仅接受固定的goods／logistics字段，以及communication.summary／tags／last_business_at；null解除覆盖，恢复显示模型值。notes仅goods／logistics两组，空／null清除。标签限制枚举及互斥规则，业务时间要求带时区ISO。
- PATCH `/api/shipments/{id}/numbers`：body明确account_id、contact_id、expected_version、numbers；去重保序、去掉首尾空格，最多100个且每个非空／不超过256字。空数组清除。不改变批次stage。
- schema13：profile_manual与profile_manual_events保存人工值及前后变更；shipments增加version与numbers_origin。人工编辑在同一事务内增加heads.manual_version，旧分析结果因此拒绝发布；模型改变批次stage／payload时也增加shipment version，防止旧单号编辑覆盖新结果。
- 快照冻结人工fields／notes，ContextReader返回副本；WorkflowV1消费冻结manual_constraints及已有批次单号／来源。人工内容不生成聊天引用，模型原始记录和发布历史保持。

## 版本与显示合同

人工编辑期待manual_version；单号编辑期待批次version。冲突409不写入，无变化不增加版本／事件。单号保存后，界面应重新GET profile取得当前manual_version和合成结果。未生成模型档案也可保存人工资料，model=null，不补示例模型结果。

有效Fact中的origin=manual、sources=[]标明人工；model保持原值和原来源。communication.tags／last_business_at用field_origins区分来源。补充资料存manual.notes。shipments顶层numbers／numbers_origin是当前单号，details保留模型批次数据，不应把其中旧numbers作为当前人工单号。

只允许active非本人联系人读取；非商家可看历史资料但不能编辑。写入时再核对账号、客户及商家身份，人工资料不会解除业务范围排除或触发模型调用。客户端必须携带显式账号／客户上下文，和主计划的简略示例相比增加这两项校验。

GET pending同时比较发布时状态、人工版本和当前模型取材范围内消息ID／revision。发布后新增、历史修订或新会话不会继续显示已更新；模型取材范围保持独立于原文UI的按日筛选。

## 验收

完整Python476通过，其中新增30项回归；前端单元31、浏览器49及Node24.14.1构建通过。覆盖字段／备注清除、互斥标签、非法日期／号码、409、跨账号／客户404、隔离身份、provider只读、重开连接持久化、事件写入失败整批回滚、人工覆盖与单号跨模型重跑保留、冻结约束进入真实gateway回放。

一次只读独立审查发现“发布后新增／修订消息未让GET pending变化”，新增三种用例观察红灯后修复，最终完整Python回归通过；无保留审查问题。

## 取舍与后续

- 只接受固定字段路径和两组补充资料，不引入自定义字段系统；后续界面需按本API发送字段，null与省略含义不同。
- 单号额外要求客户上下文，避免只凭同账号批次ID修改另一客户；任务6需携带当前客户ID。
- 本轮没有页面编辑器和生产真实模型注册。下一项Task6接这些API，之后Task7验证真实模型与完整闭环。

Mac更新、构建并重启后health应为schema13，保留原库及wx-cli；真实语义准确率仍须后续实机验收。
