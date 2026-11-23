# Mac 更新与验证

更新：2026-11-16（北京时间）。云端负责开发，Mac只更新、运行和验证。你已安装项目补丁版wx-cli，本次只执行下面1—4步；**无需重装Rust或wx-cli；依赖是否变化以锁文件为准，第2步可重复执行**。首次安装单列在文末，旧阶段命令见[历史归档](archive/verification/mac-setup-history.md)。

<a id="update-repository"></a>
## 1. 停止应用并更新代码

先在运行8766应用的终端按Ctrl+C停止旧API；保持9100的wx-cli服务运行。在项目目录执行：

```bash
cd "$(git rev-parse --show-toplevel)"
git status --short
```

有不清楚的本地修改就保留并反馈，不reset或强制覆盖。工作区无待处理修改后执行整个代码框；括号内set -e遇错即停：

```bash
(
  set -e
  git switch main
  git pull --ff-only origin main
  git merge-base --is-ancestor 0b42eac HEAD
  test -f src/wechat_agent/api/messages.py
  test -f src/wechat_agent/profiles/manual.py
  test -f src/wechat_agent/analysis/runtime.py
  test -f src/wechat_agent/storage/migrations/014_model_budget_reviews.sql
  test -f src/wechat_agent/storage/migrations/015_operation_reports.sql
  git log -1 --oneline
)
```

通过标准：pull成功，包含原文查询优化交付提交0b42eac，原文与人工资料接口文件存在。以本次交付的最新main为准，该祖先检查只排除仍在运行旧阶段代码的情况。**pull失败就先处理连接，后续旧版测试成功不算完成更新。**

SSH连接失败时，可临时指定22端口再重跑上框：

```bash
export GIT_SSH_COMMAND='ssh -o HostName=github.com -p 22 -o ConnectTimeout=15'
```

若仍失败，运行`ssh -vT -o HostName=github.com -p 22 -o ConnectTimeout=15 git@github.com`；认证成功以`Hi ... You've successfully authenticated`为准（GitHub不提供shell，退出码1可以正常）。22端口被阻断时可改用`ssh.github.com:443`：

```bash
export GIT_SSH_COMMAND='ssh -o HostName=ssh.github.com -p 443 -o ConnectTimeout=15'
```

198.18.x.x可能是本机代理的Fake-IP映射，不能当成GitHub真实地址，也不能据提前关闭连接断定密钥失效。两个端口均不通时先检查代理/TUN对github.com、ssh.github.com的路由，不继续安装或清库。

<a id="build-app"></a>
## 2. 检查并构建

```bash
(
  set -e
  .venv/bin/python --version
  node --version
  .venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
  .venv/bin/python -m pip install --no-deps --no-build-isolation -e .
  .venv/bin/python -m pytest -q
  npm --prefix frontend ci --engine-strict
  npm --prefix frontend run build
)
```

通过标准：Python3.12.x、Node24.14.1或更高24.x，后端测试和前端构建均成功。最近完整云端验收及其对应提交统一见[状态页](STATUS.md)；本地结果按本次实际输出判断。已有.venv无需重建；Mac不需要运行浏览器开发测试。

<a id="start-app"></a>
## 3. 启动正式应用

复用现有来源配置和数据库：

```bash
.venv/bin/python -m uvicorn wechat_agent.api.app:app_factory --factory \
  --host 127.0.0.1 --port 8766
```

保持终端运行，在浏览器打开 http://127.0.0.1:8766 ，刷新页面。另一终端检查：

```bash
curl -fsS http://127.0.0.1:8766/api/health
```

通过标准：`{"status":"ok","schema_version":18}`。启动会按既有迁移升级数据库，保留原文和人工身份；不清库、不降级。原型8765及Vite开发端口5173不是正式应用入口。

若出现来源配置错误，核对既有`.local/config/source.json`的base_url与expected_account_id，沿用token_env，不把凭据贴到聊天。原文浏览和手动导入使用已归档数据，不需要再次全量同步。

<a id="report"></a>
## 4. 验证新增入口并回传结果

依次检查：

1. 工作台业务活跃联系人／设置全量管理，核对搜索、身份、人工移出不被同步加回。
2. 联系人沟通原文：日历、当天所有人物、本人高亮及箭头定位；日期／来源／关键词范围一致，回到最新不隐式同步。边缘滚动自动补页，不再有加载更早／更多按钮。系统通知隐藏、特殊消息摘要、复制反馈位于弹窗上方。
3. 设置CSV／JSON导入先预览，再确认，重复导入不增行；附件仅访问库内已存在且位于应用附件目录的安全文件。来源获取与解析仍待M3。
4. 模型配置和主动连接检查按文末任务3步骤验证；连接通过不代表容量／视觉通过。每日自动执行尚未接通，不报告计划执行成功。

