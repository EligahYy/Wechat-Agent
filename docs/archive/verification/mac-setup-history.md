# 历史 Mac 阶段验证命令（归档）

> 历史归档：保留当时方案、命令和验证结果，不代表当前实现。当前入口见[实施状态](../../STATUS.md)。

本页保存各阶段当时的命令和版本，不能作为当前安装流程。当前请只执行[Mac操作指南](../../MAC_SETUP.md)。

# Mac 拉取项目与本地验证

更新：2026-11-12（北京时间）。所有开发在云端完成，测试通过后直接推送 `main`；Mac 只拉取、安装运行依赖并验证，问题由云端修复。

## 1. 首次下载

终端运行 `git --version`。缺少 Git 时先执行 `xcode-select --install`，完成系统安装后重新打开终端。

```bash
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone https://github.com/EligahYy/Wechat-Agent.git
cd Wechat-Agent
```

私有仓库需要有权限的 GitHub 登录；也可用 GitHub Desktop 克隆。不要把密码或 token 写进仓库 URL。

## 2. 已下载项目：更新 main

先确认 `git status --short` 没有需要保留的本地修改，再执行：

```bash
cd "$HOME/Projects/Wechat-Agent"
git fetch origin
git switch main
git pull --ff-only origin main
```

此前拉取了 `codex/m0-local-foundation` 的，也按上述命令切回 main。若 Git 提示本地修改或分支分叉，保留现状，把提示发给云端处理，不使用强制覆盖。

## 3. 当前 Python 验证步骤

当前已实现M0检查工具、M1原文归档／联系人身份API、持久化同步操作及React正式工作台／设置。首次安装按下列锁文件恢复环境；已有任务3环境本次无新增依赖，无需重建虚拟环境。

需要 Python 3.12。已有 Homebrew 时：

```bash
brew install python@3.12
export PATH="$(brew --prefix python@3.12)/bin:$PATH"
python3.12 --version
```

