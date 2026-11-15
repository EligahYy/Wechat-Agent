import { ModelConfigDialog } from "./ModelConfigDialog";
import { ImportDialog } from "./ImportDialog";
import { useState } from "react";
import { Clock3, ExternalLink, Monitor, ShieldCheck } from "lucide-react";
import { TimePicker } from "../../components/TimePicker";
import { SegmentedControl } from "../../components/SegmentedControl";
import { Dialog } from "../../components/Dialog";
import type { AppSettings, Preferences } from "../../api/types";
export function SettingsPage({
  settings,
  saving,
  onSave,
  onImported,
  onModelChanged,
  onManageContacts,
}: {
  settings: AppSettings;
  saving: boolean;
  onSave: (changes: Partial<Preferences>) => Promise<void>;
  onImported?:()=>void;
  onModelChanged?:()=>void;
  onManageContacts?:()=>void;
}) {
  const [modelOpen,setModelOpen]=useState(false);
  const [info, setInfo] = useState(false);
  const [importOpen,setImportOpen]=useState(false);
  const disabled = saving || !settings.account_id;
  return (
    <div className="settings-stack">
      <section className="settings-card"><h3>联系人管理</h3><div className="settings-row"><p>查看全部归档，单个或批量调整业务范围</p><button className="button secondary" onClick={onManageContacts}>管理全部联系人</button></div></section>
      {modelOpen&&settings.account_id&&<ModelConfigDialog accountId={settings.account_id} onClose={()=>setModelOpen(false)} onChanged={()=>onModelChanged?.()}/>}
      <section className="settings-card">
        <header>
          <ShieldCheck size={21} />
          <h3>本机数据与模型</h3>
        </header>
        <div className="settings-row">
          <div>
            <strong>工作微信 / wx-cli</strong>
            <p>{settings.account_id ? "工作账号已绑定" : "工作账号未绑定"}</p>
          </div>
          <div className="config-status">
            <span className="info-chip">
              {{
                last_metadata_succeeded: "上次联系人刷新完成",
                last_metadata_failed: "上次联系人刷新未完成",
                last_metadata_stopped: "上次联系人刷新已停止",
                last_metadata_running: "正在刷新联系人",
                last_metadata_queued: "联系人刷新已排队",
                last_sync_succeeded: "上次同步成功",
                last_sync_failed: "上次同步未完成",
                last_sync_stopped: "上次同步已停止",
                last_sync_running: "正在同步",
                last_sync_queued: "同步已排队",
              }[settings.source.state] || "连接未检查"}
            </span>
            <button className="button secondary" onClick={() => setInfo(true)}>
              连接说明 <ExternalLink size={14} />
            </button>
          </div>
        </div>
        <div className="settings-row">
          <div>
            <strong>{settings.model.model_id || "模型服务"}</strong>
            <p>
              {settings.model.state === "configured"
                ? "配置已保存，运行能力尚未验证"
                : "模型整理尚未接入"}
            </p>
          </div>
          <button className="button secondary" disabled={!settings.account_id} onClick={()=>setModelOpen(true)}>配置模型</button>
        </div>
        <div className="settings-row">
          <div>
            <strong>图片与文件</strong>
            <p>原文和附件引用已归档，文件获取与解析尚未接入</p>
          </div>
          <span className="info-chip">待接入</span>
        </div>
      </section>
      <section className="settings-card">
        <header>
          <Clock3 size={21} />
          <h3>每日整理</h3>
          <span className="info-chip">调度待接入</span>
        </header>
        <div className="settings-row">
          <div>
            <strong>每日自动整理</strong>
            <p>当前仅保存配置，自动执行在调度接入后启用</p>
          </div>
          <button
            className="switch"
            role="switch"
            aria-label="每日自动整理"
            aria-checked={settings.preferences.daily_enabled}
            disabled={disabled}
            onClick={() =>
              void onSave({
                daily_enabled: !settings.preferences.daily_enabled,
              }).catch(() => {})
            }
          >
            <span />
          </button>
        </div>
        <div className="settings-row">
          <div>
            <strong>每天开始时间</strong>
          </div>
          <TimePicker
            value={settings.preferences.daily_time}
            disabled={disabled || !settings.preferences.daily_enabled}
            onCommit={(value) => onSave({ daily_time: value })}
          />
        </div>
      </section>
      <section className="settings-card">
        <header>
          <Monitor size={21} />
          <h3>外观</h3>
        </header>
        <div className="settings-row">
          <strong>主题</strong>
          <div inert={disabled}>
            <SegmentedControl
              label="外观主题"
              value={settings.preferences.appearance}
              onChange={(appearance) =>
                void onSave({ appearance }).catch(() => {})
              }
              options={[
                { value: "system", label: "跟随系统" },
                { value: "light", label: "浅色" },
                { value: "dark", label: "深色" },
              ]}
            />
          </div>
        </div>
        <div className="settings-row">
          <div>
            <strong>减少动态效果</strong>
            <p>系统已启用时会自动遵循</p>
          </div>
          <button
            className="switch"
            role="switch"
            aria-label="减少动态效果"
            aria-checked={settings.preferences.reduce_motion}
            disabled={disabled}
            onClick={() =>
              void onSave({
                reduce_motion: !settings.preferences.reduce_motion,
              }).catch(() => {})
            }
          >
            <span />
          </button>
        </div>
      </section>
      <section className="settings-card"><header><ShieldCheck size={21}/><h3>消息导入</h3></header><div className="settings-row"><div><strong>导入聊天原文</strong><p>CSV／JSON先预览，核对字段后导入</p></div><button className="button secondary" disabled={disabled} onClick={()=>setImportOpen(true)}>导入消息</button></div></section>
      {importOpen&&settings.account_id&&<ImportDialog accountId={settings.account_id} onClose={()=>setImportOpen(false)} onImported={()=>onImported?.()}/>}
      <Dialog
        open={info}
        title="连接说明"
        onClose={() => setInfo(false)}
        footer={
          <button className="button primary" onClick={() => setInfo(false)}>
            完成
          </button>
        }
      >
        <p className="muted">
          wx-cli
          是独立的只读来源服务。当前界面只展示配置，实际连接由显式同步验证。
        </p>
        <p style={{ margin: "20px 0 10px" }}>在本机启动并确认来源状态：</p>
        <div className="code-line">wx-cli server status</div>
        <p className="muted" style={{ marginTop: 16 }}>
          来源地址与账号固定配置在项目的
          .local/config/source.json。模型凭据保存在后端，界面不读取密钥。
        </p>
      </Dialog>
    </div>
  );
}
