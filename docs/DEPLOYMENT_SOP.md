# Wechat-Agent 从零部署、真实微信接入与验收 SOP

本文是当前唯一的部署入口。历史设计和迭代记录保留在 [archive](archive/)，不作为安装步骤；其中未实现的目标不代表现有功能。

适用：单人、本机 Mac、个人微信私信／普通微信群。目标：商家备货与头程服务商三方协同。此账号为纯工作微信，归档范围覆盖全部个人私信与群聊；保留 1–2 群试点入口以及手动文件导入。先本地归档，再选择业务范围启用 DeepSeek；发送消息、加好友、建群均由人工执行。

## 0. 当前验证状态与重要边界

| 层级 | 当前证据 | 不能据此推断 |
| --- | --- | --- |
| 用户设备 | 用户报告 Apple Silicon、macOS 27.0（26A428）、官网微信 4.1.15（界面 4.1.15.55） | 其他设备／版本都兼容 |
| 旧密钥 | 用户报告旧 raw key 通过 21 个库首页 HMAC，导入成功 | 所有历史或所有账号的密钥都有效 |
| 解密 | 用户报告 21 decrypted、0 errors | WAL／最新消息一定全部覆盖 |
| 源服务与试点 | 用户报告链路打通，截图证明群列表可见、可选择两个群 | 每条消息与图片完整归档、DeepSeek 实际分析成功 |
| 应用回归 | 51 项自动测试通过；Chromium 模拟源验证双群试采、图片预览、缩略图提示和移动布局 | 自动代替用户设备的真实验收 |
| 图片 | 本版新增按需读取源服务图片、缓存、质量标记 | 自动全量图片归档、OCR、价卡理解已经完成 |

安装与密钥获取是两件事。没有有效密钥时，当前候选 wx-cli 的首次提取路径有 SIP 前提；本 SOP 不自动关闭 SIP、不重签微信、不重新提取。**从零安装可以完成，但保持现有系统保护且没有已有密钥时，真实采集须停在密钥准入关口。** 不要把演示数据当作真实接入成功。

本地应用不等于数据不出本机：DeepSeek 启用后，获准的脱敏文本会外发。微信密钥、整库、图片原件默认不外发。当前群授权粒度为整个会话文本，不能自动识别所有内部机密。

## 1. 先准备目录和工具

需要 Git、Python 3.12+、uv、Apple Silicon Mac 和本机正常登录的微信。

```bash
git --version
python3 --version
uv --version
uname -m
```

缺 uv 时，可在已有 Homebrew 的机器执行 `brew install uv`；没有 Homebrew 则按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装。不要复制不明来源脚本。

本地数据默认位于 `~/Library/Application Support/Wechat-Agent/`，上游解密缓存默认位于 `~/Library/Caches/wx-cli/`；都不要放进 iCloud、网盘或 Git 仓库。

## 2. 克隆并安装应用

首次安装：

```bash
git clone git@github.com:EligahYy/Wechat-Agent.git
cd Wechat-Agent
uv sync --frozen
uv run wechat-agent init
```

私有仓库需要有权限的 GitHub 账号与 SSH key，可用 `ssh -T git@github.com` 验证；HTTPS Git 不接受账号密码。不要为了访问仓库把个人 token 写进 clone URL。

已有仓库／数据：停止本应用的 serve、collect、worker，先备份，再在仓库目录执行：

```bash
git pull origin main
uv sync --frozen
```

不要删除数据库，不重复导入 demo。启动时会事务迁移数据库 v1／v2／v3 到 v4；迁移前的旧备份应保留，旧版应用不保证能打开新版库。

演示是可选分支，**不要在真实目录执行 demo**：

```bash
uv run wechat-agent --data-dir /tmp/wechat-agent-demo demo
uv run wechat-agent --data-dir /tmp/wechat-agent-demo token
uv run wechat-agent --data-dir /tmp/wechat-agent-demo serve
```

## 3. 安装 wx-cli 并确认它是哪一个项目

