from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey,Boolean,UniqueConstraint
from sqlalchemy.orm import relationship
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True,nullable=False);password=Column(String(200));role=Column(String(20))
class Pair(Base):
 __tablename__='pairs'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);team=Column(String(40));before=Column(Float,nullable=True);after=Column(Float,nullable=True);note=Column(Text,default='')
class Evaluation(Base):
 __tablename__='evaluations'
 id=Column(Integer,primary_key=True);name=Column(String(100));team=Column(String(40));state=Column(String(20),default='queued');result=Column(JSON,nullable=True);error=Column(Text,default='')
class Plan(Base):
 __tablename__='plans'
 id=Column(Integer,primary_key=True);name=Column(String(100),nullable=False)
 state=Column(String(20),default='pending');alpha=Column(Float,default=.05)
 sample=Column(JSON,nullable=False);design_checksum=Column(String(64),default='')
 result=Column(JSON,nullable=True);error=Column(Text,default='')
 attempts=Column(Integer,default=0);version=Column(Integer,default=0)
 attempt_log=Column(JSON,default=list);created=Column(String(40),default='')
 hypotheses=relationship('PlanHypothesis',back_populates='plan',cascade='all, delete-orphan',order_by='PlanHypothesis.ordinal')
class PlanHypothesis(Base):
 __tablename__='plan_hypotheses'
 __table_args__=(UniqueConstraint('plan_id','ordinal'),)
 id=Column(Integer,primary_key=True);plan_id=Column(Integer,ForeignKey('plans.id'),nullable=False)
 plan=relationship('Plan',back_populates='hypotheses')
 ordinal=Column(Integer,nullable=False);scope=Column(String(20),nullable=False);team=Column(String(40),nullable=True)
 label=Column(String(120),nullable=False);statement=Column(Text,default='');member_codes=Column(JSON,default=list)
 state=Column(String(20),default='registered');error=Column(Text,default='')
 n=Column(Integer,nullable=True);difference=Column(Float,nullable=True);sd=Column(Float,nullable=True)
 t=Column(Float,nullable=True);df=Column(Integer,nullable=True);p_value=Column(Float,nullable=True)
 ci=Column(JSON,nullable=True);cohen_dz=Column(Float,nullable=True);excluded=Column(JSON,default=list)
 adjusted_p=Column(Float,nullable=True);rank=Column(Integer,nullable=True);tie_group=Column(Integer,nullable=True)
 tie_size=Column(Integer,nullable=True);significant=Column(Boolean,nullable=True)
class Adoption(Base):
 __tablename__='adoptions'
 id=Column(Integer,primary_key=True);evaluation_id=Column(Integer,ForeignKey('evaluations.id'),nullable=True);decision=Column(String(30));note=Column(Text);status=Column(String(20),default='draft')
 plan_id=Column(Integer,ForeignKey('plans.id'),nullable=True);hypothesis_id=Column(Integer,ForeignKey('plan_hypotheses.id'),nullable=True)
 plan_version=Column(Integer,nullable=True);evidence=Column(JSON,nullable=True)
 approved_by=Column(String(100),nullable=True);approved_at=Column(String(40),nullable=True)
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40));plan_id=Column(Integer,nullable=True)
