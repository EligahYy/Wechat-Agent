'use strict';
const $ = selector => document.querySelector(selector);
const csrf = $('meta[name="csrf-token"]').content;
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const party = {self:'我方协调',merchant:'商家',service_provider:'头程服务商',other:'其他方',unknown:'责任待确认'};
const stages = {needs:'需求确认',connecting:'三方对接',proposal:'方案确认',planned:'备货计划',executing:'执行中',verification:'结果待核验',done:'已完成',paused:'暂停',cancelled:'终止'};
const statuses = {open:'待处理',waiting_external:'等待反馈',snoozed:'暂缓',done:'已完成',cancelled:'已取消'};
const pages = {
  customers:['客户全景档案','把私信和群聊，连接到同一位客户','按稳定身份汇总沟通，再确认商家、角色和备货项目。'],
  archive:['全量消息档案','让沟通记录留在本机','按私信和群聊浏览已归档记录，业务关联与模型分析可稍后配置。'],
  today:['今日工作台','把每一次沟通，推进成备货进展','聚焦今天该跟进的商家、需要协调的服务商，以及下一步。'],
  projects:['商家与备货项目','每一批货，都有清晰的下一步','把商家需求、三方方案与执行节点，归到正确的备货批次。'],
  materials:['价卡与服务商','带着合适的方案，再联系商家','管理有效版本与使用范围，保留每个项目自己的确认报价。'],
  sources:['微信接入与分析','先从一两个群，开始真实跟进','先核对本地采集，再决定哪些业务上下文可以交给 DeepSeek。']
};
const sourceError = code => ({
  source_not_ready:'采集服务仍在准备，请确认微信登录和数据库可读后重试。',
  source_account_unavailable:'采集服务未返回账号身份，请核对工具版本。',
  source_account_mismatch_or_unconfigured:'源端账号与本机绑定不符，请重新检测并确认工作账号。',
  source_schema_incompatible:'接口结构与当前适配器不兼容，请先核对 wx-cli 版本。',
  full_content_unavailable:'上游未提供完整正文；本窗口没有导入，请核对工具版本。',
  source_partial_shards:'有分片不可读或消息被跳过，请先检查上游密钥覆盖。',
  stable_server_id_unavailable:'部分消息缺少稳定 ID，需先核对适配，避免错归档。',
  window_too_large_split_required:'最近窗口消息过多，请使用更小时间范围回填。'
}[code] || code);
let state = {}, taskFilter = 'active', draftText = '', sourceAccount = null;
const imageURLs = [];
let discovered = new Map(), selected = new Set(), nextOffset = 0, toastTimer;

