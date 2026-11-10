# 部署、微信接入与自动客户整理 SOP

适用 v0.12.1、数据库 v14。先读已交付边界：[当前交付](README.md)。默认使用新客户工作台；升级保留原消息、分册、名单和用量，自动模型队列由工作台开关控制。

## 已有用户：升级并开启自动整理

先停止旧 start／serve／worker。保留原数据目录，无需重新导入、init或demo。

```bash
git pull origin main
uv sync --frozen
# wx-cli已运行则跳过；多账号请按已验证方式明确--account
~/.local/bin/wx-cli server run --host 127.0.0.1 --port 9100
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent start
```

首次升级前会生成 `pre-v14-*.sqlite3`，保留备份和原数据目录。不要用旧代码直接打开v14数据库。默认 `start` 已运行新后台，先前命令中的 `--pilot` 应去掉。

1. 打开 http://127.0.0.1:8765，口令通过另一终端 `uv run wechat-agent token` 查看；登录后直接进入客户工作台。
2. 点“设置与接入”，确认工作账号、wx-cli连接、DeepSeek key、文本分析授权；已有配置复用。
3. 在会话范围维护免跟进白名单，排除同事、买手和纯服务商来源／人物。
4. 回到客户工作台“整理与进度”，点击“开启自动整理”。开关按账号持久保存，首次升级不会擅自开启。页面显示来源联系人总量、排队、整理、续跑和需要处理数量；每页最多50位。
5. 后台每分钟检查新消息和范围变化，优先近15天活跃联系人，但每位都从完整历史整理。每轮最多新增12次模型请求；本轮达到上限后自动继续，不设每日Token预算门槛。保留用量统计，不需要调整预算。
6. 客户资料全部分册完成后才发布最终档案；点击档案可看全部原文、资料分册和来源证据。新消息在分析期间进入时，当前快照可保存，新增部分下一轮处理；修订、排除和人工判断变化仍阻止过期结果。
7. “今日”分为今日到期、后续安排、等待回复、已完成；在待确认中核对少量关键判断。完成、暂停、改期和纠正写入该客户版本，后台不得覆盖。
8. 需要暂停时点击“暂停自动整理”。已发出的模型请求可能仍完成并计费，但不会再发下一次请求或在暂停后发布新结果。手动分析入口继续保留。
9. 网络／超时／限流会退避，认证／余额错误会暂停账号队列。处理后点击恢复；也可重试单联系人。显式重试重新生成失败响应，但复用已经验证的资料分册。

**运行模式**：`start --pilot` 只手动分析，不运行自动队列；`start --legacy` 才恢复旧模型后台。原工作台可通过 `/legacy` 查看；日常使用默认客户工作台，避免新旧任务混淆。

### 建档后如何使用

- “客户”可搜索姓名／备注／来源群，按批次阶段筛选，每页最多50位；白名单人物不会展示。
- 打开档案：“资料概览”看线索卡片与原文、分册及版本；“完整时间线”按首次接触顺序分页，也可搜索单号或正文。搜索只影响展示。
- “批次与行动”看每批进展、待办和关键确认。已经核对实际走货时，可展开“人工确认批次阶段”选择阶段并填写依据；人工判断优先，必要时可恢复自动判断。
- 当前行动可“生成跟进草稿”，使用相同文本分析授权；对照来源编辑后复制，回微信人工发送。草稿不会自动发送或标记已联系。
- 发送或收到反馈后，在“人工跟进”填写实际内容。可只记客户记录，或关联一项待办并保持、等待、完成、取消，设置下次日期。保存后后台更新档案，不把已联系当成已发货。
- 确认、跟进和批次判断并发修改会检查版本；提示版本冲突时关闭并重新打开档案，再核对最新内容。

### 核实线索和查看分册

“资料概览 → 查看已保存资料分册”可反复展开／收起，首次打开才读取本机保存的分册，再次展开保留当前内容，不调用模型。SELF表示你自己的工作微信，派生摘要显示“我方”；只引用我方发言的背景卡标为“我方（工作微信）”。原始聊天不改写。

“待核实线索”中展开“核实或编辑这条线索”，对照来源修改内容，并勾选已确认属于当前客户，再保存为已核实资料。只保存客户资料，不直接创建待办或改变批次。与此客户无关或不成立的内容点击“不采纳此线索”。

处理结果在“已处理线索”保留，可撤销，恢复待核实；撤销核实会撤回该条人工核实资料。人工结果写入客户版本，相同内容与来源修订的线索不重复提出；原文修订后需重新核对。其他尚未保存的线索编辑会保留。详情页签支持方向键、Home、End切换，打开详情保留客户列表筛选。

### 图片如何进入分析

在详情的来源证据或完整时间线，点击“查看图片与识别文字”。wx-cli可提供的原图／缩略图会在本机缓存，页面明确标记缩略图。

