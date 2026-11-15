import { AnimatePresence } from "motion/react";
import { SelectField } from "../../components/SelectField";
import { RoleMenu } from "../../components/RoleMenu";
import { MessageBrowser } from "../messages/MessageBrowser";
import { CustomerSyncStatus } from "../../components/CustomerSyncStatus";
import { active } from "../../app/useOperations";
import { nameNotice, sourceLabel, avatarText } from "./presentation";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Archive,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  FileText,
  RefreshCw,
  Search,
  Users,
  X,
} from "lucide-react";
import { FormField } from "../../components/FormField";
import { SegmentedControl } from "../../components/SegmentedControl";
import { Dialog } from "../../components/Dialog";
import { RoleTag, roleNames } from "../../components/RoleTag";
import { request, ApiError, messageFor } from "../../api/client";
import type {
  AppSettings,
  Contact,
  ContactPage,
  Role,
  RoleUpdate,
  Operation,
  ContactKey,
} from "../../api/types";
const initialCounts = {
  all: 0,
  merchant: 0,
  provider: 0,
  platform: 0,
  unknown: 0,
};
export function ContactsPage({
  settings,
  revision,
  onSync,
  notify,
  banner,
  management=false,
  onScopeChanged,
  operation,
  syncSubmitting,
  syncError,
  syncErrorScope,
  onStop,
  onShowOperation,
}: {
  banner?: ReactNode;
  management?:boolean;
  onScopeChanged?:()=>void;
  settings: AppSettings;
  revision: number;
  onSync: (contactId?: string) => Promise<void>;
  notify: (text: string) => void;
  operation: Operation|null;
  syncSubmitting:boolean;
  syncError:string;
  syncErrorScope:ContactKey|null;
  onStop:()=>void;
  onShowOperation:(operation:Operation)=>void;
}) {
  const [view, setView] = useState<"merchants" | "all">(management?"all":"merchants"),
    [role, setRole] = useState<Role | "all">("all"),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(1);
  const [scopeResult,setScopeResult]=useState("");
  const [membership,setMembership]=useState("all");
  const [scopeBusy,setScopeBusy]=useState(false);
  const [data, setData] = useState<ContactPage | null>(null),
    [counts, setCounts] = useState(initialCounts),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<Map<string, Contact>>(new Map()),
    [detail, setDetail] = useState<Contact | null>(null),
    [detailOpen, setDetailOpen] = useState(false);
  const detailTabs=useRef<HTMLDivElement>(null);
  const [messageContact,setMessageContact]=useState<string|null>(null);
  const [detailView,setDetailView]=useState<"overview"|"messages">("overview");
  const detailOperation=detail&&operation?.scope.account_id===detail.key.account_id&&operation.scope.contact_id===detail.key.contact_id?operation:null;
  const detailError=detail&&syncErrorScope?.account_id===detail.key.account_id&&syncErrorScope.contact_id===detail.key.contact_id?syncError:'';
  const [roleAnchor,setRoleAnchor]=useState<HTMLElement|null>(null);
  const [roleOpen, setRoleOpen] = useState(false),
    [roleTargets, setRoleTargets] = useState<Contact[]>([]),
    [nextRole, setNextRole] = useState<Role>("merchant"),
    [saving, setSaving] = useState(false),
    [roleError, setRoleError] = useState("");
  const sequence = useRef(0),
    checkAll = useRef<HTMLInputElement>(null),
    tableHeading = useRef<HTMLButtonElement>(null);
  const tableContent = useRef<HTMLDivElement>(null);
  const [tableHeight, setTableHeight] = useState<number>();
  useLayoutEffect(() => {
    const node=tableContent.current;
    if(!node)return;
    const measure=()=>{
      const height=node.getBoundingClientRect().height;
      if(height>0)setTableHeight(previous=>previous!==undefined&&Math.abs(previous-height)<0.5?previous:height);
    };
    measure();
    if(typeof ResizeObserver==="undefined")return;
    const observer=new ResizeObserver(measure);observer.observe(node);
    return ()=>observer.disconnect();
  }, [data, view]);
  const account = settings.account_id;
  useEffect(() => {
    if (!account) return;
    const id = ++sequence.current,
      controller = new AbortController();
    setBusy(true);
    const timer = setTimeout(
      () => {
        const params = new URLSearchParams({
          account_id: account,
          scope:management?"all":"business",
          membership:management?membership:"all",
          q: query,
          role: view === "merchants" ? "merchant" : role,
          page: String(page),
          page_size: "20",
        });
        request<ContactPage>(`/api/contacts?${params}`, {
          signal: controller.signal,
        })
          .then((result) => {
            if (id !== sequence.current) return;
            if (result.total > 0 && page > Math.ceil(result.total / 20)) {
              setPage(Math.ceil(result.total / 20));
              return;
            }
            setData(result);
            setError("");
            if (!query) setCounts(result.role_counts);
          })
          .catch((reason) => {
            if (!controller.signal.aborted && id === sequence.current)
              setError(messageFor(reason));
          })
          .finally(() => {
            if (id === sequence.current && !controller.signal.aborted)
              setBusy(false);
          });
      },
      query ? 140 : 0,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [account, query, role, page, view, refresh, revision, management, membership]);
  const rows = data?.items || [];
  const selectedOnPage = rows.filter((person) =>
    selected.has(person.key.contact_id),
  ).length;
  useEffect(() => {
    if (checkAll.current)
      checkAll.current.indeterminate =
        selectedOnPage > 0 && selectedOnPage < rows.length;
  }, [selectedOnPage, rows.length]);
  useEffect(() => {
    if (detail) {
      const fresh = rows.find(
        (person) => person.key.contact_id === detail.key.contact_id,
      );
      if (fresh) setDetail(fresh);
    }
  }, [data]);
  const switchView = (next: "merchants" | "all") => {
    setView(next);
    setPage(1);
    setRole("all");
    setQuery("");
    setSelected(new Map());
  };
  const toggle = (contact: Contact, checked: boolean) =>
    setSelected((previous) => {
      const next = new Map(previous);
      if (checked) next.set(contact.key.contact_id, contact);
      else next.delete(contact.key.contact_id);
      return next;
    });
  const openRoles = (contacts: Contact[],anchor?:HTMLElement) => {
    setRoleAnchor(anchor||null);
    setRoleTargets(contacts);
    setNextRole(contacts.length === 1 ? contacts[0].role : "merchant");
    setRoleError("");
    setRoleOpen(true);
  };
  const copy = async (contact: Contact) => {
    if (!contact.copy_name) return;
    try {
      await navigator.clipboard.writeText(contact.copy_name);
      notify("已复制微信名称");
    } catch {
      notify("复制失败，请检查浏览器权限");
    }
  };
  const saveRoles = async (chosenRole?:Role) => {
    if (saving || !account) return;
    setSaving(true);
    setRoleError("");
    let result: RoleUpdate;
    try {
      try {
        result = await request<RoleUpdate>("/api/contacts/roles", {
          method: "PATCH",
          body: JSON.stringify({
            account_id: account,
            role: chosenRole||nextRole,
            items: roleTargets.map((contact) => ({
              key: contact.key,
              expected_version: contact.role_version,
            })),
          }),
        });
      } catch (reason) {
        if (
          reason instanceof ApiError &&
          reason.status === 409 &&
          Array.isArray(reason.details.updated)
        )
          result = reason.details as RoleUpdate;
        else throw reason;
      }
      const updates = new Map(
        result.updated.map((item) => [item.key.contact_id, item]),
      );
      setData((previous) =>
        previous
          ? {
              ...previous,
              items: previous.items.map((contact) => {
                const update = updates.get(contact.key.contact_id);
                return update
                  ? {
                      ...contact,
                      role: update.role,
                      role_version: update.role_version,
                    }
                  : contact;
              }),
            }
          : previous,
      );
      setDetail((previous) => {
        const update = previous && updates.get(previous.key.contact_id);
        return previous && update
          ? {
              ...previous,
              role: update.role,
              role_version: update.role_version,
            }
          : previous;
      });
      setSelected((previous) => {
        const next = new Map(previous);
        for (const item of result.updated) next.delete(item.key.contact_id);
        for (const failed of result.failed) {
          const person = next.get(failed.key.contact_id);
          if (person && failed.current_version)
            next.set(failed.key.contact_id, {
              ...person,
              role_version: failed.current_version,
            });
        }
        return next;
      });
      setRefresh((value) => value + 1);
      if(result.updated.length)onScopeChanged?.();
      if (result.failed.length) {
        setRoleTargets((previous) =>
          previous
            .filter((person) =>
              result.failed.some(
                (item) => item.key.contact_id === person.key.contact_id,
              ),
            )
            .map((person) => ({
              ...person,
              role_version:
                result.failed.find(
                  (item) => item.key.contact_id === person.key.contact_id,
                )?.current_version || person.role_version,
            })),
        );
        setRoleError(
          `已保存 ${result.updated.length} 位，${result.failed.length} 位信息已变化，请核对后重试`,
        );
      } else {
        setRoleOpen(false);
        notify(`已更新 ${result.updated.length} 位联系人的身份`);
      }
    } catch (reason) {
      setRoleError(messageFor(reason));
    } finally {
      setSaving(false);
    }
  };
  const changeScope=async(people:Contact[],included:boolean)=>{
    if(scopeBusy||!account)return;
    setScopeBusy(true);setScopeResult("");
    try{
      let result:{updated:{key:ContactKey}[];failed:{key:ContactKey;current_version:number|null}[]};
      try{result=await request("/api/contacts/scope",{method:"PATCH",body:JSON.stringify({account_id:account,included,items:people.map(person=>({key:person.key,expected_version:person.business_scope.version}))})});}
      catch(reason){if(reason instanceof ApiError&&reason.status===409&&Array.isArray(reason.details.updated))result=reason.details as typeof result;else throw reason;}
      setSelected(previous=>{const next=new Map(previous);for(const item of [...result.updated,...result.failed])next.delete(item.key.contact_id);return next;});
      if(result.failed.length)setScopeResult(`已更新 ${result.updated.length} 位，${result.failed.length} 位信息已变化，请重新选择后重试`);
      else notify(included?"已加入业务范围":"已移出业务范围；同步不会自动加回");
      setRefresh(value=>value+1);onScopeChanged?.();
    }catch(reason){setScopeResult(messageFor(reason));}finally{setScopeBusy(false);}
  };
  const scopeReason=(contact:Contact)=>contact.business_scope.reasons.map(reason=>({manual_include:"已手动加入",manual_exclude:"已手动移出",confirmed_role:"已确认身份",recent_private:"近90天私聊",direct_interaction:"近90天直接互动",group_demand:"群内业务需求",group_discovery_pending:"群需求识别待完成"})[reason]||reason).join(" · ")||"未纳入业务范围";
  return (
    <>
      {!management&&<div className="workspace-tabs">
        <SegmentedControl
          kind="tabs"
          value={view}
          label="工作台视图"
          onChange={switchView}
          options={[
            { value: "merchants", label: "商家档案", count: counts.merchant },
            { value: "all", label: "业务活跃联系人", count: counts.all },
          ]}
        />
      </div>}
      {management&&<div className="table-toolbar"><span className="muted">保留全部归档；人工移出优先，不会随同步自动恢复。</span><SelectField label="业务范围筛选" value={membership} onValueChange={value=>{setMembership(value);setPage(1);setSelected(new Map());}} options={[{value:"all",label:"全部归档"},{value:"included",label:"业务范围内"},{value:"excluded",label:"未在业务范围内"}]}/></div>}
      {banner}
      {!account ? (
        <div className="panel empty-state">
          <div className="empty-icon">
            <Archive />
          </div>
          <strong>尚未归档微信资料</strong>
          <span>先在本机完成来源配置和首次归档</span>
        </div>
      ) : (
        <section
          className="panel"
          aria-label={view === "all" ? "联系人管理" : "商家档案列表"}
        >
          <div className="table-toolbar">
            <FormField
              label={view === "all" ? "搜索联系人" : "搜索商家"}
              type="search"
              placeholder="搜索姓名或备注"
              value={query}
              leading={<Search size={17} />}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(1);
              }}
              trailing={
                query ? (
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="清空搜索"
                    onClick={() => {
                      setQuery("");
                      setPage(1);
                    }}
                  >
                    <X size={15} />
                  </button>
                ) : undefined
              }
            />
            {view === "all" ? (
              <SegmentedControl
                value={role}
                label="联系人身份筛选"
                onChange={(value) => {
                  setRole(value);
                  setPage(1);
                }}
                options={(
                  [
                    "all",
                    "merchant",
                    "provider",
                    "platform",
                    "unknown",
                  ] as const
                ).map((value) => ({
                  value,
                  label: value === "all" ? "全部" : roleNames[value],
                  count: data?.role_counts[value] || 0,
                }))}
              />
            ) : (
              <div className="field">
                <label>资料状态</label>
                <button
                  type="button"
                  className="button secondary"
                  disabled
                  title="档案整理接入后开放筛选"
                >
                  全部资料 <ChevronDown size={15} />
                </button>
              </div>
            )}
          </div>
          <div className="table-meta" aria-live="polite">
            <span>
              {data?.total || 0} 位{view === "all" ? "联系人" : "商家"}
              {busy ? " · 更新中" : ""}
            </span>
            <span title="包含来源联系人资料和已有沟通人物；历史归档不代表当前微信好友">归档范围 · 每页 20 位</span>
          </div>
          <div
            className={`batch-collapse ${selected.size ? "is-open" : ""}`}
            aria-hidden={!selected.size}
            inert={!selected.size}
          >
            <div className="batch-clip">
              <div className="batch-bar">
                <span>已选 {selected.size} 位联系人</span>
                {management&&<button className="button secondary" disabled={scopeBusy} onClick={()=>void changeScope(Array.from(selected.values()),true)}>批量加入业务范围</button>}
                <button className="button secondary" disabled={scopeBusy} onClick={()=>void changeScope(Array.from(selected.values()),false)}>批量移出业务范围</button>
                <button
                  type="button"
                  className="button primary"
                  onClick={() => openRoles(Array.from(selected.values()))}
                >
                  设置身份
                </button>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => {
                    setSelected(new Map());
                    checkAll.current?.focus();
                  }}
                >
                  清空
                </button>
              </div>
            </div>
          </div>
          {scopeResult&&<div className="error-banner" role="alert">{scopeResult}</div>}
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button
                className="text-button"
                onClick={() => setRefresh((value) => value + 1)}
              >
                重试
              </button>
            </div>
          )}
          <div
            className="table-shell"
            aria-busy={busy}
            style={{ height: tableHeight }}
          >
            <div ref={tableContent}>
              <table
                className="contact-table"
                aria-label={view === "all" ? "全部联系人列表" : "商家列表"}
              >
                <thead>
                  <tr>
                    {view === "all" && (
                      <th className="check-cell">
                        <input
                          ref={checkAll}
                          type="checkbox"
                          aria-label="选择本页联系人"
                          checked={
                            rows.length > 0 && selectedOnPage === rows.length
                          }
                          disabled={!rows.length}
                          onChange={(event) => {
                            const checked = event.target.checked;
                            setSelected((previous) => {
                              const next = new Map(previous);
                              for (const contact of rows) {
                                if (checked)
                                  next.set(contact.key.contact_id, contact);
                                else next.delete(contact.key.contact_id);
                              }
                              return next;
                            });
                          }}
                        />
                      </th>
                    )}
                    <th className="name-column">联系人</th>
                    {view === "all" ? (
                      <>
                        <th className="role-column">身份</th>
                        <th>关联来源</th>
                      </>
                    ) : (
                      <>
                        <th>货品与路线</th>
                        <th>当前沟通</th>
                        <th className="date-column">资料更新</th>
                      </>
                    )}
                    <th className="action-column">
                      <span className="sr-only">操作</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((contact) => (
                    <tr
                      key={contact.key.contact_id}
                      data-contact={contact.key.contact_id}
                      data-selected={selected.has(contact.key.contact_id)}
                    >
                      {view === "all" && (
                        <td className="check-cell">
                          <input
                            type="checkbox"
                            aria-label={`选择 ${contact.display_name}`}
                            checked={selected.has(contact.key.contact_id)}
                            onChange={(event) =>
                              toggle(contact, event.target.checked)
                            }
                          />
                        </td>
                      )}
                      <td>
                        <div className="contact-name">
                          <span className="avatar" aria-hidden="true">
                            {avatarText(contact.display_name)}
                          </span>
                          <div>
                            <button
                              className="name-button"
                              aria-label={`查看 ${contact.display_name}`}
                              onClick={() => {
                                setDetail(contact);setMessageContact(null);
                                setDetailView("overview");
                                setDetailOpen(true);
                              }}
                            >
                              {contact.display_name}
                            </button>
                            {nameNotice(contact) && <span className="source-line" title="群内、会话及历史名称不能作为当前全局微信名称复制">{nameNotice(contact)}</span>}
                            {view === "all" ? (
                              <div className="contact-id">
                                {contact.key.contact_id}
                              </div>
                            ) : (
                              <span className="source-line">
                                {contact.sources.some(
                                  (source) => source.kind === "private",
                                )
                                  ? "私信"
                                  : ""}
                                {contact.sources.filter(
                                  (source) => source.kind === "group",
                                ).length
                                  ? ` · ${contact.sources.filter((source) => source.kind === "group").length} 个群聊`
                                  : ""}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>
                      {view === "all" ? (
                        <>
                          <td>
                            <RoleTag role={contact.role} /><span className="source-line">{scopeReason(contact)}</span>
                          </td>
                          <td>
                            {contact.sources.length ? (
                              contact.sources.slice(0, 2).map((source) => (
                                <span
                                  key={source.conversation_id}
                                  className="source-line"
                                >
                                  {sourceLabel(source)}
                                </span>
                              ))
                            ) : (
                              <span className="muted">—</span>
                            )}
                            {contact.sources.length > 2 && (
                              <span className="source-line">
                                另有 {contact.sources.length - 2} 个来源
                              </span>
                            )}
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="muted">—</td>
                          <td>
                            <span className="info-chip">
                              {contact.profile_status === "pending"
                                ? "待整理"
                                : "暂无资料"}
                            </span>
                            {contact.source_gaps.length > 0 && (
                              <span className="source-line">来源有缺口</span>
                            )}
                          </td>
                          <td className="muted">
                            {contact.profile_updated_at
                              ? new Intl.DateTimeFormat("zh-CN", {
                                  timeZone: "Asia/Shanghai",
                                  month: "numeric",
                                  day: "numeric",
                                }).format(new Date(contact.profile_updated_at))
                              : "—"}
                          </td>
                        </>
                      )}
                      <td>
                        <div className="cell-actions">
                          <button
                            className="icon-button"
                            aria-label="复制微信名称"
                            title={contact.copy_name ? "复制微信名称" : "当前无可确认的全局微信名称"}
                            disabled={!contact.copy_name}
                            onClick={() => void copy(contact)}
                          >
                            <Copy size={15} />
                          </button>
                          {view === "all"&&<button className="text-button" disabled={scopeBusy} onClick={()=>void changeScope([contact],!contact.business_scope.included)}>{contact.business_scope.included?"移出业务范围":"加入业务范围"}</button>}
                          {view === "all" ? (
                            <button
                              className="text-button"
                              onClick={event => openRoles([contact],event.currentTarget)}
                            >
                              修改身份
                            </button>
                          ) : (
                            <button
                              className="icon-button"
                              aria-label={`打开 ${contact.display_name}`}
                              onClick={() => {
                                setDetail(contact);setMessageContact(null);
                                setDetailView("overview");
                                setDetailOpen(true);
                              }}
                            >
                              <ChevronRight size={18} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length === 0 && (
                <div className="empty-state">
                  <div className="empty-icon">
                    <Users size={24} />
                  </div>
                  <strong>
                    {busy
                      ? "正在读取联系人"
                      : query
                        ? "没有匹配的联系人"
                        : view === "merchants"
                          ? "尚无已确认商家"
                          : "没有联系人"}
                  </strong>
                  {!busy && !query && view === "merchants" && (
                    <button
                      ref={tableHeading}
                      className="text-button"
                      onClick={() => switchView("all")}
                    >
                      前往业务活跃联系人
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
          <footer className="pagination">
            <button
              className="icon-button"
              aria-label="上一页"
              disabled={page === 1 || busy}
              onClick={() => setPage((value) => value - 1)}
            >
              <ChevronLeft size={18} />
            </button>
            <span>
              第 {page} / {Math.max(1, Math.ceil((data?.total || 0) / 20))} 页
            </span>
            <button
              className="icon-button"
              aria-label="下一页"
              disabled={busy || page * 20 >= (data?.total || 0)}
              onClick={() => setPage((value) => value + 1)}
            >
              <ChevronRight size={18} />
            </button>
          </footer>
        </section>
      )}
      <Dialog
        open={detailOpen && !!detail}
        className="dialog-contact"
        wide
        onClose={() => setDetailOpen(false)}
        headerActions={
          detail && (
            <button
              className="button secondary"
              disabled={syncSubmitting||active(operation)}
              title={active(operation)&&!detailOperation?'其他任务正在进行，请稍后再试':undefined}
              onClick={() => void onSync(detail.key.contact_id)}
            >
              <RefreshCw size={15} className={active(detailOperation)?'spin':undefined}/>
              {active(detailOperation)?detailOperation?.phase==='source'?'同步中…':'任务进行中…':detail.role==='merchant'?'同步并整理此客户':'同步该联系人消息'}
            </button>
          )
        }
        status={detail&&(detailOperation||detailError)&&<CustomerSyncStatus operation={detailOperation} error={detailError} submitting={syncSubmitting} onStop={onStop} onDetails={onShowOperation}/>}
        title={
          detail && (
            <span className="detail-heading">
              <span className="avatar" aria-hidden="true">
                {avatarText(detail.display_name)}
              </span>
              <span>
                <span className="detail-name">
                  {detail.display_name}
                  <button
                    className="role-trigger"
                    aria-label="修改身份"
                    onClick={event => openRoles([detail],event.currentTarget)}
                  >
                    <RoleTag role={detail.role} />
                    <ChevronDown size={12} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label="复制微信名称"
                    title={detail.copy_name ? "复制微信名称" : "当前无可确认的全局微信名称"}
                    disabled={!detail.copy_name}
                    onClick={() => void copy(detail)}
                  >
                    <Copy size={15} />
                  </button>
                </span>
                <span className="contact-id">{detail.key.contact_id}</span>
                {nameNotice(detail) && <span className="source-line">{nameNotice(detail)}</span>}
              </span>
            </span>
          )
        }
      >
        {detail && (
          <>
            <div className="detail-tabs" ref={detailTabs}><SegmentedControl label="客户资料视图" value={detailView} onChange={value=>{setDetailView(value);if(value==="messages")setMessageContact(detail.key.contact_id);}} options={[{value:"overview",label:"资料概览"},{value:"messages",label:"沟通原文"}]}/></div>
            {(detailView==="messages"||messageContact===detail.key.contact_id)&&<div hidden={detailView!=="messages"}><MessageBrowser key={`${detail.key.account_id}:${detail.key.contact_id}`} contact={detail.key} revision={revision} visible={detailView==="messages"}/></div>}<div className="detail-overview-pane page-enter" hidden={detailView!=="overview"}><div className="detail-unavailable">
              <FileText size={28} />
              <strong>
                {detail.role === "merchant" ? "档案尚未生成" : "仅保留沟通资料"}
              </strong>
              <span>
                {detail.role === "merchant"
                  ? "模型整理将在后续阶段接入"
                  : "此身份不参与商家档案整理"}
              </span>
            </div></div>
          </>
        )}
      </Dialog>
      <AnimatePresence>{roleOpen&&roleAnchor&&roleTargets.length===1&&<RoleMenu key="single-role" anchor={roleAnchor} value={roleTargets[0].role} busy={saving} error={roleError} onChoose={value=>void saveRoles(value)} onClose={()=>setRoleOpen(false)}/>}</AnimatePresence>
      <Dialog
        open={roleOpen&&!roleAnchor}
        title="设置身份"
        onClose={() => {
          if (!saving) setRoleOpen(false);
        }}
        footer={
          <>
            <button
              type="button"
              className="button secondary"
              disabled={saving}
              onClick={() => setRoleOpen(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="button primary"
              disabled={saving}
              onClick={() => void saveRoles()}
            >
              {saving ? "保存中…" : "保存身份"}
            </button>
          </>
        }
      >
        <p className="muted">
          {roleTargets.length === 1
            ? roleTargets[0].display_name
            : `${roleTargets.length} 位联系人`}
        </p>
        {roleError && (
          <div role="alert" className="error-banner">
            {roleError}
          </div>
        )}
        <div className="role-options" role="radiogroup" aria-label="联系人身份">
          {(["merchant", "provider", "platform", "unknown"] as const).map(
            (value) => (
              <button
                className="role-option"
                type="button"
                role="radio"
                aria-label={roleNames[value]}
                aria-checked={nextRole === value}
                key={value}
                disabled={saving}
                tabIndex={nextRole === value ? 0 : -1}
                onKeyDown={(event) => {
                  const options: Role[] = [
                    "merchant",
                    "provider",
                    "platform",
                    "unknown",
                  ];
                  if (
                    [
                      "ArrowRight",
                      "ArrowDown",
                      "ArrowLeft",
                      "ArrowUp",
                      "Home",
                      "End",
                    ].includes(event.key)
                  ) {
                    event.preventDefault();
                    const next =
                      event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? 3
                          : (options.indexOf(value) +
                              (["ArrowLeft", "ArrowUp"].includes(event.key)
                                ? -1
                                : 1) +
                              4) %
                            4;
                    setNextRole(options[next]);
                    (
                      event.currentTarget.parentElement?.children[
                        next
                      ] as HTMLElement
                    )?.focus();
                  }
                }}
                onClick={() => setNextRole(value)}
              >
                <RoleTag role={value} />
                {nextRole === value && <Check size={18} />}
              </button>
            ),
          )}
        </div>
      </Dialog>
    </>
  );
}