function notify(message, error=false) {
  const toast = $('#notice'); toast.textContent = message;
  toast.className = 'toast ' + (error ? 'error' : 'success');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.add('hidden'), 6500);
}
async function api(url, body) {
  const response = await fetch(url, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(body)
  });
  let data; try { data = await response.json(); } catch { throw Error('服务响应异常，请确认后端仍在运行'); }
  if (!response.ok) throw Error(sourceError(data.error) || (typeof data.detail === 'string' ? data.detail : '操作失败，请核对输入'));
  return data;
}
async function busy(button, action) {
  const original = button.textContent; button.disabled = true; button.textContent = '处理中…';
  try { return await action(); } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; button.textContent = original; }
}
const name = (table,id) => state[table]?.find(x => x.id === id)?.name || '未关联';
const date = value => value ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : '尚未设置';
const empty = (title,description='') => `<div class="empty"><div class="empty-icon">◇</div><strong>${escape(title)}</strong><p>${escape(description)}</p></div>`;
function tab(id) {
  if(id==='archive')loadArchive().catch(error=>notify(error.message,true));
  if(id==='customers')loadCustomers().catch(error=>notify(error.message,true));
  document.querySelectorAll('main>section').forEach(s => s.classList.toggle('hidden',s.id !== id));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active',b.dataset.tab === id));
  const page = pages[id]; $('#breadcrumb').textContent=page[0]; $('#page-title').textContent=page[1]; $('#page-description').textContent=page[2];
  $('#heading-action').textContent = id === 'sources' ? '检测微信连接' : '＋ 新建待办';
  $('#heading-action').dataset.page = id;
}
function fillOptions() {
  document.querySelectorAll('[data-options]').forEach(select => {
    const previous = select.value;
    let values = state[select.dataset.options] || [];
    if (select.dataset.options === 'projects') {
      const merchantSelect = select.closest('form')?.querySelector('[name="merchant_id"]') || (select.name === 'pilot_project' ? $('[name="pilot_merchant"]') : null);
      if (merchantSelect?.value) values = values.filter(x => x.merchant_id === merchantSelect.value);
    }
    select.innerHTML = (select.hasAttribute('data-optional') ? '<option value="">暂不关联</option>' : '') + values.map(x => `<option value="${escape(x.id)}">${escape(x.name || x.title || x.sender_id)}</option>`).join('');
    if ([...select.options].some(x => x.value === previous)) select.value = previous;
  });
}
function renderTasks() {
  const tasks = state.tasks.filter(t => taskFilter === 'all' || (taskFilter === 'done' ? t.state === 'done' : !['done','cancelled'].includes(t.state)));
  tasks.sort((a,b) => (a.due_at || '9999').localeCompare(b.due_at || '9999'));
  $('#tasks').innerHTML = tasks.map(t => {
    const late = t.due_at && new Date(t.due_at) < new Date() && !['done','cancelled'].includes(t.state);
    return `<article class="card"><div class="card-top"><span class="badge ${late?'red':t.state==='done'?'green':'amber'}">${late?'已到跟进时间':escape(statuses[t.state])}</span><span class="small muted">${escape(party[t.party])}</span></div><h3>${escape(t.summary)}</h3><p>${escape(name('merchants',t.merchant_id))} · ${escape(name('projects',t.project_id))}</p><p>下次跟进：${escape(t.due_at?date(t.due_at):t.due_text||'待人工确认')}</p><div class="actions">${t.state!=='done'?`<button class="primary" data-action="task" data-id="${t.id}" data-state="done" data-version="${t.version}">确认完成</button><button data-action="task" data-id="${t.id}" data-state="snoozed" data-version="${t.version}">稍后跟进</button><button data-action="task" data-id="${t.id}" data-state="waiting_external" data-version="${t.version}">等待反馈</button>`:`<button data-action="task" data-id="${t.id}" data-state="open" data-version="${t.version}">重新打开</button>`}<button class="subtle" data-action="task" data-id="${t.id}" data-state="cancelled" data-version="${t.version}">取消</button></div></article>`;
  }).join('') || empty(taskFilter==='active'?'暂时没有进行中的待办':'这里还没有记录','手工创建一个事项，或从 AI 建议中确认下一步。');
}
function render() {
  const open = state.tasks.filter(t => !['done','cancelled'].includes(t.state));
  const pending = state.suggestions.filter(s => s.status === 'pending');
  $('#metrics').innerHTML = [
    ['在跟商家',state.merchants.length,'跨私信与群聊聚合','↗'],
    ['备货项目',state.projects.filter(p=>!['done','cancelled'].includes(p.stage)).length,'按批次独立推进','▥'],
    ['待跟进事项',open.length,'区分商家、服务商与我方','◷'],
    ['待确认建议',pending.length,'证据核对后进入跟进','✧']
  ].map(([label,value,note,icon])=>`<div class="metric"><span class="metric-label">${label}</span><span class="metric-icon">${icon}</span><b>${value}</b><small>${note}</small></div>`).join('');
  const real=state.conversations.filter(c=>c.source==='wx_cli' && c.allowlisted);
  $('#onboarding-banner').classList.toggle('hidden',real.length>0);
  fillOptions(); renderTasks();
  $('#suggestions').innerHTML = pending.map(s => `<article class="card"><div class="card-top"><span class="badge">待确认</span><span class="small muted">${escape(party[s.payload.responsible_party])}</span></div><h3>${escape(s.payload.summary)}</h3><p>${escape(name('merchants',s.payload.merchant_id))} · ${escape(name('projects',s.payload.project_id))}</p><p>时间原文：${escape(s.payload.due_text || '未约定')}</p><div class="actions"><button class="primary" data-action="accept" data-id="${s.id}">确认建任务</button><button data-action="evidence" data-id="${s.payload.conversation_id}">核对消息</button><button class="subtle" data-action="dismiss" data-id="${s.id}">忽略</button></div></article>`).join('') || empty('暂无新的建议','接入微信后，核对授权并启动 DeepSeek worker 才会产生分析结果。');
  $('#activation').innerHTML = state.activation.map(a=>`<article class="card"><div class="card-top"><span class="badge green">市场匹配</span></div><h3>${escape(a.project.merchant_name)}</h3><p>${escape(a.project.name)}</p><p>${escape(a.reason)}</p><p class="summary">${a.materials.map(m=>escape(m.name+' · '+m.version)).join('、')}</p></article>`).join('') || empty('等待合适的重新联系理由','录入有效价卡与商家需求后，这里会展示可核对的匹配候选。');
  $('#project-count').textContent=state.projects.length+' 个项目';
  $('#project-list').innerHTML = state.projects.map(p=>{
    const steps=['needs','connecting','proposal','planned','executing','verification','done'];
    const progress=Math.max(0,steps.indexOf(p.stage))*100/(steps.length-1);
    const quotes=state.quotes.filter(q=>q.project_id===p.id), milestones=state.milestones.filter(m=>m.project_id===p.id);
    return `<article class="card project-entry"><div class="card-top"><span class="badge ${p.stage==='done'?'green':''}">${escape(stages[p.stage])}</span><span class="muted small">${escape(p.market||'市场待确认')}</span></div><h3>${escape(p.name)}</h3><p>${escape(name('merchants',p.merchant_id))}</p><div class="progress"><i style="width:${progress}%"></i></div><div class="row"><select data-stage="${p.id}" data-version="${p.version}" aria-label="项目阶段">${Object.entries(stages).map(([key,label])=>`<option value="${key}" ${key===p.stage?'selected':''}>${label}</option>`).join('')}</select><button data-action="stage" data-id="${p.id}">确认阶段</button></div><details><summary>报价 ${quotes.length} · 节点 ${milestones.length}</summary><div class="detail-body">${quotes.map(q=>`<p class="small"><span class="badge ${q.confirmed?'green':'gray'}">${q.confirmed?'已确认报价':'待确认报价'}</span> ${escape(q.terms)}</p>`).join('')}${milestones.map(m=>`<p class="small"><span class="badge ${m.verified?'green':'gray'}">${m.verified?'已核验':'未核验'}</span> ${escape(({dispatch:'发货',arrival:'到仓',stocking_result:'备货结果'})[m.kind]||m.kind)} · ${escape(m.note)}</p>`).join('') || '<p class="hint">尚无节点记录</p>'}</div></details></article>`;
  }).join('') || empty('先建立第一个备货项目','将商家的本批货物、目标市场和后续沟通放到一起。');
  $('#conversation-count').textContent='最近 '+real.length+' 个；完整列表见消息档案';
  $('#conversations').innerHTML=state.conversations.map(c=>`<article class="card"><div class="card-top"><span class="badge ${c.source==='wx_cli'?'green':'gray'}">${c.source==='wx_cli'?'真实微信':c.source==='fixture'?'虚构样例':'人工导入'}</span><span class="small muted">${!c.allowlisted?'已暂停':c.egress?'已授权分析':'仅本地归档'}</span></div><h3>${escape(c.title)}</h3><p>${escape(name('merchants',c.merchant_id))} · ${escape(name('projects',c.project_id))}</p><div class="actions"><button data-action="evidence" data-id="${c.id}">查看消息</button><button data-action="configure" data-id="${c.id}">关联与授权</button>${c.egress?`<button data-action="preview" data-id="${c.id}">脱敏预览</button><button data-action="enqueue" data-id="${c.id}">安排分析</button><button data-action="draft" data-id="${c.id}">起草话术</button>`:''}${c.allowlisted?`<button class="subtle" data-action="pause" data-id="${c.id}">暂停采集</button>`:''}</div></article>`).join('') || empty('还没有接入会话','先通过上方向导选择 1–2 个试点群，默认只归档到本机。');
  $('#material-list').innerHTML=state.materials.map(m=>`<article class="card"><div class="card-top"><span class="badge ${m.status==='approved'?'green':'gray'}">${({approved:'已审核',pending:'待审核',withdrawn:'已撤回'})[m.status]||escape(m.status)}</span><span class="small muted">${escape(m.market)} · ${m.scope==='external'?'可对外使用':'仅内部'}</span></div><h3>${escape(m.name)} <span class="muted">${escape(m.version)}</span></h3><p class="summary">${escape(m.terms)}</p><p>有效至 ${escape(m.valid_until?date(m.valid_until):'未知，不自动推荐')}</p><button class="subtle" data-action="withdraw" data-id="${m.id}">撤回此版本</button></article>`).join('') || empty('让素材带着明确的适用条件','保存价卡版本、有效期和税费口径，再用于商家匹配。');
  $('#runtime').textContent=JSON.stringify({runtime:state.runtime,analysis:state.jobs,coverage:state.sync,usage:state.usage},null,2);
  const worker=state.runtime.find(r=>r.name==='worker');
  const recent=worker && Date.now()-new Date(worker.updated_at).getTime()<60000;
  const gaps=state.sync.filter(s=>s.status==='gap').length;
  $('#overview-status').innerHTML=`<div class="status-line"><span>真实采集会话</span><strong>${state.conversation_totals.find(x=>x.source==='wx_cli')?.n||0} 个</strong></div><div class="status-line"><span>分析 worker</span><span class="badge ${recent?'green':'gray'}">${recent?'最近有心跳':'等待启动 / 心跳过期'}</span></div><div class="status-line"><span>最近窗口待核查</span><strong>${gaps} 项</strong></div><div class="status-line"><span>DeepSeek 今日用量</span><strong>${(state.usage.find(u=>u.day===new Date().toISOString().slice(0,10))?.tokens||0).toLocaleString()} tokens</strong></div>`;
}
async function load(){state=await api('/api/state');render();if(!$('#archive').classList.contains('hidden'))await loadArchive();if(!$('#customers').classList.contains('hidden'))await loadCustomers();}
function previewMessages(messages) {
  if($('#preview-dialog').open)$('#preview-dialog').close();
  $('#preview-title').textContent='本地消息 · 最近 100 条'; $('#preview').classList.add('hidden'); $('#message-preview').classList.remove('hidden');
  $('#message-preview').innerHTML=messages.map(m=>`<article class="message"><div class="meta">${m.conversation_title?escape(m.conversation_title)+' · ':''}${escape(date(m.event_time))} · ${m.direction==='outgoing'?'我方发出':'收到'} · ${m.completeness==='full'?'文本正文':'非全文 / 元数据'}</div><p>${escape(m.text)}</p>${['3','image'].includes(m.type)?`<div class="image-preview" data-image-box="${m.id}"><button data-action="load-image" data-id="${m.id}">读取本机图片</button><p class="hint">仅在本机获取并缓存，不调用 DeepSeek。能否读到原图取决于微信下载与图片解密状态。</p></div>`:''}<small class="muted">发送者 ID：${escape(m.sender_id)}</small></article>`).join('') || empty('最近还没有采集到消息','可以在微信中正常产生一条业务消息，然后重新试采。');
  draftText='';$('#copy-draft').classList.add('hidden');$('#preview-dialog').showModal();
}
function step(index){document.querySelectorAll('[data-step]').forEach(s=>{s.classList.toggle('active',Number(s.dataset.step)===index);s.classList.toggle('done',Number(s.dataset.step)<index);});}
function renderGroups(){
  const search=$('#group-search').value.trim().toLowerCase();
  const groups=[...discovered.values()].filter(g=>g.title.toLowerCase().includes(search));
  $('#group-options').innerHTML=groups.map(g=>`<label class="group-option"><input type="checkbox" data-group="${escape(g.source_id)}" ${selected.has(g.source_id)?'checked':''}><span><strong>${escape(g.title)}</strong><small>${escape(g.source_id)}</small></span></label>`).join('') || empty('当前页没有匹配的群','可以加载更多会话，或在微信里打开试点群后重新检测。');
  $('#selected-count').textContent=`已选 ${selected.size} / 2`;
}
async function fetchGroups(offset=0){
  const result=await api('/api/source/groups',{offset});
  result.groups.forEach(g=>discovered.set(g.source_id,g)); nextOffset=result.next_offset;
  $('#more-groups').classList.toggle('hidden',!result.has_more);$('#group-picker').classList.remove('hidden');renderGroups();step(3);
}
$('#probe-source').onclick=()=>busy($('#probe-source'),async()=>{
  $('#source-error').classList.add('hidden');$('#group-picker').classList.add('hidden');$('#account-confirm').classList.add('hidden');
  try {
    sourceAccount=await api('/api/source/probe',{}); discovered.clear();selected.clear();nextOffset=0;$('#pilot-results').innerHTML='';
    $('#source-status-title').textContent='已连接本机采集服务';$('#source-status-detail').textContent=`版本 ${sourceAccount.source_version||'未知'} · 请核对工作微信账号`;
    $('#account-name').textContent=sourceAccount.account_name;$('#account-id').textContent=sourceAccount.account_id;
    if(sourceAccount.bound){await fetchGroups();}else{$('#account-confirm').classList.remove('hidden');step(2);}
  } catch(error){$('#source-status-title').textContent='采集服务尚未就绪';$('#source-status-detail').textContent='工作台运行正常；请先完成右侧的采集准备。';$('#source-error').textContent=error.message;$('#source-error').classList.remove('hidden');step(1);}
});
$('#bind-source').onclick=()=>busy($('#bind-source'),async()=>{await api('/api/source/bind',{account_id:sourceAccount.account_id});$('#account-confirm').classList.add('hidden');await fetchGroups();});
$('#more-groups').onclick=()=>busy($('#more-groups'),()=>fetchGroups(nextOffset));
$('#group-search').oninput=renderGroups;
$('#group-options').onchange=event=>{const input=event.target;if(!input.dataset.group)return;if(input.checked && selected.size>=2){input.checked=false;notify('先选最多两个群，核对后再扩大范围',true);return;}if(input.checked)selected.add(input.dataset.group);else selected.delete(input.dataset.group);$('#selected-count').textContent=`已选 ${selected.size} / 2`;};
$('#start-pilot').onclick=()=>busy($('#start-pilot'),async()=>{
  if(!selected.size)throw Error('请先选择 1–2 个群聊');
  const groups=[...selected].map(id=>({...discovered.get(id),merchant_id:$('[name="pilot_merchant"]').value,project_id:$('[name="pilot_project"]').value}));
  const result=await api('/api/source/pilot',{groups});
  $('#pilot-results').innerHTML=result.results.map(r=>`<div class="trial-result"><div class="row"><strong>${escape(r.title)}</strong><span class="badge ${r.error?'amber':'green'}">${r.error?'需检查':'试采完成'}</span></div>${r.error?`<p class="warn">${escape(sourceError(r.error))} · 未将本窗口标为完整</p>`:`<p class="small">本地共 ${r.message_count} 条 · 本次新增 ${r.inserted} 条 · 重复 ${r.duplicates} 条</p>`}<p class="hint">最近 15 分钟；DeepSeek 外发已关闭。重复试采不会重复归档。</p><button data-action="evidence" data-id="${r.conversation_id}">核对群消息 →</button></div>`).join('');
  step(4);await load();notify('试采结果已显示；先核对正文、账号与发送者，再考虑分析。');
});
$('#heading-action').onclick=()=>$('#heading-action').dataset.page==='sources'?$('#probe-source').click():$('#task-dialog').showModal();
$('#refresh').onclick=()=>busy($('#refresh'),load);
$('#copy-draft').onclick=async()=>{try{await navigator.clipboard.writeText(draftText);notify('已复制；请到微信人工核对后发送，系统未记录已联系。');}catch{notify('浏览器未允许剪贴板，请手工复制。',true);}};
document.querySelectorAll('form[data-api]').forEach(form=>form.onsubmit=async event=>{
  event.preventDefault();const button=form.querySelector('button');
  await busy(button,async()=>{const body=Object.fromEntries(new FormData(form));form.querySelectorAll('[data-bool]').forEach(s=>body[s.name]=s.value==='true');await api(form.dataset.api,body);if(form.closest('dialog')?.open)form.closest('dialog').close();notify('已保存');await load();});
});
$('#import').onsubmit=async event=>{event.preventDefault();await busy(event.target.querySelector('button'),async()=>{const records=event.target.records.value.trim().split('\n').filter(Boolean).map(x=>JSON.parse(x));const result=await api('/api/imports',{records});notify(`新增 ${result.inserted} 条，重复 ${result.duplicates} 条，排除 ${result.excluded} 条`);await load();});};
document.addEventListener('change',event=>{if(['merchant_id','pilot_merchant'].includes(event.target.name))fillOptions();});
document.addEventListener('click',async event=>{
  const tabButton=event.target.closest('[data-tab]');if(tabButton)tab(tabButton.dataset.tab);
  const close=event.target.closest('[data-close]');if(close)$('#'+close.dataset.close).close();
  const button=event.target.closest('[data-action]');if(!button)return;
  await busy(button,async()=>{
    const id=button.dataset.id, action=button.dataset.action;
    if(action==='accept')await api(`/api/suggestions/${id}/accept`,{});
    if(action==='dismiss')await api(`/api/suggestions/${id}/dismiss`,{});
    if(action==='task'){
      let due=null;if(button.dataset.state==='snoozed'){due=prompt('下次跟进时间（含时区，例如 2026-11-10T09:00:00+08:00）');if(!due)return;}
      await api(`/api/tasks/${id}/transition`,{state:button.dataset.state,version:Number(button.dataset.version),due_at:due});
    }
    if(action==='stage'){const s=$(`[data-stage="${id}"]`);await api(`/api/projects/${id}/transition`,{stage:s.value,version:Number(s.dataset.version)});}
    if(action==='withdraw')await api(`/api/materials/${id}/withdraw`,{});
    if(action==='pause')await api(`/api/conversations/${id}/pause`,{});
    if(action==='enqueue'){await api(`/api/analysis/${id}/enqueue`,{});notify('已安排分析；需启动本地 worker 执行。');}
    if(action==='configure'){
      const c=state.conversations.find(c=>c.id===id)||archiveRows.find(c=>c.id===id);const f=document.querySelector('form[data-api="/api/conversations"]');
      tab('sources');f.closest('details').open=true;
      for(const [key,value] of Object.entries(c)){const input=f.elements.namedItem(key);if(input)input.value=key==='egress'?String(Boolean(value)):value??'';}
      f.elements.namedItem('source_id').value=c.source_id;f.scrollIntoView({behavior:'smooth',block:'center'});
    }
    if(action==='load-image'){
      const response=await fetch(`/api/messages/${id}/image`);
      if(!response.ok){const error=await response.json();throw Error(error.error||'图片读取失败');}
      const url=URL.createObjectURL(await response.blob());imageURLs.push(url);
      const box=$(`[data-image-box="${id}"]`);const img=document.createElement('img');img.src=url;img.alt='本机归档的群聊图片';img.className='archived-image';box.appendChild(img);
      const quality=response.headers.get('X-Wechat-Media-Quality');box.querySelector('.hint').textContent=quality==='thumbnail'?'当前只有缩略图，价格等细小文字需核对原图。':quality==='full'?'上游标记为完整图；尚未进行 OCR 或模型分析。':'图像已读取，清晰度未知；尚未进行 OCR。';button.remove();
    }
    if(action==='evidence'){messageConversation=id;messagePage=1;await showMessagePage();}
    if(action==='preview'||action==='draft'){
      const result=await api(action==='preview'?`/api/analysis/${id}/preview`:`/api/drafts/${id}`,{});
      $('#preview-title').textContent=action==='draft'?'话术草稿 · 尚未发送':'脱敏请求预览 · 未调用模型';
      $('#message-pagination').classList.add('hidden');
      $('#message-preview').classList.add('hidden');$('#preview').classList.remove('hidden');$('#preview').textContent=action==='draft'?result.text:JSON.stringify(result.payload,null,2);
      draftText=action==='draft'?result.text:'';$('#copy-draft').classList.toggle('hidden',!draftText);$('#preview-dialog').showModal();
    }
    await load();
  });
});
$('#today-date').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(new Date());
$('#task-filters').onclick=event=>{if(!event.target.dataset.filter)return;taskFilter=event.target.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter===taskFilter));renderTasks();};
load().catch(error=>notify(error.message,true));