1. 可点击“在本机识别文字”。Mac使用随包提供的Apple Vision脚本，需要可用的Command Line Tools（`xcrun`）；其他环境若安装Tesseract则使用本机语言包。
2. 没有识别工具时仍可对照图片手填文字。OCR候选不直接进入模型；核对单号、货量、单位、币种、有效期和费用条件后再确认。
3. 点击“确认文字并用于后续分析”后，文字按消息修订与图片哈希保存版本，相关客户重新排队。原图／原聊天不修改，图片不发送给DeepSeek。
4. 改正文字会使旧派生证据过期；等待重新整理后再处理相关建议。图片的布局和未填写内容仍可能缺失，所以媒体覆盖提示不会自动消失。

Mac Vision尚需用户实机验收；不保证复杂价卡表格能正确还原。识别失败可手填，源端图片不可用时应先在微信中下载原图，再点击“重新读取原图”绕过本机缓存重读；仍失败则检查wx-cli媒体能力。

### 联系人列表为空或按钮不可用

联系人来自当前账号正常跟进范围的本地归档：私信按会话对象识别，群聊按实际发送者识别，不依赖旧客户库或先运行模型。查看列表不需要模型授权、不消耗 token；人物／会话白名单仍然排除。

页面显示归档消息、正常跟进会话和可识别联系人数量，并提供搜索与「刷新联系人」。按提示处理：

| 提示 | 处理 |
| :--- | :--- |
| 尚未绑定工作微信 | 点击连接设置，确认当前工作账号 |
| 当前账号尚无归档消息 | 检查 wx-cli、采集状态、绑定账号及数据目录；已有记录不要重新 init／导入 |
| 暂无正常跟进会话 | 检查会话范围与人物白名单，只恢复真正需要跟进的来源 |
| 暂未找到可选联系人 | 检查人物白名单和源端身份信息；未知群成员不靠模型猜测 |
| 没有匹配的联系人 | 清空搜索或尝试其他备注／昵称 |
| 待就绪 | 选中后查看具体原因：未开启分析授权、缺少 key、来源未授权或没有完整文本 |

修改设置后返回整理页，点击「刷新联系人」。未授权时联系人仍可见，但分析按钮不可用；不会自动扩大外发范围。`--pilot` 模式下新引擎仍需手动点击分析，不会因开启账号授权自动分析全库。

CLI可选入口（contact为本机真实来源ID，页面选择通常更方便）：

```bash
uv run wechat-agent rebuild inspect
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent rebuild analyze --contact '联系人的source_id'
```

inspect只读现有归档，不联网、不调用模型；analyze使用相同文本分析授权。运行命令时不要粘贴API key或解密密钥。

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

不要删除数据库，不重复导入 demo。启动时会事务迁移旧数据库到 v14；迁移前的旧备份应保留，旧版应用不保证能打开新版库。

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

启动本机wx-cli后，按上方 `start` 进入“设置”，检测连接并明确确认工作账号。系统发现私信和普通群聊；仍需授权相应来源才可发送文本给模型。名称来自微信元数据，不需要模型猜测。

检查本机可见归档：

```bash
uv run wechat-agent archive status --details
uv run wechat-agent rebuild inspect
```

需要首次初始化或补历史时使用已有 `archive init-all --account 当前工作账号`、`archive resume`；不要与start的归档循环并行操作。隐藏、删除、未同步历史不保证读取；unknown sender、隔离行、缺稳定ID单独报告。SIP提示或status误报不应单独作为重装微信的依据。

## 一个备用文件入口

新版“设置 → 补充导入聊天记录”提供CSV／JSON／JSONL导入预览，CLI共用标准格式；不依赖wechat-export专有格式。示例：

```json
[{"source":"manual","account_id":"工作账号","conversation_id":"对方稳定ID","conversation_type":"private","source_id":"稳定消息ID","sender_id":"对方稳定ID","direction":"incoming","event_time":"2026-11-08T09:00:00+08:00","message_type":"text","text":"请确认本批附加费"}]
```

```bash
uv run wechat-agent import /路径/messages.json --account 当前工作账号 --preview
uv run wechat-agent import /路径/messages.json --account 当前工作账号
```

CSV列名相同。时间包含时区。新版页面上限750KB（传输请求上限2MB），CLI上限64MB；错误文件不部分写入，导入按已有会话授权执行；新会话是否继承授权取决于已保存的账号include-new设置。跨source命名空间不盲目认定重复消息。

## 没有产出时怎么看

