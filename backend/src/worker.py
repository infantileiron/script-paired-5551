import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import Evaluation,Plan
from src.services.analysis import evaluate
from src.services import plans
r=redis.Redis.from_url(os.environ['REDIS_URL'])
with Session() as recovery:
 for pending in recovery.query(Evaluation).filter(Evaluation.state.in_(['queued','running'])).all():
  pending.state='queued';r.rpush('paired:evaluations',pending.id)
 plans.recover_running(recovery,lambda plan_id:r.rpush(plans.QUEUE,plan_id))
while True:
 Path('/tmp/heartbeat').touch()
 try:
  item=r.blpop(['paired:evaluations',plans.QUEUE],timeout=3)
  if not item:continue
  queue,raw=item[0].decode(),item[1]
  if queue==plans.QUEUE:
   try:plans.run_attempt(int(raw))
   except Exception:logging.exception('plan')
   continue
  with Session() as s:
   row=s.get(Evaluation,int(raw))
   if not row or row.state!='queued':continue
   snapshot=row.result['snapshot'];row.state='running';s.commit()
   try:
    row.result={**evaluate(snapshot),'snapshot':snapshot};row.state='done'
    Path('/artifacts/'+str(row.id)+'.json').write_text(json.dumps(row.result,ensure_ascii=False))
   except Exception as e:row.state='failed';row.error=str(e)
   s.commit()
 except Exception:logging.exception('worker');time.sleep(2)
