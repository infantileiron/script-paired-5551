import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {badge} from '../components/common/status.js';import {select} from '../components/common/fields.js';import {DECISIONS,PLAN_STATE_LABELS} from '../constants/enums.js';
const p=v=>v===null||v===undefined?'—':Number(v).toExponential(3);
function binding(r){
 if(r.plan_id)return `<p class="eyebrow">联合检验计划 #${r.plan_id} · 假设 #${r.evidence?.hypothesis_ordinal??'—'} · ${esc(r.evidence?.hypothesis_label||'')} · 计划版本 v${r.plan_version??'—'}</p>`;
 return `<p>独立评估 #${r.evaluation_id}</p>`;
}
function evidence(r){
 if(!r.plan_id||!r.evidence)return '';
 let e=r.evidence;
 return `<details ${r.status==='approved'?'open':''}><summary>签核依据</summary><ul><li>假设 ${esc(e.hypothesis_label)}（第 ${e.hypothesis_ordinal} 项 / 共 ${e.family_size} 项）</li><li>原 p ${p(e.p_value)} · Holm 校正 ${p(e.adjusted_p)} · α=${e.alpha}</li><li>差值 ${Number(e.difference).toFixed(2)} · n=${e.n} · 排序 ${e.rank}${e.tie_size>1?' · 并列 '+e.tie_size+' 项':''}</li><li>设计校验 ${esc((e.design_checksum||'').slice(0,16))}… · 样本校验 ${esc((e.sample_checksum||'').slice(0,16))}…</li>${e.approved_plan_version?`<li>签核所用计划版本 v${e.approved_plan_version} · ${esc(e.approved_by)} · ${esc(e.approved_at)}</li>`:''}</ul></details>`;
}
export function render(){
 let plans=state.plans.filter(x=>x.state==='available');
 let options=[...plans.flatMap(x=>x.hypotheses.filter(h=>h.significant===true).map(h=>[`plan:${h.id}`,`${x.name} · #${h.ordinal} ${h.label}（校正 ${p(h.adjusted_p)}）`])),...state.evaluations.filter(e=>e.state==='done').map(e=>[`evaluation:${e.id}`,`独立评估 · ${e.name}`])];
 return `<div class="split"><section class="panel"><h2>把显著性放回业务背景</h2><p class="notice">统计结果不直接触发话术发布。绑定联合检验的采纳意见只能选择校正后显著的假设，签核时再次核对计划版本与封存校验值。旧独立评估仍可照常采纳。</p>${state.adoptions.map(r=>`<article class="rec"><h3>${esc(r.decision)} ${badge(r.status)}</h3>${binding(r)}<p>${esc(r.note)}</p>${evidence(r)}${state.user.role==='admin'&&r.status==='draft'?`<button data-approve="${r.id}">负责人签核</button>`:''}</article>`).join('')||'<p>尚无采纳意见。完成评估或联合检验后起草第一条。</p>'}</section><aside class="side"><h2>起草采纳意见</h2><form id="adoption">${select('证据来源（仅校正后显著或已完成评估）','evidence',options.length?options:[['','暂无可用证据']])}${select('业务决定','decision',DECISIONS.map(t=>[t,t]))}<label>理由与限制<textarea name="note" minlength="8" required rows="7"></textarea></label><button class="primary">保存待签核意见</button></form>${plans.length?'':'<p>尚无可用的联合检验计划；失败计划不能起草采纳。</p>'}<p>可用计划：${plans.length} 份${plans.length?'（仅显著假设列出）':''}</p></aside></div>`;
}
