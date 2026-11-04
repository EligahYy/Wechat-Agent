# 真实微信试点：先接入 1–2 个群

目标：用实际 Mac 微信验证采集全文、账号、发送者与去重。先只本地归档，不接 DeepSeek，不自动发送或拉群。

## 当前设备信息与已知限制

用户报告：macOS 27.0（26A428），官网下载的微信 4.1.15.55。芯片类型与 wx-cli 安装状态尚未确认；本项目未在这个版本组合上实测。

候选为 [pandorafuture/wx-cli](https://github.com/pandorafuture/wx-cli)，不是其他同名 CLI。该项目最新 README 声明 Apple Silicon／微信 4.1.7+，但不能据此认定 macOS 27 已兼容。README 仍明确写首次密钥提取需要 SIP 关闭；已有有效密钥可跳过该提取要求。

应用不会替用户安装内存读取权限、重签微信、关闭 SIP 或提取密钥。如果设备保持现有保护无法取得有效密钥，真实接入仍阻塞；应先核对具体诊断，不为试用直接修改系统保护。只分享非敏感错误码与版本，不分享密钥、微信数据库或完整诊断文件。

## 1. 更新应用

在 Wechat-Agent 仓库目录，先 Ctrl+C 停止旧后端，再执行：

```bash
git pull origin main
uv sync --frozen
uv run wechat-agent serve
```

不要重新 init、demo 或删除数据。页面若仍是旧样式，请刷新；本版静态资源响应使用 no-store。

## 2. 先确认本机工具与权限状态

另开终端，仅运行只读诊断：

```bash
sw_vers
uname -m
command -v wx-cli
csrutil status
```

- uname -m 应核对是否 arm64；候选目前声明 Apple Silicon 平台。
- command -v 没有结果表示尚未安装该命令，不等同于微信不存在。
- csrutil status 只读查看系统保护状态，不会更改设置。

如果已安装，继续：

```bash
wx-cli --version
wx-cli doctor
wx-cli status
```

核对工具来自上述仓库。status 仅用于本地查看账号与密钥状态；不要把 key list、凭据文件、完整日志或数据库发到聊天。

若未安装，可从上述项目的 [Releases](https://github.com/pandorafuture/wx-cli/releases/latest) 选择 macOS arm64 包，检查发布者／版本和项目提供的校验信息，解压后安装到个人 PATH。不要执行来源不明的同名安装脚本；遇校验或系统信任失败应停止排查，不禁用校验。

有 Rust 工具链和 Xcode Command Line Tools 时，也可在独立目录从已审阅源版本构建：

```bash
git clone https://github.com/pandorafuture/wx-cli.git
cd wx-cli
git checkout 2abe708f55bfe135539a385df856fdc58f97fc74
cargo build --locked --release
```

该 commit 是本项目适配器已核对的源码契约，不是已实测支持当前 macOS 的保证。编译成功也不等于已取得微信数据库密钥。切换版本时需重做接口与权限验证。

## 3. 有可用密钥后启动上游服务

仅当 doctor／status 和本地查询确认采集条件满足时，在一个独立终端运行：

```bash
wx-cli server run --host 127.0.0.1 --port 9100
```

以上命令以所选版本 --help 为准。微信与采集器必须在同一台 Mac；只登录微信不足以提供 API。不要绑定 0.0.0.0，不向公网开放端口。

若源服务启用了 token，用 `uv run wechat-agent credentials WX_SOURCE_TOKEN` 在本机安全输入，然后重启工作台与 collector。系统钥匙串或 WX_SOURCE_TOKEN 环境变量均可提供源认证；token 不放 URL 或网页表单。

## 4. 在新工作台中试采

1. 点击侧栏“微信接入与分析” → “检测连接”。失败时会显示未启动、认证或接口不兼容的说明。
2. 核对显示的工作微信账号，点击确认。账号绑定只保存到本机 source-binding.json，不含密钥；CLI collector 同样读取它。
3. 从群列表选 1–2 个授权的商家业务群；搜索仅针对已加载群，可继续加载更多。此处读取会话名称用于选择，不保存私信名称或正文。
4. 如两个群属于不同商家，先不关联，试采后分别设置商家／批次。默认不允许 DeepSeek 外发。
5. 点击“读取所选群最近 15 分钟”，查看新增／重复数量和缺口提示。此操作会关闭所选会话已有的 DeepSeek 外发授权，避免把试点自动送模型。
6. 点击“核对群消息”，确认正文、账号、时间、方向、发送者和真实业务范围。
7. 没有近期消息时，只代表窗口没有内容。可在微信中正常发一条业务测试消息，或等待群里自然有新消息，再次试采；应用不代发。

同一条消息重复采集应计为重复，而不是新增。非文本仅占位；图片、语音、文件尚未全文解析。上游缺少稳定 ID、正文或分片时会记录 gap，不假装完成归档。

## 5. 确认后持续采集

保持工作台运行，另开终端进入同一仓库／数据目录：

```bash
uv run wechat-agent collect
```

页面的一次试采不会偷偷启动后台守护进程。collector 持续扫描全部启用的真实白名单会话；试点期间请只启用这 1–2 个群。需要停某群时点击“暂停采集”，同时关闭该群分析授权，保留已归档历史。

向导确认的账号会自动用于 collector，无需手工复制账号环境变量；若已有 WX_ACCOUNT_ID／WX_SELF_ID 环境变量，必须与绑定一致。换号后重新核对，并重启 collector，不能混用数据。

连续验证至少：新消息可见、重复无新增、重启后可恢复、出错可见。Mac 休眠／微信离线的覆盖能力需实际验证，不能承诺补齐所有历史。

## 6. 采集正确后再开启 DeepSeek

先关联明确商家、批次和群成员角色，再检查允许外发的范围，配置 API key，预览脱敏请求后启用分析。混合商家群先保持仅本地。具体步骤见 [运行指南](05-run-local.md)。

一期样例不代表真实接入已经成功；浏览器端到端检查使用模拟上游，真实设备必须按上述步骤验证。
