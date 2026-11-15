import {useEffect,useRef,useState} from 'react';
import {CalendarDays} from 'lucide-react';
import {request,messageFor} from '../../api/client';
import type {ContactKey} from '../../api/types';
import {MessageCalendar,beijingToday,type CalendarData} from './MessageCalendar';
import {MessageTimeline} from './MessageTimeline';
export function MessageBrowser({contact,revision,visible=true}:{contact:ContactKey;revision:number;visible?:boolean}){
 const [month,setMonth]=useState(beijingToday().slice(0,7)),[day,setDay]=useState<string|null>(null),[source,setSource]=useState(''),[data,setData]=useState<CalendarData|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[refresh,setRefresh]=useState(0),[latest,setLatest]=useState(0),[calendarOpen,setCalendarOpen]=useState(false);
 const root=useRef<HTMLElement>(null),version=useRef(0);
 useEffect(()=>{const dialog=root.current?.closest("dialog");dialog?.classList.toggle("dialog-messages-expanded",!!day&&visible);return()=>dialog?.classList.remove("dialog-messages-expanded");},[day,visible]);
 useEffect(()=>{const id=++version.current,controller=new AbortController();setBusy(true);setError('');
 request<CalendarData>(`/api/contacts/${encodeURIComponent(contact.contact_id)}/message-calendar?${new URLSearchParams({account_id:contact.account_id,month,...(source?{conversation_id:source}:{})})}`,{signal:controller.signal}).then(result=>{if(id===version.current)setData(result);}).catch(reason=>{if(!controller.signal.aborted)setError(messageFor(reason));}).finally(()=>{if(id===version.current&&!controller.signal.aborted)setBusy(false);});return()=>controller.abort();
 },[contact.account_id,contact.contact_id,month,source,revision,refresh]);
 const select=(value:string)=>{setDay(value);setLatest(0);setCalendarOpen(false);};
 const goLatest=()=>{if(data?.latest_day){setDay(data.latest_day);setMonth(data.latest_day.slice(0,7));setLatest(value=>value+1);setCalendarOpen(false);}};
 return <section ref={root} className={`message-browser${day?' has-details':''}${calendarOpen?' calendar-open':''}`} aria-label="聊天记录浏览">
  {error&&<div className="error-banner" role="alert">{error}<button className="text-button" onClick={()=>setRefresh(value=>value+1)}>重试日历</button></div>}
  <aside className="message-calendar-column"><MessageCalendar month={month} selected={day} data={data} busy={busy} onMonth={setMonth} onSelect={select} onLatest={goLatest}/></aside>
  {day&&<section className="message-details" aria-label="当天消息详情"><header className="message-details-heading"><button className="text-button calendar-toggle" onClick={()=>setCalendarOpen(value=>!value)} aria-expanded={calendarOpen}><CalendarDays size={16}/>选择日期</button><h3>{day.replaceAll('-',' / ')}</h3><button className="text-button" disabled={busy||!data?.latest_day} onClick={goLatest}>回到最新</button></header><MessageTimeline contact={contact} revision={revision} visible={visible} day={day} latestVersion={latest} onSourceChange={setSource}/></section>}
 </section>;
}
