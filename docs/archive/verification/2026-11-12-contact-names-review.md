# 联系人来源与名称链路代码审查

> 历史归档：保留当时方案、命令和验证结果，不代表当前实现。当前入口见[实施状态](../../STATUS.md)。

日期：2026-11-12（北京时间）。审查本项目main／137f246（上一基线78955d3）及第三方pandorafuture/wx-cli固定提交7bed9e767a55d86ac2b9142a49ca078f95623c8b。使用Superpowers requesting-code-review，由单个独立代理只读审查；主代理核对关键源码并用内存数据库复现。未读取用户Mac真实库、未调用模型、未修改wx-cli或本项目运行时代码。

## 结论与当前实机证据

**结论：With fixes。上一轮XML隔离有效，但不能据此宣布名称准确性或错误发送人问题已解决。当前仍位于M1任务5修复，M1任务6尚未开始。**

用户已pull最新代码并运行页面，反馈大量缺名／微信搜不到；随后明确截图中只有一位可在微信搜索到，其他示例搜不到。本报告不保存截图中的真实姓名或wxid。尚无对应源记录、好友关系状态、源端模式／刷新时间、schema4健康或最新诊断回传，不能逐行判断是历史名称、非好友、缓存滞后还是错误归属。

检查确认contacts字段映射为user_name／remark／nick_name，没有发现Python或React把正确名称再次转码；数字、短英文及含emoji的名称可正常保留。因此既不能把所有数字昵称认作乱码，也不能仅凭这些字符串证明它们是当前好友。

## 已确认发现

### 范围说明：全部归档人物与当前微信好友不同

