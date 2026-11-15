import {useMessageEdges} from "./useMessageEdges";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Search, X, FileText, Download, RotateCcw, ArrowUp, ArrowDown } from "lucide-react";
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
export function MessageTimeline({contact,revision,visible=true,scrollBookmark=null,day,latestVersion=0,onSourceChange}:{contact:ContactKey;revision:number;visible?:boolean;scrollBookmark?:number|null;day?:string;latestVersion?:number;onSourceChange?:(value:string)=>void}) {
  const [query,setQuery]=useState("");const [source,setSource]=useState("");const [reload,setReload]=useState(0);
  const scopeKey=JSON.stringify([contact.account_id,contact.contact_id,day,query,source,revision,reload,latestVersion]);
  const [dataState,setDataState]=useState<{scope:string;value:TimelinePage}|null>(null);
  const data=dataState?.scope===scopeKey?dataState.value:null;
  const setData=(value:TimelinePage)=>setDataState({scope:scopeKey,value});const [loading,setLoading]=useState(false);const [loadingMore,setLoadingMore]=useState(false);
  const [resultVersion,setResultVersion]=useState(0);
  const [error,setError]=useState("");const [stale,setStale]=useState(false);const [downloadError,setDownloadError]=useState("");
  const position=useRef<'start'|'latest'|'speech'>('start');
  const scrollRef=useRef<HTMLDivElement>(null),ownScroll=useRef(0);
  const wasVisible=useRef(visible);
  const root=useRef<HTMLElement>(null),navLock=useRef(false);
  const [jumping,setJumping]=useState(false);
  const generation=useRef(0);const loadController=useRef<AbortController|null>(null);
  const path=(cursor?:string,before=false,focus?:string)=>`/api/contacts/${encodeURIComponent(contact.contact_id)}/messages?${new URLSearchParams({account_id:contact.account_id,q:query,...(day?{day}:{}), ...(source?{conversation_id:source}:{}),...(cursor?{[before?"before_cursor":"cursor"]:cursor}:focus?{focus_id:focus}:(day?(latestVersion?{date_latest:"true"}:{}):{focus_latest:"true"}))})}`;
  useEffect(()=>{
    const id=++generation.current;const controller=new AbortController();loadController.current?.abort();setLoadingMore(false);navLock.current=false;setJumping(false);
    setLoading(true);setStale(false);setError("");if(scrollRef.current)scrollRef.current.scrollTop=0;
    const timer=setTimeout(()=>{request<TimelinePage>(path(),{signal:controller.signal}).then(result=>{
      if(id===generation.current){position.current=day?(latestVersion?'latest':'start'):'speech';setData(result);setResultVersion(version=>version+1);setError("");}
    }).catch(reason=>{if(!controller.signal.aborted&&id===generation.current)setError(messageFor(reason));})
      .finally(()=>{if(!controller.signal.aborted&&id===generation.current)setLoading(false);});},query?180:0);
    return ()=>{controller.abort();clearTimeout(timer);loadController.current?.abort();};
  },[contact.account_id,contact.contact_id,query,source,revision,reload,day,latestVersion]);
  const more=async(before=false)=>{
    const cursor=before?data?.previous_cursor:data?.next_cursor;
    if(!cursor||!data||loading||loadingMore||jumping)return;
    const id=generation.current;const controller=new AbortController();loadController.current=controller;setLoadingMore(true);
    try {const result=await request<TimelinePage>(path(cursor,before),{signal:controller.signal});
      if(id===generation.current)setData({...result,speech:data.speech,previous_cursor:before?result.previous_cursor:data.previous_cursor,next_cursor:before?data.next_cursor:result.next_cursor,has_more:before?data.has_more:result.has_more,items:before?[...result.items,...data.items]:[...data.items,...result.items]});
    } catch(reason){if(!controller.signal.aborted&&id===generation.current){setStale(reason instanceof ApiError&&reason.code==="message_cursor_stale");setError(messageFor(reason));}}
    finally {if(id===generation.current&&!controller.signal.aborted)setLoadingMore(false);}
  };
  const jump=async(id:string|null|undefined)=>{
    if(!id||loading||loadingMore||navLock.current)return;
    navLock.current=true;setJumping(true);const version=++generation.current;
    loadController.current?.abort();const controller=new AbortController();loadController.current=controller;
    try{const result=await request<TimelinePage>(path(undefined,false,id),{signal:controller.signal});
      if(version===generation.current){position.current='speech';setData(result);setResultVersion(value=>value+1);setError("");}}
    catch(reason){if(!controller.signal.aborted&&version===generation.current)setError(messageFor(reason));}
    finally{if(version===generation.current){navLock.current=false;setJumping(false);}}
  };
  useLayoutEffect(()=>{
    const returning=visible&&!wasVisible.current;wasVisible.current=visible;
    if(!visible)return;
    if(!data)return;
    const frame=requestAnimationFrame(()=>{
      const node=Array.from(root.current?.querySelectorAll<HTMLElement>('[data-message]')||[]).find(item=>item.dataset.message===data.speech?.current_id);
      const scroll=scrollRef.current;
      if(returning&&scroll){scroll.scrollTo({top:scrollBookmark??ownScroll.current,behavior:'instant'});return;}
      if(position.current==='start'&&scroll){scroll.scrollTo({top:0,behavior:'instant'});return;}
      if(position.current==='latest'&&scroll){scroll.scrollTo({top:scroll.scrollHeight,behavior:'instant'});return;}
      if(node&&scroll&&node.getBoundingClientRect().height){
        const reduce=document.documentElement.dataset.reduceMotion==='true'||window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        scroll.scrollTo({top:scroll.scrollTop+node.getBoundingClientRect().top-scroll.getBoundingClientRect().top-scroll.clientHeight/2+Math.min(node.offsetHeight,scroll.clientHeight/2)/2,behavior:reduce?'instant':'smooth'});
      }
    });return()=>cancelAnimationFrame(frame);
  },[data?.speech?.current_id,visible,resultVersion]);
  useMessageEdges(scrollRef,data?.items,data?.previous_cursor,data?.next_cursor,loading||loadingMore||jumping||stale||!!error||!visible,more,`${day}:${query}:${source}:${revision}:${latestVersion}`);
  const download=async(attachment:TimelineItem["attachments"][number])=>{
    setDownloadError("");
    try {const response=await fetch(`/api/attachments/${encodeURIComponent(attachment.id)}?${new URLSearchParams({account_id:contact.account_id})}`,{credentials:"same-origin"});
      if(!response.ok){const reason=await response.json();throw new ApiError(reason.code,response.status,reason.details);}
      const object=URL.createObjectURL(await response.blob());const link=document.createElement("a");link.href=object;link.download="attachment";link.click();setTimeout(()=>URL.revokeObjectURL(object),1000);
    }catch(reason){setDownloadError(messageFor(reason));}
  };
  return <section ref={root} className="timeline" aria-label="沟通原文">
    <div className="timeline-tools">
      <FormField label="搜索沟通原文" type="search" placeholder="搜索原文内容" value={query} leading={<Search size={17}/>} onChange={event=>setQuery(event.target.value)} trailing={query?<button type="button" className="icon-button" aria-label="清空原文搜索" onClick={()=>setQuery("")}><X size={15}/></button>:undefined}/>
      <SelectField label="消息来源" value={source} onValueChange={value=>{setSource(value);onSourceChange?.(value);}} options={[{value:"",label:"全部来源"},...(data?.sources||dataState?.value.sources||[]).map(item=>({value:item.conversation_id,label:item.title|| (item.kind==="group"?"群名称缺失":"私聊")}))]}/>
    </div>
    <div className="timeline-scroll" ref={scrollRef} onScroll={()=>{if(visible&&scrollRef.current)ownScroll.current=scrollRef.current.scrollTop;}} tabIndex={0} aria-label="消息原文滚动区">
    <div className="table-meta" aria-live="polite"><span>{data?.total||0} 条原文{loading?" · 更新中":""}</span><span>北京时间 · 不含系统通知</span></div>
    <div className="speech-navigation-slot">
      <div className="speech-navigation" role="group" aria-label="当前联系人发言定位">
        <span role="status" className="speech-count" title={data?.speech?.total?'当前联系人发言位置':'当前范围内无他的发言'} aria-label={loading?'正在读取发言':jumping?'正在定位':data?.speech?.total?`当前联系人发言 ${data.speech.index} / ${data.speech.total}`:'当前范围内无他的发言'}>{loading||loadingMore||jumping?'…':`${data?.speech?.index||0} / ${data?.speech?.total||0}`}</span>
        <button type="button" className="icon-button" aria-label="上一条" title="上一条发言" disabled={loading||loadingMore||jumping||!data?.speech?.previous_id} onClick={()=>void jump(data?.speech?.previous_id)}><ArrowUp size={16}/></button>
        <button type="button" className="icon-button" aria-label="下一条" title="下一条发言" disabled={loading||loadingMore||jumping||!data?.speech?.next_id} onClick={()=>void jump(data?.speech?.next_id)}><ArrowDown size={16}/></button>
      </div>
    </div>
    {error&&<div className="error-banner" role="alert"><span>{error}</span><button className="text-button" onClick={()=>setReload(value=>value+1)}><RotateCcw size={14}/>{stale?"重新加载原文":"重试"}</button></div>}
    {downloadError&&<p className="error-banner" role="alert">{downloadError}</p>}
    <div className="timeline-items" aria-busy={loading}>
      <div key={resultVersion} className="timeline-result-enter">
      {!data&&loading?<p className="muted">正在读取原文…</p>:!data?.items.length&&!error?<div className="empty-state"><FileText size={26}/><strong>{query||source?"没有匹配的原文":day?"当天暂无已同步消息":"尚无可展示的聊天原文"}</strong><span>{day?"可选择其他日期，或回到最新记录":"可先同步此客户，或在设置中导入消息"}</span></div>:data?.items.map((item,index)=><div key={item.message_id}>
        {(index===0||date(item.sent_at,true)!==date(data.items[index-1].sent_at,true))&&<div className="timeline-day">{date(item.sent_at,true)}</div>}
        <article className={`timeline-message ${item.sender.is_self?"is-self":""} ${item.sender.contact_id===contact.contact_id?"is-contact":""} ${item.message_id===data.speech?.current_id?"is-current-speech":""}`} data-message={item.message_id}>
          <div className="timeline-meta"><strong className={item.sender.is_self?"self-speaker":""}>{item.sender.display_name}</strong>{item.sender.role&&<RoleTag role={item.sender.role}/>}<time dateTime={item.sent_at}>{date(item.sent_at)}</time>{item.origin==="import"&&<span>手动导入</span>}</div>
          <p className="original-body">{item.body||`${kinds[item.kind]||"消息"}（暂无文本）`}</p>
          {!!item.attachments.length&&<div className="message-attachments">{item.attachments.map(attachment=><span className="info-chip" key={attachment.id}><FileText size={13}/>{attachment.mime?.startsWith("image/")?"图片":"附件"} · {stateNames[attachment.state]||"状态待核实"}{attachment.downloadable&&<button className="text-button" aria-label="下载附件" onClick={()=>void download(attachment)}><Download size={13}/></button>}</span>)}</div>}
          <span className="source-line">{item.source_title|| (item.source_kind==="group"?"群名称缺失":"私聊")}</span>
        </article>
      </div>)}
      </div>
    </div>
    </div>
  </section>;
}
