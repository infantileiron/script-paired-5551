import json
import pytest

from tests.conftest import auth,add_pair,seeded_pairs
from src.services.plans import holm,compute


# ---------- 纯统计层 ----------

def test_holm_ties_share_adjusted_value_and_rank_by_registration():
    entries=[{'ordinal':3,'p_value':.04},{'ordinal':1,'p_value':.01},{'ordinal':2,'p_value':.01},
             {'ordinal':4,'p_value':.20}]
    adjusted,ranks,tie_groups,tie_sizes=holm(entries,.05)
    assert adjusted[1]==adjusted[2]==pytest.approx(.04)
    assert adjusted[3]==pytest.approx(.08)
    assert adjusted[4]==pytest.approx(.20)
    assert ranks[1]==1 and ranks[2]==2 and ranks[3]==3 and ranks[4]==4
    assert tie_groups[1]==tie_groups[2] and tie_sizes[1]==2
    # 校正值随原概率单调不减
    ordered=sorted(entries,key=lambda e:e['ordinal'])
    values=[adjusted[e['ordinal']] for e in ordered]
    assert values==sorted(values)


def test_holm_ordering_basis_documented_in_result():
    from src.models.entities import Plan,PlanHypothesis
    sample=[{'code':f'QY-{i}','team':'企业一组','before':70.0,'after':70.0+d}
            for i,d in enumerate([0,0,0,0,0,0,0,0,0,0],1)]
    plan=Plan(name='t',alpha=.05,sample=sample,created='now')
    plan.hypotheses=[PlanHypothesis(id=1,ordinal=1,scope='overall',team=None,label='总体',
                                    statement='s',member_codes=[r['code'] for r in sample])]
    out=compute(plan)
    assert '并列' in out['result']['ordering_basis']
    assert out['result']['family_size']==1


# ---------- API / 流程 ----------

def test_plan_registers_overall_and_team_hypotheses_with_shared_sealed_sample(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3]*10)
    seeded_pairs(client,h,'企业二组',[2]*10,before=65.0)
    r=client.post('/plans',json={'name':'11月联合检验','teams':['企业一组','企业二组']},headers=h)
    assert r.status_code==200,r.text
    plan=r.json()
    assert [x['scope'] for x in plan['hypotheses']]==['overall','team','team']
    assert plan['sample_checksum'] and plan['design_checksum']
    assert plan['family_size']==3
    assert plan['overlap']['overall_members']==20
    assert all(t['shared_with_overall']==10 for t in plan['overlap']['teams'])
    # 共用样本：每个组的成员都在总体假设内
    assert set(plan['hypotheses'][1]['member_codes'])<set(plan['hypotheses'][0]['member_codes'])


def test_sealed_sample_ignores_later_pair_revisions(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[4]*10)
    plan=client.post('/plans',json={'name':'封存','teams':['企业一组']},headers=h).json()
    before=plan['sample_checksum']
    assert add_pair(client,h,'企业一组-99','企业一组',10,100).status_code==200
    detail=client.get(f"/plans/{plan['id']}",headers=h).json()
    assert detail['sample_checksum']==before
    assert all(code!='企业一组-99' for code in detail['hypotheses'][0]['member_codes'])


def test_only_pending_can_start_and_duplicate_queue_messages_are_ignored(client):
    from src.services.plans import begin_attempt,finish_attempt
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3]*10)
    plan=client.post('/plans',json={'name':'幂等'},headers=h).json()
    assert begin_attempt(plan['id']) is not None
    assert begin_attempt(plan['id']) is None
    assert finish_attempt(plan['id'],'available',{'hypotheses':[]},'') is True
    assert finish_attempt(plan['id'],'available',{'hypotheses':[]},'') is False


