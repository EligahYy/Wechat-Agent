import {useEffect,useRef,useState} from 'react';
import {ModelConnectionStatus} from './ModelConnectionStatus';
import {RefreshCw} from 'lucide-react';
import {Dialog} from '../../components/Dialog';
import {FormField} from '../../components/FormField';
import {SelectField} from '../../components/SelectField';
import {request,messageFor} from '../../api/client';
export type ModelSettings={account_id:string;version:number;configured:boolean;endpoint?:string;model_id?:string;response_mode?:string;context_tokens?:number;max_output_tokens?:number;runtime_ready?:boolean;budget_reference?:string|null;budget_review?:{method:string;reference:string}|null;connection:{state:string;code?:string|null;capacity_verified:boolean;vision_verified:boolean}};
export function ModelConfigDialog({accountId,onClose,onChanged}:{accountId:string;onClose:()=>void;onChanged:()=>void}){
  const [saved,setSaved]=useState<ModelSettings|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState('loading');
  const [endpoint,setEndpoint]=useState(''),[model,setModel]=useState(''),[secret,setSecret]=useState(''),[mode,setMode]=useState('json_object');
  const [context,setContext]=useState(''),[output,setOutput]=useState('');
  const [budgetReference,setBudgetReference]=useState(''),[budgetAck,setBudgetAck]=useState(false),[schemaAck,setSchemaAck]=useState(false);
  const mounted=useRef(true);
  const apply=(value:ModelSettings)=>{setSaved(value);setEndpoint(value.endpoint||'');setModel(value.model_id||'');setMode(value.response_mode||'json_object');setContext(value.context_tokens?String(value.context_tokens):'');setOutput(value.max_output_tokens?String(value.max_output_tokens):'');setSecret('');setBudgetReference(value.budget_review?.reference||value.budget_reference||'');setBudgetAck(false);setSchemaAck(false);};
  useEffect(()=>{mounted.current=true;const controller=new AbortController();
    request<ModelSettings>(`/api/model?${new URLSearchParams({account_id:accountId})}`,{signal:controller.signal}).then(value=>{if(mounted.current&&!controller.signal.aborted){apply(value);if(value.configured&&value.connection.state!=='running')onChanged();}}).catch(reason=>{if(!controller.signal.aborted)setError(messageFor(reason));}).finally(()=>{if(mounted.current)setBusy('');});
    return()=>{mounted.current=false;controller.abort();};
  },[accountId]);
  useEffect(()=>{
    if(saved?.connection.state!=='running')return;
    const controller=new AbortController();
    const timer=window.setInterval(()=>{
      request<ModelSettings>(`/api/model?${new URLSearchParams({account_id:accountId})}`,{signal:controller.signal})
        .then(value=>{if(mounted.current&&!controller.signal.aborted){setSaved(previous=>previous?.version===value.version?value:previous);if(value.connection.state!=='running')onChanged();}})
        .catch(()=>{});
    },1000);
    return()=>{window.clearInterval(timer);controller.abort();};
  },[accountId,saved?.connection.state]);
  const dirty=!!saved&&(!!secret||endpoint!==(saved.endpoint||'')||model!==(saved.model_id||'')||mode!==(saved.response_mode||'json_object')||context!==(saved.context_tokens?String(saved.context_tokens):'')||output!==(saved.max_output_tokens?String(saved.max_output_tokens):''));
  const save=async()=>{if(!saved||busy)return;setBusy('saving');setError('');
    try{const value=await request<ModelSettings>('/api/model',{method:'PUT',body:JSON.stringify({account_id:accountId,expected_version:saved.version,endpoint,model_id:model,response_mode:mode,context_tokens:Number(context),max_output_tokens:Number(output),api_key:secret||null})});if(mounted.current)apply(value);onChanged();}
    catch(reason){if(mounted.current)setError(messageFor(reason));}finally{if(mounted.current)setBusy('');}
  };
  const check=async()=>{if(!saved||busy||dirty)return;setBusy('checking');setError('');
    try{const value=await request<ModelSettings>('/api/model/check',{method:'POST',body:JSON.stringify({account_id:accountId,expected_version:saved.version})});if(mounted.current)setSaved(value);onChanged();}
    catch(reason){if(mounted.current)setError(messageFor(reason));}finally{if(mounted.current)setBusy('');}
  };
  const confirmBudget=async()=>{if(!saved||busy||dirty||!budgetAck)return;setBusy('budget');setError('');try{const value=await request<ModelSettings>('/api/model/budget-review',{method:'POST',body:JSON.stringify({account_id:accountId,expected_version:saved.version,reference:budgetReference,acknowledged:true,schema_supported:schemaAck})});if(mounted.current)apply(value);onChanged();}catch(reason){if(mounted.current)setError(messageFor(reason));}finally{if(mounted.current)setBusy('');}};
  const state=saved?.connection.state;
  return <Dialog open wide title="模型配置" onClose={()=>{if(busy!=='saving')onClose();}} footer={<>
    <button className="button secondary" disabled={busy==='saving'} onClick={onClose}>完成</button>
    <button className="button primary" disabled={!!busy||!dirty||!endpoint||!model||!context||!output||(!saved?.configured&&!secret)} onClick={()=>void save()}>{busy==='saving'?'正在保存…':'保存配置'}</button>
  </>}>
    <div className="import-stack">
      {error&&<p className="error-banner" role="alert">{error}</p>}
      {busy==='loading'&&<p role="status">正在读取配置…</p>}
      <section><h3>服务连接</h3><div className="import-mapping">
        <FormField label="服务地址" value={endpoint} disabled={!!busy} placeholder="HTTPS chat-completions 地址" onChange={event=>setEndpoint(event.target.value)}/>
        <FormField label="模型 ID" value={model} disabled={!!busy} onChange={event=>setModel(event.target.value)} autoComplete="off"/>
        <FormField label="API 密钥" type="password" value={secret} disabled={!!busy} onChange={event=>setSecret(event.target.value)} autoComplete="new-password" placeholder={saved?.configured?'留空沿用当前服务的密钥':'首次配置需要填写'}/>
        <SelectField label="响应格式" value={mode} disabled={!!busy} onValueChange={setMode} options={[{value:'json_object',label:'JSON 对象'},{value:'json_schema',label:'JSON Schema'},{value:'text',label:'文本 JSON'}]}/>
      </div><p className="field-hint">密钥仅保存到本机 Keychain，不回填页面。更换服务地址需重新填写密钥；保存不会调用模型。</p></section>
      <section><h3>处理范围</h3><div className="import-mapping">
        <FormField label="上下文上限" type="number" min={1} value={context} disabled={!!busy} onChange={event=>setContext(event.target.value)}/>
        <FormField label="最大输出" type="number" min={16} value={output} disabled={!!busy} onChange={event=>setOutput(event.target.value)}/>
      </div><p className="field-hint">上下文容量与单次最大输出是独立限制，请分别按模型文档填写。系统从小额度开始，必要时增加或拆分，不会直接请求整个窗口的输出。连接检查不证明窗口容量或视觉能力；未验证能力不会自动启用图片处理。</p></section>
      {saved?.configured&&<section className="import-preview"><h3>连接检查</h3>
        <div className="model-connection-row">
          <ModelConnectionStatus state={busy==='checking'?'running':state} modified={dirty}/>
          <button className="button secondary" disabled={!!busy||dirty||state==='running'} onClick={()=>void check()}><RefreshCw size={16} className={busy==='checking'||state==='running'?'spin':undefined}/>检查连接</button>
        </div>
        {!dirty&&state==='failed'&&<p className="muted">{saved.connection.code==='model_authentication_failed'?'请检查 API 密钥及服务权限。':'请核对服务地址、模型 ID、响应格式及网络后重试。'}</p>}
        <p className="field-hint">检查使用与正式整理相同的连接和超时设置，并发送一条合成测试消息，可能产生少量费用。容量和视觉能力尚未验证。整理质量需用业务样本核对。</p>
        {dirty&&<p className="field-hint">请先保存修改，再检查连接。</p>}
      </section>}
      {saved?.configured&&state==='passed'&&<section className="import-preview"><h3>文本整理预算</h3>
        {saved.runtime_ready&&!dirty?<><p className="model-connection-status" data-state="passed"><span className="connection-status-indicator" aria-hidden="true"/>文本预算已核对，可整理文本资料</p><p className="field-hint">依据：{saved.budget_review?.reference}。配置变更后需重新核对。</p></>:<>
          <p className="field-hint">同一模型的文档链接会保留；调整上下文或输出上限后需重新勾选确认。请对照供应商文档核对上方预算。本步骤只保存人工文档核对记录，不发送模型请求，不代表容量实测或视觉验证。</p>
          <FormField label="预算依据（供应商文档HTTPS地址）" value={budgetReference} disabled={!!busy||dirty} onChange={event=>setBudgetReference(event.target.value)}/>
          <label className="budget-confirm"><input type="checkbox" checked={budgetAck} disabled={!!busy||dirty} onChange={event=>setBudgetAck(event.target.checked)}/>我已核对供应商文档，支持以上文本上下文和最大输出预算</label>
          {mode==='json_schema'&&<label className="budget-confirm"><input type="checkbox" checked={schemaAck} disabled={!!busy||dirty} onChange={event=>setSchemaAck(event.target.checked)}/>我已核对服务支持JSON Schema响应格式</label>}
          <button className="button secondary" disabled={!!busy||dirty||!budgetAck||!budgetReference||(mode==='json_schema'&&!schemaAck)} onClick={()=>void confirmBudget()}>{busy==='budget'?'正在保存核对记录…':'确认文本预算'}</button>
        </>}
        <p className="field-hint">连接检查、文档预算核对和真实整理质量分别验证；当前不自动启用图片理解。文本长历史将自动分段处理，未完成时可重新同步并复用有效分段。</p>
      </section>}
    </div>
  </Dialog>;
}