本适配器针对 [pandorafuture/wx-cli](https://github.com/pandorafuture/wx-cli)，不要混用同名 CLI。当前安装参考 v0.7.4，接口参考其 `/api/v1/health`、`sessions`、`messages`、`media`。版本变化要重做准入验证。

### 3.1 下载并校验

以下 SHA-256 是本次从 GitHub 官方 v0.7.4 安装包实际计算的摘要，并非作者发布的签名。默认下载官方 URL；若网络慢，可以将 curl URL 改为同一个 URL 前加 `https://ghfast.top/`，校验不变。镜像为第三方，不能跳过校验。

```bash
(
  set -e
  wx_install_dir="$(mktemp -d)"
  curl -fL --connect-timeout 20 \
    "https://github.com/pandorafuture/wx-cli/releases/download/v0.7.4/wx-cli-v0.7.4-macos-arm64.tar.gz" \
    -o "$wx_install_dir/wx-cli.tar.gz"
  printf '%s  %s\n' \
    '4ff42daf28b8f8fe4096840886fa5b15c8cd2f82910b4fa28bfebe4994177e50' \
    "$wx_install_dir/wx-cli.tar.gz" | shasum -a 256 -c -
  tar -xzf "$wx_install_dir/wx-cli.tar.gz" -C "$wx_install_dir"
  mkdir -p ~/.local/bin
  install -m 755 "$wx_install_dir/wx-cli" ~/.local/bin/wx-cli
  ~/.local/bin/wx-cli --version
)
```

已有安装先检查版本和来源，保留需要回退的二进制。校验、签名或系统信任失败时停下诊断，不使用关闭验证的下载参数。

### 3.2 只读诊断

```bash
~/.local/bin/wx-cli doctor
~/.local/bin/wx-cli status
csrutil status
```

`doctor` 的 SIP 提示描述提取路径，不代表已有密钥不可使用。`status` 的 not running 已在用户设备观察到误报：手工 pgrep 与 defaults 都成功，且后续真实解密成功；确切误报根因未定，不据此重装或重签微信。

## 4. 密钥准入：有旧密钥则本地迁移，没有则暂停

### 4.1 旧导出项目还在

在旧工具项目目录执行 `./wechat-export doctor --json`。需看到 keys.status=VALIDATED 和校验通过数量；仅首页校验通过还需后续逐页解密。

回到 **Wechat-Agent 仓库目录**。以下路径按实际旧项目位置修改，不要把路径误填为新仓库：

```bash
uv run wechat-agent key-import --legacy-root "$HOME/Codes/wechat-export"
```

验收：status=preview_ok、written=false、账号正确，且消息／联系人／会话库首页校验均通过。命令不会输出密钥。

停止任何正在写入 wx-cli 密钥库的服务／命令，再显式导入：

```bash
uv run wechat-agent key-import --legacy-root "$HOME/Codes/wechat-export" --write
```

验收：status=imported、written=true；若同一密钥已在库中则 already_present。目标为 `~/Library/Application Support/wx-cli/config/keys.toml`，已有文件先做 600 权限备份，保留其他账号，冲突时拒绝覆盖。旧文件不改动。

禁止把 all_keys.json、keys.toml 或备份上传到聊天／Git；不要通过命令行参数粘贴真实密钥。

### 4.2 没有可用旧密钥

停止真实接入步骤。不能从当前已知流程推断无需保护设置变更即可取得密钥。可以继续使用隔离样例或获准的导入数据验证工作台；这不等于实时接入已完成。

### 4.3 实际解密

```bash
~/.local/bin/wx-cli status
~/.local/bin/wx-cli decrypt
```

验收：对应账号 key 可用、实际解密 0 errors。不要执行 key list 并分享其输出。存在多个账号时核对导入账号；不要自动把另一个账号的数据当成本次业务范围。

`0 WAL patched` 不代表最新数据都完整。必须通过步骤 6 的新消息测试验证刷新能力。

## 5. 启动源服务与工作台

终端 A：用导入预览输出的 account_id 替换下方占位符（带目录后缀的账号标识，不是密钥）：

```bash
~/.local/bin/wx-cli server run \
  --host 127.0.0.1 --port 9100 --account 你的account_id
```

上游可能以受管后台进程运行；以 server status／health 判断，不单凭终端是否占用。只监听回环地址，不使用 0.0.0.0。

终端 B，在 Wechat-Agent 仓库目录：

```bash
uv run wechat-agent token
uv run wechat-agent serve
```

本机浏览器独立标签页打开 `http://127.0.0.1:8765`，输入本地口令。不要从其他网站 iframe 打开。页面口令、源服务 token、DeepSeek key 是三种不同凭据。

若上游启用了 Bearer token，在仓库目录执行 `uv run wechat-agent credentials WX_SOURCE_TOKEN` 安全输入，重启 serve／collect。不要把 token 放 URL。

## 6. 只接入 1–2 个群，验证文本与图片

1. 在工作台“微信接入与分析”点击“检测连接”。
2. 核对工作账号后确认绑定，选择 1–2 个授权业务群。群列表只是会话发现，不代表正文已归档。
3. 两群分属不同商家时先不关联；单群混合多个商家／批次时保持仅本地，后续人工归属。
4. 点击“读取所选群最近 15 分钟”。试采会关闭所选群已有 DeepSeek 外发授权。
5. 查看结果中新增、重复、错误与本地总数，再点击“核对群消息”。
6. 通过正常业务沟通产生一条带可识别内容的文本，再试采；重复试采应计重复而不是新增。应用不代发测试消息。

### 图片专项检查

此前版本仅保存非文本占位，没有图片内容请求。本版新增：

- 保留图片来源 MD5（上游有提供时）与消息定位；已存在消息需重扫对应时间窗口才能补齐这些元数据。
- 图片消息显示“读取本机图片”，点击后通过本机源服务 `/api/v1/media` 获取并保存到应用私有 `media/` 缓存。
- 只接受 JPEG／PNG／GIF／WebP 栅格图片；单图 10 MB 上限；不展示 HTML／SVG 响应。
- 显示 full／thumbnail／unknown 上游质量标记。缩略图不能作为可靠价卡文字来源。
- 图片读取不调用 DeepSeek，也不自动 OCR；文字分析排除非文本并报告 nontext_omitted。

验收：在目标群选择一张已授权图片，先在微信打开／下载原图，再在工作台点击读取，检查图像、质量与再次打开本地缓存。若消息不在最近窗口，按步骤 7 回填。

缺图可能是微信未下载、图片密钥缺失／格式不支持、接口版本不兼容，不等于聊天数据库损坏。数据库 raw key 有效不等于独立图片 AES key 已具备。本版保留错误供重试，不自动提取图片密钥、不修改系统保护。

图片支持目前为本地按需归档预览，不是自动全量附件归档。实际用户设备图片链路仍需按本节验收。

## 6A. 全量私信 + 群聊初始化（推荐正式使用路径）

### 架构

```text
已登录工作微信 → wx-cli 本机只读 API → 会话发现
                                         ↓
                                 历史分页 + 持久断点
                                         ↓
旧 wechat-export 的 CSV/JSON → 格式校验 → 同一消息库 → 私信/群聊档案
                                         ↓
                            按稳定身份关联客户时间线
                                         ↓
                        商家/批次/角色确认 → 按授权分析
```

直接采集不运行旧 wechat-export，不需要先生成导出文件。旧项目只作为可选的数据入口，既有密钥导入也无需重复执行。当前读取层继续复用 wx-cli，不是重写微信解密器。

### 操作顺序

1. 确认 wx-cli 服务已健康运行；停止本应用旧版 serve、collect、worker，按步骤 2 更新与备份。
2. 在仓库目录先发现会话。使用源 health 展示的 **基础 wxid**（不是带目录后缀的 account_id，也不是昵称）：

```bash
uv run wechat-agent archive discover --account 你的wxid
```

输出私信／群聊数量及排除数量，不导入历史。若未绑定，本命令按明确提供的 wxid 核对源端后在本机保存账号绑定。

3. 启动全量初始化：

```bash
uv run wechat-agent archive init-all --account 你的wxid
```

此命令明确授权当前源端可见的工作私信／群聊本地归档，包括之前暂停的匹配会话；关闭当前账号已有会话的 DeepSeek 外发授权，不自动建商家、不生成历史 AI 任务或今日待办。系统／公众号按已知名称或上游类型排除；无明确类型的来源分类不等于完整通讯录鉴定。

4. 另开终端可查看状态（或在工作台“全量消息档案”查看）：

```bash
uv run wechat-agent archive status
```

状态含 pending、failed、scanned、scanned_with_gaps。scanned 是本次固定时间上界的源端分页扫描结束，不等于微信服务器历史完整。source_rows 含上游行数，messages 是本地实际消息数，issues 单独列明异常。存在 failed／scanned_with_gaps 时命令返回退出码 2，不能用它当作全量成功。

失败诊断与补回缺少发送者的记录：

```bash
uv run wechat-agent archive status --details
uv run wechat-agent archive repair
uv run wechat-agent archive status --details
```

repair 只将旧 sender_unavailable 相关会话从第一页重扫，并续跑失败／待处理会话；保留已归档消息和业务数据，不重新发现全账号或开启外发。没有这些旧缺口时不会重扫所有已完成会话。缺少发送者的消息现在保存正文、sender_id=unknown、direction=unknown，计入 metadata_warnings 而不是丢掉正文；客户档案不会据此虚构联系人。stable_server_id_unavailable 仍保留为记录缺口，不能凭文本相同生成假唯一 ID。

failure_reasons 给出失败原因汇总，--details 增加本地会话 UUID、页断点和错误，不含正文或密钥。旧 HTTPStatusError 记录需 resume／repair 实际重试后才能细分为 HTTP_404、HTTP_500 等。不能从 failed 数量单独判断是超时还是版本问题。

5. Ctrl+C／网络中断后续跑：

```bash
uv run wechat-agent archive resume
```

历史每页最多 200 条，保存消息和页断点在同一事务中，已完成会话跳过；恢复失败页可重复读取但不重复新增。新一轮完整重查／修复迟到历史使用：

```bash
uv run wechat-agent archive init-all --rescan
```

重扫会保留已有消息、重置扫描断点及重查记录缺口；不会删除你的任务、商家或项目。每次 init-all 都关闭账号范围外发，正式启用分析后再次执行需重新确认授权。新增私信／群尚不自动扩展白名单，需再次初始化发现或手动登记；collect 只扫描已启用会话。不要并行运行两个初始化命令。

6. 首次初始化结束后运行 serve 和 collect，先不要启动 worker。增量从历史上界衔接，而不是仅从启动前 15 分钟开始，防止长时间初始化造成中间空档。

### 覆盖边界

- “全量”指当前账号、当前 Mac、本地源端可见且可读的历史。无法恢复已删除／未同步记录；上游隐藏规则仍有效。
- 会话清单来自 sessions API，未列入该表的孤立消息表不保证枚举；疑似触达上游会话数量上限时中止发现并报告，而不是默默声称全部。
- 固定 until 不能提供数据库快照隔离；分页期间迟到补录可能使 offset 漂移，需重扫／抽查。当前不保证 exactly-once 远端读出，只保证本地幂等写入。
- 无稳定 ID／正文不可解码的行进入 archive_issues，不冒充完整成功；分片不可读或整页失败停在该页，其他会话继续。
- 初始化保存文字和媒体消息定位，不自动下载所有图片／语音／视频二进制；图片仍按需本地读取，尚不 OCR。
- 不把所有群都绑定为一个商家，也不将每个私信对象自动判为商家；商家主体、服务商角色和批次仍可人工确认。

## 6B. 保留手动入口：旧项目导出 / CSV / JSON

### 页面导入

进入“全量消息档案” → “手动导入”。选择 CSV、JSON 或 JSONL，填写文件所属微信账号（或留空使用已绑定工作账号），先校验预览再确认导入。网页最多 1.5 MB；大文件走下面 CLI。

### CLI 导入

```bash
uv run wechat-agent import /实际路径/all_messages.csv --account 你的wxid --preview
uv run wechat-agent import /实际路径/all_messages.csv --account 你的wxid
```

支持旧项目直接生成的 all_messages.csv／all_messages.json；也支持标准 JSON 数组、包含 messages／items 列表的 JSON，以及 JSONL、标准字段 CSV。单文件最多 64 MB，超过请按时间／会话拆分。不会调用旧导出程序，不需要旧密钥，也不会执行文件中的代码。

旧文件按导出程序的明确约定，将不带时区的 time 解释为 Asia/Shanghai；标准消息的 event_time 必须显式带时区。CSV 推荐 UTF-8／UTF-8 BOM。暂未提供任意列名的可视化映射，未知列名文件需转换为下列标准字段。

标准消息示例（虚构）：

```json
{"source":"manual","account_id":"work-account","conversation_id":"customer-id","conversation_type":"private","source_id":"message-001","sender_id":"customer-id","direction":"incoming","event_time":"2026-11-04T09:00:00+08:00","message_type":"text","text":"请确认下周备货安排"}
```

缺少稳定会话 ID、时间、账号或消息 ID 的行在预览中报告；若有错误，正式导入整份文件拒绝写入，避免部分成功不明。有效文件在同一事务分批入库。已暂停的现有会话保留暂停，导入报告会列出 excluded 数量；需要导入该会话时先明确恢复。

旧文件有真实 server_id 且账号／会话 ID 一致时使用与直接采集相同的身份，可跨 CSV／JSON／直接采集去重。没有 server_id 时仅使用带 db／table／local_id 的 legacy 命名空间，不凭文本相同吞掉真实重复发言；这类记录与后来真实 server_id 的语义合并仍待人工确认。通用标准文件 source=manual 保持明确来源，不声称所有异构文件都能自动跨源去重。

文件内容只写入本地，不触发模型调用，不覆盖商家归属和已有外发策略。旧项目可继续独立导出，但不是直接采集的依赖。

## 6C. 客户全景档案与历史浏览

工作台“全量消息档案”按私信／群聊、名称／ID 搜索，分页浏览会话；消息对话框可翻页查看更早历史，不只显示最近 100 条。

“客户全景档案”按当前账号下稳定联系人 ID 汇总私信对象与已观察到的群内发送者。点开可看到该联系人私信和群内发言的最近 100 条时间线，包含来自哪个会话；不是完整通讯录导入或已经自动生成的 AI 画像。

同名不同 ID 保持分开，未知发送者不伪造身份。同一微信联系人也不必然只有一个商家主体；商家、服务商、项目关联以确认结果为准。当前还未自动提取长期需求、偏好和商家画像事实，后续通过有证据的审核建议补齐。

## 7. 启动持续采集与历史回填

终端 C，在同一仓库／数据目录：

```bash
uv run wechat-agent collect
```

一次页面试采不会自动启动 collector。持续采集扫描所有启用的真实白名单会话，试点期间只启用这 1–2 个群。暂停会话会关闭该私信／群聊采集与外发，保留归档。

近期重叠回查和幂等去重已实现。更早历史需按内部会话 UUID、Unix 秒手工回填：

```bash
uv run wechat-agent collect --conversation 会话UUID --since 起始Unix秒 --until 结束Unix秒
```

每窗口最多 24 小时、1000 条；超量缩小窗口。历史回填与持续新消息最好分时运行。scanned 表示查询完成，不保证全部历史；gap 独立保留，不能被后来的成功自动当作已解决。Mac 休眠／微信离线后重启 collector 并核对新消息与缺口。

账号绑定保存在 source-binding.json。若设置了 WX_ACCOUNT_ID／WX_SELF_ID 环境变量，必须一致；换号后重新核对，重启 collector。

## 8. 建业务关联，再接 DeepSeek

先创建商家、备货项目、服务商；将会话关联到明确商家和批次，并确认群成员角色。三方任务分别记录我方／商家／服务商，建群或发价卡不等于备货完成。

本机安全配置 API key：

```bash
uv run wechat-agent credentials DEEPSEEK_API_KEY
uv run wechat-agent model validate --fixture tests/fixtures/deepseek-smoke.json
```

第一次仅发虚构数据，会产生实际 API 调用和费用。当前默认模型候选 deepseek-chat，使用账户已验证模型；具体可用模型和参数以实际响应为准。成功标准是 live_api_succeeded，不是 mock 通过或仅 key 存在。

随后：

1. 查看会话原文，确认有权外发该范围；当前没有逐字段机密识别。
2. 在“关联与授权”中开启该会话分析授权，查看脱敏预览。开启后 worker 可自动分析新数据，不是逐请求审批。
3. 在终端 D 启动：

```bash
uv run wechat-agent worker --engine deepseek
```

4. 安排一次分析，确认建议包含正确商家、批次、三方责任和可核对证据。
5. 人工接受建议才生成正式任务；复制话术不算已发送，实际联系后再记录结果。

默认每日 100000 token 保守预算（当前按 UTC 日计），最大输出 2000 token、每任务最多三次调用；超时可能已计费，usage 缺失保留预留量。长会话、上下文不足或权限问题会明确阻塞；不悄悄发送全文到其他服务。

## 9. 全链路验收清单

| 检查 | 必须看到的结果 |
| --- | --- |
| 密钥 | 正确账号，HMAC 校验通过，解密 0 errors |
| 源服务 | health ready 且 current_account 与绑定一致 |
| 试采 | 仅所选群入库，查看到真实正文 |
| 新消息 | 正常新消息产生后可看到，来源与方向正确 |
| 去重 | 同窗口重复扫描不重复新增 |
| 图片 | 能读则显示真实图和质量；不能读有明确错误，不冒充 OCR 成功 |
| 暂停／重启 | 暂停群不继续读取；恢复进程后检查覆盖与 gap |
| 模型授权 | 未授权会话无外发；授权后能预览允许上下文 |
| DeepSeek | 虚构真实 API 请求成功，真实小样本证据正确 |
| 人工闭环 | 接受建议 → 待办 → 人工沟通 → 记录 → 下次跟进 |
| 结果口径 | 聊天“收到／已发”不自动等于平台备货完成 |

上次 21 库解密成功和群列表截图仅覆盖其中部分关口。图片和真实 DeepSeek 结果需分别记录，不把“能看到群”写成“全链路完备”。

## 10. 故障定位与日常维护

| 表现 | 处理 |
| --- | --- |
| GitHub 密码认证失败 | 使用有权限的 SSH key／GitHub 支持的认证方式，不用账号密码 |
| cross_site | 更新代码、重启后端，独立标签页手工输入本机地址；iframe 和跨站 API 仍被拒绝 |
| 旧口令外泄 | 相同数据目录运行 `uv run wechat-agent token --rotate`，旧会话失效 |
| not running 但微信可见 | 查看 pgrep、defaults、签名和实际解密结果；不要直接重装 |
| key ✗ | 不同工具密钥库独立；旧密钥 VALIDATED 时走本地导入 |
| 读取图片 404 | 微信打开／下载原图，核对图片解密能力与上游版本；本地 DB key 不保证媒体 key 有效 |
| 试采零消息 | 最近 15 分钟可能无消息；产生正常测试消息或回填指定窗口 |
| source_account_mismatch | 微信换号或绑定冲突，重新确认账号后重启相关进程 |
| blocked_policy／association | 核对外发授权、商家与项目关联，不放宽全局权限 |
| blocked_credentials／budget | 本机核对 key、账户额度或预算，恢复后安排重试，不分享凭据 |
| blocked_context_limit | 当前上下文上限触发；缩小范围／分项目，不能用截断冒充全文 |
| 只有图片无建议 | 当前模型只分析文本；不代表图片被 OCR 或没有业务信息 |

停止时对自己启动的进程 Ctrl+C；上游受管服务按其 server stop 关闭。不要 killall 微信或对数据目录 chmod -R。

### 更新与备份

更新前停止应用采集／分析进程。数据库一致性备份：

```bash
mkdir -p "$HOME/Wechat-Agent-backups"
uv run wechat-agent backup "$HOME/Wechat-Agent-backups/agent-$(date +%Y%m%d-%H%M%S).sqlite3"
```

backup 命令只备份数据库，不含图片文件。图片已启用时还要在停止本应用后备份数据目录的 media/；同时保留 source-binding.json。所有副本留在本机受限／加密存储，不能提交 Git 或随意同步云盘。wx-cli 密钥库与旧密钥另行安全保管，不把它们打包给他人。

恢复到新的私有目录，放入 agent.sqlite3 和 media/，使用统一 --data-dir 启动相关命令并核对商家、消息、任务、图片与证据；不要覆盖唯一备份。恢复后重新检查账号绑定与授权。

## 11. 下一阶段完善顺序

| 优先级 | 要解决的问题 | 交付与验收 |
| --- | --- | --- |
| P0 | 图片中的价卡／海报不可检索 | 在本机验证原图／缩略图、媒体密钥覆盖与下载失败重试；建立附件状态。用户选择需要 OCR 的素材，本地 OCR 保留区域、置信度、原图证据；人工审核价格、单位、税费、线路、有效期。图片不直接默认送文本模型 |
| P0 | 文本接通不等于 AI 业务闭环可靠 | 少量真实授权样本跑通 DeepSeek，标注需求／责任方／日期，检查漏提取、误报与跨批次归属；通过后再扩大群范围 |
| P1 | 重复任务和人工反复整理 | 任务新增／更新／取消建议、语义去重、人工编辑保护，跨批次不串单；历史导入的旧待办先复核 |
| P1 | 群内多商家／多批次 | 消息级身份和项目关联、报价隔离、上下文回查；群不能无条件整体绑定一个项目 |
| P1 | 采集覆盖与常驻稳定性 | 自适应回填、分片／WAL 覆盖、gap 对账、休眠恢复、健康告警；稳定后再做 launchd，一周实际运行验收 |
| P2 | 激活历史商家 | 经审核价卡、历史顾虑和约定回访驱动候选；计费口径相同才能比较降价；频率与拒绝联系规则先于模型 |
| P2 | 平台产品运营复盘 | 汇总真实阻塞、产品问题、需求与备货漏斗；按商家／批次明确分母和来源，不把建群数当备货转化 |

建议下一轮先完成“2 个试点群的图片／价卡识别 + 真实 DeepSeek 跟进闭环”，暂不扩展更多群、自动发送或服务器部署。当前按需图片读取是这一步的基础，不是 OCR 交付。
