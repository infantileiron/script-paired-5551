import hashlib,json
from datetime import datetime,timezone

from sqlalchemy import select

from src.config.database import Session as DBSession
from src.models.entities import Plan,PlanHypothesis
from src.services.analysis import paired_statistics

QUEUE='paired:plans'
TIE_TOLERANCE=1e-12


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def seal_sample(s):
    """一次性封存共用样本；此后任何配对修订都不会进入该计划。"""
    from src.models.entities import Pair
    rows=[{'record_id':p.id,'code':p.code,'team':p.team,'before':p.before,'after':p.after,'note':p.note or ''}
          for p in s.query(Pair).order_by(Pair.id).all()]
    if not rows:raise ValueError('当前没有可封存的配对记录')
    return rows,checksum(rows)


def _statement(scope,team):
    where='总体（全部顾问）' if scope=='overall' else f'{team}（该组全部顾问）'
    return f'{where}接受同一续约话术切换；聚合配对差值 d=后测−前测 的总体均值不为 0（双侧配对 t 检验）。'


def build_hypotheses(sample,teams):
    """总体 + 每个登记小组各一个假设；共用同一份封存样本。"""
    ordered=[]
    ordered.append({'ordinal':1,'scope':'overall','team':None,'label':'总体 · 全部顾问',
                    'statement':_statement('overall',None),
                    'member_codes':[r['code'] for r in sample]})
    for ordinal,team in enumerate(teams,start=2):
        members=[r['code'] for r in sample if r['team']==team]
        ordered.append({'ordinal':ordinal,'scope':'team','team':team,'label':f'{team} · 组内顾问',
                        'statement':_statement('team',team),'member_codes':members})
    return ordered


def design_of(name,alpha,sample_checksum,hypotheses):
    return {'name':name,'alpha':alpha,'sample_checksum':sample_checksum,
            'hypotheses':[{'ordinal':h['ordinal'],'scope':h['scope'],'team':h['team'],
                           'label':h['label'],'statement':h['statement'],
                           'member_codes':h['member_codes']} for h in hypotheses]}


def design_checksum(plan):
    hypotheses=[{'ordinal':h.ordinal,'scope':h.scope,'team':h.team,'label':h.label,
                 'statement':h.statement,'member_codes':h.member_codes} for h in sorted(plan.hypotheses,key=lambda h:h.ordinal)]
    return checksum(design_of(plan.name,plan.alpha,checksum(plan.sample),hypotheses))


def holm(entries,alpha):
    """标准 Holm 逐步下降校正；并列原概率获得相同校正值，并列内按登记序号排序。"""
    m=len(entries)
    order=sorted(entries,key=lambda e:(e['p_value'],e['ordinal']))
    adjusted={};ranks={};tie_groups={};tie_sizes={}
    running=0.0;group=0;group_start=0
    for index,entry in enumerate(order):
        running=max(running,(m-index)*entry['p_value'])
        adjusted[entry['ordinal']]=min(1.0,running)
        ranks[entry['ordinal']]=index+1
        if index==0 or abs(entry['p_value']-order[group_start]['p_value'])>TIE_TOLERANCE:
            if index:group_start=index
            group+=1
        tie_groups[entry['ordinal']]=group
    for g in set(tie_groups.values()):
        size=sum(1 for x in tie_groups.values() if x==g)
        for ordinal,value in tie_groups.items():
            if value==g:tie_sizes[ordinal]=size
    return adjusted,ranks,tie_groups,tie_sizes


