from fastapi import HTTPException
from sqlalchemy import select
from src.models.entities import Evaluation,Plan,PlanHypothesis
from src.services.plans import design_checksum,checksum

def ensure_evaluation(s,i):
 row=s.get(Evaluation,i)
 if not row:raise HTTPException(404,'评估任务不存在')
 return row

def ensure_plan(s,i,lock=False):
 query=select(Plan).where(Plan.id==i)
 if lock:query=query.with_for_update()
 row=s.execute(query).scalar_one_or_none()
 if not row:raise HTTPException(404,'联合检验计划不存在')
 return row

def ensure_hypothesis(s,plan,hid):
 row=s.get(PlanHypothesis,hid)
 if not row or row.plan_id!=plan.id:raise HTTPException(404,'假设不属于该计划')
 return row

def approved_gate(s,plan,hypothesis):
 """签核门禁：只接受同一计划版本、校正后显著且计划可用的假设。"""
 if plan.state!='available':raise HTTPException(409,'计划尚未可用，不能签核；失败计划不得发布或签核半份结果')
 if hypothesis.significant is not True:raise HTTPException(409,'该假设校正后不显著，不能签核')
 if plan.version<1 or hypothesis.adjusted_p is None:raise HTTPException(409,'计划没有发布的校正结果，不能签核')
 if design_checksum(plan)!=plan.design_checksum:raise HTTPException(409,'计划封存设计与当前记录不一致，不能签核')

def evidence_for(s,plan,hypothesis):
 return {'plan_id':plan.id,'plan_name':plan.name,'plan_version':plan.version,
         'design_checksum':plan.design_checksum,'sample_checksum':checksum(plan.sample),
         'family_size':len(plan.hypotheses),'alpha':plan.alpha,
         'hypothesis_id':hypothesis.id,'hypothesis_ordinal':hypothesis.ordinal,
         'hypothesis_label':hypothesis.label,'scope':hypothesis.scope,'team':hypothesis.team,
         'statement':hypothesis.statement,'n':hypothesis.n,'difference':hypothesis.difference,
         't':hypothesis.t,'df':hypothesis.df,'p_value':hypothesis.p_value,
         'adjusted_p':hypothesis.adjusted_p,'rank':hypothesis.rank,
         'tie_group':hypothesis.tie_group,'tie_size':hypothesis.tie_size,
         'significant':hypothesis.significant,
         'ordering_basis':'原概率升序，并列按登记序号；Holm 校正值由该计划假设全集（含失败项）决定'}
