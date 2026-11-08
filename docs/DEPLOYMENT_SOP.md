# 部署、微信接入与新工作台试点 SOP

适用 v0.8.1、数据库 v10。先读已交付边界：[实施状态](IMPLEMENTATION_STATUS.md)。新工作台为M1技术试点，原工作台保留；升级不清空消息、名单或账单，不自动全库重建。

## 已有用户：升级并进入试点

先停止旧 start／serve／worker。保留原数据目录，无需重新导入、init或demo。

```bash
git pull origin main
uv sync --frozen
# wx-cli已运行则跳过；多账号请按已验证方式明确--account
~/.local/bin/wx-cli server run --host 127.0.0.1 --port 9100
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent start --pilot
```

`--pilot`继续采集和补历史，暂停旧模型后台，不会自动分析全部客户。升级现有库前自动创建 `pre-v10-*.sqlite3`。保留此备份及数据目录；不要使用旧代码直接打开v10库。

1. 打开 http://127.0.0.1:8765，口令通过另一终端 `uv run wechat-agent token` 查看。
2. 原工作台设置中检测wx-cli、确认账号；已有绑定和密钥可复用。刷新微信联系人以补名称。
3. 设置DeepSeek key及预算，开启账号文本分析授权；在会话范围排除同事、买手和纯服务商会话／人物。pilot模式下开启授权不会启动旧模型后台。
4. 点击原工作台“新工作台试点”，进入 `/workspace`，再选择“试点与进度”。
5. 在联系人搜索框输入备注、昵称或微信 ID，先选1–2位消息量较少、身份明确的商家（每次选一位），点击“分析此联系人”。这一步真实调用DeepSeek，计入共同预算，最多3次请求。
6. 在新工作台“客户／待确认／今日”核对身份、批次及原文。完成、暂停和角色判断会写入同一客户文档；刷新后保留。
7. 升级 v0.8.1 后，对已试点联系人重新点击分析：旧结果会经新版来源复核更新，不需重导消息。每条线索、批次和待办独立成卡；展开来源核对原文，可用「纠正这条内容」保存人工约束。
8. 在「待确认」核对行动建议，确认是自己要处理的事项后点「确认由我跟进」。到期任务进入今日；详情可保存下次联系日期、等待回复、标记已处理。覆盖不全不会再被误写为无需行动。
9. 后续有新消息或人工确认后，重新对该联系人分析。当前不会自动运行新引擎的全量队列。

### 联系人列表为空或按钮不可用

v0.8.1 起，联系人来自当前账号正常跟进范围的本地归档：私信按会话对象识别，群聊按实际发送者识别，不依赖旧客户库或先运行模型。查看列表不需要模型授权、不消耗 token；人物／会话白名单仍然排除。

页面显示归档消息、正常跟进会话和可识别联系人数量，并提供搜索与「刷新联系人」。按提示处理：

| 提示 | 处理 |
| :--- | :--- |
| 尚未绑定工作微信 | 点击连接设置，确认当前工作账号 |
| 当前账号尚无归档消息 | 检查 wx-cli、采集状态、绑定账号及数据目录；已有记录不要重新 init／导入 |
| 暂无正常跟进会话 | 检查会话范围与人物白名单，只恢复真正需要跟进的来源 |
| 暂未找到可选联系人 | 检查人物白名单和源端身份信息；未知群成员不靠模型猜测 |
| 没有匹配的联系人 | 清空搜索或尝试其他备注／昵称 |
| 待就绪 | 选中后查看具体原因：未开启分析授权、缺少 key、来源未授权或没有完整文本 |

修改原工作台设置后返回试点页，点击「刷新联系人」。未授权时联系人仍可见，但分析按钮不可用；不会自动扩大外发范围。`--pilot` 模式下新引擎仍需手动点击分析，不会因开启账号授权自动分析全库。

CLI可选入口（contact为本机真实来源ID，页面选择通常更方便）：

```bash
uv run wechat-agent rebuild inspect
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent rebuild analyze --contact '联系人的source_id'
```

inspect只读现有归档，不联网、不调用模型；analyze使用相同授权与预算。运行命令时不要粘贴API key或解密密钥。

## 首次安装与源端准备

以下步骤仅供尚未部署者；已接通的用户不必重装微信或重取密钥。

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

不要删除数据库，不重复导入 demo。启动时会事务迁移旧数据库到 v8；迁移前的旧备份应保留，旧版应用不保证能打开新版库。

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

`0 WAL patched` 不代表最新数据都完整。必须通过后续实机新消息验收验证刷新能力。


## 首次接入归档

启动本机wx-cli后，按上方 `start --pilot` 进入原工作台设置，检测连接并明确确认工作账号。系统发现私信和普通群聊；仍需授权相应来源才可发送文本给模型。名称来自微信元数据，不需要模型猜测。

检查本机可见归档：

```bash
uv run wechat-agent archive status --details
uv run wechat-agent rebuild inspect
```

需要首次初始化或补历史时使用已有 `archive init-all --account 当前工作账号`、`archive resume`；不要与start的归档循环并行操作。隐藏、删除、未同步历史不保证读取；unknown sender、隔离行、缺稳定ID单独报告。SIP提示或status误报不应单独作为重装微信的依据。

## 一个备用文件入口

原工作台设置保留CSV／JSON／JSONL导入预览，CLI共用标准格式；不依赖wechat-export专有格式。示例：

