from pydantic import BaseModel,Field,model_validator
from typing import Optional,Literal,List
class Login(BaseModel):email:str;password:str
class PairInput(BaseModel):
 code:str=Field(min_length=1,max_length=60)
 team:Literal['企业一组','企业二组']
 before:Optional[float]=Field(default=None,ge=0,le=100,allow_inf_nan=False)
 after:Optional[float]=Field(default=None,ge=0,le=100,allow_inf_nan=False)
 note:str=Field(default='',max_length=1000)
class EvaluationInput(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 team:Literal['全部','企业一组','企业二组']='全部'
class PlanInput(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 teams:Optional[List[Literal['企业一组','企业二组']]]=Field(default=None,max_length=2)
 alpha:float=Field(default=.05,gt=0,lt=1,allow_inf_nan=False)
 @model_validator(mode='after')
 def unique_teams(self):
  if self.teams is not None and len(set(self.teams))!=len(self.teams):raise ValueError('业务组不能重复登记')
  return self
class AdoptionInput(BaseModel):
 evaluation_id:Optional[int]=Field(default=None,gt=0)
 plan_id:Optional[int]=Field(default=None,gt=0)
 hypothesis_id:Optional[int]=Field(default=None,gt=0)
 decision:Literal['继续试点','分组采纳','暂缓采纳']
 note:str=Field(min_length=8,max_length=2000)
 @model_validator(mode='after')
 def one_binding(self):
  legacy=self.evaluation_id is not None
  planned=self.plan_id is not None or self.hypothesis_id is not None
  if legacy and planned:raise ValueError('采纳意见只能绑定旧独立评估或联合检验计划之一')
  if planned and (self.plan_id is None or self.hypothesis_id is None):
   raise ValueError('绑定联合检验时必须同时给出计划与假设')
  if not legacy and not planned:raise ValueError('请选择要采纳的评估或计划假设')
  return self
