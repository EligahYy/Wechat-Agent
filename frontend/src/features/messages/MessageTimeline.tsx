import { useEffect, useRef, useState } from "react";
import { Search, X, FileText, Download, RotateCcw } from "lucide-react";
import type { ContactKey, TimelinePage, TimelineItem } from "../../api/types";
import { request, messageFor, ApiError } from "../../api/client";
import { FormField } from "../../components/FormField";
import { SelectField } from "../../components/SelectField";
import { RoleTag } from "../../components/RoleTag";

const stateNames:Record<string,string>={unfetched:"未获取",original:"原件",thumbnail:"缩略图",missing:"本机缺失",unavailable:"不可用",failed:"获取失败"};
const kinds:Record<string,string>={text:"文字",image:"图片",file:"文件",video:"视频",voice:"语音",system:"系统事件",revoke:"撤回事件",quote:"引用"};
function date(value:string,day=false) {
  const parsed=new Date(value);if(!Number.isFinite(parsed.getTime())) return "时间待核实";
  return new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",...(day?{year:"numeric",month:"2-digit",day:"2-digit"}:{hour:"2-digit",minute:"2-digit",hour12:false})} as Intl.DateTimeFormatOptions).format(parsed);
}
export function MessageTimeline({contact,revision}:{contact:ContactKey;revision:number}) {
  const [query,setQuery]=useState("");const [source,setSource]=useState("");const [reload,setReload]=useState(0);
  const [data,setData]=useState<TimelinePage|null>(null);const [loading,setLoading]=useState(false);const [loadingMore,setLoadingMore]=useState(false);
  const [error,setError]=useState("");const [stale,setStale]=useState(false);const [downloadError,setDownloadError]=useState("");
  const generation=useRef(0);const loadController=useRef<AbortController|null>(null);
  const path=(cursor?:string)=>`/api/contacts/${encodeURIComponent(contact.contact_id)}/messages?${new URLSearchParams({account_id:contact.account_id,q:query, ...(source?{conversation_id:source}:{}),...(cursor?{cursor}:{})})}`;
  useEffect(()=>{
    const id=++generation.current;const controller=new AbortController();loadController.current?.abort();setLoadingMore(false);
    setLoading(true);setStale(false);
    const timer=setTimeout(()=>{request<TimelinePage>(path(),{signal:controller.signal}).then(result=>{
      if(id===generation.current){setData(result);setError("");}
    }).catch(reason=>{if(!controller.signal.aborted&&id===generation.current)setError(messageFor(reason));})
      .finally(()=>{if(!controller.signal.aborted&&id===generation.current)setLoading(false);});},query?180:0);
    return ()=>{controller.abort();clearTimeout(timer);loadController.current?.abort();};
  },[contact.account_id,contact.contact_id,query,source,revision,reload]);
  const more=async()=>{
    if(!data?.next_cursor||loading||loadingMore)return;
    const id=generation.current;const controller=new AbortController();loadController.current=controller;setLoadingMore(true);
    try {const result=await request<TimelinePage>(path(data.next_cursor),{signal:controller.signal});
      if(id===generation.current)setData({...result,items:[...data.items,...result.items]});
    } catch(reason){if(!controller.signal.aborted&&id===generation.current){setStale(reason instanceof ApiError&&reason.code==="message_cursor_stale");setError(messageFor(reason));}}
    finally {if(id===generation.current&&!controller.signal.aborted)setLoadingMore(false);}
  };
  const download=async(attachment:TimelineItem["attachments"][number])=>{
    setDownloadError("");
    try {const response=await fetch(`/api/attachments/${encodeURIComponent(attachment.id)}?${new URLSearchParams({account_id:contact.account_id})}`,{credentials:"same-origin"});
      if(!response.ok){const reason=await response.json();throw new ApiError(reason.code,response.status,reason.details);}
      const object=URL.createObjectURL(await response.blob());const link=document.createElement("a");link.href=object;link.download="attachment";link.click();setTimeout(()=>URL.revokeObjectURL(object),1000);
    }catch(reason){setDownloadError(messageFor(reason));}
  };
  return <section className="timeline" aria-label="沟通原文">
    <div className="timeline-tools">
      <FormField label="搜索沟通原文" type="search" placeholder="搜索原文内容" value={query} leading={<Search size={17}/>} onChange={event=>setQuery(event.target.value)} trailing={query?<button type="button" className="icon-button" aria-label="清空原文搜索" onClick={()=>setQuery("")}><X size={15}/></button>:undefined}/>
      <SelectField label="消息来源" value={source} onChange={event=>setSource(event.target.value)} options={[{value:"",label:"全部来源"},...(data?.sources||[]).map(item=>({value:item.conversation_id,label:item.title|| (item.kind==="group"?"群名称缺失":"私聊")}))]}/>
    </div>
    <div className="table-meta" aria-live="polite"><span>{data?.total||0} 条原文{loading?" · 更新中":""}</span><span>北京时间 · 只读</span></div>
    {error&&<div className="error-banner" role="alert"><span>{error}</span><button className="text-button" onClick={()=>setReload(value=>value+1)}><RotateCcw size={14}/>{stale?"重新加载原文":"重试"}</button></div>}
    {downloadError&&<p className="error-banner" role="alert">{downloadError}</p>}
    <div className="timeline-items" aria-busy={loading}>
      {!data&&loading?<p className="muted">正在读取原文…</p>:!data?.items.length&&!error?<div className="empty-state"><FileText size={26}/><strong>{query||source?"没有匹配的原文":"尚无已归档原文"}</strong><span>可先同步此客户，或在设置中导入消息</span></div>:data?.items.map((item,index)=><div key={item.message_id}>
        {(index===0||date(item.sent_at,true)!==date(data.items[index-1].sent_at,true))&&<div className="timeline-day">{date(item.sent_at,true)}</div>}
        <article className={`timeline-message ${item.sender.is_self?"is-self":""}`} data-message={item.message_id}>
          <div className="timeline-meta"><strong className={item.sender.is_self?"self-speaker":""}>{item.sender.display_name}</strong>{item.sender.role&&<RoleTag role={item.sender.role}/>}<time dateTime={item.sent_at}>{date(item.sent_at)}</time>{item.origin==="import"&&<span>手动导入</span>}</div>
          <p className="original-body">{item.body||`${kinds[item.kind]||"消息"}（暂无文本）`}</p>
          {!!item.attachments.length&&<div className="message-attachments">{item.attachments.map(attachment=><span className="info-chip" key={attachment.id}><FileText size={13}/>{attachment.mime?.startsWith("image/")?"图片":"附件"} · {stateNames[attachment.state]||"状态待核实"}{attachment.downloadable&&<button className="text-button" aria-label="下载附件" onClick={()=>void download(attachment)}><Download size={13}/></button>}</span>)}</div>}
          <span className="source-line">{item.source_title|| (item.source_kind==="group"?"群名称缺失":"私聊")}</span>
        </article>
      </div>)}
    </div>
    {data?.has_more&&!stale&&<button className="button secondary timeline-more" disabled={loading||loadingMore} onClick={()=>void more()}>{loadingMore?"正在加载…":"加载更多原文"}</button>}
  </section>;
}
