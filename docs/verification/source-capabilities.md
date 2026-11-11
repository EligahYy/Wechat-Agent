# 第三方 wx-cli 来源核验

更新：2026-11-11（北京时间）。云端开发已完成来源探测及回放测试；用户 Mac 的真实接口采样仍待运行新工具验证。

## 来源身份

使用 [pandorafuture/wx-cli](https://github.com/pandorafuture/wx-cli)，这是第三方开源项目，不是腾讯／微信官方接口。这里的版本说明指第三方项目自身的上游发布，不代表微信官方支持。

- 用户已有服务：本机 `127.0.0.1:9100`，用户日志显示 ready、healthy。
- 用户报告 CLI 0.7.4，提交短号 7bed9e7。
- 云端读取 v0.7.4 标签，确认为 `7bed9e767a55d86ac2b9142a49ca078f95623c8b`。
- 只查阅旧项目的来源名称元信息，随后重新核对该上游版本源码；未恢复旧业务实现或产品规则。

推荐继续使用该本机 HTTP 服务，适合当前桌面资料应用。应用仅使用经过核对的 GET 接口，通过独立适配器隔离来源升级，不自行维护微信数据库解密或在每次读取时拼 shell 命令。此选择不承诺源端覆盖完整、所有附件一定可取或模型归纳一定正确。

## 已核对的上游协议

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

完整群成员目录没有独立 HTTP 路由；已发言成员通过 sender 稳定 ID 归一，不能声称已拿到每个未发言成员的完整资料。单独群成员目录是否需要其他来源，在 M1 接入时按真实缺口处理。

## 当前探测范围

`--check-source` 只读取 health，不读聊天、不调用模型。未绑定账号为 pending；绑定正确后 `scope=connection` 的 passed 仅代表该连接检查通过。

加 `--source-samples` 后，读取最多20个联系人／会话的元信息，分别对一位私信、一组群聊读取至多两页、每页2条消息，再核对账号与 worker 未改变。只报告计数及字段错误路径，不向终端输出聊天正文。M0 不自动保存聊天原文，完整可追溯归档由 M1 实现；这项范围缩减已记录，避免诊断报告变成原文导出。

所有请求直连 loopback、绕过环境代理、不跟随重定向；若源服务有 token，用本地环境变量引用，不回显 token 或上游错误正文。查询失败不能报“无新消息”；样本成功始终 `history_complete=false`。

## 实机状态

| 项目           | 云端证据                                 | 用户 Mac                                                       |
| -------------- | ---------------------------------------- | -------------------------------------------------------------- |
| 运行环境与原型 | 7个初始测试通过                          | 用户报告 3.12.13、Darwin arm64、7 passed、原型 GET 200，已验证 |
| wx-cli 服务    | 已核对上游 v0.7.4 协议                   | 用户报告健康；应用端新探测待验证                               |
| 联系人与消息   | 合成回放覆盖账号、同名、群聊、分页及错误 | 待运行带账号绑定的有限采样                                     |
| 图片和文件     | 已核对源端路由及质量头                   | 原件、缩略图、缺失及解析仍待验证                               |

本文不包含用户真实账号 ID、姓名、聊天正文或本机绝对路径。