def compute(plan):
    """纯计算：任何一项样本不足/零方差都令整份失败；失败项仍计入假设总数 m。"""
    sample=plan.sample
    hypotheses=sorted(plan.hypotheses,key=lambda h:h.ordinal)
    m=len(hypotheses)
    computed=[];failures=[]
    for h in hypotheses:
        rows=[r for r in sample if h.scope=='overall' or r['team']==h.team]
        try:
            stats_=paired_statistics(rows)
            computed.append({'hypothesis':h,'stats':stats_})
        except ValueError as exc:
            failures.append({'hypothesis':h,'error':str(exc)})
    base={'family_size':m,'alpha':plan.alpha,'test':'双侧配对 t 检验',
          'ordering_basis':'原概率升序；原概率并列（容差 1e-12）按登记序号升序，并列假设共用同一校正值',
          'sample_checksum':checksum(sample),'sample_total':len(sample),'sealed_at':plan.created}
    if failures:
        details=[]
        failed_ordinals={f['hypothesis'].ordinal for f in failures}
        for entry in computed:
            h=entry['hypothesis']
            details.append(_hypothesis_result(h,None,None,None,None,None,None,'withheld',
                '整份计划失败，原概率、校正值与显著性均不发布，不可用于签核'))
        for entry in failures:
            h=entry['hypothesis']
            details.append(_hypothesis_result(h,None,None,None,None,None,None,'failed',entry['error']))
        details.sort(key=lambda d:d['ordinal'])
        return {'outcome':'failed','result':{**base,'hypotheses':details,
                'failure_count':len(failures),'failed_ordinals':sorted(failed_ordinals),
                'message':'至少一项假设样本不足或零方差，整份计划失败；失败项仍计入假设总数 '+str(m)+'，未发布任何原概率或校正结果'}}
    adjusted,ranks,tie_groups,tie_sizes=holm([{'ordinal':e['hypothesis'].ordinal,'p_value':e['stats']['p_value']} for e in computed],plan.alpha)
    details=[]
    for entry in computed:
        h=entry['hypothesis'];st=entry['stats'];ordinal=h.ordinal
        significant=adjusted[ordinal]<=plan.alpha+TIE_TOLERANCE
        details.append(_hypothesis_result(h,st,adjusted[ordinal],ranks[ordinal],tie_groups[ordinal],
            tie_sizes[ordinal],significant,'significant' if significant else 'not-significant',None))
    details.sort(key=lambda d:d['ordinal'])
    return {'outcome':'available','result':{**base,'hypotheses':details,'failure_count':0,
            'significant_count':sum(1 for d in details if d['significant'])}}


def _hypothesis_result(h,st,adjusted_p,rank,tie_group,tie_size,significant,state,error):
    return {'hypothesis_id':h.id,'ordinal':h.ordinal,'scope':h.scope,'team':h.team,'label':h.label,
            'statement':h.statement,'member_codes':h.member_codes,'member_count':len(h.member_codes),
            'n':st['n'] if st else None,'difference':st['difference'] if st else None,
            'sd':st['sd'] if st else None,'t':st['t'] if st else None,'df':st['df'] if st else None,
            'p_value':st['p_value'] if st else None,'ci':st['ci'] if st else None,
            'cohen_dz':st['cohen_dz'] if st else None,
            'complete_codes':st['complete_codes'] if st else [],
            'excluded':st['excluded'] if st else [],
            'adjusted_p':adjusted_p,'rank':rank,'tie_group':tie_group,'tie_size':tie_size,
            'significant':significant,'state':state,'error':error}


def overlap_view(sample,hypotheses):
    overall=next((h for h in hypotheses if h.scope=='overall'),None)
    overall_codes=set(overall.member_codes) if overall else set()
    groups=[]
    for h in hypotheses:
        if h.scope!='team':continue
        codes=set(h.member_codes)
        groups.append({'hypothesis_id':h.id,'ordinal':h.ordinal,'team':h.team,
                       'members':len(codes),'shared_with_overall':len(codes&overall_codes),
                       'only_in_group':len(codes-overall_codes),'only_in_overall':len(overall_codes-codes)})
    duplicates=sorted({c for h in hypotheses for c in h.member_codes
                       if sum(1 for x in hypotheses if c in x.member_codes)>1})
    return {'overall_members':len(overall_codes),'teams':groups,'shared_codes':duplicates,
            'shared_code_count':len(duplicates)}


def integrity_error(plan):
    if not plan.design_checksum:return '计划缺少封存设计校验值'
    try:
        if plan.design_checksum!=design_checksum(plan):
            return '计划假设或封存样本与登记设计不一致，拒绝沿用封存依据'
    except Exception:
        return '计划封存设计无法校验'
    return ''

def begin_attempt(plan_id):
    """原子占用一次计算：仅 pending 可转为 running；重复队列消息被忽略。"""
    with DBSession() as s:
        plan=s.execute(select(Plan).where(Plan.id==plan_id).with_for_update()).scalar_one_or_none()
        if not plan or plan.state!='pending':return None
        error=integrity_error(plan)
        plan.state='running';plan.attempts=(plan.attempts or 0)+1;plan.error=''
        log=list(plan.attempt_log or [])
        log.append({'attempt':plan.attempts,'started_at':now(),'outcome':'running',
                    'design_checksum':plan.design_checksum,'sample_checksum':checksum(plan.sample)})
        plan.attempt_log=log
        s.commit()
        return {'id':plan.id,'checksum_error':error}

