import {useState} from 'react';
import type {ContactKey} from '../../api/types';
import {NumberEditor} from './NumberEditor';
import type {Shipment,SourceRef} from './types';
export function ShipmentList({shipments,contact,onSaved,onEvidence}:{shipments:Shipment[];contact:ContactKey;onSaved:()=>void;onEvidence:(refs:SourceRef[])=>void}){
 const [editing,setEditing]=useState<Shipment|null>(null);
 return <section className="profile-shipments" aria-label="备货记录">{!shipments.length?<div className="empty-state"><strong>暂无备货记录</strong><span>已确认的独立需求将在整理后展示</span></div>:shipments.map((row,index)=><article className="profile-card" key={row.shipment_id}><header><h3>备货记录 {index+1}</h3><span className="info-chip">{row.stage}</span></header><p>{row.details.goods.map(f=>f.value).filter(Boolean).join('；')||'货品待确认'}</p><p>{row.details.logistics.map(f=>f.value).filter(Boolean).join('；')}</p><div className="profile-numbers">{row.numbers.map(number=><span className="info-chip" key={number}>{number}</span>)}{row.numbers_origin==='manual'&&<span className="muted">人工录入</span>}</div><div className="profile-actions"><button className="text-button" onClick={()=>setEditing(row)}>编辑单号</button>{!!row.details.sources.length&&<button className="text-button" onClick={()=>onEvidence(row.details.sources)}>查看备货来源</button>}</div></article>)}{editing&&<NumberEditor shipment={editing} contact={contact} onClose={()=>setEditing(null)} onSaved={onSaved}/>}</section>;
}
