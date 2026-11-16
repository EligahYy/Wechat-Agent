import {historyScopeLabel} from './operationOutcome';
import {OperationHistory} from '../components/OperationHistory';
import {Toast} from "../components/Toast";
import { ContactManager } from "../features/settings/ContactManager";
import { metadataSummary } from "./operationPresentation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  Settings as SettingsIcon,
  Sun,
  Moon,
  RefreshCw,
  ChevronRight,
  Check,
  Clock3,
  AlertCircle,
  Inbox,
} from "lucide-react";
import { MotionConfig, motion } from "motion/react";
import { request, messageFor } from "../api/client";
import type { AppSettings, Preferences, Operation } from "../api/types";
import { ContactsPage } from "../features/contacts/ContactsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { Dialog } from "../components/Dialog";
import { OperationDetails } from "../components/OperationDetails";
import { active, operationTitle, useOperations } from "./useOperations";
export function App() {
  const [manageContacts,setManageContacts]=useState(false);
  const [settings, setSettings] = useState<AppSettings | null>(null),
    [loadError, setLoadError] = useState(""),
    [prefError, setPrefError] = useState(""),
    [page, setPage] = useState<"workspace" | "settings">("workspace"),
    [revision, setRevision] = useState(0),
    [saving, setSaving] = useState(false),
    [toast, setToast] = useState(""),
    [theme, setTheme] = useState("light");
  const [recordsOpen, setRecordsOpen] = useState(false),
    [recordsLoading, setRecordsLoading] = useState(false),
    [recordsError, setRecordsError] = useState(""),
    [selectedJob, setSelectedJob] = useState<Operation | null>(null),
    [recordDetailLoading, setRecordDetailLoading] = useState(false),
    [recordDetailError, setRecordDetailError] = useState("");
  const recordRequest = useRef<AbortController | null>(null);
  const recordDetailRef = useRef<HTMLElement | null>(null), revealRecord = useRef(false);
  useEffect(() => () => recordRequest.current?.abort(), [recordsOpen, settings?.account_id]);
  const settingsRef = useRef<AppSettings | null>(null),
    prefLock = useRef(false);
  const loadSettings = useCallback(async () => {
    try {
      const result = await request<AppSettings>("/api/settings");
      settingsRef.current = result;
      setSettings(result);
      setLoadError("");
    } catch (reason) {
      setLoadError(messageFor(reason));
    }
  }, []);
  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);
  const finished = useCallback(() => {
    setRevision((value) => value + 1);
    void loadSettings();
  }, [loadSettings]);
  const operations = useOperations(settings?.account_id || null, finished);
  useEffect(() => {
    if (recordsOpen && revealRecord.current && recordDetailRef.current) {
      recordDetailRef.current.scrollIntoView({block:"start", behavior:"instant"});
      revealRecord.current = false;
    }
  }, [recordsOpen, selectedJob?.id, recordsLoading, operations.history]);
  useEffect(() => {
    if (!settings) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const actual =
        settings?.preferences.appearance === "system"
          ? media.matches
            ? "dark"
            : "light"
          : settings?.preferences.appearance || "light";
      document.documentElement.dataset.theme = actual;
      try {
        localStorage.setItem(
          "wechat-agent-appearance",
          settings.preferences.appearance,
        );
      } catch {}
      document.documentElement.dataset.reduceMotion = String(
        settings?.preferences.reduce_motion || false,
      );
      setTheme(actual);
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [settings?.preferences.appearance, settings?.preferences.reduce_motion]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3200);
    return () => clearTimeout(timer);
  }, [toast]);
  const savePreferences = async (changes: Partial<Preferences>) => {
    const current = settingsRef.current;
    if (!current?.account_id || prefLock.current)
      throw Error("settings_not_ready");
    prefLock.current = true;
    setSaving(true);
    setPrefError("");
    try {
      const result = await request<AppSettings>("/api/settings", {
        method: "PATCH",
        body: JSON.stringify({
          account_id: current.account_id,
          expected_version: current.version,
          preferences: changes,
        }),
      });
      settingsRef.current = result;
      setSettings(result);
    } catch (reason) {
      setPrefError(messageFor(reason));
      await loadSettings();
      throw reason;
    } finally {
      prefLock.current = false;
      setSaving(false);
    }
  };
  const selectRecord = async (item: Operation, retry = false) => {
    revealRecord.current = false;
    recordRequest.current?.abort();
    setRecordDetailError("");
    setRecordDetailLoading(false);
    if (!retry && selectedJob?.id === item.id) {
      setSelectedJob(null);
      return;
    }
    setSelectedJob(item);
    const controller = new AbortController();
    recordRequest.current = controller;
    setRecordDetailLoading(true);
    try {
      const result = await operations.read(item.id, controller.signal);
      if (!controller.signal.aborted) setSelectedJob(result);
    } catch (reason) {
      if (!controller.signal.aborted) setRecordDetailError(messageFor(reason));
    } finally {
      if (!controller.signal.aborted) setRecordDetailLoading(false);
    }
  };
  const showOperation = (operation: Operation) => {
    revealRecord.current = true;
    recordRequest.current?.abort();
    setRecordDetailLoading(false);
    setRecordDetailError("");
    setRecordsError("");
    setSelectedJob(operation);
    setRecordsOpen(true);
  };
  const showRecords = async () => {
    revealRecord.current = false;
    recordRequest.current?.abort();
    setRecordDetailLoading(false);
    setRecordDetailError("");
    setRecordsOpen(true);
    setRecordsLoading(true);
    setRecordsError("");
    setSelectedJob(null);
    try {
      await operations.loadHistory();
    } catch (reason) {
      setRecordsError(messageFor(reason));
    } finally {
      setRecordsLoading(false);
    }
  };
  if (!settings)
    return (
      <main className="app-loading">
        {loadError ? (
          <>
            <p role="alert">{loadError}</p>
            <button
              className="button primary"
              onClick={() => void loadSettings()}
            >
              重新连接
            </button>
          </>
        ) : (
          <p className="muted" role="status">
            正在打开工作台…
          </p>
        )}
      </main>
    );
  const job = operations.job;
  const current =
    selectedJob &&
    selectedJob.id === job?.id &&
    job?.items &&
    Date.parse(job.updated_at) >= Date.parse(selectedJob.updated_at)
      ? job
      : selectedJob;
  const recordDetail = current && (
    <section ref={recordDetailRef} className="history-detail" id={`record-${current.id}`} role="region" aria-label="记录详情" aria-busy={recordDetailLoading}>
      {recordDetailLoading ? <p className="muted" role="status">正在读取记录详情…</p> : recordDetailError ? (
        <div className="error-banner" role="alert"><span>{recordDetailError}</span><button className="text-button" onClick={() => void selectRecord(current, true)}>重试</button></div>
      ) : <>
        <OperationDetails operation={current} label={historyScopeLabel(current,operations.history)} onAction={(action)=>{if(action==='open_model_settings'){setRecordsOpen(false);setManageContacts(false);setPage('settings');}else if(action==='review_contact'){setRecordsOpen(false);setManageContacts(true);setPage('settings');}else if(action==='retry_sync'){void operations.start(current.scope.contact_id||undefined);}}} />
        {current.available_actions.includes("stop") && current.id === job?.id && (
          <button className="button secondary" disabled={operations.submitting} onClick={() => void operations.stop()}>停止本次</button>
        )}
      </>}
    </section>
  );
  return (
    <MotionConfig
      reducedMotion={settings.preferences.reduce_motion ? "always" : "user"}
    >
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">EU</span>
            <span>
              半托管欧区
              <br />
              备货用户助手
            </span>
          </div>
          <nav aria-label="主导航">
            {(
              [
                { value: "workspace", label: "工作台", icon: LayoutDashboard },
                { value: "settings", label: "设置", icon: SettingsIcon },
              ] as const
            ).map((item) => (
              <button
                type="button"
                className="nav-button"
                key={item.value}
                aria-current={page === item.value ? "page" : undefined}
                onClick={() => setPage(item.value)}
              >
                {page === item.value && (
                  <motion.span
                    className="nav-indicator"
                    layoutId="main-navigation"
                    transition={{ type: "spring", stiffness: 400, damping: 36 }}
                  />
                )}
                <span>
                  <item.icon size={19} />
                  {item.label}
                </span>
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="theme-toggle" aria-label="快速切换外观">
              {(
                [
                  { value: "light", label: "切换浅色外观", icon: Sun },
                  { value: "dark", label: "切换深色外观", icon: Moon },
                ] as const
              ).map((item) => (
                <button
                  key={item.value}
                  type="button"
                  aria-label={item.label}
                  aria-pressed={theme === item.value}
                  disabled={saving || !settings.account_id}
                  onClick={() =>
                    void savePreferences({ appearance: item.value }).catch(
                      () => {},
                    )
                  }
                >
                  {theme === item.value && (
                    <motion.span
                      className="theme-indicator"
                      layoutId="theme-indicator"
                      transition={{
                        type: "spring",
                        stiffness: 460,
                        damping: 36,
                      }}
                    />
                  )}
                  <item.icon size={16} />
                </button>
              ))}
            </div>
          </div>
        </aside>
        <main className="main">
          <header className="page-header">
            <h1>{page === "workspace" ? "工作台" : "设置"}</h1>
            {page === "workspace" && (
              <div className="header-actions">
                <button
                  className="button primary"
                  disabled={
                    operations.submitting ||
                    !settings.account_id ||
                    job?.state === "stop_requested"
                  }
                  onClick={() =>
                    void (active(job) ? operations.stop() : operations.start())
                  }
                >
                  <RefreshCw size={17} className={active(job) ? "spin" : ""} />
                  {operations.submitting
                    ? "提交中…"
                    : active(job)
                      ? job?.state === "stop_requested"
                        ? "正在停止"
                        : "停止本次"
                      : "同步并整理"}
                </button>
                <button
                  className="button secondary"
                  disabled={!settings.account_id}
                  onClick={() => void showRecords()}
                >
                  整理记录
                </button>
              </div>
            )}
          </header>
          {prefError && (
            <div className="error-banner" role="alert">
              <span>{prefError}</span>
              <button className="text-button" onClick={() => setPrefError("")}>
                关闭
              </button>
            </div>
          )}
          <div
            hidden={page !== "workspace"}
            className={page === "workspace" ? "page-enter" : undefined}
          >
            <ContactsPage
              onScopeChanged={()=>setRevision(value=>value+1)}
              banner={
                <>
                  <div className="status-banner" role="status">
                    <span className="status-icon">
                      {active(job) ? (
                        <RefreshCw size={18} className="spin" />
                      ) : job?.state === "succeeded" ? (
                        <Check size={18} />
                      ) : job?.state === "failed" ? (
                        <AlertCircle size={18} />
                      ) : (
                        <Clock3 size={18} />
                      )}
                    </span>
                    <div>
                      <strong>{operationTitle(job)}</strong>
                      {job && (
                        job.action === "refresh_contacts" ? <p>{metadataSummary(job)}</p> : <p>
                          已归档 {job.counts.inserted || 0} 条新增 ·{" "}
                          {job.counts.unchanged || 0} 条不变 ·{" "}
                          {job.counts.completed_conversations || 0} 个会话完成
                        </p>
                      )}
                    </div>
                    <button
                      className="text-button"
                      onClick={() => void showRecords()}
                    >
                      查看记录 <ChevronRight size={17} />
                    </button>
                  </div>
                  {operations.error && (
                    <div className="error-banner" role="alert">
                      {operations.error}
                    </div>
                  )}
                </>
              }
              settings={settings}
              revision={revision}
              onSync={operations.start}
              operation={job}
              syncSubmitting={operations.submitting}
              syncError={operations.error}
              syncErrorScope={operations.errorScope}
              onStop={()=>void operations.stop()}
              onShowOperation={showOperation}
              notify={setToast}
            />
          </div>
          <div
            hidden={page !== "settings"}
            className={page === "settings" ? "page-enter" : undefined}
          >
            {manageContacts?<><button className="text-button" onClick={()=>setManageContacts(false)}>返回设置</button><ContactManager settings={settings} revision={revision} onScopeChanged={()=>setRevision(value=>value+1)} onSync={operations.start} operation={job} syncSubmitting={operations.submitting} syncError={operations.error} syncErrorScope={operations.errorScope} onStop={()=>void operations.stop()} onShowOperation={showOperation} notify={setToast}/></>:<SettingsPage
              settings={settings}
              saving={saving}
              onSave={savePreferences}
              onImported={finished}
              onModelChanged={()=>void loadSettings()}
              onManageContacts={()=>setManageContacts(true)}
            />}
          </div>
        </main>
        <Dialog
          open={recordsOpen}
          title="整理记录"
          onClose={() => setRecordsOpen(false)}
          wide
        >
          {recordsError && (
            <div className="error-banner" role="alert">
              <span>{recordsError}</span>
              <button
                className="text-button"
                onClick={() => void showRecords()}
              >
                重试
              </button>
            </div>
          )}
          {current && !operations.history.some(item => item.id === current.id) && recordDetail}
          {recordsLoading ? (
            <p className="muted" role="status">
              正在读取记录…
            </p>
          ) : operations.history.length ? (
            <OperationHistory operations={operations.history} selectedId={current?.id} onSelect={item=>void selectRecord(item)} detail={recordDetail}/>
          ) : (
            <div className="empty-state">
              <Inbox size={28} />
              <strong>暂无整理记录</strong>
            </div>
          )}
        </Dialog>
        {toast && <Toast message={toast} onDismiss={()=>setToast("")}/>}
      </div>
    </MotionConfig>
  );
}
