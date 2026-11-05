# 从零部署、微信接入与日常使用 SOP

适用：个人工作 Mac、本地 wx-cli、DeepSeek API。当前应用 v0.5.4、数据库 v8。目标设计与尚待交付项见 [改造设计](AI_CRM_DESIGN.md)。

## 已有数据用户：更新后这样使用

先停止旧 serve／collect／worker（Ctrl+C），避免新旧后台同时运行。保留原数据目录，不用重新 init、demo、导入或删除数据库。

```bash
git pull origin main
uv sync --frozen
# wx-cli 已运行则无需重复启动
~/.local/bin/wx-cli server run --host 127.0.0.1 --port 9100
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent start
```

打开 http://127.0.0.1:8765；另一终端查看本地登录口令：

```bash
uv run wechat-agent token
```

进入“设置”：确认工作账号 → 保存 DeepSeek API key（已有可跳过）→ 设置每日 token 预算并确认文本分析范围 → “开始自动整理” → 在“管理免跟进白名单”把同事／纯服务商的私信和群聊加入免跟进名单。**不创建商家、不创建项目、不逐群绑定、不逐条接受建议。** 然后回“今日跟进”等待后台产出结果。

`start` 统一运行 Web、采集、历史补齐和分析；`serve` 也采用相同后台行为。浏览器关掉不影响进程，终端退出或 Mac 休眠会暂停。恢复后重新 start，从断点继续。不要同时另外运行 collect／worker；这些命令仅保留用于诊断。

旧库升级前会在原数据目录生成 `pre-v8-*.sqlite3` 一致性备份，消息主键不变；旧人工事项保留。备份不包含媒体文件，完整恢复仍需保留 media/、账号绑定和凭据。旧版未审核建议不会批量转成新任务。

## 免跟进白名单、监控和待确认清理（v0.5.4）

**白名单内不做跟进；名单外默认正常整理。** 这是对 v0.5.3 规则的调整。升级前停止旧进程，启动时自动备份为 `pre-v8-*.sqlite3`，已有聊天／客户／行动／用量保留，无需重导。上一版“允许分析会话”的选择不会被反向解释成免跟进；升级后免跟进名单初始为空，请把需排除会话加入。账号授权与预算继续生效，不会绕过暂停开关；已授权账号会恢复名单外的分析。

1. 设置中点击“管理免跟进白名单”，直接查看已排除会话。切换“全部会话”可搜索名称／ID、筛选私信／群聊并批量加入；勾选名单项点击“移出白名单”即可恢复跟进。
2. 名单按整个会话生效。加入同事私信／纯服务商群后仍继续归档，但不触发客户建档、模型分析或今日跟进，也不作为模型辅助上下文。包含商家的三方群可以保持正常跟进。当前不支持只排除群内单个成员，同一个人其他会话仍按各自会话规则处理。
3. 加入后未完成分析暂停、相关历史行动退出今日推荐；移出后恢复已授权分析，已成功且未变化的数据不重复调用。已发出的请求无法撤回，用量不清零。
4. 设置顶部“连接与后台状态”分别显示工作台、wx-cli／账号绑定、采集与历史补齐、DeepSeek 分析后台。进入设置自动检测，也可点击“检测全部状态”；这一步只探测本机 health、读数据库心跳，不读聊天、不调用模型。“需留意”可能是尚未授权、后台未启动或状态更新较旧，不能直接等同于微信离线。wx-cli 正常不代表 DeepSeek 网络正常，外网问题仍用 `wechat-agent diagnose --network` 排查。
5. 升级会一次性清除当前账号现有 pending 待确认，之后到“待确认 → 一键清空待确认”可再次清空。仅标记为 cleared，已确认的判断保留，也不会把清除当成模型业务结论。清空后新识别出的关键问题仍可出现；同一已清除问题不会因列表刷新而恢复。
6. 到“分析概览”核对近期队列与具体错误，再抽样核对真实客户、证据、计划时间及新回复更新。未来到期计划不提前进入今日列表；不含商家需求的会话分析成功也可能无客户产出。

