# 固定 wx-cli 来源补丁

上游pandorafuture/wx-cli为MIT许可第三方项目；本补丁不是腾讯官方接口，也不冒充上游原版。固定commit及patch SHA256见manifest.json，依赖沿用上游Cargo.lock。

版本：`0.7.4+wechat-agent.2`，能力契约：`wechat-agent-source-v1`。

- 群正文仅在前缀与Name2Id发送人一致时剥离；URL／XML不替换发送人。缺数据库发送人保留空归属和完整正文。候选仅从剥离前的原始前缀取得，不将剥离后的正文二次解析。已知人物前缀与Name2Id冲突时，HTTP返回空sender及sender_issue、sender_fallback、sender_candidate供归档，不能猜人物。
- `GET /api/v1/identity/contacts?show_hidden=1&limit=200&offset=0`返回user_name、remark／nickname的value与known／empty／unreadable状态，relationship为unknown。字段类型／UTF8错误不伪装空值，行错误计入skipped。
- `GET /api/v1/identity/groups?show_hidden=1&limit=200&offset=0`返回username、members_state及成员user_name／display_name。无资料和解码失败分开；不把群名片当全局昵称。新增全量元数据接口要求显式show_hidden=1，沿用服务Bearer鉴权。
- health及元数据页返回metadata：contract、patch_id、mode（sqlcipher／decrypted_cache）、generation、resolver_generation、refreshed_at、refresh_state。generation参数不匹配返回409。refreshed_at是本服务最近成功打开／刷新来源及resolver的时间，不证明微信好友资料完整或不存在隐藏历史。
- `POST /api/v1/identity/refresh`只请求更新来源读取缓存，202不等于完成；待health代次前进且refresh_state=ready。接受请求前发布running，已有在途刷新则合并；失败代次不前进，状态failed；本项目不能把失败当成空名称。
- 联系人／会话连接的SQLite data_version在元数据读取前后和health中核验，外部写入使旧代次失效并标记stale等待刷新，区别于执行失败failed；这不代表跨微信多库原子快照。成功刷新后原子替换共享名称resolver，后续会话／发送人显示不再固定使用启动时名称缓存。旧式contacts等端点保持上游兼容，新项目须消费带状态的identity接口。

## 安装

本项目根目录运行`bash scripts/install-wx-cli.sh`；GitHub使用SSH时加`--transport ssh`。需要已安装Git、Rust／Cargo及平台C编译工具；在Mac这些是依赖安装，不需要修改源码。工具安装到`.local/tools/wx-cli/0.7.4+wechat-agent.2/bin/wx-cli`，不覆盖原全局wx-cli，不启动或停止真实服务。

安装器验证固定基线与补丁哈希，拒绝覆盖非预期checkout、额外本地修改或符号链接；再次运行同一补丁幂等。`--prepare-only`只准备可审查源码。Mac来源服务切换与回滚见主项目Mac指南的本次修复章节。

## 云端验证

Python安装器测试位于tests/test_wx_cli_installer.py；Rust回归随patch一并交付。在固定上游应用patch后执行`cargo test --locked --workspace --no-fail-fast`。Linux云端若bindgen缺少float.h，可在该构建命令中用`BINDGEN_EXTRA_CLANG_ARGS="-I$(cc -print-file-name=include)"`引用已安装编译器头文件，不修改系统或平台源码。

本次完整Rust回归的3个server_manager_cli失败已在干净上游同commit复现：进程已退出但云端PID1未回收为僵尸，kill(0)仍报告存在。它们不是本补丁绿灯证据，Mac生命周期仍需实测。其他失败须先定位，不能据此忽略。本次完整工作区：800通过、3个上述既有失败、11忽略；Linux release构建及干净源码安装／重复完整性检查通过。Mac实际来源验证仍待用户执行。
