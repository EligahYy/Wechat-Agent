# 在 Mac 上初始化项目

更新：2026-11-11（北京时间）。现有仓库可运行桌面交互原型；正式后端和模型任务仍按 M0–M5 计划开发。

## 1. 下载仓库

打开 Mac 的“终端”，先检查 Git：

```bash
git --version
```

若系统提示缺少命令行工具，执行 `xcode-select --install`，完成系统安装后重新打开终端。然后下载项目：

```bash
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone https://github.com/EligahYy/Wechat-Agent.git
cd Wechat-Agent
git status
```

这是已有仓库，使用 clone 即可。若提示没有仓库权限，先在 GitHub Desktop 登录有权限的账号并克隆，或用已配置 GitHub 身份的终端重试；不要把 GitHub 密码或 token 写进仓库地址。

已有该目录时先进入目录运行 `git status`；没有本地修改再用 `git pull --ff-only origin main` 更新，不能覆盖已有工作。

当前 M0 开发代码和六阶段任务计划位于 `codex/m0-local-foundation` 分支。全新 clone 后可切换：

```bash
git fetch origin
git switch --track origin/codex/m0-local-foundation
```

若本地已有该分支，使用 `git switch codex/m0-local-foundation`。也可在第一次 clone 时直接加 `--branch codex/m0-local-foundation`。

## 2. 恢复 Superpowers

在项目根目录执行：

```bash
bash scripts/install-superpowers.sh
test -r .agents/skills/superpowers-writing-plans/SKILL.md && echo "Superpowers ready"
```

脚本下载固定的 7.0.2 版本，恢复 15 个项目技能。代码仓库只保存安装脚本，不包含上游依赖目录；每台新机器都需要运行一次。

在 Codex App 中添加／打开 `$HOME/Projects/Wechat-Agent` 作为本地项目，选择本地运行环境。项目的 `AGENTS.md` 会要求开发助手读取 Superpowers；可直接输入：

```text
读取 AGENTS.md，使用 Superpowers 的 executing-plans，先执行 M0 开发计划。
```

项目技能与客户端全局插件分别管理；如需全局使用，可在 Codex App 的 Plugins 中安装 Superpowers。云端会话无法直接读取这台 Mac 的微信本机数据，实机能力核验要在 Mac 本地执行。

## 3. 现在就能运行原型

先运行 `python3 --version`。已有 Python 3 时，直接执行：

```bash
python3 -m http.server 8765 --directory ui-prototype --bind 127.0.0.1
```

保持终端打开，浏览器访问 http://127.0.0.1:8765/preview.html 。结束时在终端按 Control+C。原型无需 Node、API Key 或微信连接，人物和任务均为示例。

没有 Python 时可从 [python.org](https://www.python.org/downloads/macos/) 安装，或使用下一节的 Homebrew 方法。也可以先在浏览器打开 `ui-prototype/preview.html` 查看效果；正式开发与检查推荐使用本地 HTTP 服务。

## 4. 开发时再准备依赖

实施默认使用 Python 3.12 和 Node 24。若已经安装 [Homebrew](https://brew.sh/)，可以执行：

```bash
brew install python@3.12 node@24
export PATH="$(brew --prefix python@3.12)/bin:$(brew --prefix node@24)/bin:$PATH"
python3.12 --version
node --version
npm --version
```

上述 PATH 只影响当前终端；新终端可重新执行 export，或按 Homebrew 的提示配置 shell。已有其他版本无需卸载，给本项目使用指定版本即可。

M0 任务 1 已提供 Python 包及含哈希的依赖锁文件，在上述开发分支可执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pytest -q
.venv/bin/python -m wechat_agent.doctor --output .local/evidence/m0.json
```

当前预期 7 个测试通过；doctor 输出环境和 pending 能力状态，默认不连微信、不调用模型。此刻尚未提供 `--check-source`／`--check-model`，它们由 M0 后续任务实现。CLI 成功只表示报告已生成，不表示源端或模型已核验。

正式 API 后端和 React `package.json` 尚未创建，不要执行后续阶段的启动命令。

wx-cli 的具体来源、版本及只读接口在 M0 本地核验，不猜测安装地址、启动参数或端口。DeepSeek 凭据在本地配置，不通过聊天发送，不写进 Git。

## 5. 开发顺序

入口见 [六阶段计划](superpowers/plans/README.md)。先执行 M0 并留下实测记录，再进入 M1；之后每阶段完成测试与验收后继续。M1–M5 对已定义的内部契约细化，但源端／模型真实协议以 M0 实测为准。

这里提供的是操作指南；尚未在你的 Mac 执行命令，也未声称已经连接微信或模型。