当前先复用直接 DeepSeek 调用，Harness 暂缓。模型效果仍需你的真实 Mac 验收，本仓库模拟与浏览器测试不代表真实提取质量。Clash Verge 当前7897混合端口沿用上面的 `DEEPSEEK_PROXY` 启动方式。

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


## 5. 首次启动与接入全部工作会话

微信登录正确工作账号，已有有效密钥并成功解密后：

```bash
~/.local/bin/wx-cli server run --host 127.0.0.1 --port 9100
uv run wechat-agent start
```

打开工作台“设置”，检测本机连接，确认工作账号。后台自动发现源端可见的私信与群聊，增量采集与历史分批补齐；不要求手工运行全量归档命令。排除系统号／公众号，不保证未同步、隐藏、删除消息可读取。

DeepSeek key 可在页面保存到系统凭据存储，或在本机终端执行：

```bash
uv run wechat-agent credentials DEEPSEEK_API_KEY
```

确认账号级授权后，名单外工作会话正常分析，新会话默认正常跟进。可在设置的免跟进白名单排除同事和纯服务商会话；消息档案单会话外发授权仍是独立开关，白名单不能绕过外发暂停。首次分析优先最近 15 天，再补更早历史；导入完成、分析完成、媒体理解是三件不同的事。

本地运行不等于数据不外发：获准的脱敏文本经 HTTPS 发往 DeepSeek，密钥、整库、图片原件不外发。当前为文本分析，媒体标明尚未自动理解。

## 6. 每天怎么用

1. **今日跟进**：查看客户、联系对象、下一步、原因和日期；默认最多 10 张，剩余事项在“全部计划”。没有到期事项就显示空状态。
2. **查看依据**：回查原始消息及修订；来源修订后旧依据不再用于起草。图片可按需从本机读取，显示原图／缩略图质量，不等于 OCR。
3. **查看话术**：按需调用模型生成简短草稿，自行编辑、复制并在微信发送。复制不会记录联系，也不会完成任务。
4. **记录结果／改期**：电话或线下结果补充一句；可标等待、完成、不再推进。人工完成、取消和改期受保护，后续模型不静默覆盖。
5. **客户**：查看自动提取的需求、顾虑、机会和私信／群内发言。来源明确展示；不知道公司名也可以正常建档。
6. **待确认**：仅处理角色／归属冲突等关键问题，补充判断作为后续分析依据。常规客户和待办自动生效。

消息默认折叠空文本和简短寒暄／确认，不删除记录；“查看全部消息”能恢复。数字、日期、否定、问题、附件保留。当前是保守过滤，不能把“未被过滤”理解成 AI 已判定高价值；模型仍读取完整上下文。

历史超过 30 天、无新证据的旧承诺保留为历史未决，不堆进今日逾期。新回复可更新／完成对应任务，不能把“收到／已建群”当作平台备货完成。私信实际外发自动记联系记录，不自动证明事项解决；群聊外发的具体客户归属仍依赖分析。

## 7. 唯一备用入口：文件导入

一般使用 wx-cli 即可。设置 → “备用：手动导入文件”，选文件 → 预览 → 确认导入。支持同一种标准消息结构的 CSV、JSON、JSONL，不再维护 wechat-export 专用字段转换。

```json
[{"source":"manual","account_id":"当前工作账号","conversation_id":"对方稳定ID","conversation_type":"private","source_id":"稳定消息ID","sender_id":"对方稳定ID","direction":"incoming","event_time":"2026-11-05T09:00:00+08:00","message_type":"text","text":"请确认本批附加费"}]
```

CSV 采用相同列名。时间须含时区，群聊使用 group；相同 source／账号／会话／消息 ID 去重。不同 source 命名空间不会自动认定为同一条源消息，避免盲目去重。

页面上限 1.5 MB，CLI 使用同一个导入实现支持最多 64 MB：

```bash
uv run wechat-agent import /路径/messages.json --account 当前工作账号 --preview
uv run wechat-agent import /路径/messages.json --account 当前工作账号
```

错误文件不部分写入；手动导入不会隐式授权外发。标准导入会话仍受账号分析授权、外发开关与免跟进白名单控制。无需运行任何旧导出项目。