也可从 [python.org](https://www.python.org/downloads/macos/) 安装 Python 3.12。已有其他版本可以保留；当前终端用指定版本即可。然后在仓库根目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pytest -q
.venv/bin/python -m wechat_agent.doctor --output .local/evidence/m0.json
```

测试应全部通过，数量以当前提交为准；doctor 默认不连微信、不调用模型。CLI 成功表示报告已生成，不表示微信、模型或完整历史已经核验。

Superpowers 供云端开发使用；本地执行上述验证无需恢复技能。后续 React 代码交付时，云端会补充 Node 24、构建和启动的验证步骤。

## 4. 查看现有 UI 原型

在另一终端进入仓库，执行：

```bash
python3 -m http.server 8765 --directory ui-prototype --bind 127.0.0.1
```

浏览器打开 http://127.0.0.1:8765/preview.html 。结束时按 Control+C。人物、消息和任务都是示例，原型不连接微信或模型。

## 5. 后续验证与反馈

每次云端交付后：pull main → 安装更新的锁定依赖 → 运行当次提供的测试／验证命令 → 反馈结果。每次交付会列清已实现能力和实机待验证项。

微信数据只在本机读取；模型凭据只在本地受控配置，不发到聊天或提交 Git。反馈时提供提交号（`git rev-parse --short HEAD`）、命令、版本、退出码及必要的脱敏错误，不上传原始聊天或密钥。云端据此修代码，再推 main 复验。

[六阶段开发计划](../../superpowers/plans/README.md)分别记录云端开发与本地验收，不把未实测内容标为成功。这里的命令尚未在你的 Mac 执行。

## 6. 验证已有 wx-cli 服务

来源是第三方 [pandorafuture/wx-cli](https://github.com/pandorafuture/wx-cli)，不是腾讯／微信官方工具。目前核对 v0.7.4；已有 `127.0.0.1:9100` 服务直接复用，无需重装或重启。

先只检查健康状态，不读聊天：

```bash
.venv/bin/python -m wechat_agent.doctor --check-source --output .local/evidence/m0.json
```

未明确绑定账号时 source=pending，gap=source_account_not_pinned。下一步从 `wx-cli server status` 的 Account 获取 canonical wxid（不是启动参数中可能带目录后缀的选择值），替换下面的示例账号：

```bash
.venv/bin/python -m wechat_agent.doctor --check-source --source-account wxid_your_account --output .local/evidence/m0.json
```

预期 scope=connection、status=passed、history_complete=false，仅说明该账号的源服务连接通过。加 `--source-samples` 可以继续做有限私信／群聊采样，不调用模型，也不向终端输出聊天正文：

```bash
.venv/bin/python -m wechat_agent.doctor --check-source --source-account wxid_your_account --source-samples --output .local/evidence/m0.json
```

有限采样不会证明全历史完整；缺群聊样本、跳行或分片错误会给出具体 gap。若启用源服务 token，在 `.local/config/source.json` 配置 `token_env` 环境变量名，密钥值放本机环境变量。配置还支持 base_url、expected_account_id、timeout_seconds；配置目录不入 Git。

## 7. 模型和媒体：按需验证

模型配置见 [模型检查说明](../../verification/model-capabilities.md)。真实model_id和凭据未准备时保持pending即可，不用为本轮来源验证配置模型。只有明确执行 `--check-model` 才发送一次最小请求，不自动重试，不发聊天正文。

媒体检查只读取你指定的本机文件；替换为实际路径再运行：

```bash
.venv/bin/python -m wechat_agent.doctor --check-media "$HOME/Downloads/报价单.pdf" --output .local/evidence/m0.json --shareable-output .local/evidence/shareable.json
```

scope=file_availability、status=passed仅证明可读并计算哈希，parsed=false，不代表OCR／表格解析。quality默认unknown；只有来源确认后才传 `--media-quality original` 或thumbnail，不从文件名猜原件。

## 8. 回传技术报告

来源采样命令可附加 `--shareable-output .local/evidence/shareable.json`。完整报告仍写入 `--output`；终端和shareable文件只输出允许的技术字段、状态及计数，剔除本机路径、姓名、聊天正文和凭据。

如果出现 `message_sender_missing`，连接可能已经正常，缺口是部分消息没有可用发送人。新版报告的 `messages_sampled` 是总采样数，`messages_checked` 是通过校验数，`messages_rejected` 是未通过数；`message_issues` 会列出异常消息类型、私信／群聊类别和页内位置。把shareable报告反馈即可，无需复制聊天正文。不能凭 incoming 或显示名称把记录归给某人。

system／revoke事件允许没有人物发送人，分别计入 `system_events_checked` 和其中的 `unattributed_events_checked`，不再仅因发送人为空报错；消息ID、时间等仍须有效。如果同类会话只读到系统事件，仍报告人物消息样本不足。`scope=sample`的passed仅说明本轮有限采样通过。

请反馈 `git rev-parse --short HEAD`、测试结果及shareable报告。原始聊天、完整原文文件和API Key留在本机。报告输出路径不能与源配置、模型配置或待检查文件相同，避免覆盖输入。

## 9. M1任务1：数据库与API启动验证

在仓库根目录更新后执行：

```bash
git pull --ff-only origin main
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn wechat_agent.api.app:app_factory --factory --host 127.0.0.1 --port 8766
```

浏览器打开 http://127.0.0.1:8766/api/health ，或在另一终端执行 `curl -fsS http://127.0.0.1:8766/api/health`。任务1检查点返回schema_version=1；拉取后会自动升级，当前预期为 `{"status":"ok","schema_version":4}`。结束按Control+C。

首次启动在应用数据目录创建`archive.sqlite3`，启用外键和WAL，原子执行迁移；需要SQLite的FTS5／trigram与JSON支持。默认Mac路径为`~/Library/Application Support/Wechat-Agent/`，可用`WECHAT_AGENT_DATA_DIR`指定独立测试目录。迁移失败或数据库版本高于程序时拒绝启动，不自动降级或清库；健康查询只读，不创建或修复数据库。

此接口只证明应用数据库/API可用，不会发起微信同步或模型调用；原型仍在8765端口单独查看。来源归档通过下节独立命令验证，UI操作入口由M1后续任务接入。

## 10. M1任务2：小范围分页归档与重复验证

先用Control+C结束之前运行的API，避免旧进程继续使用schema1口径；拉取后运行测试。本轮无新增依赖，沿用现有Python环境。

```bash
git pull --ff-only origin main
.venv/bin/python -m pytest -q

for sync_check_round in first second; do
  .venv/bin/python -m wechat_agent.source.sync \
    --source-account wxid_your_account --sample --from-start \
    --output ".local/evidence/source-sync-${sync_check_round}.json"
done
```

将示例账号替换为M0已经验证的canonical wxid。默认复用127.0.0.1:9100的wx-cli；有鉴权或自定义地址时沿用本地source.json，或传`--source-config`。不需要重启wx-cli或启动API。

--sample读取来源联系人／会话元数据，原文只选择一个私信和一个群，每个至多2页、每页20条，最多80条。--from-start保证两次从所选历史开头重读；若源端未变化，第二次inserted和revised应为0、unchanged应增加，正常记录总数不重复增长。首次命令自动将数据库从schema1原子升级到2，保留已有内容。

报告中的completed_conversations表示本轮该会话可见窗口已读到末尾；incomplete_conversations表示达到页数上限，failed_conversations表示实际错误。超过限量时status=partial、gap=source_page_limit_reached属于预期，不表示已读完历史，也不算源端故障。其他gap需反馈处理；history_complete始终false，不证明隐藏或删除的历史可恢复。

归属不足或没有稳定ID的原文保存在数据库source_issues中，该页游标不推进。报告仅列计数、具体gap和最多20类issue_types技术类型，不含姓名、消息ID、正文、本机路径或凭据。unresolved_issues_total是该账号的问题观察记录数；没有稳定ID的多次观察不能当成同一条消息合并。反馈两份报告和测试结果即可，原始聊天留在本机。

任务2检查点API为schema_version=2，任务4检查点为3，当前修复版本为4。指定其他已知会话可用重复的`--conversation`参数；不传--from-start时续读已保存的未完成游标，必须沿用原page-size。完成的会话下一次会从头检查修订；当前实现优先保证可追溯，不声称已有只取增量的源端变更流。附件先保留引用，文件获取／解析和模型整理仍在后续阶段。

## 11. M1任务3：联系人API验证

任务3检查点没有新增依赖或迁移，schema为2；任务4检查点升级到3，当前修复启动升级到4。停止旧API后拉取、运行测试并重启：

```bash
git pull --ff-only origin main
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn wechat_agent.api.app:app_factory --factory --host 127.0.0.1 --port 8766
```

在另一终端用已验证的工作账号读取联系人。以下只打印统计，避免把真实姓名和ID带入反馈：

```bash
curl -fsS 'http://127.0.0.1:8766/api/contacts?account_id=wxid_your_account&page=1&page_size=20' \
  | .venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"total":d["total"],"page":d["page"],"returned":len(d["items"]),"role_counts":d["role_counts"]},ensure_ascii=False))'
```

HTTP应为200，每页最多20位，不包含本人或群标识。首次归档的人工身份默认为unknown，商家数量为0并不表示漏读；身份待人工确认。默认读取本机唯一的已归档账号；若有多个账号，需在本地source.json明确expected_account_id。请求里的account_id不能越过服务端绑定。

接口文档在 http://127.0.0.1:8766/docs ，可查看搜索、分页和PATCH身份的结构。真实身份由用户确认后再修改；云端已在临时库覆盖单个／批量修改、版本冲突、部分成功和原文保留，不需要为本轮验收批量改动真实联系人。

角色变更带expected_version；409的details.updated可能已成功提交，details.failed才是失败项。冲突时核对新版本后只重试失败项。原文与来源不会被角色切换删除；正式桌面页面已在任务5交付，商家分析仍未接入。反馈测试结果和上述统计即可，不回传联系人清单。

## 12. M1任务4：后台同步任务验证

本节是任务4的历史检查点（当时schema3／203项测试）；当前版本为schema4，执行位置见[状态页](../../STATUS.md)。先Control+C停止旧API，再拉取并重启，保留已有归档。

```bash
git pull --ff-only origin main
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn wechat_agent.api.app:app_factory --factory --host 127.0.0.1 --port 8766
```

在另一终端进入项目目录，将示例账号换成此前验证的canonical账号：

```bash
.venv/bin/python -m wechat_agent.operations.check \
  --account wxid_your_account \
  --output .local/evidence/operation.json
```

该命令只POST一次source-only任务，随后查询同一operation_id，最多等30秒；API先202入队，lifespan后台worker执行。复用本地source.json或默认9100的wx-cli，服务必须已运行。本次只选一个私信和一个群，每会话至多2页、每页20条，从开头重读以验证幂等；读取联系人／会话元数据不受这个消息采样数限制。不调用模型，也不修改人工身份。

成功时state和source_state均为succeeded。counts返回真实inserted、revised、unchanged、页数及会话数；再次运行创建新的任务，源端未变化且所选范围相同时，新增和修订应为0。history_complete始终false，不能把样本窗口完成当成全历史已同步。来源不可用明确失败；超过样本页数或存在归属缺口会返回source_incomplete及source_gaps，请反馈实际报告，不放宽为成功。

若30秒后仍queued／running，可用返回的UUID继续查询，避免重复建任务：

```bash
.venv/bin/python -m wechat_agent.operations.check \
  --account wxid_your_account --operation-id UUID_FROM_REPORT \
  --output .local/evidence/operation.json
```

报告只含操作UUID、技术状态、计数和缺口，不含姓名、聊天、来源ID或本机路径。HTTP／协议错误返回固定operation_check_failed；正常但尚未结束的任务如实保留当前状态。

接口文档仍在 http://127.0.0.1:8766/docs 。GET /api/operations携带account_id查询历史，GET /api/operations/{id}查询实际进度；POST停止body为`{action:"stop",account_id:"...",operation_id:"..."}`。停止先写generation屏障，迟到页不能归档；已经提交的原文保留。M1暂不提供继续／重试；普通退出或确认进程已退出的遗留任务记为stopped，完整恢复在M4交付。

目前sync_and_organize若存在需要分析的商家，来源可成功但总任务会failed／capability_not_ready，因为模型整理尚未接入。这是能力边界，不能据此宣称已生成真实档案。正式UI和设置交互已由任务5交付，启动见第13节；当前名称问题仍按审查修复。

## 13. M1任务5：正式桌面页面与设置

需要Node 24.14.1及以上的24.x，可先运行`node --version`确认；没有时安装[Node 24](https://nodejs.org/en/download)。本次新增前端运行／构建依赖，无新增Python依赖。先Control+C停止旧API，再在项目根目录执行：

```bash
git pull --ff-only origin main
.venv/bin/python -m pytest -q
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m uvicorn wechat_agent.api.app:app_factory --factory --host 127.0.0.1 --port 8766
```

浏览器打开 http://127.0.0.1:8766/ 。这是正式React页面，API和静态资源同源，继续使用现有本机数据库并升级至schema4；8765的静态原型仍只作效果参照。每次拉取前端更新后重跑build，重启后端以加载最新接口；未构建时API仍可用，首页返回404。Node只用于安装／构建前端，运行已构建页面只需后端服务。

验证重点：

- 全部联系人总数与现有归档相符，每页20位；搜索真实姓名／群名，切换身份、翻页和勾选时列表不整体闪白。跨页保留选择，切换商家／全部联系人清空选择，工作台／设置之间保留搜索上下文。
- 复制按钮复制真实备注／微信名称，不复制wxid。身份修改立即走后端并保存；409部分冲突只保留失败项。真实角色仍按实际业务确认，无需为验收批量改标签。
- 设置中的时间为单一输入控件，时区只在时钟面板内。输入9:05后失焦或Enter保存为09:05；选择面板里先改草稿，应用才保存，取消／Escape／点击外部不保存。可用方向键、Home／End和Tab，保存后刷新核对。
- 太阳／月亮、导航和筛选有动画；深色覆盖整页、输入框和弹窗，刷新不闪回浅色。系统减少动态效果和设置中的开关均生效。
- 同步、停止、进度和整理记录使用实际操作API；模型尚未接入时明确保留来源完成与分析未完成的区别。

每日开关和时间目前仅持久化设置，界面明确标为“调度待接入”，尚不会自动执行。模型档案、编辑资料、附件处理按后续阶段接入；沟通原文浏览及手动导入在M1任务6。来源标签表示上次同步证据，不把历史成功冒充当前在线健康。

开发预览可在另一个终端运行`WECHAT_API_URL=http://127.0.0.1:8766 npm --prefix frontend run dev`，打开5173；Vite默认代理8000，上述变量沿用当前8766。浏览器验收在云端完成，本机不必安装Playwright。若要自行重跑，先在frontend执行`npx playwright install chromium`，再执行`npm run test:e2e`；隔离测试使用18001／18002和临时合成库，不读取真实归档。


## 14. 联系人异常标识与同步缺口修复

先在运行API的终端按Control+C结束旧进程，再更新、构建和启动。不要让schema3旧进程与升级后的schema4同时使用同一数据库；不需要清库或重新安装wx-cli。

```bash
git pull --ff-only origin main
.venv/bin/python -m pytest -q
npm --prefix frontend ci --engine-strict
npm --prefix frontend run build
.venv/bin/python -m uvicorn wechat_agent.api.app:app_factory --factory --host 127.0.0.1 --port 8766
```

pull／build／重启不会隐式发起微信同步。启动自动执行migration004，隔离XML／正文等明显无效的联系人标识，保留消息、来源关系、人工身份及其版本；它不会重新读取名称，也不会补出群成员昵称。健康接口应返回schema_version=4。刷新正式页面后，客户详情的“同步此客户”位于顶部关闭按钮左侧；整理记录显示目标／完成／未完成会话数及已保存的来源缺口，已有记录无需重跑同步即可查看。

在另一终端运行只读诊断，将示例账号替换为已验证的canonical账号：

```bash
.venv/bin/python -m wechat_agent.operations.check \
  --account wxid_your_account --latest \
  --output .local/evidence/operation-latest.json
```

`--latest`只读取该账号最近一次操作，不创建同步任务；没有历史时返回operation_check_failed。若最近一条不是待查记录，使用第12节的`--operation-id`读取指定UUID。失败记录会保留state=failed并返回退出码1，这是诊断结果，不会被改成成功。

报告的source_gaps表示该次记录保存的具体缺口；contact_quality.quarantined为当前隔离的异常联系人数量，names_unavailable为有效标识但无可用备注／昵称的数量，均为当前账号的全局计数。它们不包含姓名、消息正文或来源ID。联系人质量读取失败时省略contact_quality，仍返回任务诊断。

“来源同步不完整”表示本次存在具体读取／归属／覆盖缺口，例如发送人标识异常、源端跳过记录、页数上限或单客户群覆盖范围无法确认；已完成会话数量不代表没有其他缺口。新增为0或history_complete=false本身不触发这个状态。真实缺少昵称的群成员仍显示“名称缺失”，不会用wxid或猜测名称代替；本次隔离也不代表已修复wx-cli上游解析或恢复了其丢失的发送人。


## 15. 联系人来源与名称修复R1—R4

这一节替代第14节作为当前版本验证流程；历史实机结果不改写。当前应用schema5，来源要求项目固定补丁`0.7.4+wechat-agent.1`，只pull应用不会更新已有wx-cli服务。

先在应用终端按Ctrl+C停止旧API，在项目根目录拉取并检查：

```bash
git pull --ff-only origin main
.venv/bin/python -m pytest -q
npm --prefix frontend ci --engine-strict
npm --prefix frontend run build
```

安装来源补丁需要Git、Rust/Cargo及Xcode命令行工具。`cargo --version`应可运行；缺少时安装Rust稳定工具链，缺少编译工具时执行`xcode-select --install`。安装器从固定上游commit应用仓库内校验过的patch并构建，首次耗时取决于网络和编译；不用编辑源码，不覆盖原`~/.local/bin/wx-cli`。

```bash
bash scripts/install-wx-cli.sh --transport ssh
.local/tools/wx-cli/0.7.4+wechat-agent.1/bin/wx-cli --version
```

先停止旧来源，再用项目工具启动。将示例账号替换为本机已验证的账号；保留原有账号目录参数（若使用），不要误选其他微信：

```bash
~/.local/bin/wx-cli server stop
.local/tools/wx-cli/0.7.4+wechat-agent.1/bin/wx-cli server run \
  --host 127.0.0.1 --port 9100 --account wxid_your_account
curl -fsS http://127.0.0.1:9100/api/v1/health
```

健康返回应有新CLI版本及metadata：`contract=wechat-agent-source-v1`、`patch_id=wechat-agent.1`、`refresh_state=ready`，generation与resolver_generation一致。若仍是旧版本，先检查旧worker是否已停止；显示“server already running”不证明已更换服务。启用了Bearer鉴权时，沿用本机环境变量／配置，不把token粘贴到聊天或仓库。

启动应用后访问`http://127.0.0.1:8766`：

```bash
.venv/bin/python -m uvicorn wechat_agent.api.app:app_factory --factory \
  --host 127.0.0.1 --port 8766
```

另一终端检查`curl -fsS http://127.0.0.1:8766/api/health`应返回schema_version=5。在工作台顶部点击“刷新联系人”，等待“联系人资料已刷新”，在整理记录查看联系人／群资料数量和缺口。该操作只读取来源元数据，不读取聊天正文、不调用模型；不删除旧人物、不改旧消息作者或人工身份。部分失败会保留旧值并显示具体原因，不以0新增消息判断成功。

可分别搜索几个微信中能确认的人，检查备注／昵称优先级、群内／会话／历史名称提示及复制按钮；群内与历史名称不能复制成已确认的全局微信名称。归档可包含历史人物和非好友，补丁没有可靠好友关系字段，微信搜不到不自动等于乱码。现存无证据的旧作者不会按昵称批量重写；重新读取原文时仍须检查来源缺口。

只读脱敏诊断（不创建刷新操作、不读取消息正文）用于回传技术证据：

```bash
.venv/bin/python -m wechat_agent.contacts.check \
  --account wxid_your_account --output .local/evidence/contact-names.json
.venv/bin/python -m wechat_agent.operations.check \
  --account wxid_your_account --latest --output .local/evidence/operation-latest.json
```

诊断只导出计数／状态，包含源与归档差异、名称质量、读取模式和刷新代次；pending或非零退出码表示仍有缺口，不能改成成功。回传这两份脱敏结果及健康schema即可，不上传聊天或联系人原始库。

如需回退来源，先停止项目工具的服务，再用原`~/.local/bin/wx-cli server run ...`启动原工具；归档不清库。原版0.7.4可做有限诊断，应用会拒绝继续信任其未修复的群作者解析，显示需安装补丁。
