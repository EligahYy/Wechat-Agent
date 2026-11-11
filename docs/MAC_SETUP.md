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

当前已实现 M0 环境、来源、模型及媒体检查，还没有正式业务 API 后端或 React 应用。本轮没有新增依赖，已有 `.venv` 可在 pull 后直接运行测试。

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

请反馈 `git rev-parse --short HEAD`、测试结果及shareable报告。原始聊天、完整原文文件和API Key留在本机。报告输出路径不能与源配置、模型配置或待检查文件相同，避免覆盖输入。
