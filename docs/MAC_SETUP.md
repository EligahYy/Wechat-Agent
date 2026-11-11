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

当前只实现 M0 任务 1 的离线环境检查，还没有正式 API 后端或 React 应用。

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

当前预期 7 个测试通过；doctor 默认不连微信、不调用模型，Mac 上 source/model/media 仍为 pending。CLI 成功表示诊断报告已生成，不表示微信或模型连接成功。此刻尚未实现 `--check-source`／`--check-model`，云端后续交付后再运行对应验证。

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
