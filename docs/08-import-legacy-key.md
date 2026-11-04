# 在本机复用旧导出工具密钥

适用：wechat-export-macos/raw-key-v1 的 account_raw_key，旧工具诊断显示 VALIDATED。只在你的 Mac 上读取旧配置和密钥；无需把文件或密钥上传，也无需关闭 SIP、重签或重新提取。

导入不保证后续 wx-cli 解密与消息解析必然兼容；它验证的是账号、数据库首页 HMAC 和目标 TOML 格式。导入后仍需逐页解密及接口验收。

## 1. 更新应用

在 Wechat-Agent 仓库目录运行：

```bash
git pull origin main
uv sync --frozen
```

旧工具项目目录需保留完整：优先读取 data/config.json，否则根 config.json；按其 keys_file 与 db_dir 定位，不修改旧文件。旧密钥声明的账号目录必须与配置一致，不自动在两个账号间猜测。

## 2. 先预览，不写文件

以下假设旧工具目录是 ~/Codes/wechat-export；如不同，改成你运行旧 doctor 时所在目录的实际路径：

```bash
uv run wechat-agent key-import --legacy-root "$HOME/Codes/wechat-export"
```

预期 status=preview_ok，显示账号、通过校验的数据库数、目标文件路径和 written=false。不会显示密钥。数据库首页不匹配、缺必要库、配置格式异常或目标条目冲突都会停止。

若报错，请保留旧文件和系统保护设置；可提供非敏感错误文字，不提供 all_keys.json、keys.toml 或其备份。

## 3. 明确写入

先停止任何正在运行的 wx-cli 服务及密钥修改命令，避免并发更新密钥库；不需要退出正常运行的微信。

```bash
uv run wechat-agent key-import --legacy-root "$HOME/Codes/wechat-export" --write
```

目标默认为 ~/Library/Application Support/wx-cli/config/keys.toml，匹配当前使用的候选工具路径。其他平台或自定义配置路径不在当前 CLI 范围内。

已有文件先生成同目录私有备份；新文件权限为 600，使用原子替换。保留其他账号，当前账号已有不同条目时拒绝覆盖；同一密钥重复导入返回 already_present。导入前后会检查目标是否发生变化，但未与第三方工具共用锁，所以必须停止其写入操作。

旧 raw key 转为候选 wx-cli AccountKey.data_key，不转换成预派生 enc_key，不写命令行参数或日志。目标格式按已核对的 pandorafuture/wx-cli AccountKey 定义生成，不适用于其他同名 CLI。

## 4. 验证并启动试点

```bash
~/.local/bin/wx-cli status
~/.local/bin/wx-cli decrypt
```

期望对应账号从 key ✗ 变成有密钥，并且实际解密成功。status 的运行状态误报与密钥导入是两件事，不用为修复它而重装微信。

解密成功后，使用预览显示的确切 account_id 启动服务：

```bash
~/.local/bin/wx-cli server run --host 127.0.0.1 --port 9100 --account 你的account_id
```

这里 account_id 不是密钥，可以使用预览显示的带目录后缀账号标识。随后打开工作台“微信接入与分析”，检测服务、确认账号、选 1–2 个群试采。未确认真实消息正确前保持 DeepSeek 外发关闭。

本功能在合成加密页上验证成功、篡改拒绝、账号冲突、备份和权限；尚未在用户 Mac 上真实迁移，结果须以本机命令和后续解密为准。
