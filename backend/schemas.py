from typing import Literal, Annotated
from pydantic import BaseModel, Field, field_validator
from .monitoring.ai_tool import VegetationChangeArguments

class Site(BaseModel):
 soil:Literal['sand','loam','clay']='loam'
 moisture:float=Field(.4,ge=0,le=1)
 salinity:float=Field(.2,ge=0,le=1)
 traffic:float=Field(.5,ge=0,le=1)
 temperature:float=Field(-38,ge=-60,le=10)
 light:Literal['sun','partial']='sun'
 purpose:Literal['public','children','road']='public'
 provenance:Literal['synthetic','user_input','measured']='user_input'
class PlanPlant(BaseModel):
 id:str=Field(max_length=80)
 count:int=Field(ge=0,le=5000)
class AnalysisInput(BaseModel):
 geometry:dict
 zone_id:str|None=Field(None,max_length=80,pattern=r'^[a-zA-Z0-9:_-]+$')
 zone_name:str|None=Field(None,min_length=1,max_length=120)
 site:Site=Field(default_factory=Site)
 budget:float=Field(5_000_000,ge=0,le=1_000_000_000)
 years:int=Field(3,ge=1,le=3)
 plantable:float=Field(.45,ge=.05,le=.95)
 irrigation:bool=True
 maintenance:float=Field(.8,ge=0,le=1)
 plants:list[PlanPlant]|None=Field(None,max_length=30)
 goal:Literal['shade','road','children','low_maintenance']|None=None
 @field_validator('plants')
 @classmethod
 def unique(cls,v):
  if v and len({x.id for x in v})!=len(v): raise ValueError('Растения не должны дублироваться')
  return v
class Credentials(BaseModel):
 email:str=Field(min_length=5,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
 password:str=Field(min_length=8,max_length=128)
 name:str=Field('Пользователь',min_length=1,max_length=80)
class FirebaseToken(BaseModel):
 token:str=Field(min_length=100,max_length=10000)
class ProjectInput(BaseModel):
 name:str=Field(min_length=1,max_length=120)
 payload:AnalysisInput
class ChatInput(BaseModel):
 message:str=Field(min_length=1,max_length=1500)
 analysis:AnalysisInput|None=None
 language:Literal['ru','kk']|None=None
 monitoring:VegetationChangeArguments|None=None
class RoleInput(BaseModel):
 role:Literal['user','specialist','admin']
 blocked:bool=False
class PriorityInput(BaseModel):
 budget:float=Field(5_000_000,ge=0,le=1_000_000_000)
 weights:dict[str,float]|None=None

class ZoneNameInput(BaseModel):
 ru:str=Field(min_length=1,max_length=120)
 kk:str=Field(min_length=1,max_length=120)
 @field_validator('ru','kk')
 @classmethod
 def clean_name(cls,value):
  value=value.strip()
  if not value: raise ValueError('Название не может быть пустым')
  if any(ord(c)<32 for c in value): raise ValueError('Недопустимые управляющие символы')
  return value