def test_failure_is_whole_plan_and_retry_keeps_sealed_design(client):
    h=auth(client,'analyst')
    # 企业一组只有 2 对完整配对 -> 总体与组内都失败
    add_pair(client,h,'A-1','企业一组',70,73)
    add_pair(client,h,'A-2','企业一组',70,74)
    add_pair(client,h,'A-3','企业一组',70,None)
    seeded_pairs(client,h,'企业二组',[2]*10,before=60.0)
    plan=client.post('/plans',json={'name':'部分失败'},headers=h).json()
    from src.services.plans import run_attempt
    run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    assert p['state']=='failed'
    assert p['result']['outcome']=='failed'
    assert p['result']['family_size']==3
    assert p['result']['failure_count']>=1
    # 失败项仍计入假设总数，且没有任何已发布校正结果
    assert all(x['adjusted_p'] is None for x in p['result']['hypotheses'])
    assert all(x['significant'] is None for x in p['result']['hypotheses'])
    assert p['published'] is False
    design=p['design_checksum']
    # 补录后重试：仍沿用封存样本，补录不会进入
    assert add_pair(client,h,'A-3','企业一组',70,None).status_code==409
    client.put('/pairs/3',json={'code':'A-3','team':'企业一组','before':70,'after':80,'note':'补录'},headers=h)
    r=client.post(f"/plans/{plan['id']}/retry",headers=h)
    assert r.status_code==200,r.text
    assert r.json()['design_checksum']==design
    run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    assert p['state']=='failed'  # 封存样本未变，失败可重复且不发布
    assert p['attempts']==2
    assert p['version']==0
    assert len(p['attempt_log'])==2


def test_successful_plan_publishes_holm_and_ranks(client):
    h=auth(client,'analyst')
    # 两组都显著且方向一致；总体更强
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    seeded_pairs(client,h,'企业二组',[4,3,5,2,4,3,5,4,2,3],before=60.0)
    plan=client.post('/plans',json={'name':'成功'},headers=h).json()
    from src.services.plans import run_attempt
    run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    assert p['state']=='available',p
    assert p['version']==1
    hyps=p['result']['hypotheses']
    assert len(hyps)==3
    for x in hyps:
        assert x['p_value'] is not None and x['adjusted_p'] is not None
        assert x['adjusted_p']>=x['p_value']
        assert x['rank'] in (1,2,3)
    assert sorted(x['rank'] for x in hyps)==[1,2,3]
    assert p['published'] is True


def test_adoption_requires_significant_adjusted_hypothesis(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[-1,2,-1,2,-1,2,-1,2,-1,2])
    seeded_pairs(client,h,'企业二组',[2,3,2,3,2,3,2,3,2,3],before=60.0)
    plan=client.post('/plans',json={'name':'不显著'},headers=h).json()
    from src.services.plans import run_attempt
    run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    hyps={x['scope']+str(x['team']):x for x in p['hypotheses']}
    ns=next(x for x in p['hypotheses'] if x['significant'] is False)
    r=client.post('/adoptions',json={'plan_id':plan['id'],'hypothesis_id':ns['id'],
                                     'decision':'继续试点','note':'校正后不显著，不应允许起草采纳意见'},headers=h)
    assert r.status_code==409


def test_concurrent_approve_never_lands_half_result(client,monkeypatch):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'并发'},headers=h).json()
    from src.services import plans as plan_service
    plan_service.run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    sig=next(x for x in p['hypotheses'] if x['significant'])
    created=client.post('/adoptions',json={'plan_id':plan['id'],'hypothesis_id':sig['id'],
                                            'decision':'继续试点','note':'联合检验显著后的业务结论'},headers=h)
    assert created.status_code==200,created.text
    aid=created.json()['id']
    admin_h=auth(client,'admin')
    # 计算结果并发变化：计划重算后版本提升，草稿绑定旧版本 -> 拒绝
    with __import__('src.config.database').config.database.Session() as s:
        row=s.get(__import__('src.models.entities',fromlist=['Plan']).Plan,plan['id'])
        row.version=row.version+1;s.commit()
    r=client.post(f'/adoptions/{aid}/approve',json={},headers=admin_h)
    assert r.status_code==409
    assert client.get('/adoptions',headers=admin_h).json()[0]['status']=='draft'
    # 计划被标为失败/不可用时也不能签发
    with __import__('src.config.database').config.database.Session() as s:
        row=s.get(__import__('src.models.entities',fromlist=['Plan']).Plan,plan['id'])
        row.version=p['version'];row.state='failed';s.commit()
    assert client.post(f'/adoptions/{aid}/approve',json={},headers=admin_h).status_code==409


def test_approve_success_records_evidence_and_second_approve_rejected(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'签核'},headers=h).json()
    from src.services.plans import run_attempt
    run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    sig=next(x for x in p['hypotheses'] if x['significant'])
    a=client.post('/adoptions',json={'plan_id':plan['id'],'hypothesis_id':sig['id'],
                                      'decision':'继续试点','note':'联合检验校正后显著，作为试点签核依据'},headers=h).json()
    admin_h=auth(client,'admin')
    r=client.post(f"/adoptions/{a['id']}/approve",json={},headers=admin_h)
    assert r.status_code==200,r.text
    assert r.json()['status']=='approved'
    assert r.json()['evidence']['hypothesis_id']==sig['id']
    assert r.json()['evidence']['adjusted_p']==sig['adjusted_p']
    assert client.post(f"/adoptions/{a['id']}/approve",json={},headers=admin_h).status_code==409