```json
[{"source":"manual","account_id":"工作账号","conversation_id":"对方稳定ID","conversation_type":"private","source_id":"稳定消息ID","sender_id":"对方稳定ID","direction":"incoming","event_time":"2026-11-08T09:00:00+08:00","message_type":"text","text":"请确认本批附加费"}]
```

```bash
uv run wechat-agent import /路径/messages.json --account 当前工作账号 --preview
uv run wechat-agent import /路径/messages.json --account 当前工作账号
```

CSV列名相同。时间包含时区。页面上限1.5MB，CLI上限64MB；错误文件不部分写入，导入不隐式授权外发。跨source命名空间不盲目认定重复消息。

## 没有产出时怎么看

| 现象／错误 | 检查 |
| --- | --- |
| 没有可选联系人 | 工作账号绑定、归档、会话授权、人物及会话免跟进；来源人物不等于已确认客户 |
| blocked_policy／blocked_credentials | 原工作台设置授权与DeepSeek key |
| blocked_budget | 共用预算不足；适量调整或次日再手动试点 |
| workspace_already_running | 同一联系人正在其他请求／进程分析，完成后再试 |
| workspace_stale_input | 分析期间来源、范围或人工状态改变；当前结果未覆盖新状态，再次运行 |
| workspace_stale_evidence | 原文修订或范围变化；旧档案暂时隐藏，重新分析有效来源 |
| workspace_model_schema／unknown_evidence | 模型输出契约／引用错误，查看安全错误码；不用发送聊天正文或key |
| 资料覆盖有限 | 上下文超限、存在未读媒体；可以生成资料，但不强行产生今日任务 |
| 候选／非目标客户 | 商家角色证据不足，或判断为同事／服务商；不会硬凑客户与任务 |
| 近期有新进展待整理 | 原有行动不立即推荐，重新分析此联系人 |

新工作台“试点与进度”显示最近20次执行和请求数；旧“分析概览”仍描述原队列，不是新引擎覆盖进度。原工作台监控里的 `pilot_manual` 表示等待手动试点，不代表模型故障。

## 网络与预算

用户当前已验证模型代理为7897；wx-cli仍走本机9100。无key连接检查：

```bash
curl --noproxy '' --proxy http://127.0.0.1:7897 --connect-timeout 10 --max-time 20 -sS -o /dev/null -w 'HTTP %{http_code}\n' https://api.deepseek.com/models
uv run wechat-agent diagnose --network
```

HTTP401表示未带key但连通。源服务连通不代表DeepSeek连通。TLS验证保持开启。未建立连接的请求释放预留；ReadTimeout等保留费用不确定记录，不清空历史账单。成功响应保留后可重放解析，相同已完成输入复用文档；已发送但丢失响应时不能保证不重复计费。

本地运行仍会将获准的必要脱敏文本发往DeepSeek；不发送整库、解密密钥或图片原件。当前新引擎没有OCR，不把图片缺失当作无需求。

## 备份与恢复

```bash
uv run wechat-agent backup /安全路径/wechat-agent-backup.sqlite3
```

同时保留media/、source-binding.json、wx-cli密钥配置和系统凭据存储。备份不自动包含这些文件。不要提交Git或上传聊天。

新引擎存储独立，未删除旧客户／任务。离开试点可停止服务，再不带 `--pilot` 启动以恢复旧后台；两套业务结果不会自动互相合并。若需回退旧代码，在独立目录使用升级前备份，新v10库与后来采集的记录必须保留；不要用旧备份覆盖唯一现库。

真实效果按 [验收计划](ACCEPTANCE_PLAN.md) 抽查同人跨群、同批后续回复、已发货、人物排除及人工判断。代码回归和模拟模型测试不代替用户本机业务验收。

### 运输术语校验失败

`workspace_transport_term` 是内容校验错误，不是网络故障。0次请求表示复用响应缓存，不是又调用模型。升级到v0.8.1并重启后再分析，旧版本缓存失效。单次仍最多3次请求；最终仍有问题的表述将隔离，页面提示「部分内容需要核实」，不擅自把汽运替换为海运。独立通过校验的行动保留为待确认建议，核对后可确认由我跟进。

### v0.8.1 更新时 annotated-types 下载 404

提交 `39832cf` 曾误改第三方锁定条目。拉取后续修复后重新执行 `uv sync --frozen` 即可，无需删除环境或数据；正确依赖为 `annotated-types==0.8.0`，项目版本仍为 `wechat-agent==0.8.1`。

维护发布版本时，只更新项目自身版本并使用 `uv lock` 更新锁文件，禁止全局替换 `uv.lock` 中的版本字符串。发布前除业务测试外，须在独立临时虚拟环境运行 `uv sync --frozen`，检查实际下载与安装。

联系人选择已改为单一搜索框：输入备注／昵称后点击匹配联系人，再点击分析。运行时间显示北京时间。升级后需重新分析原试点联系人，使旧确认问题按新规则重新核定。

### 客户关联证据不足

`workspace_customer_anchor_required` 表示结论未引用能关联当前联系人的证据，不是网络错误。修复版本将该校验前移至模型复核阶段，并向模型提供 `customer_related` 标记；单条无归属内容可隔离，整份身份没有依据仍不写入。升级并重启后重新分析，旧缓存自动失效，无需重新导入消息；单次最多3次请求的上限不变。