## 8. 检查进度与异常恢复

“设置 → 消息档案与运行诊断”查看归档缺口、隔离行和后台状态。首页显示消息量、成功分析分片数和总数；分片数会随新消息和修订增加，不等于消息分析百分比。首次全历史未完成时，客户结果属于初步档案。

| 状态 | 处理 |
| --- | --- |
| awaiting_account | 检测本机源服务并确认工作账号 |
| awaiting_authorization | 设置中确认 DeepSeek 分析范围 |
| blocked_credentials | 本机核对 key／模型权限，修正后“重试失败分析” |
| blocked_budget | 提高预算后重试，或等待北京时间次日自动恢复 |
| retry_wait／failed | 暂态错误有限重试；失败后在设置重试，不删除数据 |
| blocked_context_limit | 个别超长消息明确阻塞；不会静默截断冒充已完成 |
| 来源已变化 | 已排除旧修订证据，等待相关片段重算 |
| collector error | 检查微信、wx-cli、当前账号与本地端口；诊断不打印敏感正文 |

默认每日 100,000 token、并发 1、每任务最多 3 次调用，含重试的保守预算预留。时区为 Asia/Shanghai；实际费用看 DeepSeek 账单，不保证全历史当天处理完。分析暂停后采集仍可运行；已发出请求不能收回，但撤销授权后禁止结果写入。

需要单独检查本地全量状态时：

```bash
uv run wechat-agent archive status --details
```

scanned 表示源端查询完成，不保证所有历史存在；sender 缺失、无稳定 ID、异常行单独保留，不伪造补齐。

## 9. 备份与验收

停止应用后可执行：

```bash
mkdir -p "$HOME/Wechat-Agent-backups"
uv run wechat-agent backup "$HOME/Wechat-Agent-backups/agent-$(date +%Y%m%d-%H%M%S).sqlite3"
```

另保留媒体 media/、source-binding.json 与 wx-cli 密钥配置。不要把这些文件提交 Git 或上传聊天。回退用迁移前备份和旧代码，在独立目录恢复；新库保留，不能用旧代码直接打开 v8。

实机验收：选择一个近期真实需求，核对客户身份、归属、事实证据、责任方、日期和生成行动；正常产生一条回复，检查对应事项更新；检查重启续跑、暂停授权和重复导入。真实 API 成功不等于事实提取准确，还须抽样核对。

当前开发环境只验证模拟 wx-cli／DeepSeek 和真实 Chromium，不具备你的 Mac 数据或真实 API key。OCR／价卡结构化、公司主体合并、素材驱动激活等仍按设计后续交付，不能视为本版已实现。

## 10. 昵称、近期优先与分析概览（v0.5.1）

更新后停止旧 start，再 `git pull origin main && uv sync --frozen`，运行 `uv run wechat-agent start`。无需删除归档、任务或数据库。源服务返回的账号昵称会自动保存，设置中优先显示昵称，wxid 仅辅助核对；源端不提供昵称时保留真实 ID，不伪造名称。

新调度器自动替换旧的未完成全量队列，保留可验证的成功结果。近15天按较小上下文分片，每轮最多8个近期分片；近期未处理完时更早历史等待。历史阶段每次调度一个分片，并保留20%日预算给近期新增消息和按需话术。纯寒暄／确认的独立窗口可本地标记无需模型分析，混合业务窗口仍保留完整上下文。

首页点击“查看分析进度”，或打开“分析概览”。可查看：

- 近15天／更早历史的完整文本总量、已分析、无需分析和待处理量；媒体、残缺文本单列，不冒充已理解。
- 运行中、入队、后台待调度、失败、等待预算等状态，以及逐分片会话昵称、时间范围、消息数、尝试次数和安全错误码。
- 今日 API 已报告用量、未确认预留、可用余额及近7天原始请求记录。token 预估有余量但不等于精确账单；最终以服务商账单为准。
- 连续失败、凭据错误、限流或预算不足时的暂停原因和自动复查时间。修正原因后可“恢复／重试分析”。

