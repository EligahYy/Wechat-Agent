import {useEffect,useRef,useState} from 'react';
import {ModelConnectionStatus} from './ModelConnectionStatus';
import {RefreshCw} from 'lucide-react';
import {Dialog} from '../../components/Dialog';
import {FormField} from '../../components/FormField';
import {SelectField} from '../../components/SelectField';
import {request,messageFor} from '../../api/client';
export type ModelSettings={account_id:string;version:number;configured:boolean;endpoint?:string;model_id?:string;response_mode?:string;context_tokens?:number;max_output_tokens?:number;connection:{state:string;code?:string|null;capacity_verified:boolean;vision_verified:boolean}};
export function ModelConfigDialog({accountId,onClose,onChanged}:{accountId:string;onClose:()=>void;onChanged:()=>void}){
  const [saved,setSaved]=useState<ModelSettings|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState('loading');
  const [endpoint,setEndpoint]=useState(''),[model,setModel]=useState(''),[secret,setSecret]=useState(''),[mode,setMode]=useState('json_object');
  const [context,setContext]=useState(''),[output,setOutput]=useState('');
  const mounted=useRef(true);
  const apply=(value:ModelSettings)=>{setSaved(value);setEndpoint(value.endpoint||'');setModel(value.model_id||'');setMode(value.response_mode||'json_object');setContext(value.context_tokens?String(value.context_tokens):'');setOutput(value.max_output_tokens?String(value.max_output_tokens):'');setSecret('');};
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
      </div><p className="field-hint">按服务文档填写声明值。连接检查不证明窗口容量或视觉能力；未验证能力不会自动启用图片处理。</p></section>
      {saved?.configured&&<section className="import-preview"><h3>连接检查</h3>
        <div className="model-connection-row">
          <ModelConnectionStatus state={busy==='checking'?'running':state} modified={dirty}/>
          <button className="button secondary" disabled={!!busy||dirty||state==='running'} onClick={()=>void check()}><RefreshCw size={16} className={busy==='checking'||state==='running'?'spin':undefined}/>检查连接</button>
        </div>
        {!dirty&&state==='failed'&&<p className="muted">{saved.connection.code==='model_authentication_failed'?'请检查 API 密钥及服务权限。':'请核对服务地址、模型 ID、响应格式及网络后重试。'}</p>}
        <p className="field-hint">点击将发送一次不含客户资料的最小请求，可能产生少量费用。容量和视觉能力尚未验证。</p>
        {dirty&&<p className="field-hint">请先保存修改，再检查连接。</p>}
      </section>}
    </div>
  </Dialog>;
}
