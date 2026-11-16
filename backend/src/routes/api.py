import os,json
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.config.database import db,Session
from src.models.entities import User,Pair,Evaluation,Adoption,Audit,Plan,PlanHypothesis
from src.schemas.business import Login,PairInput,EvaluationInput,AdoptionInput,PlanInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services import plans
from src.controllers.business import ensure_evaluation,ensure_plan,ensure_hypothesis,approved_gate,evidence_for
router=APIRouter()
def enqueue_plan(plan_id):
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush(plans.QUEUE,plan_id)
 except redis.RedisError:
  with Session() as s:
   row=s.get(Plan,plan_id)
   if row and row.state=='pending':
    row.state='failed';row.error='队列暂不可用，计划未计算；可重试（沿用封存依据）'
    log=list(row.attempt_log or [])
    log.append({'attempt':row.attempts or 0,'started_at':plans.now(),'finished_at':plans.now(),
                'outcome':'failed','error':row.error,'design_checksum':row.design_checksum,
                'sample_checksum':plans.checksum(row.sample)})
    row.attempt_log=log;s.commit()
  raise HTTPException(503,'队列暂不可用，请稍后重试')
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/pairs')
def pairs(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Pair).order_by(Pair.id).all()]
@router.post('/pairs')
def create_pair(data:PairInput,u=Depends(editor),s=Depends(db)):
 r=Pair(**data.model_dump());s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'顾问编号已存在，每位顾问仅保留一组前后测')
 audit(s,u,'录入顾问配对 '+r.code);return dump(r)
@router.put('/pairs/{i}')
def edit_pair(i:int,data:PairInput,u=Depends(editor),s=Depends(db)):
 r=s.get(Pair,i)
 if not r:raise HTTPException(404,'配对记录不存在')
 for k,v in data.model_dump().items():setattr(r,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'顾问编号重复')
 audit(s,u,'修订配对 '+str(i)+'；已封存计划样本不受影响');return dump(r)
