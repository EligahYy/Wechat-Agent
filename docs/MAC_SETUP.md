# Mac 更新与验证

更新：2026-11-15（北京时间）。云端负责开发，Mac只更新、运行和验证。你已安装项目补丁版wx-cli，本次只执行下面1—4步；**无需重装Rust或wx-cli；依赖是否变化以锁文件为准，第2步可重复执行**。首次安装单列在文末，旧阶段命令见[历史归档](archive/verification/mac-setup-history.md)。

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
  git merge-base --is-ancestor 30bb407 HEAD
  test -f src/wechat_agent/api/messages.py
  git log -1 --oneline
)
```

通过标准：pull成功，包含日历双栏交付提交30bb407，原文接口文件存在。以本次交付的最新main为准，该祖先检查只排除仍在运行旧阶段代码的情况。**pull失败就先处理连接，后续旧版测试成功不算完成更新。**

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

通过标准：Python3.12.x、Node24.14.1或更高24.x，后端测试和前端构建均成功。最新日历交付基线为405项后端测试；后续修复以[状态页](STATUS.md)记录为准。已有.venv无需重建；Mac不需要运行浏览器开发测试。

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

通过标准：`{"status":"ok","schema_version":11}`。启动会按既有迁移升级数据库，保留原文和人工身份；不清库、不降级。原型8765及Vite开发端口5173不是正式应用入口。

若出现来源配置错误，核对既有`.local/config/source.json`的base_url与expected_account_id，沿用token_env，不把凭据贴到聊天。原文浏览和手动导入使用已归档数据，不需要再次全量同步。

<a id="report"></a>
## 4. 验证新增入口并回传结果

依次检查：

1. 工作台业务活跃联系人／设置全量管理，核对搜索、身份、人工移出不被同步加回。
2. 联系人沟通原文：日历、当天所有人物、本人高亮及箭头定位；日期／来源／关键词范围一致，回到最新不隐式同步。边缘滚动自动补页，不再有加载更早／更多按钮。系统通知隐藏、特殊消息摘要、复制反馈位于弹窗上方。
3. 设置CSV／JSON导入先预览，再确认，重复导入不增行；附件仅访问库内已存在且位于应用附件目录的安全文件。来源获取与解析仍待M3。
4. 模型配置和主动连接检查按文末任务3步骤验证；连接通过不代表容量／视觉通过。不开真实自动整理或计划假成功。

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

按前文方式重启应用，健康接口应报告schema_version=11。本轮无需重装wx-cli。

1. 确认左上角EU、工作台业务活跃联系人及设置→管理全部联系人。先搜索一名联系人，手动移出，再同步，确认不自动回来；在全量管理重新加入。
2. 设置→配置模型，按服务文档填写HTTPS完整chat-completions地址、准确模型ID、响应格式和声明容量。首次填写密钥，保存后页面应留空；密钥只写本机Keychain。
3. 如需验证连接，主动点击“检查连接”（一次最小付费请求，不含客户资料）。未点击不调用模型。此检查不验证容量、图片或真实整理质量。
4. 近90天实际群发言、群名片和需求归属需用真实样本核对。未有经验证的运行时能力／分类结果时显示“群需求识别待完成”，保守保留候选。模型档案发布闭环仍在M2任务4—7实施，不将来源同步成功当作档案生成成功。

排障时提供脱敏结果即可，不发送API密钥、完整联系人库或聊天原文。
