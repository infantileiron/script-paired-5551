from datetime import datetime,timezone
from src.models.entities import Audit
def audit(s,u,action,plan_id=None,commit=True):
 s.add(Audit(actor=u.email,action=action,created=datetime.now(timezone.utc).isoformat(),plan_id=plan_id))
 if commit:s.commit()
def dump(obj):return {c.name:getattr(obj,c.name) for c in obj.__table__.columns if c.name!='password'}
