# M0 Mac 环境与真实能力 Implementation Plan

> 历史归档：保留当时方案、命令和验证结果，不代表当前实现。当前入口见[实施状态](../../STATUS.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在云端开发可重复执行的环境、微信源和模型检查工具，由用户 Mac 运行验证并反馈真实证据。

**Architecture:** 创建最小 Python 包与只读 doctor 工具。来源和模型的内部契约与上游协议隔离；自动检查结果与人工核验事实分别记录，未实测保持 pending。

**Tech Stack:** Python 3.12、Pydantic、HTTPX、pytest、pip-tools；真实 wx-cli 协议待本机核验。

**Spec:** [实施方案 §11](../../IMPLEMENTATION_PLAN.md)、[模型执行方案](../../MODEL_EXECUTION.md)、[Mac 指南](../../MAC_SETUP.md)、[内部契约](../../superpowers/plans/CONTRACTS.md)。

## Global Constraints

- 所有代码、修复和自动化测试在云端完成，检查后直接推 main；Mac 只运行交付工具验证。云端开发完成与实机通过分别记录，实机门槛不阻塞可独立测试的代码开发。

- 仓库当前只有原型；不在 M0 开始全客户分析，不假装已经实现数据底座。
- Python 3.12；依赖实际解析后生成 `requirements-dev.lock`，不手填包版本。
- 模型实际 API model ID、上下文和图像能力先核验，不凭产品名称编造参数。
- 微信源只读；凭据、原始聊天和媒体放本地目录，不进 Git。
- 每项实机证据含执行时间、版本、范围和结果；Linux 合成测试不能替代 Mac 实测。

## Review Focus

1. 不在 Mac、未装源端或未配置模型时，报告 pending／unsupported 而非 passed：Task 1、3。
2. 两个同名人、同人不同昵称及群内发言不能丢稳定 ID：Task 2。
3. 源分页失败、无法定位姓名、无原件不能描述为“全量已获取”：Task 2、4。
4. 模型接口返回 200 但 ID 不符、输出截断或不支持结构输出时不能假通过：Task 3。
5. 实测材料和日志不能泄露真实账号、路径或密钥到提交内容：Task 4。

## File Structure

`src/wechat_agent/config.py` 负责本地路径；`doctor.py` 汇总报告；`source/contracts.py` 与 `model/contracts.py` 定义内部类型；`source/probe.py`、`model/probe.py` 分别核验；`tests/` 放合成及脱敏回放；`.local/evidence/` 保存真实原始证据且忽略。

### Task 1: 可运行的本地 doctor 与测试入口

**Files:** Create `pyproject.toml`, `requirements-dev.lock`, `src/wechat_agent/__init__.py`, `src/wechat_agent/config.py`, `src/wechat_agent/doctor.py`, `tests/test_doctor.py`；Modify `.gitignore`。

**Interfaces:** Creates `Settings(data_dir: Path, source_config: Path | None, model_config: Path | None)`、`collect_runtime() -> dict`；doctor 输出 `{runtime, source, model, media}`，各项有 `status`。Mac 默认数据目录为 `~/Library/Application Support/Wechat-Agent`，测试显式覆盖；本地探测配置默认读取项目下存在的 `.local/config/source.json`／`model.json`，不存在即 None。模型探测可用 `env:DEEPSEEK_API_KEY` 凭据引用，不把 key 值写入配置或报告；M2 正式配置改存 Keychain。

- [x] **Step 1 — 建立测试环境：** `pyproject.toml` 使用 setuptools 的 src 布局，声明 Python `>=3.12,<3.13`；运行依赖 Pydantic、HTTPX，dev 增加 pytest、pytest-asyncio、pip-tools。创建虚拟环境，安装 pip-tools，运行 `pip-compile --extra dev --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --no-emit-trusted-host -o requirements-dev.lock pyproject.toml`，再 `python -m pip install -r requirements-dev.lock` 和 `python -m pip install --no-deps -e .`。实际解析失败就修依赖，不提交虚构锁文件。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install pip-tools
```

- [x] **Step 2 — 先写失败测试：**

```python
def test_missing_connections_stay_pending(tmp_path, monkeypatch):
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    from wechat_agent.doctor import build_report
    report = build_report(data_dir=tmp_path, source=None, model=None)
    assert report["source"]["status"] == "pending"
    assert report["model"]["status"] == "pending"
```

- [x] **Step 3 — 验证红灯：** `python -m pytest tests/test_doctor.py -q`，预期缺少 `doctor` 或 `build_report` 导致失败；环境安装错误不是有效红灯。
- [x] **Step 4 — 最小实现：** `build_report(*, data_dir: Path, source: dict | None, model: dict | None) -> dict`；doctor CLI 支持 `--output PATH`，默认只检查运行环境，不隐式发模型请求。增加合成测试：输出路径带空格；非 Mac 的 source 标记 unsupported；报告不序列化凭据。`.gitignore` 增加 `.venv/`, `.local/`, `.env`, `.pytest_cache/`, `*.egg-info/`。
- [x] **Step 5 — 验证：** 上述 pytest 通过；`python -m wechat_agent.doctor --output .local/evidence/m0.json` 成功生成报告。Mac 未配置的 source/model 为 pending；实际 Linux 执行器的 source 为 unsupported、model 为 pending，不冒充完成 Mac 实测。
- [x] **Step 6 — 提交检查点：** `git add pyproject.toml requirements-dev.lock src/wechat_agent tests/test_doctor.py .gitignore`；获准提交时 `git commit -m "feat: add local capability doctor"`。

### Task 2: 来源契约、只读探测与真实协议记录

**Files:** Create `src/wechat_agent/source/{__init__,contracts,probe}.py`, `tests/test_source_probe.py`, `tests/fixtures/source-probe.json`, `docs/verification/source-capabilities.md`；Modify `doctor.py`。

**Interfaces:** Creates [M0 来源类型](../../superpowers/plans/CONTRACTS.md)；`normalize_probe(raw: dict, mapping: dict) -> CapabilityReport`；`run_source_probe(config_path: Path) -> CapabilityReport`（async）。mapping 只根据真实响应记录填写，不猜上游字段。

- [x] **Step 1 — 先写失败测试：**

```python
def test_no_sender_mapping_cannot_pass():
    from wechat_agent.source.probe import normalize_probe
    report = normalize_probe({"messages": [{"body": "已发出"}]}, mapping={})
    assert report.status != "passed"
    assert "sender_mapping_missing" in report.gaps
```

- [x] **Step 2 — 验证红灯：** `python -m pytest tests/test_source_probe.py -q`，预期尚无 probe 实现。
- [x] **Step 3 — 最小实现：** 按内部契约建立类型与探测器；来源命令／URL 必须来自显式配置和已核验的只读操作。不通过 shell 拼接执行来源参数。缺稳定发送者、消息身份、分页或账号信息分别列 gaps；不把 HTTP 200 当完整同步。
- [ ] **Step 4 — 实机取证：** Mac 上检查实际安装及版本、官方帮助和运行模式；选择一个私信、一个含多人的群读取至少两页，保留发送者、备注／群名、引用、同文本不同消息、修订及终止游标样本。把原始结果放 `.local/evidence/source/`，仅把脱敏字段映射、实际只读命令和能力结论写入 source-capabilities.md。若源端缺功能，明确标注，修订 M1 适配范围后再进入 M1。
- [x] **Step 5 — 有限验证：** 云端同名、账号、分页及错误回放通过；Mac已回传来源有限采样passed：4页8条有效消息、0异常，含2条无人物系统事件。只证明该样本；Step4要求的修订／引用及完整姓名覆盖证据尚未全部取得，不能将其标为完整实机通过。
- [x] **Step 6 — 提交检查点：** 仅暂存上述实现、脱敏 fixture 与能力文档；检查后 `git commit -m "feat: verify local source capabilities"` 并推 main。缺实机证据时本地验证项保持未完成，已通过回放测试的云端开发结果单独记录。

### Task 3: 模型真实能力与失败分类

**Files:** Create `src/wechat_agent/model/{__init__,contracts,probe}.py`, `tests/test_model_probe.py`, `docs/verification/model-capabilities.md`；Modify `doctor.py`。

**Interfaces:** Creates `ModelCapabilities`；`probe_model(config: dict, transport: httpx.AsyncBaseTransport | None = None) -> CapabilityReport`（async）。config 含明确 endpoint、model_id、凭据引用和经核验窗口；报告不含凭据值。

- [x] **Step 1 — 先写失败测试：** 用 HTTPX MockTransport 分别返回 401、429、200 但不同 model、截断结果；断言 `probe_model` 区分鉴权／限流／ID 不符／截断，且没有一项被伪装为 passed。无配置时不发网络请求。

```python
@pytest.mark.asyncio
async def test_missing_model_config_stays_pending():
    from wechat_agent.model.probe import probe_model
    report = await probe_model({})
    assert report.status == "pending"
```

- [x] **Step 2 — 验证红灯：** `python -m pytest tests/test_model_probe.py -q`，预期缺少 probe 实现。
- [x] **Step 3 — 最小实现：** 根据实际 DeepSeek 协议实现最小一次验证；窗口和最大输出由官方资料及实际账号能力核对，不从一次短回复推断。结构化输出、视觉分别记录 verified／unsupported／pending；不支持结构输出可走后续本地校验，但不可标为支持。
- [ ] **Step 4 — 显式实机核验：** 在 Mac 本地配置凭据后执行 `python -m wechat_agent.doctor --check-model --output .local/evidence/m0.json`，发一个最小验证请求，记录 model_id、日期、接口、结束原因、用量和资料出处。缺可用 Pro 时报告 blocked，不静默换成别的模型。视觉验证仅在实际支持并提供样本时进行。
- [ ] **Step 5 — 验证：** 回放用 `python -m pytest tests/test_model_probe.py -q`；真实能力记录与响应相互核对。doctor 默认运行仍不会自动调用模型，测试日志不含 key。
- [x] **Step 6 — 提交检查点：** 获准时提交 model 模块、脱敏测试和 model-capabilities.md，消息 `feat: verify configured model capabilities`。

### Task 4: 媒体可见性与 M0 出口

**Files:** Create `src/wechat_agent/attachments/{__init__,probe}.py`, `tests/test_media_probe.py`, `docs/verification/m0-report.md`；Modify `docs/MAC_SETUP.md`, `.gitignore`。

**Interfaces:** `inspect_media(path: Path) -> dict` 返回获取状态、字节数、哈希和类型；只证明原件可读，不证明内容已解析。

- [x] **Step 1 — 先写失败测试：** `test_missing_media_is_not_parsed` 用不存在路径，断言 `state == 'missing'`、`parsed is False`；另测缩略图与原件分开、零字节文件失败、证据导出剔除本机绝对路径和 key。

```python
def test_missing_media_is_not_parsed(tmp_path):
    from wechat_agent.attachments.probe import inspect_media
    report = inspect_media(tmp_path / "absent.png")
    assert report["state"] == "missing"
    assert report["parsed"] is False
```

- [x] **Step 2 — 验证红灯：** `python -m pytest tests/test_media_probe.py -q`，预期缺少 probe。
- [ ] **Step 3 — 最小实现与采样：** 从实际来源取图片、PDF、CSV／XLSX 样本各一份及缺失附件样本；记录原件／缩略图与可见范围，暂不实现 OCR。整理账号数、会话数、可见时间段、样本体积及 M0 未闭合项。
- [x] **Step 4 — 验证：** `python -m pytest tests/test_doctor.py tests/test_source_probe.py tests/test_model_probe.py tests/test_media_probe.py -q` 全过；云端已逐项记录实施方案 §11，m0-report.md 区分云端完成、用户运行环境已验证和其余真实能力待验证。复查 `git diff --cached`，原始消息、附件、凭据不在提交清单。
- [x] **Step 5 — 提交检查点：** 获准时提交媒体探测、测试和脱敏 M0 报告，消息 `docs: record verified local capability baseline`。

## 执行记录

- M0 任务 1 已完成：7 个测试先失败后通过；离线 CLI 已实际运行，Linux 来源明确为 unsupported，模型／媒体为 pending。
- 任务4云端已实现：媒体只读检查、流式哈希和脱敏报告；79个Python测试通过。
- 任务3云端已实现：明确配置的最小模型探测、错误分类、容量声明与实际验证区分；真实Pro ID、凭据、容量及视觉仍待实测。
- 任务2云端已实现：只读 HTTP 检查、来源契约、有限样本与错误分类，37个测试通过。已核对第三方 wx-cli v0.7.4 上游；随后Mac有限采样passed（8条有效、0异常），不声称全历史或姓名准确性已通过。当前执行位置见[状态页](../../STATUS.md)。

## 退出条件

- [x] Mac已可clone、运行doctor及启动原型（用户验证）；技能仅云端开发使用，本地无需恢复。
- [ ] 真实源账号、消息 ID、分页、姓名和只读操作均有证据；关键缺口不能留成假成功。
- [ ] 实际 Pro 模型、容量、协议及输出能力得到确认，或明确无法进入模型阶段的阻碍。
- [ ] 已取得的核验结果同步到契约及 M1／M2 计划；未知协议保持显式待验证，可独立测试的模块继续云端开发，媒体支持不足按格式降级。