$('#preview-dialog').addEventListener('close',()=>{imageURLs.forEach(url=>URL.revokeObjectURL(url));imageURLs.length=0;});

let archivePage=1,archiveRows=[];
async function loadArchive(){
  const form=$('#archive-search');const q=form.elements.q.value;const kind=form.elements.kind.value;
  const data=await api(`/api/archive/conversations?q=${encodeURIComponent(q)}&kind=${kind}&page=${archivePage}`);
  archiveRows=data.items;
  const summary=await api('/api/archive/status');
  $('#archive-progress').textContent=`当前账号已归档 ${summary.messages} 条；${summary.progress.map(p=>({scanned:'已扫描',scanned_with_gaps:'已扫描但有缺口',pending:'待处理',failed:'失败待重试'}[p.status]||p.status)+': '+p.conversations+' 个会话').join('，')||'尚未运行历史初始化'}。发送者未知但正文保留 ${summary.metadata_warnings?.messages||0} 条；失败原因 ${summary.failure_reasons?.map(r=>r.error+' × '+r.conversations).join('，')||'无'}。扫描完成不代表源端历史完整。`;
  $('#archive-list').innerHTML=data.items.map(c=>`<article class="card"><div class="card-top"><h3>${escape(c.title)}</h3><span class="badge">${c.kind==='group'?'群聊':'私信'}</span></div><p>${c.message_count} 条已归档消息 · ${c.egress?'已授权分析':'仅本地归档'} · ${c.allowlisted?'持续采集启用':'已暂停'}</p><div class="actions"><button data-action="evidence" data-id="${c.id}">查看消息</button><button data-action="configure" data-id="${c.id}">业务关联与授权</button><button data-action="pause" data-id="${c.id}">暂停</button></div></article>`).join('')||empty('当前没有匹配的归档会话','先运行会话发现与全量初始化命令。');
  $('#archive-page').textContent=`第 ${archivePage} 页 · 共 ${data.total} 个会话`;
  $('#archive-prev').disabled=archivePage<=1;$('#archive-next').disabled=!data.has_more;
}
$('#archive-search').onsubmit=event=>{event.preventDefault();archivePage=1;loadArchive().catch(error=>notify(error.message,true));};
$('#archive-prev').onclick=()=>{archivePage=Math.max(1,archivePage-1);loadArchive().catch(error=>notify(error.message,true));};
$('#archive-next').onclick=()=>{archivePage+=1;loadArchive().catch(error=>notify(error.message,true));};

