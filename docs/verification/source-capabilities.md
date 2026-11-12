# 第三方 wx-cli 来源核验

更新：2026-11-12（北京时间）。Mac已验证事件契约修复：来源有限采样passed，8条全部有效，包含4条system／revoke事件，其中2条无人物发送人；没有异常或gap，history_complete=false。

## 来源身份

使用 [pandorafuture/wx-cli](https://github.com/pandorafuture/wx-cli)，这是第三方开源项目，不是腾讯／微信官方接口。这里的版本说明指第三方项目自身的上游发布，不代表微信官方支持。

- 用户已有服务：本机 `127.0.0.1:9100`，用户日志显示 ready、healthy。
- 用户报告 CLI 0.7.4，提交短号 7bed9e7。
- 云端读取 v0.7.4 标签，确认为 `7bed9e767a55d86ac2b9142a49ca078f95623c8b`。
- 只查阅旧项目的来源名称元信息，随后重新核对该上游版本源码；未恢复旧业务实现或产品规则。

推荐继续使用该本机 HTTP 服务，适合当前桌面资料应用。应用读取使用经过核对的GET接口，独立元数据刷新显式调用项目补丁的POST接口，通过独立适配器隔离来源升级，不自行维护微信数据库解密或在每次读取时拼 shell 命令。此选择不承诺源端覆盖完整、所有附件一定可取或模型归纳一定正确。

## 原版0.7.4已核对的协议（历史基线）

源码依据：[路由](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-cli/src/cmd/serve/routes.rs)、[处理器](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-cli/src/cmd/serve/handlers.rs)、[消息字段](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-db/src/model.rs)、[分页结构](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-cli/src/output.rs)、[媒体实现](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-cli/src/cmd/serve/media.rs)。

| 范围       | 路径与字段                                                                                    | 实现约定                                                                                                                     |
| ---------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 健康及账号 | GET `/api/v1/health`；ready、worker_id、cli_version、current_account.wxid                     | 先核对 ready 和明确绑定的 canonical wxid；HTTP 200 本身不足以通过                                                            |
| 联系人     | GET `/api/v1/contacts`；user_name、remark、nick_name                                          | 稳定 ID 归一，名称只作显示；`@chatroom` 为会话，不建成人物                                                                   |
| 会话       | GET `/api/v1/sessions`；username、display_name                                                | 根据源 ID 识别私信和群；不按会话标题合并人物                                                                                 |
| 消息       | GET `/api/v1/messages?contact=...`；server_id、talker、sender、create_time、content、sort_seq | 保存实际发送人、完整 content 和引用结构；snippet 不能替代全文                                                                |
| 分页       | items、paging(limit/offset/returned/has_more/total)、stats(skipped/shard_warnings)            | 下一 offset 按源窗口 limit 推进，不能按过滤后 returned；跳行或分片错误必须报缺口                                             |
| 隐藏数据   | `show_hidden=1`                                                                               | 保留源端可读连续上下文，避免旧源端 ignore 配置悄悄隐藏材料；分析范围仍由本应用身份决定                                       |
| 媒体       | GET `/api/v1/media?server_id=...&talker=...`                                                  | 上游支持图片、普通文件及部分音视频；图片质量头 `X-Wechat-Media-Quality: full/thumbnail` 区分原件与缩略图；实际获取／解析另验 |

启动时 `--account` 可接受工具的账号选择值；应用绑定的是 health 返回的 `current_account.wxid`，不能根据目录名后缀自行截断猜测。版本变化先重新验协议。0／缺失 server_id 暂不提供伪造稳定 ID，不以正文哈希去重。

原版0.7.4完整群成员目录没有独立HTTP路由；已发言成员通过 sender 稳定 ID 归一，不能声称已拿到每个未发言成员的完整资料。单独群成员目录是否需要其他来源，在 M1 接入时按真实缺口处理。

## 诊断探测范围

`--check-source` 只读取 health，不读聊天、不调用模型。未绑定账号为 pending；绑定正确后 `scope=connection` 的 passed 仅代表该连接检查通过。

加 `--source-samples` 后，读取最多20个联系人／会话的元信息，分别对一位私信、一组群聊读取至多两页、每页2条消息，再核对账号与 worker 未改变。只报告计数及技术诊断，不向终端输出聊天正文。M0 不自动保存聊天原文，完整可追溯归档由 M1 实现；这项范围缩减已记录，避免诊断报告变成原文导出。

- `messages_sampled`：源端实际返回的条数；`messages_checked`：通过契约校验的条数；`messages_rejected`：未通过的条数。后者只表示校验结果，不是从归档中删除消息。
- `system_events_checked`：通过校验的system／revoke事件数，包含在messages_checked中；`unattributed_events_checked`：其中无人物发送人的事件数，不是丢失的聊天。正常聊天数量可由messages_checked减去system_events_checked得到。
- `message_issues`：每条异常的首个失败原因、私信／群聊类别、分页 offset、页内从0开始的位置、msg_type、sub_type 与上游 direction。最多8条采样异常；不含消息ID、账号ID、姓名、时间和正文。异常类型字段只接受整数或固定枚举，不能借错误值回显原文。
- msg_type=10000为系统消息、10002为撤回事件：上游sender为空字符串时，内部映射为sender_id=None，保留内容、时间与来源；有真实发送人则原样保留。字段缺失或null仍属协议缺口；稳定消息ID和时间校验继续执行。普通聊天缺发送人仍报message_sender_missing并pending；方向不能补身份。
- 某类会话只采到事件时，报source_private_person_messages_unavailable或source_group_person_messages_unavailable，不能用系统事件证明人物消息契约已验证。

上游依据：[发送人关联](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-db/src/messages.rs)、[群聊前缀解析](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-db/src/decode.rs)、[消息方向](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-context/src/contact.rs)。Name2Id关联缺失时 sender 可为空；空 sender 也会被上游标为 incoming，不能反推其属于对方。

所有请求直连 loopback、绕过环境代理、不跟随重定向；若源服务有 token，用本地环境变量引用，不回显 token 或上游错误正文。查询失败不能报“无新消息”；样本成功始终 `history_complete=false`。

## 实机状态

| 项目           | 云端证据                               | 用户 Mac                                                       |
| -------------- | -------------------------------------- | -------------------------------------------------------------- |
| 运行环境与原型 | 7个初始测试通过                        | 用户报告 3.12.13、Darwin arm64、7 passed、原型 GET 200，已验证 |
| wx-cli 服务    | 已核对上游 v0.7.4 协议                 | 应用端 ready、版本及账号绑定已验证                             |
| 联系人与消息   | 合成回放覆盖账号、群聊、分页及匿名事件 | 4页共8条全部通过；4条事件中2条无人物发送人，有限采样passed     |
| 图片和文件     | 已核对源端路由及质量头                 | 原件、缩略图、缺失及解析仍待验证                               |

本文不包含用户真实账号 ID、姓名、聊天正文或本机绝对路径。


## 2026-11-12：联系人名称与覆盖审查补充

有限采样通过不等于联系人姓名或当前好友覆盖通过。固定上游contacts查询整个contact表，不暴露经验证的当前好友状态；本项目又保留会话成员、已观察发送人和历史人物，因此“全部联系人”不是当前微信好友清单。

本次确认：群正文前缀拆分仍可能把URL等当发送人；名称读取错误可被上游吞成空串；会话携带的特定发送人名称未被本项目消费；DB已有群成员解码但HTTP未提供对应路由；缓存模式和启动时名称resolver也可能使派生名称滞后。具体截图记录的实际来源和真实库编码异常尚未证实。

用户已授权必要时改进wx-cli。拟采用固定基线加可识别补丁，先补只读分层诊断，再修来源归属／名称状态与成员能力、本项目名称来源归档及旧数据回补。审查当时未改动wx-cli、未新增成员接口；后续已实施的补丁见下节。完整证据与待实施验收见[独立审查](2026-11-12-contact-names-review.md)，当前阶段见[状态页](../STATUS.md)。


## R1—R4已交付的项目补丁契约

固定基线仍为7bed9e7，应用归档要求`0.7.4+wechat-agent.1`和`wechat-agent-source-v1`。补丁、SHA256及安装器见[patch说明](../../patches/wx-cli/README.md)。原版仅允许有限只读诊断，消息归档显式返回source_patch_required，不能静默信任旧前缀拆分。

- GET identity/contacts提供known／empty／unreadable的原始备注和昵称；GET identity/groups提供成员目录与解码状态。路径均在`/api/v1/`下，分页带generation，要求show_hidden=1并沿用鉴权。
- POST identity/refresh只发起来源缓存／连接／resolver刷新；202不代表完成。应用等待新generation和ready，失败或超时保留缺口。
- health.metadata提供读取模式、服务代次、resolver代次和最近成功刷新时间；联系人与会话连接的SQLite data_version在元数据读取前后和health检查。外部写入使旧代次失效，直到成功刷新；不声称跨所有微信数据库拥有原子快照。应用从首次检查到消息页保持同一代次，变化即中止，已有已完成归档保留。
- 发送人只采用Name2Id依据，原始前缀与其相同才剥离；冲突候选从剥离前保留，不二次解析正文。已知冲突保留两个候选与完整原文，不猜作者。
- schema5保存人物全局名、群／会话名作用域、群目录和刷新状态；群标题同样区分明确清空和读取失败。名称读取失败保留旧值并提示；只有当前可确认的全局微信名称允许复制。
- “刷新联系人”为账号范围持久化操作，只更新元数据，不请求聊天正文、不调用模型，不删除旧人物或修改旧消息作者／人工身份。完整群名单单独保存，不将所有未观察群成员创建为联系人。当前好友关系依旧unknown。

云端Python276、前端20单元／14浏览器和生产构建通过；Rust800通过、11忽略、3个已在原版复现的云端进程回收失败。干净补丁安装、重复校验、合成加密来源与解包wheel的真实HTTP链路通过；Mac补丁及真实姓名准确性仍待[第15节](../MAC_SETUP.md#15-联系人来源与名称修复r1r4)复验。
