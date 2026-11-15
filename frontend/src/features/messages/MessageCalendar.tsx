import {useEffect,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight} from 'lucide-react';
import {SelectField} from '../../components/SelectField';
export type CalendarData={month:string;days:Record<string,number>;speech_days?:Record<string,number>;latest_day:string|null;earliest_day?:string|null};
export const beijingToday=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export function MessageCalendar({month,selected,data,busy,onMonth,onSelect,onLatest}:{month:string;selected:string|null;data:CalendarData|null;busy:boolean;onMonth:(value:string)=>void;onSelect:(value:string)=>void;onLatest:()=>void}){
 const today=beijingToday(),[year,number]=month.split('-').map(Number),count=new Date(Date.UTC(year,number,0)).getUTCDate();
 const offset=(new Date(Date.UTC(year,number-1,1)).getUTCDay()+6)%7;
 const [focus,setFocus]=useState('');const pending=useRef<string|null>(null),grid=useRef<HTMLDivElement>(null);
 useEffect(()=>{
  if(pending.current&&!pending.current.startsWith(month))pending.current=null;
  const value=pending.current||(selected?.startsWith(month)?selected:today.startsWith(month)?today:month+'-01');setFocus(value);
  if(pending.current&&!busy&&data?.month===month){const frame=requestAnimationFrame(()=>{const button=grid.current?.querySelector<HTMLButtonElement>(`[data-day="${value}"]`);if(button&&!button.disabled){button.focus();pending.current=null;}});return()=>cancelAnimationFrame(frame);}
 },[month,selected,busy,data?.month]);
 const moveMonth=(step:number)=>{const d=new Date(Date.UTC(year,number-1+step,1));onMonth(d.toISOString().slice(0,7));};
 const minimum=Math.min(Number(data?.earliest_day?.slice(0,4)||today.slice(0,4))-1,year),maximum=Math.max(Number(today.slice(0,4)),year);
 return <section className="message-calendar" aria-label="消息日历" aria-busy={busy}>
  <div className="calendar-heading"><button className="icon-button" aria-label="上个月" onClick={()=>moveMonth(-1)}><ChevronLeft size={17}/></button><strong>消息日历</strong><button className="icon-button" aria-label="下个月" onClick={()=>moveMonth(1)}><ChevronRight size={17}/></button></div>
  <div className="calendar-month-controls"><SelectField label="年份" value={String(year)} onValueChange={value=>onMonth(value+'-'+String(number).padStart(2,'0'))} options={Array.from({length:maximum-minimum+1},(_,i)=>({value:String(minimum+i),label:`${minimum+i}年`}))}/><SelectField label="月份" value={String(number)} onValueChange={value=>onMonth(`${year}-${value.padStart(2,'0')}`)} options={Array.from({length:12},(_,i)=>({value:String(i+1),label:`${i+1}月`}))}/></div>
  <div className="calendar-weekdays" aria-hidden="true">{'一二三四五六日'.split('').map(day=><span key={day}>{day}</span>)}</div>
  <div className="calendar-days" ref={grid} aria-label={`${year}年${number}月`}>
   {Array.from({length:offset},(_,i)=><span key={`blank${i}`}/>)}
   {Array.from({length:count},(_,i)=>{const day=`${month}-${String(i+1).padStart(2,'0')}`,messages=data?.days[day]||0;return <button type="button" key={day} data-day={day} className={`calendar-day${day===today?' is-today':''}`} aria-label={`${day}，${messages?`${messages}条本人发言`:'暂无消息'}`} title={messages?`本人${messages}条发言`:undefined} aria-pressed={day===selected} disabled={busy||(day>today&&!messages)} tabIndex={day===focus?0:-1} onFocus={()=>setFocus(day)} onClick={()=>onSelect(day)} onKeyDown={event=>{
    const step=({ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7} as Record<string,number>)[event.key];if(!step)return;event.preventDefault();const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+step);const next=d.toISOString().slice(0,10);if(next>today)return;
    if(next.slice(0,7)!==month){pending.current=next;onMonth(next.slice(0,7));}else{setFocus(next);grid.current?.querySelector<HTMLButtonElement>(`[data-day="${next}"]`)?.focus();}
   }}><span>{i+1}</span>{messages>0&&<i className="calendar-dot" aria-hidden="true"/>}</button>;})}
  </div>
  <div className="calendar-footer"><span>{busy?'正在读取…':'蓝点：本人发言'}</span><button className="text-button" disabled={busy||!data?.latest_day} onClick={onLatest}>回到最新</button></div>
 </section>;
}