let messageConversation=null,messagePage=1;
async function showMessagePage(){
  const rows=await api(`/api/messages/${messageConversation}?page=${messagePage}`);previewMessages(rows);
  $('#preview-title').textContent='本地消息 · 第 '+messagePage+' 页';
  $('#message-pagination').classList.remove('hidden');$('#messages-prev').disabled=messagePage<=1;$('#messages-next').disabled=rows.length<100;$('#messages-page').textContent='第 '+messagePage+' 页';
}
$('#messages-prev').onclick=()=>{messagePage=Math.max(1,messagePage-1);showMessagePage().catch(error=>notify(error.message,true));};
$('#messages-next').onclick=()=>{messagePage++;showMessagePage().catch(error=>notify(error.message,true));};
let importedFile=null;
$('#file-import').onsubmit=event=>{event.preventDefault();busy($('#preview-file'),async()=>{
 const f=event.target.file.files[0];if(!f)throw Error('请选择文件');if(f.size>1500000)throw Error('网页最多 1.5 MB，更大文件请使用 CLI import');
 importedFile={filename:f.name,text:await f.text(),account_id:event.target.account_id.value};
 const result=await api('/api/imports/file',{...importedFile,write:false});$('#file-report').classList.remove('hidden');$('#file-report').textContent=JSON.stringify(result,null,2);$('#write-file').disabled=result.rejected>0||result.valid===0;
});};
$('#file-import').addEventListener('change',()=>{$('#write-file').disabled=true;importedFile=null;});
$('#write-file').onclick=()=>busy($('#write-file'),async()=>{if(!importedFile)throw Error('请先校验预览');const result=await api('/api/imports/file',{...importedFile,write:true});$('#file-report').textContent=JSON.stringify(result,null,2);notify('手动导入完成，未调用 DeepSeek');await load();await loadArchive();});
let customerPage=1;
async function loadCustomers(){const q=$('#customer-search').elements.q.value;const data=await api(`/api/customers?q=${encodeURIComponent(q)}&page=${customerPage}`);$('#customer-list').innerHTML=data.items.map(c=>`<article class="card"><h3>${escape(c.display_name)}</h3><p>${escape(c.identity)}</p><button data-customer="${escape(c.identity)}">私信与群内沟通时间线</button></article>`).join('')||empty('尚未发现可关联联系人','归档私信与群消息后，这里按稳定身份汇总。');$('#customer-page').textContent=`第 ${customerPage} 页 · ${data.total} 位联系人`;
$('#customer-prev').disabled=customerPage<=1;$('#customer-next').disabled=!data.has_more;}
$('#customer-search').onsubmit=e=>{e.preventDefault();customerPage=1;loadCustomers().catch(error=>notify(error.message,true));};
$('#customer-prev').onclick=()=>{customerPage=Math.max(1,customerPage-1);loadCustomers().catch(error=>notify(error.message,true));};
$('#customer-next').onclick=()=>{customerPage++;loadCustomers().catch(error=>notify(error.message,true));};
document.addEventListener('click',async event=>{const button=event.target.closest('[data-customer]');if(!button)return;busy(button,async()=>{const rows=await api(`/api/customers/${encodeURIComponent(button.dataset.customer)}/timeline`);previewMessages(rows);$('#message-pagination').classList.add('hidden');$('#preview-title').textContent='客户沟通时间线 · 最近 100 条';});});
