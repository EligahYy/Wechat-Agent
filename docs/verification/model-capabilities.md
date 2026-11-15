# 模型探测范围

更新：2026-11-15（北京时间）。用户截图已回传deepseek-flash最小连接检查通过；这不证明容量、视觉或真实客户质量。云端已接通单客户生产工作流及合成回放，实际预算与质量仍分别核对。

## doctor诊断工具

使用明确配置的 HTTPS、OpenAI 兼容 chat-completions 端点，发送一条无客户数据的最小 JSON 请求。不提供猜测的 Pro 默认 model ID，不自动退换模型。默认 doctor 离线；只有 `--check-model` 才可能发出一次付费请求，M0 不自动重试。

这里的 `.local/config/model.json` 仅用于doctor诊断，不入Git；正式设置页已使用版本化SQLite非敏感配置和本机Keychain，见[M2任务3](m2-task3-report.md)。两者不应混用或把最小请求当作容量证明。doctor配置字段：

| 字段                | 含义                                                                 |
| ------------------- | -------------------------------------------------------------------- |
| endpoint            | 完整 chat-completions HTTPS URL；不能内嵌账号密码、query 或 fragment |
| model_id            | 实际 API 账号可调用的模型 ID，必须自行确认后填写                     |
| key_env             | 本地环境变量名，默认 DEEPSEEK_API_KEY，文件不保存密钥值              |
| proxy_url           | 可选的显式模型代理；来源服务和模型代理分别配置                       |
| response_mode       | text／json_object／json_schema，默认 json_object                     |
| probe_output_tokens | 最小请求输出预留，默认256，允许16–4096；结束原因 length 按截断报错   |
| accepted_model_ids  | 可选，只有经核对的返回别名才加入；不按相似前缀接受错误模型           |
| context_tokens      | 可选的已查资料声明，仅报告 declared；短请求不能证明完整窗口          |

配置好后：

```bash
.venv/bin/python -m wechat_agent.doctor --check-model --output .local/evidence/m0.json
```

未配置为 pending，不发网络；未提供环境变量密钥也不发请求。API 返回鉴权、权限、模型不存在、限流、重定向、服务错误、输出格式不支持、模型 ID 不符、截断、错误 JSON 时分别报具体 gap。只记录状态、模型标识和用量，不记录密钥、响应正文或内部推理内容。

## 不能从这个探测推导的结论

- passed 只代表本次最小请求成功、返回模型符合明确配置、JSON 内容通过本地校验。
- json_object 成功不代表强制 JSON Schema；json_schema 成功也只记录本次参数接受情况，不证明所有业务 schema 的约束效果。
- capacity_verified 始终为 false；完整上下文窗口与最大输出能力需要依据供应商资料及专门核验记录，不从短回复猜测。
- vision=not_checked；本次没有图片，不能自动宣称支持／不支持视觉。
- usage 缺失为 unknown，不能填0或编造费用；没有真实样本时不能声称客户档案质量通过。

ModelCapabilities 类型只接受正容量、带时区的 verified_at 和不大于上下文的输出上限，不会由最小探测自动生成“已验证全部能力”。


## M2生产文本预算记录

设置页保存声明值与最小检查之外，新增明确的操作者文档核对记录，包含供应商HTTPS依据、当前配置版本、文本预算及可选JSON Schema格式支持。只有当前版本已通过连接检查且具有该独立记录时才启用生产文本整理；更改配置使记录失效。capacity_verified／vision_verified保持false，不把文档核对伪装成压测，图片理解仍未启用。

网关以核对预算为上限，保守估算规则／schema／完整原文和输出余量；超窗失败并保留旧档案，后续M3再分段。操作者填错预算可能被供应商拒绝，不能通过裁剪来伪装成功。真实业务质量按[M2清单](m2-profile-review.md)逐项实测。