@router.get('/evaluations')
def evaluations(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Evaluation).order_by(Evaluation.id.desc()).all()]
@router.post('/evaluations')
def evaluate(data:EvaluationInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Pair).order_by(Pair.id).all() if data.team=='全部' or r.team==data.team]
 r=Evaluation(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('paired:evaluations',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请稍后重新提交';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交评估 '+str(r.id));return dump(r)
@router.get('/evaluations/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_evaluation(s,i))
@router.get('/evaluations/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_evaluation(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功评估可导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="script-paired-{i}.json"'})

@router.get('/plans')
def list_plans(u=Depends(current),s=Depends(db)):
 return [plans.dump_plan(r) for r in s.query(Plan).order_by(Plan.id.desc()).all()]
@router.post('/plans')
def create_plan(data:PlanInput,u=Depends(editor),s=Depends(db)):
 try:sample,sample_checksum=plans.seal_sample(s)
 except ValueError as exc:raise HTTPException(422,str(exc))
 teams=data.teams if data.teams is not None else [t for t in ('企业一组','企业二组') if any(r['team']==t for r in sample)]
 if not teams:raise HTTPException(422,'封存样本里没有可登记的业务组')
 missing=[t for t in teams if not any(r['team']==t for r in sample)]
 if missing:raise HTTPException(422,'所选业务组在封存样本中没有顾问：'+'、'.join(missing))
 hypotheses=plans.build_hypotheses(sample,teams)
 p=Plan(name=data.name,alpha=data.alpha,state='pending',sample=sample,created=plans.now())
 p.hypotheses=[PlanHypothesis(**h) for h in hypotheses]
 p.design_checksum=plans.checksum(plans.design_of(p.name,p.alpha,sample_checksum,hypotheses))
 s.add(p);s.commit()
 enqueue_plan(p.id)
 audit(s,u,'登记联合检验计划 '+str(p.id)+'（'+str(len(hypotheses))+' 项假设，样本已封存）',plan_id=p.id)
 return plans.dump_plan(p)
@router.get('/plans/{i}')
def plan_detail(i:int,u=Depends(current),s=Depends(db)):return plans.dump_plan(ensure_plan(s,i))
@router.post('/plans/{i}/retry')
def retry_plan(i:int,u=Depends(editor),s=Depends(db)):
 p=ensure_plan(s,i,lock=True)
 if p.state!='failed':raise HTTPException(409,'只有失败的整份计划可以重试')
 env=plans.integrity_error(p)
 if env:raise HTTPException(409,env+'；不能用改动后的样本或假设重试')
 p.state='pending';p.error='';s.commit()
 enqueue_plan(p.id)
 audit(s,u,'重试联合检验计划 '+str(p.id)+'（沿用封存样本与假设，不重复发布）',plan_id=p.id)
 return plans.dump_plan(ensure_plan(s,i))
@router.get('/plans/{i}/export')
def export_plan(i:int,u=Depends(current),s=Depends(db)):
 p=ensure_plan(s,i)
 view=plans.dump_plan(p)
 doc={'kind':'joint-test-plan','plan':view,'hypothesis_family':view['hypotheses'],
      'sample_overlap':view['overlap'],
      'approvals':[a.evidence for a in s.query(Adoption).filter_by(plan_id=p.id).order_by(Adoption.id).all() if a.status=='approved'],
      'note':'导出包含登记假设全集与封存样本校验值；失败项仍计入假设总数。'}
 return Response(json.dumps(doc,ensure_ascii=False,indent=2),media_type='application/json',
   headers={'Content-Disposition':f'attachment; filename="joint-plan-{i}.json"'})

@router.get('/adoptions')
def adoptions(u=Depends(current),s=Depends(db)):
 return [dump(r) for r in s.query(Adoption).order_by(Adoption.id.desc()).all()]
@router.post('/adoptions')
def adoption(data:AdoptionInput,u=Depends(editor),s=Depends(db)):
 values=data.model_dump()
 if values.get('evaluation_id'):
  if ensure_evaluation(s,values['evaluation_id']).state!='done':raise HTTPException(409,'评估完成后才能起草采纳意见')
  r=Adoption(**values);s.add(r);s.commit();audit(s,u,'起草采纳意见 '+str(r.id));return dump(r)
 plan=ensure_plan(s,values['plan_id'])
 hypothesis=ensure_hypothesis(s,plan,values['hypothesis_id'])
 if plan.state!='available':raise HTTPException(409,'计划可用后才能起草绑定采纳意见')
 if hypothesis.significant is not True:raise HTTPException(409,'仅校正后显著的假设可起草采纳意见')
 r=Adoption(evaluation_id=None,plan_id=plan.id,hypothesis_id=hypothesis.id,plan_version=plan.version,
   decision=values['decision'],note=values['note'],status='draft',evidence=evidence_for(s,plan,hypothesis))
 s.add(r);s.commit();audit(s,u,'起草绑定采纳意见 '+str(r.id)+' → 计划 '+str(plan.id)+' 假设 #'+str(hypothesis.ordinal),plan_id=plan.id)
 return dump(r)

@router.post('/adoptions/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=s.execute(select(Adoption).where(Adoption.id==i).with_for_update()).scalar_one_or_none()
 if not r:raise HTTPException(404,'采纳意见不存在')
 if r.status!='draft':raise HTTPException(409,'已签核意见不可重复签核')
 if r.plan_id:
  plan=ensure_plan(s,r.plan_id,lock=True)
  hypothesis=ensure_hypothesis(s,plan,r.hypothesis_id)
  approved_gate(s,plan,hypothesis)
  if r.plan_version!=plan.version:raise HTTPException(409,'计划已重算，草稿绑定的是旧版本结果，请重新起草')
  if r.evidence and r.evidence.get('adjusted_p')!=hypothesis.adjusted_p:
   raise HTTPException(409,'草稿证据与当前发布结果不一致，拒绝签核')
  r.evidence={**r.evidence,'approved_plan_version':plan.version,'approved_adjusted_p':hypothesis.adjusted_p,
              'approved_by':u.email,'approved_at':plans.now()}
 r.status='approved';r.approved_by=u.email;r.approved_at=plans.now();s.commit()
 audit(s,u,'签核意见 '+str(i),plan_id=r.plan_id)
 return dump(r)

@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