升级不会把真实已消耗额度清零。旧版本明确凭据拒绝造成的预留可自动释放；其他未确认预留仍保留。如核对 DeepSeek 今日账单确认与本机预留不一致，可在预算面板展开“未确认预留与账单不一致”，填写已确认的今日总token，校正本机预算；原始请求记录保留，不修改服务商账单。请求仍在进行时不能校正。

视觉展示名为“半托管欧区备货用户助手”；CLI 名称和仓库路径保持不变。页面动效遵循系统“减少动态效果”，刷新不会重播整页动画，也不会打断填写或消息核对。

### 连续失败暂停：先看错误，再恢复

“连续请求未成功”是保护性暂停，不代表仍未入队，也不能据此判断余额或网络。分析概览暂停提示会显示最近失败的具体错误与处理方向，可“复制诊断信息”；诊断不含聊天正文、账号ID或API key。

终端也可运行 `uv run wechat-agent diagnose`。该命令只读取本机状态，不发起模型请求。若仍使用旧界面，可在“分析队列”筛选“需要关注”，查看原有错误码。HTTP_402 是模型账户余额问题；ReadTimeout 是响应超时；model_schema／model_unknown_actor 等表示输出校验失败，需修复契约，不能通过调高预算或关闭证据校验解决。


### ConnectError：双网卡／Clash连接排查

ConnectError 是模型连接阶段失败，不是聊天入队、JSON提取或每日预算问题。先用同一个启动终端运行 `uv run wechat-agent diagnose --network`：只向官方 `/models` 发出无 key 的 GET，不发送聊天，不调用推理；返回 HTTP 401 表示该无鉴权自检已建立连接，但不验证模型权限。

输出会区分 DNS、连接拒绝、路由不可达、证书校验失败等，且不打印代理地址／密码、证书路径或聊天。分析请求与自检使用相同代理及 CA 配置。默认沿用 Python 系统／环境代理；不会在失败时偷偷改走其他出口。

Clash Verge 应以设置面板的实际混合端口为准，配置文件里的 mixed-port 可能被客户端覆写。本次实际端口为 7897，可只对本应用的模型请求指定 HTTP 入口：

```bash
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent diagnose --network
```

确认连接成功后，停止旧 start，再以相同配置启动：

```bash
DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent start
```

然后在分析概览点“恢复／重试分析”。本地 wx-cli 仍通过回环地址读取，不使用该模型代理。此变量只选择模型客户端的代理入口；实际外网出口仍由 Clash 规则决定。

若要明确不使用 HTTP／系统代理，可以设置 `DEEPSEEK_PROXY=direct`；这不等于绕开 TUN 或网卡路由。指定路由仍尊重 SSL_CERT_FILE／SSL_CERT_DIR 并保持证书校验；证书错误应修复 CA 配置，不能关闭校验。

对于“ChatGPT域名走代理、其他 MATCH DIRECT-HOTSPOT”的分流，DeepSeek 会走热点直连，不会自动使用 ChatGPT 策略组。无需为了调用 DeepSeek 改动公司内网规则。


### 责任方字段校验与近七天用量（v0.5.2）

`model_schema:actions.*.party` 表示模型已返回结果，但责任方字段不符合契约，并不是网络或预算问题。新版统一为 self／merchant／service_provider／other／unknown，并将明确的中英文角色别名转换为标准值；姓名、微信ID、多方混合值仍不能充当角色。未知或空责任方记 unknown，不默认指派给我方；身份和证据校验继续严格执行。

更新后用原来的 `DEEPSEEK_PROXY=http://127.0.0.1:7897 uv run wechat-agent start` 启动，在分析概览点击“恢复／重试分析”，重新处理未成功分片。此操作不重复创建已成功的任务；失败响应未被保存为可重放模型结果，因此可能产生新的 API 请求用量。

近七天用量固定展示北京时间最近7个日期，无请求日期显示零值；绿色柱为已报告／已核对Token，浅色纹理柱为未确认预留，明确区分“实际报告”与“尚未确认”。点击或键盘选择日期可查看精确值与请求数。账单校正会同步反映在今日预算和该日图表中，原始记录继续保留。模型结果校验失败也可能已消耗Token，不能将“任务尚未生成”理解成“没有调用或没有用量”。
