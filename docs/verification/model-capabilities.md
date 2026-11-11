# 模型探测范围

更新：2026-11-11（北京时间）。云端已实现一次性连接探测及合成回放测试；尚未提供真实 API 凭据或确认最新 Pro 模型 ID，不宣称已接入 Pro。

## 当前实现

使用明确配置的 HTTPS、OpenAI 兼容 chat-completions 端点，发送一条无客户数据的最小 JSON 请求。不提供猜测的 Pro 默认 model ID，不自动退换模型。默认 doctor 离线；只有 `--check-model` 才可能发出一次付费请求，M0 不自动重试。

配置位于 `.local/config/model.json`，不入 Git。字段：

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
