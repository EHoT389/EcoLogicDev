import os, json, time, secrets, hashlib
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Float, ForeignKey, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/'.env')
DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///./ecologic.db')
engine=create_engine(DATABASE_URL,connect_args={"check_same_thread":False} if DATABASE_URL.startswith('sqlite') else {},pool_pre_ping=True)
SessionLocal=sessionmaker(engine,expire_on_commit=False)
class Base(DeclarativeBase): pass
class User(Base):
 __tablename__='users'
 id:Mapped[str]=mapped_column(String,primary_key=True,default=lambda:secrets.token_hex(16))
 email:Mapped[str]=mapped_column(String,unique=True,index=True)
 name:Mapped[str]=mapped_column(String)
 password:Mapped[str]=mapped_column(String,default='')
 role:Mapped[str]=mapped_column(String,default='user')
 blocked:Mapped[str]=mapped_column(String,default='no')
class Session(Base):
 __tablename__='sessions'
 token_hash:Mapped[str]=mapped_column(String,primary_key=True)
 user_id:Mapped[str]=mapped_column(ForeignKey('users.id'))
 expires:Mapped[float]=mapped_column(Float)
 csrf:Mapped[str]=mapped_column(String)
class Project(Base):
 __tablename__='projects'
 id:Mapped[str]=mapped_column(String,primary_key=True,default=lambda:secrets.token_hex(12))
 owner_id:Mapped[str]=mapped_column(ForeignKey('users.id'),index=True)
 assigned_to:Mapped[str|None]=mapped_column(String,nullable=True)
 name:Mapped[str]=mapped_column(String)
 payload:Mapped[str]=mapped_column(Text)
 result:Mapped[str]=mapped_column(Text)
 updated:Mapped[str]=mapped_column(String,default=lambda:datetime.now(timezone.utc).isoformat())
class Setting(Base):
 __tablename__='settings'
 key:Mapped[str]=mapped_column(String,primary_key=True)
 value:Mapped[str]=mapped_column(Text)
class Event(Base):
 __tablename__='events'
 id:Mapped[str]=mapped_column(String,primary_key=True,default=lambda:secrets.token_hex(12))
 kind:Mapped[str]=mapped_column(String,index=True)
 actor:Mapped[str]=mapped_column(String)
 data:Mapped[str]=mapped_column(Text)
 created:Mapped[float]=mapped_column(Float,default=time.time,index=True)
class AIMessage(Base):
 __tablename__='ai_messages'
 id:Mapped[str]=mapped_column(String,primary_key=True,default=lambda:secrets.token_hex(12))
 owner_id:Mapped[str]=mapped_column(ForeignKey('users.id'),index=True)
 question:Mapped[str]=mapped_column(Text)
 answer:Mapped[str]=mapped_column(Text)
 created:Mapped[float]=mapped_column(Float,default=time.time)

def init_db():
 Base.metadata.create_all(engine)
 with engine.begin() as c:
  # Small explicit migration ledger; additive migrations live in migrations/.
  from sqlalchemy import text
  c.execute(text('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)'))
  if not c.execute(text('SELECT version FROM schema_version WHERE version = 1')).first(): c.execute(text('INSERT INTO schema_version (version) VALUES (1)'))

def get_db():
 with SessionLocal() as db: yield db

def get_setting(db,key,default):
 row=db.get(Setting,key)
 return json.loads(row.value) if row else default

def put_setting(db,key,value):
 row=db.get(Setting,key)
 if row: row.value=json.dumps(value,ensure_ascii=False)
 else: db.add(Setting(key=key,value=json.dumps(value,ensure_ascii=False)))

def log(db,kind,actor,data):
 db.add(Event(kind=kind,actor=actor,data=json.dumps(data,ensure_ascii=False)))

def password_hash(password):
 salt=secrets.token_bytes(16)
 h=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
 return salt.hex()+':'+h.hex()

def password_matches(password,encoded):
 try:
  salt,digest=encoded.split(':')
  h=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=32).hex()
  return secrets.compare_digest(h,digest)
 except (ValueError,TypeError): return False
