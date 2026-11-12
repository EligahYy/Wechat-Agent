import { useRef, useState } from "react";
import { Upload, Check } from "lucide-react";
import { Dialog } from "../../components/Dialog";
import { FormField } from "../../components/FormField";
import { SelectField } from "../../components/SelectField";
import { request, messageFor } from "../../api/client";
import type { ImportPreview, ImportResult } from "../../api/types";
const fields=[
  ["conversation_id","会话标识",true],["sender_id","发送人标识",true],["sent_at","消息时间",true],
  ["message_id","消息标识",true],["body","正文",true],["kind","消息类型",false],
  ["conversation_kind","会话类型",false],["attachment_ids","附件引用",false],["account_id","工作账号",false],
] as const;
const issueNames:Record<string,string>={
  mapping_required:"缺少必填字段映射或该行缺少对应值",sender_id_invalid:"发送人标识缺失或无效",
  conversation_id_required:"会话标识缺失",conversation_id_invalid:"会话标识无效",message_id_required:"消息标识缺失",
  time_invalid:"消息时间无效",time_timezone_required:"时间需要包含时区",body_invalid:"正文格式无效或过长",
  account_scope_mismatch:"该行工作账号与当前账号不同",message_identity_conflict:"相同消息标识已有不同原文，已保留原记录",
  duplicate_identity_conflict:"文件内相同消息标识内容冲突",row_not_object:"该行格式不完整",
  conversation_kind_conflict:"会话类型与已有来源冲突",attachment_references_invalid:"附件引用需为JSON字符串数组",
};
export function ImportDialog({accountId,onClose,onImported}:{accountId:string;onClose:()=>void;onImported:()=>void}) {
  const [namespace,setNamespace]=useState("");const [content,setContent]=useState("");const [format,setFormat]=useState<"csv"|"json">("csv");
  const [inspected,setInspected]=useState<ImportPreview|null>(null);const [mapping,setMapping]=useState<Record<string,string>>({});
  const [preview,setPreview]=useState<ImportPreview|null>(null);const [result,setResult]=useState<ImportResult|null>(null);
  const [busy,setBusy]=useState(false);const [error,setError]=useState("");const lock=useRef(false);
  const choose=async(file?:File)=>{
    if(!file||lock.current)return;
    lock.current=true;setBusy(true);setError("");setInspected(null);setPreview(null);setResult(null);setContent("");
    try {
      const extension=file.name.toLowerCase().split('.').pop();
      if(!["csv","json"].includes(extension||""))throw Error("请选择CSV或JSON文件");
      if(file.size>2*1024*1024)throw Error("文件不能超过2MB");
      let text:string;
      try{text=new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer());}catch{throw Error("请使用UTF-8编码的CSV或JSON文件");}
      const kind=extension as "csv"|"json";const name=file.name.slice(0,128);
      const response=await request<ImportPreview>("/api/imports",{method:"POST",body:JSON.stringify({mode:"preview",account_id:accountId,namespace:name,format:kind,content:text})});
      setInspected(response);setMapping(response.mapping_defaults);setNamespace(name);setContent(text);setFormat(kind);
    } catch(reason){setError(reason instanceof Error&&!("status" in reason)?reason.message:messageFor(reason));}
    finally{lock.current=false;setBusy(false);}
  };
  const prepare=async()=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError("");
    try{setPreview(await request<ImportPreview>("/api/imports",{method:"POST",body:JSON.stringify({mode:"preview",account_id:accountId,namespace,format,content,mapping})}));}
    catch(reason){setError(messageFor(reason));}finally{lock.current=false;setBusy(false);}
  };
  const commit=async()=>{
    if(!preview?.preview_id||lock.current)return;lock.current=true;setBusy(true);setError("");
    try{const completed=await request<ImportResult>("/api/imports",{method:"POST",body:JSON.stringify({mode:"commit",account_id:accountId,preview_id:preview.preview_id})});setResult(completed);onImported();}
    catch(reason){setError(messageFor(reason));}finally{lock.current=false;setBusy(false);}
  };
  return <Dialog open title="导入消息" wide onClose={()=>{if(!lock.current)onClose();}} footer={result?<button className="button primary" onClick={onClose}>完成</button>:<>
    <button className="button secondary" disabled={busy} onClick={onClose}>取消</button>
    {preview?<button className="button primary" disabled={busy||!preview.counts?.valid} onClick={()=>void commit()}>{busy?"正在导入…":"确认导入有效记录"}</button>:<button className="button primary" disabled={busy||!inspected||!namespace.trim()||fields.some(([key,,required])=>required&&!mapping[key])} onClick={()=>void prepare()}>{busy?"正在读取…":"预览导入"}</button>}
  </>}>
    {error&&<p className="error-banner" role="alert">{error}</p>}
    {result?<div className="import-result" role="status"><Check size={30}/><h3>导入处理完成</h3><p>新增 {result.counts.inserted} 条 · 重复 {result.counts.unchanged} 条 · 跳过 {result.counts.rejected} 条</p><p className="muted">原文已归档，可在对应联系人的沟通原文中查看</p>{result.issues.length>0&&<ul>{result.issues.map((issue,index)=><li key={index}>第 {issue.row} 行：{issueNames[issue.code]||"该行未通过校验"}</li>)}</ul>}</div>:<div className="import-stack">
      <p className="muted">先核对字段和原文，再确认导入。重复消息保留一份，已有原文和人工身份会保留。</p>
      <div className="field"><label htmlFor="import-file">选择CSV或JSON文件</label><input id="import-file" className="form-control" type="file" accept=".csv,.json" disabled={busy} onChange={event=>void choose(event.target.files?.[0])}/><span className="field-hint">UTF-8编码，最多2MB／5000行</span></div>
      {inspected&&<>
        <FormField label="来源批次标识" value={namespace} disabled={busy} maxLength={128} onChange={event=>{setNamespace(event.target.value);setPreview(null);}}/>
        <p className="field-hint">同一来源重复导入时保留此标识。发送人和消息使用稳定标识，不用姓名代替。</p>
        <section><h3>列映射</h3><div className="import-mapping">{fields.map(([key,label,required])=><SelectField key={key} label={label} value={mapping[key]||""} disabled={busy} required={required} onChange={event=>{setMapping(previous=>({...previous,[key]:event.target.value}));setPreview(null);}} options={[{value:"",label:required?"请选择对应列":"不导入此字段"},...inspected.columns.map(column=>({value:column,label:column}))]}/>)}</div>
          <p className="field-hint">时间格式例如2026-11-12T08:30:00+08:00。会话类型为private／group；附件仅保留引用，文件获取稍后处理。</p>
        </section>
        {preview?.counts&&<section className="import-preview"><h3>导入预览</h3><div className="operation-facts"><span className="info-chip">有效 {preview.counts.valid} 条</span><span className="info-chip">跳过 {preview.counts.rejected} 条</span><span className="info-chip">已存在／重复 {preview.counts.unchanged} 条</span></div>
          {!!preview.issues.length&&<ul className="import-issues">{preview.issues.map((issue,index)=><li key={index}>第 {issue.row} 行：{issueNames[issue.code]||"该行未通过校验"}</li>)}</ul>}
          {preview.issues_truncated&&<p className="muted">仅展示前100项问题，总跳过数量以统计为准</p>}
          <div className="import-samples">{preview.sample_messages?.map(item=><article key={item.row}><span className="source-line">第 {item.row} 行 · {item.sender_id||"系统消息"} · {item.sent_at}</span><p className="original-body">{item.body||"（暂无文本）"}</p></article>)}</div>
        </section>}
      </>}
      {!inspected&&<div className="import-empty"><Upload size={26}/><span>选择文件后设置字段映射</span></div>}
    </div>}
  </Dialog>;
}