上游[contacts.rs](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-db/src/contacts.rs#L47)查询整个contact表，没有当前好友状态筛选；Contact模型不暴露可验证的好友关系状态。本项目[source/adapter.py](../../../src/wechat_agent/source/adapter.py#L110)读取联系人／会话，归档层还通过私聊成员与群发言人建立人物；此次metadata未出现的历史人物也不会被删除。

因此现有列表是“归档来源中出现的人物集合”，不是“当前微信可搜索好友集合”。历史人物和非好友可能在里面，但不能凭搜索不到就确定已删除好友。show_hidden=1只绕过wx-cli自身的visibility规则，不是一个经核实的“微信已删除好友开关”。

修复方向：明确人物来自联系人资料、私聊、群发言或历史归档，并保存最后观察时间。若要提供“当前好友”筛选，先从实际数据库核实关系字段含义并由源端返回关系状态；无法确认时为unknown。不能猜好友、删除历史人物或重建业务白名单。

### Important 1：错误正文前缀仍可生成active联系人

上游[decode.rs:234](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-db/src/decode.rs#L234)对群正文无条件按首个`:\n`切分发送人。XML会被本项目隔离，但`https:\nexample.com`可被拆成sender=https。该字符串通过[identities.py](../../../src/wechat_agent/identities.py#L6)的结构性校验，随后[source/repository.py](../../../src/wechat_agent/source/repository.py#L43)可以建立active人物。

最小验证：依据上游拆分函数得到https，下游内存回放确认其可入库，且不产生身份异常缺口。这证明仍有错误路径，不证明截图中的某个具体wxid就是这样生成的。

修复方向：优先修改wx-cli，保留原始发送人fallback、候选前缀和归属依据；只有来源证据支持时才剥离前缀、替换发送人。未知／冲突保留完整正文和明确缺口。不要把本项目改成只接收wxid_，因为旧ID和企业微信openim仍合法。旧数据只按证据重核，不能按短名称批量隔离。

### Important 2：已有名称证据被丢弃，群成员名称尚无HTTP入口

上游[model.rs:419](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-db/src/model.rs#L419)的Session有last_msg_sender及last_sender_display_name，sessions查询直接读取这些字段；本项目[adapter.py](../../../src/wechat_agent/source/adapter.py#L156)只将会话display_name写入title，未保存上述与具体人物关联的名称。_person为无好友卡人物只插入空名称。

内存最小回放确认：contacts无某人物，但session有对应last_msg_sender和last_sender_display_name时，该人物仍显示“名称缺失”。这些字段只能补充部分已观察人物，不能代表完整群成员目录。

尤其不能直接把sessions.display_name回填nickname：上游[schema.rs:65](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-cli/src/schema.rs#L65)使用display_with_id，可能已经拼接名称和编号，或回退到alias／纯编号。

上游DB层已有ChatRoom及members(user_name,display_name)，但固定版本[HTTP路由](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-cli/src/cmd/serve/routes.rs#L14)没有群成员接口。不能声称现成/chatrooms路由可用。

修复方向：wx-cli新增明确的只读结构化成员查询，返回稳定人物ID、名称作用域和读取状态。本项目保存名称候选、来源、所属会话及观察时间；优先可用备注／全局昵称，再按来源规则展示可确认候选。群名片是群内名称，不能冒充全局微信昵称；多个群名称冲突必须可辨认。复制“微信名称”也不能复制拼接的会话标题。

### Important 3：上游静默读取失败与真实空值无法区分，下游可能清空旧名称

上游[contacts.rs:129](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-db/src/contacts.rs#L129)用row.get(String).unwrap_or_default()读取remark／nick_name，字段类型或UTF-8错误会变空串；列表也用filter_map(r.ok())吞掉行错误，而stats.skipped仍为0。

本项目将空串转None，再在[archive_metadata](../../../src/wechat_agent/source/repository.py#L65)无条件覆盖原备注／昵称。内存复现确认：先保存有名人物，再传同一ID双None元数据，旧名称被清空。**清空路径确定；用户真实库是否存在BLOB／编码异常，当前尚未证实。**

修复方向：源端区分known／empty／unreadable，提供不含原始值的类型／解码失败计数；归档保存最后成功状态和时间。真实清空应能更新，读取失败则不能冒充空值覆盖。不能用COALESCE永久保留旧备注，也不能盲猜字节编码来“修复”名字。

### Important 4：刷新状态和诊断不足以定位问题层

当前names_unavailable只计缺名，不能区分源端空名、字段读取失败、被质量规则拒绝、仅消息观察人物或尚未重新取metadata。--latest读取既有任务及当前全局计数，不触发metadata刷新，也不证明源端缓存已更新。

上游[serve/mod.rs](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-cli/src/cmd/serve/mod.rs#L84)有SQLCipher直读和PersistentCache两条路径。缓存模式可由会话事件触发重新解密／重开连接，HTTP GET不强制刷新。名称resolver在启动构建，[state.rs](https://github.com/pandorafuture/wx-cli/blob/7bed9e767a55d86ac2b9142a49ca078f95623c8b/crates/wx-cli/src/cmd/serve/state.rs#L40)明确其之后只读；重开contact连接并不重建resolver，派生的会话／发送人display_name可以滞后。/contacts自身直接查DB，不使用这个resolver。

修复方向：源端报告读取模式、联系人数据刷新时间／代次和名称resolver代次，并在刷新后原子替换名称缓存。本项目增加只读分层诊断，分别比较来源联系人与归档人物数量、名称可用／空／读取失败／被拒、仅消息观察及最后成功metadata时间；报告只含计数、技术枚举及版本，不输出姓名、正文或原始ID。

### Minor：来源标题展示不一致

人物显示经过choose_name质量检查，来源会话title直接展示，可能包含拼接编号或损坏名称。应作为名称来源规则的同一批改动处理；这本身不能解释人物在微信里搜索不到。

## 修复实施顺序与验收

以下保存审查时确定的实施方案；后续交付状态见文末和STATUS，不将审查结论当作真实Mac验收。用户已授权必要时改进wx-cli，修改在云端完成，Mac只安装／运行和验证。

| 顺序 | 改动 | 必须验证 |
| --- | --- | --- |
| R1 来源证据 | 明确source模式／版本、metadata与resolver代次、名字读取状态；补只读分层诊断 | 诊断不改库／不建任务／不读取消息正文；账号不匹配停止，部分数据失败不报完整 |
| R2 wx-cli来源修复 | 发送人前缀保真与归属依据；名称读取失败显式化；刷新resolver；暴露结构化群成员能力 | XML、URL／正文冒号换行、空前缀、旧ID／openim、系统事件；真实清空与读取失败分开；分页／账号／快照一致 |
| R3 本项目名称归档 | 新增带来源和会话作用域的名称候选、刷新状态；只消费核实过的接口 | 好友名、无好友卡群发言人、多群不同名、改名／清空、损坏字段；不覆盖人工身份、消息及旧证据 |
| R4 旧数据重核与展示 | 优先只刷新元数据，补名／重核归属有明确操作和范围；来源人物与好友关系分别展示 | 幂等、跨账号隔离、取消／中断；无证据不合并／不删人物／不改旧消息作者；复制名称与显示来源一致 |

本轮另核对上游v0.*标签，最高仍为v0.7.4，未据未核验的新版本假定问题已修复。补丁交付固定上游基线和自维护补丁版本；接入前更新目前adapter._health的0.7.4等值限制，按已核验协议和能力识别补丁，不关闭版本校验或把自维护版冒充上游原版。不能假设任意新版wx-cli兼容。

R1—R4闭合后再继续M1任务6。不要让用户通过清库、批量删联系人或反复全量重抓消息来试错；先用分层证据定位具体人物来自何处、哪个名称字段缺失及是否过期，再做有范围的修复。

## 当前验证与待确认项

- 这次审查没有Critical项，列出4项Important、1项Minor，并单独说明人物范围差异；结论为需要修复。独立审查的发现已由主代理核对关键源码并复现名称清空及合法外形错误发送人入库。
- 不承诺某个昵称一定是好友、旧名或错误归属；没有当前好友状态证据，微信搜索不到不足以证明已删除。
- 尚未读取真实contact.db列类型、服务模式、缓存代次，也未取得完整群成员名称覆盖率；这些是R1需要补齐的证据。
- 本次没有新增运行时代码或声称修好名称；现有230／16／13基线回归不覆盖这些新增失败场景。后续实施须先加入失败回放，再修改来源与归档逻辑。


## R1—R4实施与最终审查结果

本轮已交付只读`contacts.check`、固定wx-cli补丁及安装器、schema5名称来源／读取状态、顶部“刷新联系人”和独立任务进度。原文、人物ID与人工身份均保留；不以昵称合并人物，不声称归档清单是当前好友。

最终进行一次独立只读整体审查，确认4项重要边界缺陷并在同一修复轮次处理：

| 发现 | 修复和验证 |
| --- | --- |
| SQLCipher外部写入可在同一服务代次改变元数据 | 联系人／会话连接的data_version前后核验；变化使旧代次失效，成功刷新后才发布新代次；HTTP回归及实际release外部写入复验通过 |
| 初次health后和消息阶段代次保护遗漏 | 首次正常health固定代次，跨联系人／会话／消息保持；只在显式刷新后绑定新代次；3项失败回归转绿 |
| 已确认外层前缀剥离后再次误拆正文 | 保存原始未匹配前缀证据，enrich不重解析正文；真实decode→enrich嵌套引用失败回归转绿 |
| 群名读取失败清掉旧标题且无缺口 | 群标题状态入库，失败保留／提示、明确空值可清除；来源适配与归档一体回归通过 |

最终Python276、前端20项单元和14项浏览器通过，生产构建通过。Rust完整工作区800通过、11忽略、3个server_manager_cli失败；三个失败均已在干净同commit上游复现，为云端PID1未回收退出进程，未改测试规避。固定补丁release及干净安装／重复完整性校验通过；合成加密来源→解包wheel→生产API的真实HTTP确认刷新前后代次一致、外部写入使旧代次失效、再次刷新补名，消息与分析计数均为0。

上述证据只覆盖云端代码和合成回放；Mac安装、实际好友覆盖、真实名称与来源生命周期待回传。未观察群成员单独保存为目录证据，不自动扩大联系人列表；无证据的旧消息作者不批量改写。[Mac验证步骤](../../MAC_SETUP.md#update-repository)。