def test_export_traces_family_overlap_and_approval_basis(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'导出'},headers=h).json()
    from src.services.plans import run_attempt
    run_attempt(plan['id'])
    r=client.get(f"/plans/{plan['id']}/export",headers=h)
    assert r.status_code==200
    doc=json.loads(r.content)
    assert doc['plan']['design_checksum']
    assert doc['plan']['sample_checksum']
    assert len(doc['hypothesis_family'])==doc['plan']['family_size']
    assert doc['sample_overlap']['overall_members']==10
    assert 'approvals' in doc


def test_tampered_sealed_design_blocks_retry_and_new_attempt_fails(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'防篡改','teams':['企业一组']},headers=h).json()
    from src.services.plans import run_attempt
    from src.config.database import Session
    from src.models.entities import Plan
    run_attempt(plan['id'])
    with Session() as s:
        row=s.get(Plan,plan['id']);row.sample=[dict(r,after=r['after']+50) for r in row.sample]
        row.state='failed';s.commit()
    assert client.post(f"/plans/{plan['id']}/retry",headers=h).status_code==409
    # 即便队列消息绕过重试接口，计算入口也会校验并在发布前失败
    with Session() as s:
        row=s.get(Plan,plan['id']);row.state='pending';s.commit()
    assert run_attempt(plan['id']) is True
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    assert p['state']=='failed'
    assert p['error'].startswith('封存设计校验失败')
    assert p['result']['hypotheses'][0]['state']=='failed'
    assert p['published'] is False


def test_pair_revision_does_not_change_sealed_plan_values(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'修订隔离','teams':['企业一组']},headers=h).json()
    from src.services.plans import run_attempt
    run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    diff=p['hypotheses'][0]['difference']
    client.put('/pairs/1',json={'code':'企业一组-01','team':'企业一组','before':70,'after':30,'note':'事后修订'},headers=h)
    detail=client.get(f"/plans/{plan['id']}",headers=h).json()
    assert detail['hypotheses'][0]['difference']==diff
    assert detail['sample_checksum']==p['sample_checksum']


def test_retry_of_published_plan_rejected(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'不可重试'},headers=h).json()
    from src.services.plans import run_attempt
    run_attempt(plan['id'])
    assert client.get(f"/plans/{plan['id']}",headers=h).json()['state']=='available'
    assert client.post(f"/plans/{plan['id']}/retry",headers=h).status_code==409


def test_approval_between_attempts_never_releases_half_result(client):
    """签核发生时计划正被重算：门禁看到 running/失败版本均拒绝。"""
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'并发半份','teams':['企业一组']},headers=h).json()
    from src.services.plans import run_attempt,begin_attempt
    run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    sig=next(x for x in p['hypotheses'] if x['significant'])
    a=client.post('/adoptions',json={'plan_id':plan['id'],'hypothesis_id':sig['id'],'decision':'继续试点',
                                     'note':'并发签核门禁测试'},headers=h).json()
    assert begin_attempt(plan['id']) is None  # available 不能被 worker 再占用
    from src.config.database import Session
    from src.models.entities import Plan
    with Session() as s:
        row=s.get(Plan,plan['id']);row.state='running';s.commit()
    admin_h=auth(client,'admin')
    r=client.post(f"/adoptions/{a['id']}/approve",json={},headers=admin_h)
    assert r.status_code==409
    assert '可用' in r.json()['detail']


def test_worker_recovery_requeues_running_plan_with_same_design(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'重启恢复','teams':['企业一组']},headers=h).json()
    from src.config.database import Session
    from src.models.entities import Plan
    from src.services.plans import begin_attempt,recover_running
    begin_attempt(plan['id'])
    queued=[]
    with Session() as s:
        recovered=recover_running(s,queued.append)
    assert recovered==[plan['id']] and queued==[plan['id']]
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    assert p['state']=='pending'
    assert p['design_checksum']==plan['design_checksum']
    assert '沿用同一封存样本' in p['error']


