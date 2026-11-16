import {state} from '../stores/session.js';
import {esc,num} from '../utils/html.js';
import {badge} from '../components/common/status.js';
import {field} from '../components/common/fields.js';
import {TEAMS,PLAN_STATE_LABELS,HYPOTHESIS_STATE_LABELS,PLAN_SCOPES} from '../constants/enums.js';
const p=v=>v===null||v===undefined?'—':Number(v).toExponential(3);
const f2=v=>v===null||v===undefined?'—':Number(v).toFixed(2);
export function render(){
  let e=state.selectedPlan||state.plans[0]||null;
  return `<div class="split"><section class="panel">
    <h2>${e?esc(e.name):'先登记一份联合检验计划'} ${e?badge(PLAN_STATE_LABELS[e.state]||e.state):''}</h2>
    ${e?planBody(e):'<p class="notice">登记前先封存一份共用样本。总体与每个登记小组的假设一次性写入，之后只能重试，不能增删假设。</p>'}
    <h3>计划记录</h3>
    ${state.plans.map(v=>`<button class="study" data-plan="${v.id}">#${v.id} ${esc(v.name)} · ${esc(PLAN_STATE_LABELS[v.state]||v.state)} · ${v.family_size} 项假设${v.version?` · v${v.version}`:''}</button>`).join('')||'<p>尚无联合检验计划。</p>'}
  </section><aside class="side"><h2>登记联合检验</h2>
    <form id="plan">${field('计划名称','name','text','required value="11月续约话术联合检验"')}
      <fieldset><legend>登记假设的小组</legend>${TEAMS.map(t=>`<label class="inline"><input type="checkbox" name="teams" value="${esc(t)}" checked>${esc(t)}</label>`).join('')}</fieldset>
      ${field('显著性水平 α','alpha','number','min=0.001 max=0.2 step=0.001 value=0.05')}
      <p>登记即封存当前全部配对样本作为共用依据。总体与所选小组的假设数固定，失败项仍计入总数；Holm 校正只对本计划假设全集生效。</p>
      <button class="primary">封存样本并登记计划</button></form>
      <p>封存后样本不再增删；补录或修订配对只影响新计划。</p>
      ${e?`<p><button id="refresh-plan">刷新计划状态</button></p>`:''}
  </aside></div>`;
}
function planBody(e){
  let r=e.result||{};
  let hyps=e.hypotheses||[];
  let failed=e.state==='failed';
  return `<p class="eyebrow">封存样本 ${e.sample.length} 对 / 假设 ${e.family_size} 项 / α=${e.alpha} / 第 ${e.attempts} 次计算</p>
  <div class="metrics"><div><strong>${e.family_size}</strong>登记假设（含失败项）</div><div><strong>${r.significant_count??'—'}</strong>校正后显著</div><div><strong>${e.version?('v'+e.version):'未发布'}</strong>结果版本</div></div>
  ${failed?`<p class="notice">整份计划失败：${esc(e.error||r.message||'至少一项假设样本不足或零方差')}<br>失败项仍计入 ${e.family_size} 项假设总数；原概率与校正值均不发布，不能用于签核。修复后重试会沿用同一封存样本与同一组假设。</p>
  <p><button id="retry-plan">按封存依据重试</button></p>`:''}
  ${e.state==='pending'||e.state==='running'?'<p class="notice">后台正在按封存样本计算聚合配对差值，随后发布 Holm 校正结果。</p>':''}
  <h3>假设全集与校正结果</h3>
  <div class="scroll"><table><thead><tr><th>#</th><th>范围</th><th>假设</th><th>n</th><th>差值</th><th>原 p</th><th>Holm 校正</th><th>排序</th><th>并列</th><th>结论</th><th>状态</th></tr></thead><tbody>
  ${hyps.map(h=>{let withheld=e.state==='failed'||e.state==='pending'||e.state==='running';return `<tr><td>${h.ordinal}</td><td>${esc(PLAN_SCOPES[h.scope]||h.scope)}${h.team?' · '+esc(h.team):''}</td><td title="${esc(h.statement)}">${esc(h.label)}</td><td>${h.n??'—'}</td><td>${withheld?'—':f2(h.difference)}</td><td>${withheld?'—':p(h.p_value)}</td><td>${withheld?'—':p(h.adjusted_p)}</td><td>${withheld?'—':(h.rank??'—')}</td><td>${withheld?'—':(h.tie_group?('组 '+h.tie_group+' · '+h.tie_size+' 项并列'):'—')}</td><td>${withheld?'—':(h.significant===true?'显著':(h.significant===false?'不显著':'—'))}</td><td title="${esc(h.error||'')}">${esc(HYPOTHESIS_STATE_LABELS[h.state]||h.state)}</td></tr>`}).join('')}</tbody></table></div>
  <p class="notice">排序依据：${esc(r.ordering_basis||'原概率升序；并列按登记序号升序，并列假设共用同一校正值')}。校正值由假设全集（含失败项）决定，失败项不会被剔除后重算。</p>
  <h3>样本交叠</h3>
  <p>总体含 ${e.overlap.overall_members} 位顾问；${e.overlap.teams.map(t=>`${esc(t.team)} ${t.members} 位（与总体共用 ${t.shared_with_overall} 位）`).join('；')||'未登记小组'}。同一顾问的配对在总体与小组假设中重复使用，因此结果不独立，不能当作两次独立验证。</p>
  <h3>封存与审计</h3>
  <p>样本校验 <code>${esc(e.sample_checksum.slice(0,16))}…</code><br>设计校验 <code>${esc(e.design_checksum.slice(0,16))}…</code><br>样本封存于 ${esc(e.created)}</p>
  <details><summary>计算尝试记录（${e.attempt_log.length}）</summary><ul>${e.attempt_log.map(a=>`<li>第 ${a.attempt} 次 · ${esc(a.finished_at||a.started_at||'')} · ${esc(a.outcome)}${a.error?' · '+esc(a.error):''}</li>`).join('')||'<li>尚未开始。</li>'}</ul></details>
  <p><button id="download-plan">导出计划 JSON（假设全集 + 样本交叠 + 签核依据）</button></p>`;
}
