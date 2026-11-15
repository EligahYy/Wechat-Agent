import type {ContactKey} from '../../api/types';
export type SourceRef={message_id:string;revision:number;attachment_id?:string|null;locator?:string|null};
export type Fact={value:string|null;state:string;sources:SourceRef[];origin?:string|null};
export type Shipment={shipment_id:string;stage:string;version:number;numbers:string[];numbers_origin:string;details:{goods:Fact[];logistics:Fact[];sources:SourceRef[]}};
export type Profile={account_id:string;contact_id:string;applicable:boolean;model_version:number;manual_version:number;model:unknown;manual:{fields:Record<string,string|string[]>;notes:Record<string,string>};effective:{goods:Record<string,Fact>;logistics:Record<string,Fact>;communication:{summary:Fact;tags:string[];last_business_at:string|null}};conflicts:{path:string;model_value:unknown;manual_value:unknown;model_sources:SourceRef[]}[];shipments:Shipment[];complete:boolean;pending:boolean;issues:string[]};
export const groups:Record<string,Record<string,string>>={goods:{category:'货品类别',products:'具体货品',special_attributes:'特殊属性',volume:'货量'},logistics:{origins:'起运地',destinations:'目的地',warehouse_postcode:'仓库与邮编',transport:'运输方式',clearance_tax:'清关与税务',timing:'时效要求',price:'价格关注',pickup_lastmile:'提货与派送',concerns:'其他关注'},communication:{summary:'沟通摘要',tags:'沟通标签',last_business_at:'最近业务时间'}};
export const tags=['初步沟通','需求沟通中','询价中','方案对接中','备货中','暂缓','暂无新需求记录'];
export const endpoint=(key:ContactKey,suffix='profile')=>`/api/contacts/${encodeURIComponent(key.contact_id)}/${suffix}`;