| 现象／错误 | 检查 |
| --- | --- |
| 页面显示 cross_site | 页面入口被旧版跨站校验拦截；更新代码后Ctrl+C停止旧工作台，再运行start，从浏览器地址栏打开 http://127.0.0.1:8765/ 。只刷新页面不会更新已启动进程的后端代码 |
| 没有可选联系人 | 工作账号绑定、归档、会话授权、人物及会话免跟进；来源人物不等于已确认客户 |
| blocked_policy／blocked_credentials | 设置中检查授权与DeepSeek key |
| customer_paused | 此客户已手动暂停；在整理进度点击“继续分析” |
| workspace_fact_schema／workspace_fact_truncated | 分册输出格式不合法或被截断；更新后点“重试分析”，复用已整理分册，无需重导 |
| workspace_already_running | 同一联系人正在其他请求／进程分析，完成后再试 |
| workspace_stale_input | 分析期间来源、范围或人工状态改变；当前结果未覆盖新状态，再次运行 |
| workspace_stale_evidence | 原文修订或范围变化；旧档案暂时隐藏，重新分析有效来源 |
| workspace_model_schema／unknown_evidence | 模型输出契约／引用错误，查看安全错误码；不用发送聊天正文或key |
| 资料覆盖有限 | 存在未读媒体或待核实事实；已归集的事实保留，相关行动需关键确认 |
| 候选／非目标客户 | 商家角色证据不足，或判断为同事／服务商；不会硬凑客户与任务 |
| 近期有新进展待整理 | 原有行动不立即推荐，重新分析此联系人 |

客户工作台“整理与进度”按客户展示、最新更新在前，每页20位，仅显示未完成任务；旧“分析概览”仍描述原队列。设置监控里的 `pilot_manual` 表示等待手动试点，不代表模型故障。

## 网络与用量

用户当前已验证模型代理为7897；wx-cli仍走本机9100。无key连接检查：

```bash
curl --noproxy '' --proxy http://127.0.0.1:7897 --connect-timeout 10 --max-time 20 -sS -o /dev/null -w 'HTTP %{http_code}\n' https://api.deepseek.com/models
uv run wechat-agent diagnose --network
```

HTTP401表示未带key但连通。源服务连通不代表DeepSeek连通。TLS验证保持开启。未建立连接的请求释放预留；ReadTimeout等保留费用不确定记录，不清空历史账单。成功响应保留后可重放解析，相同已完成输入复用文档；已发送但丢失响应时不能保证不重复计费。

本地运行会将获准的相关脱敏文本发往DeepSeek；不发送解密密钥或图片原件。OCR候选先保存在本机，只有人工核对确认后的文字才进入后续分析；图片仍可能有布局或条件缺失，不能把它当作无需求。

## 备份与恢复

```bash
uv run wechat-agent backup /安全路径/wechat-agent-backup.sqlite3
```

同时保留media/、source-binding.json、wx-cli密钥配置和系统凭据存储。备份不自动包含这些文件。不要提交Git或上传聊天。

新引擎存储独立，未删除旧客户／任务。如需恢复旧后台，停止服务后显式带 `--legacy` 启动；两套业务结果不会自动互相合并。若需回退旧代码，在独立目录使用升级前备份，新版数据库与后来采集的记录必须保留；不要用旧备份覆盖唯一现库。

真实效果按 [产品方案的效果验收](PRODUCT_DESIGN.md#效果验收) 抽查同人跨群、同批后续回复、已发货、人物排除及人工判断。代码回归和模拟模型测试不代替用户本机业务验收。

### 分册暂停、待核实与安装错误

- 整理页按客户展示原始资料整理、分册合并、最终总结及暂停状态。完成项自动移出列表，档案仍在“客户”。每页20位，最新更新在前。未开始项点“开始分析”，已有进度点“继续分析”，失败项点“重试分析”；只有实际运行中的任务提供“暂停分析”，暂停处理中按钮禁用，结束当前请求后再提供继续入口；已完成分册复用，尚未完成不覆盖原档案。
- 单客户暂停跨刷新、重启、新消息和全局开关保留，不影响其他客户。已发出的模型请求无法撤销，可能计费；返回后不再继续调用或发布该轮档案。自动整理开启且后台可用时进入队列；全局已停或没有后台时，单次开始／继续仅分析所选客户。卡片、手动联系人入口与CLI共用同一执行服务，无需先暂停再继续来启动任务。
- 新版不设每日Token限额，设置只保留文本外发授权和用量统计。旧预算暂停任务升级后恢复排队；此前已手动暂停的客户仍需手动继续。
- 客户详情“完整时间线”可分页查看全部相关聊天，“资料概览”可展开／收起已保存分册。分册包含其他参与人的上下文，不能全部当作该客户的事实。
- 数字／日期格式差异只标记数字字段待核对，不删除整个批次。客户归属不明或运输术语错误的推断在待核实区保留原文，不能当作已确认事实。
- `workspace_empty_factbook`：模型没有整理出分册事实，系统停止而不是宣称读完；`workspace_summary_not_reduced`：分册合并未收敛，已完成分册仍保留。错误不等于客户没有需求。
- 旧版 `annotated-types==0.8.1` 404 已修正，正确依赖是 `annotated-types==0.8.0`。无需换镜像或重装Python，更新后重新 `uv sync --frozen`。

发布时只更新项目自身版本，用 `uv lock` 管理锁文件；禁止全局替换第三方版本。发布前验证独立虚拟环境 `uv sync --frozen`。当前未接入经验学习功能。