def test_queue_outage_marks_plan_failed_without_publishing(client,monkeypatch):
    import redis
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    def boom(*a,**k):raise redis.RedisError('down')
    monkeypatch.setattr(redis.Redis,'from_url',classmethod(boom))
    r=client.post('/plans',json={'name':'队列故障','teams':['企业一组']},headers=h)
    assert r.status_code==503
    monkeypatch.undo()
    from src.config.database import Session
    from src.models.entities import Plan
    with Session() as s:
        row=s.query(Plan).one()
        assert row.state=='failed' and row.version==0 and row.result is None
        assert row.attempt_log and row.attempt_log[-1]['outcome']=='failed'


def test_plan_for_team_without_members_rejected(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    r=client.post('/plans',json={'name':'空组','teams':['企业二组']},headers=h)
    assert r.status_code==422


def test_export_contains_approval_basis_after_signing(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'导出签核','teams':['企业一组']},headers=h).json()
    from src.services.plans import run_attempt
    run_attempt(plan['id'])
    p=client.get(f"/plans/{plan['id']}",headers=h).json()
    sig=next(x for x in p['hypotheses'] if x['significant'])
    a=client.post('/adoptions',json={'plan_id':plan['id'],'hypothesis_id':sig['id'],
                                     'decision':'继续试点','note':'导出需包含签核依据'},headers=h).json()
    assert client.get(f"/plans/{plan['id']}/export",headers=h).json()['approvals']==[]
    admin_h=auth(client,'admin')
    assert client.post(f"/adoptions/{a['id']}/approve",json={},headers=admin_h).status_code==200
    doc=client.get(f"/plans/{plan['id']}/export",headers=h).json()
    assert len(doc['approvals'])==1
    assert doc['approvals'][0]['approved_plan_version']==p['version']
    assert doc['hypothesis_family'][0]['adjusted_p'] is not None


def test_legacy_independent_evaluation_and_adoption_still_work(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    e=client.post('/evaluations',json={'name':'旧独立评估','team':'企业一组'},headers=h)
    assert e.status_code==200,e.text
    eid=e.json()['id']
    # 模拟 worker 完成旧评估
    from src.services.analysis import evaluate
    from src.config.database import Session
    from src.models.entities import Evaluation
    with Session() as s:
        row=s.get(Evaluation,eid);row.result={**evaluate(row.result['snapshot']),'snapshot':row.result['snapshot']}
        row.state='done';s.commit()
    assert client.get(f'/evaluations/{eid}/export',headers=h).status_code==200
    a=client.post('/adoptions',json={'evaluation_id':eid,'decision':'继续试点','note':'旧独立评估采纳保持可用'},headers=h)
    assert a.status_code==200,a.text
    assert client.post(f"/adoptions/{a.json()['id']}/approve",json={},headers=auth(client,'admin')).status_code==200


def test_mixed_binding_and_missing_binding_rejected(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    e=client.post('/evaluations',json={'name':'旧评估','team':'企业一组'},headers=h).json()
    plan=client.post('/plans',json={'name':'混合','teams':['企业一组']},headers=h).json()
    r=client.post('/adoptions',json={'evaluation_id':e['id'],'plan_id':plan['id'],'hypothesis_id':plan['hypotheses'][0]['id'],
                                     'decision':'继续试点','note':'不允许同时绑定两种来源'},headers=h)
    assert r.status_code==422
    r=client.post('/adoptions',json={'plan_id':plan['id'],'decision':'继续试点','note':'缺少假设编号不允许'},headers=h)
    assert r.status_code==422


def test_viewer_cannot_register_or_retry_plans(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'权限','teams':['企业一组']},headers=h).json()
    v=auth(client,'viewer')
    assert client.post('/plans',json={'name':'观察员登记','teams':['企业一组']},headers=v).status_code==403
    assert client.post(f"/plans/{plan['id']}/retry",headers=v).status_code==403
    assert client.get('/plans',headers=v).status_code==200


def test_worker_cannot_reserve_available_or_failed_plan(client):
    h=auth(client,'analyst')
    seeded_pairs(client,h,'企业一组',[3,4,2,5,3,4,2,3,5,4])
    plan=client.post('/plans',json={'name':'占用','teams':['企业一组']},headers=h).json()
    from src.services.plans import begin_attempt,finish_attempt,run_attempt
    assert begin_attempt(plan['id']) is not None
    plan_view=client.get(f"/plans/{plan['id']}",headers=h).json()
    assert plan_view['state']=='running'
    # pending→running 后不能再被第二个 worker 占用
    assert begin_attempt(plan['id']) is None
    finish_attempt(plan['id'],'available',{'hypotheses':[],'family_size':1},'')
    assert begin_attempt(plan['id']) is None
    assert run_attempt(plan['id']) is False