def finish_attempt(plan_id,outcome,result,error,checksum_error='',computed_sample_checksum=None):
    """落库一次计算。只有仍处 running 的尝试能发布，保证并发下不会拼接半份结果。"""
    with DBSession() as s:
        plan=s.execute(select(Plan).where(Plan.id==plan_id).with_for_update()).scalar_one_or_none()
        if not plan or plan.state!='running':return False
        log=list(plan.attempt_log or [])
        if log:log[-1]={'attempt':log[-1].get('attempt'),'started_at':log[-1].get('started_at'),
                        'finished_at':now(),'outcome':outcome,'error':(error or '')[:1000],
                        'design_checksum':plan.design_checksum,'sample_checksum':checksum(plan.sample)}
        if not checksum_error and computed_sample_checksum and checksum(plan.sample)!=computed_sample_checksum:
            checksum_error='计算期间封存样本被改动'
        if not checksum_error and integrity_error(plan):
            checksum_error=integrity_error(plan)
        if checksum_error:
            plan.state='failed';plan.error='封存设计校验失败：'+checksum_error
            plan.result={'outcome':'failed','message':plan.error,'family_size':len(plan.hypotheses),
                         'hypotheses':[{'hypothesis_id':h.id,'ordinal':h.ordinal,'label':h.label,
                                        'state':'failed','error':'未运行：封存设计校验失败',
                                        'adjusted_p':None,'significant':None} for h in plan.hypotheses]}
            for h in plan.hypotheses:h.state='failed';h.error='未运行：封存设计校验失败'
            plan.attempt_log=log;s.commit();return True
        failure=(outcome!='available')
        if failure and not result.get('hypotheses'):
            result={**result,'hypotheses':[{'hypothesis_id':h.id,'ordinal':h.ordinal,'label':h.label,
                       'state':'failed','error':(error or result.get('message') or '计算失败')[:500],
                       'n':None,'difference':None,'sd':None,'t':None,'df':None,'p_value':None,'ci':None,
                       'cohen_dz':None,'excluded':[],'adjusted_p':None,'rank':None,'tie_group':None,
                       'tie_size':None,'significant':None} for h in plan.hypotheses]}
        for detail in result['hypotheses']:
            h=s.get(PlanHypothesis,detail['hypothesis_id'])
            if not h:continue
            h.state=detail['state'];h.error=detail['error'] or ''
            h.n=detail['n'];h.difference=detail['difference'];h.sd=detail['sd']
            h.t=detail['t'];h.df=detail['df'];h.p_value=detail['p_value']
            h.ci=detail['ci'];h.cohen_dz=detail['cohen_dz'];h.excluded=detail['excluded']
            h.adjusted_p=detail['adjusted_p'];h.rank=detail['rank'];h.tie_group=detail['tie_group']
            h.tie_size=detail['tie_size'];h.significant=detail['significant']
        plan.result={**result,'outcome':outcome,'attempt':plan.attempts,'published_at':now()}
        plan.error=('整份计划失败：'+result.get('message','')) if failure else ''
        plan.state='failed' if failure else 'available'
        if not failure:plan.version=(plan.version or 0)+1
        plan.attempt_log=log
        s.commit()
        return True


def recover_running(s,enqueue):
    recovered=[]
    for plan in s.query(Plan).filter(Plan.state=='running').all():
        plan.state='pending';plan.error='worker 重启后恢复；沿用同一封存样本与假设重新计算'
        recovered.append(plan.id)
    s.commit()
    for plan_id in recovered:enqueue(plan_id)
    return recovered


def run_attempt(plan_id):
    started=begin_attempt(plan_id)
    if not started:return False
    if started['checksum_error']:
        finish_attempt(plan_id,'failed',{'hypotheses':[]},started['checksum_error'],started['checksum_error'])
        return True
    with DBSession() as s:
        plan=s.get(Plan,plan_id)
        sample_checksum=checksum(plan.sample)
        try:
            computed=compute(plan);outcome=computed['outcome'];result=computed['result'];error=''
        except Exception as exc:
            outcome='failed';result={'hypotheses':[],'family_size':len(plan.hypotheses),'message':str(exc)};error=str(exc)
    finish_attempt(plan_id,outcome,result,error,computed_sample_checksum=sample_checksum)
    return True


def dump_plan(plan):
    hypotheses=sorted(plan.hypotheses,key=lambda h:h.ordinal)
    result=plan.result or {}
    return {'id':plan.id,'name':plan.name,'state':plan.state,'alpha':plan.alpha,
            'sample':plan.sample,'sample_checksum':checksum(plan.sample),
            'design_checksum':plan.design_checksum,'result':plan.result,'error':plan.error,
            'attempts':plan.attempts or 0,'version':plan.version or 0,'attempt_log':plan.attempt_log or [],
            'created':plan.created,
            'hypotheses':[dump_hypothesis(h) for h in hypotheses],
            'family_size':len(hypotheses),
            'overlap':overlap_view(plan.sample,hypotheses),
            'published':plan.state=='available' and result.get('outcome')=='available'}


def dump_hypothesis(h):
    return {c.name:getattr(h,c.name) for c in h.__table__.columns}