回传版本、测试摘要和脱敏现象即可，不发送原始聊天库、API密钥或附件原件。完整Mac证据单列，不把云端回放冒充实机通过。

## 首次安装时再看

首次下载：`git clone git@github.com:EligahYy/Wechat-Agent.git`，进入项目。没有虚拟环境时执行：

```bash
(
  set -e
  python3.12 -m venv .venv
  .venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
  .venv/bin/python -m pip install --no-deps --no-build-isolation -e .
)
```

新机器按下面两个来源步骤安装并启动；已有0.7.4+wechat-agent.2服务的机器跳过。然后在`.local/config/source.json`明确绑定health返回的canonical账号，格式见[来源配置](verification/source-capabilities.md#来源配置)。已有机器保留配置。继续回到第2步构建应用。

<a id="install-source"></a>
## 首次来源安装：补丁版wx-cli

先检查编译依赖：

```bash
cargo --version
cc --version
```

若没有cargo，使用已有Homebrew执行`HOMEBREW_NO_AUTO_UPDATE=1 brew install rust`；若缺少Apple命令行工具，执行`xcode-select --install`并完成安装。安装完成后再继续；不需要在Mac修改源码。

```bash
(
  set -e
  test -f scripts/install-wx-cli.sh
  bash scripts/install-wx-cli.sh --transport ssh
  .local/tools/wx-cli/0.7.4+wechat-agent.2/bin/wx-cli --version
)
```

通过标准：最后显示`wx-cli 0.7.4+wechat-agent.2`。安装器下载固定上游源码、应用已校验补丁并编译；首次会下载Rust依赖。不覆盖原`~/.local/bin/wx-cli`，不自动切换正在运行的服务。脚本不存在说明代码尚未更新完整。

<a id="switch-source"></a>
## 首次来源启动：确认版本

将`wxid_your_account`替换为已验证的工作账号。保留你原有的自定义启动参数（如数据目录或鉴权）；不要启动另一个账号。先停止旧服务：

```bash
~/.local/bin/wx-cli server stop
```

看到已停止后才启动项目版本：

```bash
.local/tools/wx-cli/0.7.4+wechat-agent.2/bin/wx-cli server run \
  --host 127.0.0.1 --port 9100 --account wxid_your_account &&
curl -fsS http://127.0.0.1:9100/api/v1/health
```

通过标准：health中ready=true、cli_version包含`0.7.4+wechat-agent.2`；metadata中patch_id=wechat-agent.2、refresh_state=ready，generation与resolver_generation一致。若显示“server already running”且health仍是旧版，先处理未停止的旧worker，不进入下一步。启用Bearer鉴权时沿用本机凭据，不将token贴到聊天。


回退来源时先用项目版本server stop停止，再用原~/.local/bin/wx-cli server run及原参数启动；应用会拒绝未修复的群消息归属。保留数据库，不清空或降级。模型与媒体实测按后续交付安排。

## 验证任务3：模型配置与业务范围

在项目根目录执行（云端推送后）：

```bash
(
  set -e
  git switch main
  git pull --ff-only origin main
  .venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
  .venv/bin/python -m pip install --no-deps --no-build-isolation -e .
  .venv/bin/python -m pytest -q
  npm --prefix frontend ci --engine-strict
  npm --prefix frontend run build
)
```

按前文方式重启应用，健康接口应报告schema_version=17。本轮无需重装wx-cli。

1. 确认左上角EU、工作台业务活跃联系人及设置→管理全部联系人。先搜索一名联系人，手动移出，再同步，确认不自动回来；在全量管理重新加入。
2. 设置→配置模型，按服务文档填写HTTPS完整chat-completions地址、准确模型ID、响应格式和声明容量。首次填写密钥，保存后页面应留空；密钥只写本机Keychain。
3. 如需验证连接，主动点击“检查连接”（一次最小付费请求，不含客户资料）。未点击不调用模型。此检查不验证容量、图片或真实整理质量。
4. 近90天实际群发言、群名片和需求归属需用真实样本核对。未有经验证的运行时能力／分类结果时显示“群需求识别待完成”，保守保留候选。模型档案发布闭环已接通；真实业务质量按文末任务6—7清单核对，不将来源同步成功当作档案生成成功。

排障时提供脱敏结果即可，不发送API密钥、完整联系人库或聊天原文。


### DeepSeek 配置参考

模型配置使用完整的 OpenAI 兼容 chat-completions 地址；直连 DeepSeek 官方服务可填写 `https://api.deepseek.com/chat/completions`。第三方网关必须使用该网关的地址、密钥和模型 ID，不能混用。

| 页面字段 | 建议起点 |
| --- | --- |
| 模型 ID | 以当前服务控制台／模型列表的精确 API 标识为准 |
| 响应格式 | JSON 对象（`json_object`）；只有服务明确支持时才选 JSON Schema |
| 上下文上限 | 服务支持至少此额度时，可先设 `32768` |
| 最大输出 | 服务支持至少此额度时，可先设 `8192`；若返回截断，应结合服务上限调整 |

上述容量是保守的应用处理预算，**不是供应商标称最大容量**。截至2026年11月15日本次排查，云端访问官方文档被网络代理拒绝，尚未核实用户提及的 `v4.1-flash` 对应的精确模型 ID、容量或专用请求参数，因此不内置同名预设，也不把营销名称自动转成 API 标识。参数应对照[官方模型文档](https://api-docs.deepseek.com/quick_start/pricing)和实际服务控制台填写。

当前页面不提供 temperature、top_p 或思考模式开关，连接检查和网关请求也没有主动发送这些参数，沿用服务默认值。若该模型需要专用思考开关，应先确认官方协议再接入，不能仅靠改模型名称假定兼容。保存后主动检查连接；通过只表示一次最小 JSON 请求成功，仍不代表容量／视觉验证或生产整理链路已接通。

### 整理记录排障

整理记录支持点击条目原位展开，再次点击收起；快速换选会取消旧详情请求。历史记录中的“来源同步不完整”应在展开后查看具体来源缺口；“档案整理尚未接入”与来源读取失败分别处理。


## 验证M2任务6—7：客户资料与真实整理

当前schema17自动迁移，保持现有数据库和9100来源服务，不需重装wx-cli。按前文步骤更新、构建并重启8766。

设置→配置模型：保存完整OpenAI兼容chat-completions地址、准确API模型ID、格式和按供应商文档核对的预算；主动检查连接通过后，填写“预算依据”文档HTTPS地址，勾选确认文本预算。该记录绑定当前配置版本，改配置后需重新检查／核对；它是人工文档核对，不是容量实测，也不启用视觉。预算核对本身不发送模型请求。

先选一位业务范围内的已确认商家，在客户页点“同步并整理此客户”。消息同步完成后会执行实际模型请求并更新资料卡／备货记录；明确缺口会保留提示，文本超窗会自动分段提取、归纳；中途失败保留成功检查点和旧档案，重新同步复用有效结果。预算需包含规则、模板、结构约束、原文、输出与安全余量，32768／8192不是对任意历史可处理的保证。不要为通过而填写未经核实的窗口上限。

可直接验证编辑货品／物流／沟通、两组人工补充、单号、来源查看、重启持久化和身份头像配色。单号不自动改成已走货，模型重跑不覆盖人工值；版本冲突保留输入，核对最新版本后再保存。再同步一次，无输入变化不会重复调用档案模型；来源仍会读取最新消息。

首次实测按[单客户质量清单](verification/m2-profile-review.md)核对主体、单位、路线、旧／新批次和来源，先单客户再考虑全局，避免未确认质量时扩大付费调用。图片获取／解析及每日自动执行仍属于后续阶段；极端单字段或必要引用超窗会明确报错，不截断原文。

<a id="source-refresh-v2"></a>
## 来源刷新失败修复：升级至 `.2`

适用于启动ready、使用后反复`source_metadata_refresh_failed`的`.1`来源服务。本次需同时更新Python应用和来源工具；仅重启旧来源不能修复。保留账号配置、Keychain、应用归档及旧工具目录。先在项目目录更新并构建来源（不自动切换服务）：

```bash
git pull --ff-only
bash scripts/install-wx-cli.sh
```

GitHub通过SSH访问时安装命令加`--transport ssh`。构建完成后停止`.1`，再启动`.2`；沿用自定义数据目录及鉴权参数：

```bash
.local/tools/wx-cli/0.7.4+wechat-agent.1/bin/wx-cli server stop
.local/tools/wx-cli/0.7.4+wechat-agent.2/bin/wx-cli server run \
  --host 127.0.0.1 --port 9100 --account wxid_aiy75c1qgjcl22
curl --max-time 10 -sS http://127.0.0.1:9100/api/v1/health
```

其他账号替换上述已绑定账号。确认版本及patch_id为`.2`，并按本文第2步重启8766应用，使新的统一刷新入口生效。启动后微信有写入时可能显示stale；点击同步会先刷新，不需要反复重启。同步中途代次变化仍会停止，不能把不完整来源送给模型。若仍failed，查看stderr中的`metadata_version_read_failed`、`metadata_resolver_build_failed`或`metadata_changed_during_refresh`及原有连接错误；仅返回202不等于成功。

详细审查和边界见[来源刷新审查](verification/source-refresh-review.md)。Mac恢复及模型真实质量仍需实机验证。


## 整理范围与记录反馈更新

本轮代码启动后迁移到schema16，保留旧记录、原文和人工资料。在`.2`来源上只需执行本文1—4步更新应用；不需重装Rust／来源工具，仍在`.1`时按上面的来源升级步骤切换。首次按新覆盖策略处理已有档案可能重新调用模型，相同有效输入之后跳过。

验收：选择已确认商家执行单客户整理；未知群覆盖不再阻断已读完的已知范围，真实缺页仍阻止该客户发布。整理记录应显示客户名、同步／整理结果和可操作原因；字段待核对、模型配置错误、主动停止不能混作来源失败。待识别潜客可做业务意图发现，但不会自动改成商家身份；确认身份后才能发布商家档案。

详情与云端／实机边界见[架构及验收报告](verification/organize-outcomes-report.md)。


## M3文本长历史更新与验收

本轮从schema15自动升级16，保留原归档、档案、人工资料和任务。已使用`.2`来源时只需pull main、构建前端并重启8766，无需重装Rust或来源。核对`/api/health`的schema_version=17；新迁移文件为`src/wechat_agent/storage/migrations/016_history_checkpoints.sql`。

优先复验此前因context_requires_chunking失败的已确认商家。上下文按供应商真实支持容量配置，不需要盲目设到1M，输出设8192通常可作为起点（单次档案请求当前不超过8192，设置更大不会自动扩大输出）。点击同步并整理，确认分段提取、事实归纳、原文处理范围；完成后核对字段、主体、数量、单位与批次来源。停止或遇到故障时保留旧档案，恢复服务后重新同步，确认显示复用段数。

策略升级后已有资料可能重新处理一次；相同有效输入成功后应跳过模型。修改配置／人工资料／身份等会使相关缓存失效；同一单元的累计6次网络预算用尽后不会因再次点同步无限追加调用。附件、业务意图发现分段及真实语义质量仍不包含在这次文本验收内。


## 输出截断恢复更新

应用自动执行schema16→17增量迁移，保留已有检查点和累计请求预算。更新、构建前端并重启后，再整理原失败客户。最大输出不再固定8192，实际分配还受总窗口及必要输入影响；记录诊断可查看真实额度。多次返回由程序校验组装，不拼残缺JSON，也不自动修改供应商思考参数。见[说明](verification/output-recovery.md)。


最新输出分配修复仍为schema17，不需迁移或清库。上下文和输出是独立参数，请分别按供应商文档填写；初始输出通常不超过8192，系统按需增额／拆分。引用错误增加一次受限纠正及分类诊断，具体见[最新说明](verification/output-allocation.md)。

### 部分消息缺少稳定编号

整理记录出现 `source_message_id_unavailable` 时，wx-cli 返回的消息缺少可用于归档的正数 `server_id`。更新后从整理记录点击「重新同步」，出错会话会使用新游标从头读取；后续可识别的消息仍会归档，其他会话也会继续同步。缺少编号的原始记录保存在问题表。若缺编号是唯一的阻断原因，商家资料可基于已确认原文发布，整理记录会显示「已整理可确认消息，部分来源待补齐」，并列出受影响会话。重复读到同样的无编号记录时，需要检查来源端；本地无法确认这些记录的身份。

如只需补拉诊断详情中列出的会话，可在仓库目录执行以下命令，将两个占位符替换为工作账号和会话编号。此命令只拉消息。

```sh
.venv/bin/python -m wechat_agent.source.sync \
  --source-account '工作账号ID' --conversation '会话ID' \
  --from-start --page-size 200 --max-pages 1000
```


### 整理可靠性 v3 更新

拉取、构建并重启后，应用会从 schema 17 自动升至 18，保留旧归档和人工资料。健康接口应返回 `schema_version: 18`。首次使用新策略整理会建立新的检查点。若记录显示「整理已暂停，可继续」，打开该记录并点「继续整理」。操作详情可查看各阶段耗时和实际请求次数。详细验收见[整理可靠性 v3](verification/organize-reliability-v3.md)。


### 高价值整理试用

更新、构建前端并重启后，应用自动升级到 schema 20。在一位业务范围内的商家详情页选择「高价值整理」，完成后在「查看同步详情」核对高／中／低数量、已整理的高价值原文、模型调用数和阶段耗时。展开「查看分级与复核」可按日期和会话选择漏判原文。常规「同步并整理此客户」继续提供全量路径，可用于同样输入的对照。仅新增明确寒暄且已发布档案输入仍适用时，试用路径的模型调用数应为零。实测同时核对报价、数量、发货状态与原文引用。
