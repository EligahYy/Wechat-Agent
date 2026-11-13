# Mac 更新与验证

更新：2026-11-13（北京时间）。云端负责开发，Mac只更新、运行和验证。你已安装项目补丁版wx-cli，本次只执行下面1—4步；**无需重装Rust、wx-cli或Python依赖**。首次安装单列在文末，旧阶段命令见[历史归档](verification/mac-setup-history.md)。

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
  git merge-base --is-ancestor e6bbd76 HEAD
  test -f src/wechat_agent/api/messages.py
  git log -1 --oneline
)
```

通过标准：pull成功，包含Task6基础提交e6bbd76，原文接口文件存在。以本次交付的最新main为准，该祖先检查只排除仍在运行旧阶段代码的情况。**pull失败就先处理连接，后续旧版测试成功不算完成更新。**

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
  .venv/bin/python -m pytest -q
  npm --prefix frontend ci --engine-strict
  npm --prefix frontend run build
)
```

通过标准：Python3.12.x、Node24.14.1或更高24.x，后端测试和前端构建均成功。此次云端基线为308项Python测试，后续数量以[状态页](STATUS.md)对应版本为准。本次依赖锁未变，无需重建.venv；Mac不需要运行浏览器开发测试。

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

通过标准：`{"status":"ok","schema_version":6}`。启动会按既有迁移升级数据库，保留原文和人工身份；不清库、不降级。原型8765及Vite开发端口5173不是正式应用入口。

若出现来源配置错误，核对既有`.local/config/source.json`的base_url与expected_account_id，沿用token_env，不把凭据贴到聊天。原文浏览和手动导入使用已归档数据，不需要再次全量同步。

<a id="report"></a>
## 4. 验证新增入口并回传结果

依次检查：

1. **联系人详情 → 沟通原文**：商家、服务商、平台和待识别均可打开；核对现有私信／群聊的时间、说话人和来源。我方紫色加粗，身份标签沿用蓝／紫／绿／琥珀，正文保持普通文字。系统通知从列表隐藏，底层归档保留；下拉来源使用统一菜单。页签切换时窗口平滑伸缩，搜索保留旧结果并过渡。
2. 搜索原文（可试“海运”等短中文）、清空搜索、切换来源。超过50条可加载更多；归档在翻页间发生变化时会提示重新加载，避免混入旧分页。
3. **设置 → 导入消息**是唯一导入入口。已有CSV／JSON导出文件时，选择文件，核对列映射、来源批次标识和逐行问题，再确认导入有效记录。没有合适文件时可先只验证原文，导入保留待验证。
4. 在客户详情点击“同步并整理此客户”，本页头部下方应出现真实进度和结果，滚动时仍可见；全局入口为“同步并整理”，不再单列“刷新联系人”。当前模型未接入时必须显示“原文已同步，档案整理尚未接入”，不是资料更新成功。
5. 同一文件、相同批次标识再次导入应显示0新增和对应重复数；相同标识但内容不同会跳过冲突并保留旧原文。导入完成后可返回对应联系人的沟通原文查看，不自动调用模型。

文件要求：UTF-8、最多2MB／5000行。CSV首行为列名；JSON顶层为对象数组。必需映射为会话标识、发送人标识、含时区的消息时间（如2026-11-13T08:30:00+08:00）、消息标识和正文。使用来源真实稳定编号，不用姓名代替人物标识。重复导入同一来源时保持“来源批次标识”；它默认取文件名，改名后应手动恢复原标识，否则属于另一个导入来源。

人工导入只依据你明确映射的账号、发送人和会话编号归档，不证明其是真实人物；不会按姓名合并人或补造昵称。新编号可能形成名称待确认的联系人。只含本人发言的新私聊若没有既有对方关系，不推测收件人；核实来源映射后再使用。

附件目前只归档引用：未获取、缺失等状态如实显示；只有库内已存在、位于应用附件目录的安全文件可下载。来源媒体获取和解析属于M3，本次导入不会打开文件内写入的任意路径或URL。

回传最少信息：`git log -1 --oneline`、健康结果、原文与导入各项是否通过；出错时附页面错误码或脱敏截图。无需上传聊天正文、原始联系人库、导入文件或密钥。既有联系人搜索与计数已复验通过，无需重装来源或反复全量同步。

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

新机器按下面两个来源步骤安装并启动；已有0.7.4+wechat-agent.1服务的机器跳过。然后在`.local/config/source.json`明确绑定health返回的canonical账号，格式见[来源配置](verification/source-capabilities.md#来源配置)。已有机器保留配置。继续回到第2步构建应用。

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
  .local/tools/wx-cli/0.7.4+wechat-agent.1/bin/wx-cli --version
)
```

通过标准：最后显示`wx-cli 0.7.4+wechat-agent.1`。安装器下载固定上游源码、应用已校验补丁并编译；首次会下载Rust依赖。不覆盖原`~/.local/bin/wx-cli`，不自动切换正在运行的服务。脚本不存在说明代码尚未更新完整。

<a id="switch-source"></a>
## 首次来源启动：确认版本

将`wxid_your_account`替换为已验证的工作账号。保留你原有的自定义启动参数（如数据目录或鉴权）；不要启动另一个账号。先停止旧服务：

```bash
~/.local/bin/wx-cli server stop
```

看到已停止后才启动项目版本：

```bash
.local/tools/wx-cli/0.7.4+wechat-agent.1/bin/wx-cli server run \
  --host 127.0.0.1 --port 9100 --account wxid_your_account &&
curl -fsS http://127.0.0.1:9100/api/v1/health
```

通过标准：health中ready=true、cli_version包含`0.7.4+wechat-agent.1`；metadata中patch_id=wechat-agent.1、refresh_state=ready，generation与resolver_generation一致。若显示“server already running”且health仍是旧版，先处理未停止的旧worker，不进入下一步。启用Bearer鉴权时沿用本机凭据，不将token贴到聊天。


回退来源时先用项目版本server stop停止，再用原~/.local/bin/wx-cli server run及原参数启动；应用会拒绝未修复的群消息归属。保留数据库，不清空或降级。模型与媒体实测按后续交付安排。
