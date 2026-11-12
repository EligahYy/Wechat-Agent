# Mac 更新与验证

更新：2026-11-12（北京时间）。已有项目按下面1—6步执行，每次只复制一个步骤；报错就停在该步。云端负责开发，Mac只安装、运行和验证。旧阶段命令已移到[历史归档](verification/mac-setup-history.md)，不与当前步骤混用。

你已有Python3.12虚拟环境、Node24.14.1及旧wx-cli，这次无需重建Python环境。先在运行应用的终端按Ctrl+C停止旧API；原wx-cli保持运行，直到第4步切换。

<a id="update-repository"></a>
## 1. 更新项目并确认版本

在仓库任意子目录均可先回到项目根目录，包括当前的scripts目录：

```bash
cd "$(git rev-parse --show-toplevel)"
```

先查看`git status --short`，有不清楚的本地修改就保留并反馈，不使用reset或强制覆盖。然后运行这个完整代码框；括号中的`set -e`会在失败时停止，且不会关闭你的终端：

```bash
(
  set -e
  git switch main
  git pull --ff-only origin main
  git merge-base --is-ancestor f9545b9 HEAD
  test -f scripts/install-wx-cli.sh
  git log -1 --oneline
  ls scripts/install-wx-cli.sh patches/wx-cli/manifest.json
)
```

通过标准：pull成功；当前main包含修复提交f9545b9；最后能列出两个文件。最新提交号可比f9545b9更新。**只要pull报错，就没有完成更新；旧版测试／构建成功不算更新成功。**

### SSH连接失败时只处理这一项

`Connection closed by ... port 443`表示连接提前中断，不能单凭这条信息断定密钥或仓库权限错误。198.18.x.x属于保留测试网段，可能是本机代理的Fake-IP映射，不能当作GitHub真实地址。

已有SSH密钥时，先在当前终端临时改走GitHub标准22端口，再重跑上面的完整代码框：

```bash
export GIT_SSH_COMMAND='ssh -o HostName=github.com -p 22 -o ConnectTimeout=15'
```

这个变量只作用于当前终端及其子进程，也供第3步下载wx-cli源码使用，不改全局Git或SSH文件。若22端口也失败，先不要安装，分别检查实际SSH配置和连接：

```bash
ssh -G git@github.com | rg '^(hostname|port|proxycommand|proxyjump) '
ssh -vT -o HostName=github.com -p 22 -o ConnectTimeout=15 git@github.com
```

Mac没有rg时用`ssh -G git@github.com`直接查看这几项。成功认证会出现`Hi ... You've successfully authenticated`；`ssh -T`仍可能以1退出，因为GitHub不提供shell，这是正常的，最终以git pull成功为准。若22被网络阻断，可临时改为`export GIT_SSH_COMMAND='ssh -o HostName=ssh.github.com -p 443 -o ConnectTimeout=15'`后重试；两个端口都提前关闭时，检查代理/TUN对github.com、ssh.github.com的路由并反馈错误，不能靠继续跑安装命令绕过。

<a id="build-app"></a>
## 2. 检查并构建应用

仍在项目根目录，运行：

```bash
(
  set -e
  git merge-base --is-ancestor f9545b9 HEAD
  .venv/bin/python --version
  node --version
  .venv/bin/python -m pytest -q
  npm --prefix frontend ci --engine-strict
  npm --prefix frontend run build
)
```

通过标准：Python3.12.x；Node24.14.1或更高24.x；当前修复版280项Python测试通过，前端构建成功。后续开发会增加数量，以实际提交为准；若仍是230项，先回到第1步。此轮没有新增Python依赖，不必重建.venv。

<a id="install-source"></a>
## 3. 安装补丁版wx-cli（首次执行一次）

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

通过标准：最后显示`wx-cli 0.7.4+wechat-agent.1`。安装器下载固定上游源码、应用已校验补丁并编译；首次会下载Rust依赖。不覆盖原`~/.local/bin/wx-cli`，不自动切换正在运行的服务。脚本不存在说明第1步尚未完成。

<a id="switch-source"></a>
## 4. 切换来源服务并确认版本

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

<a id="start-app"></a>
## 5. 启动应用并刷新联系人

仍在项目根目录，复用已有`.local/config/source.json`和归档数据库：

```bash
.venv/bin/python -m uvicorn wechat_agent.api.app:app_factory --factory \
  --host 127.0.0.1 --port 8766
```

保持此终端运行，在浏览器打开 http://127.0.0.1:8766 。另一终端可检查：

```bash
curl -fsS http://127.0.0.1:8766/api/health
```

通过标准：schema_version=5。本次计数／搜索修复不需要重新安装wx-cli；已运行0.7.4+wechat-agent.1的机器可跳过第3—4步。点击顶部“刷新联系人”，等待“联系人资料已刷新”，再检查真实姓名、名称来源与整理记录。该操作不读取聊天正文、不调用模型，不删除人物或改变人工身份。群内／会话／历史名区别展示，不能当作已确认的全局微信名称复制；历史归档不等于当前好友清单。刷新提示中的来源资料条数不等于归档总人数，详情显示“归档人数＝本次来源收录＋其他归档”；身份“待识别”不等于姓名缺失。

如果出现“来源配置不可用”，检查已有source.json的base_url和expected_account_id是否匹配第4步health；保留已有token_env配置，不清库。原型8765、Vite开发预览5173均不是本次正式页面入口。

<a id="report"></a>
## 6. 回传最少的验证结果

项目根目录执行（替换示例账号）：

```bash
.venv/bin/python -m wechat_agent.contacts.check \
  --account wxid_your_account --output .local/evidence/contact-names.json
.venv/bin/python -m wechat_agent.operations.check \
  --account wxid_your_account --latest --output .local/evidence/operation-latest.json
```

回传：提交号、应用健康结果、上述两份脱敏报告。报告只导出计数和技术状态，不上传原始联系人库、聊天或密钥。pending／非零退出码表示仍有缺口，保留结果反馈；不要清库或反复全量同步试错。

## 首次安装或回退时再看

首次下载使用`git clone git@github.com:EligahYy/Wechat-Agent.git`，进入仓库后按第1步确认版本。没有虚拟环境时，先用Python3.12创建并按锁文件安装，再进入第2步：

```bash
(
  set -e
  python3.12 -m venv .venv
  .venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
  .venv/bin/python -m pip install --no-deps --no-build-isolation -e .
)
```

新机器首次运行需在`.local/config/source.json`明确绑定health返回的canonical账号（不是自行截断的目录名）；配置格式见[来源配置](verification/source-capabilities.md#来源配置)。已有机器保留现有配置。

回退来源时，先用项目版本`server stop`停止，再用原`~/.local/bin/wx-cli server run ...`及原参数启动。原版可做有限诊断，应用会拒绝未修复的群消息归属；归档数据库不清空、不降级。模型与媒体实测按后续交付安排，本次无需配置。
