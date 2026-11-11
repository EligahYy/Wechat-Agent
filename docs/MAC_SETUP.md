# Mac 拉取项目与本地验证

更新：2026-11-11（北京时间）。所有开发在云端完成，测试通过后直接推送 `main`；Mac 只拉取、安装运行依赖并验证，问题由云端修复。

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

当前已实现M0检查工具、M1原文归档／联系人身份API及持久化同步操作；React正式页面尚未接入。首次安装按下列锁文件恢复环境；已有任务3环境本次无新增依赖，无需重建虚拟环境。

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

[六阶段开发计划](superpowers/plans/README.md)分别记录云端开发与本地验收，不把未实测内容标为成功。这里的命令尚未在你的 Mac 执行。

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

模型配置见 [模型检查说明](verification/model-capabilities.md)。真实model_id和凭据未准备时保持pending即可，不用为本轮来源验证配置模型。只有明确执行 `--check-model` 才发送一次最小请求，不自动重试，不发聊天正文。

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

浏览器打开 http://127.0.0.1:8766/api/health ，或在另一终端执行 `curl -fsS http://127.0.0.1:8766/api/health`。任务1检查点返回schema_version=1；拉取后会自动升级，当前预期为 `{"status":"ok","schema_version":3}`。结束按Control+C。

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

任务2检查点API为schema_version=2，当前任务4版本为3。指定其他已知会话可用重复的`--conversation`参数；不传--from-start时续读已保存的未完成游标，必须沿用原page-size。完成的会话下一次会从头检查修订；当前实现优先保证可追溯，不声称已有只取增量的源端变更流。附件先保留引用，文件获取／解析和模型整理仍在后续阶段。

## 11. M1任务3：联系人API验证

任务3检查点没有新增依赖或迁移，schema为2；当前任务4启动会升级到3。停止旧API后拉取、运行测试并重启：

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

角色变更带expected_version；409的details.updated可能已成功提交，details.failed才是失败项。冲突时核对新版本后只重试失败项。原文与来源不会被角色切换删除；商家分析和正式桌面页面仍在后续任务接入。反馈测试结果和上述统计即可，不回传联系人清单。

## 12. M1任务4：后台同步任务验证

先Control+C停止旧API，再拉取并重启。本次无新增依赖，启动会将现有数据库原子升级到schema3，保留已有归档。云端当前203项测试通过。

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

目前sync_and_organize若存在需要分析的商家，来源可成功但总任务会failed／capability_not_ready，因为模型整理尚未接入。这是能力边界，不能据此宣称已生成真实档案。正式UI和设置交互在下一任务实现。
