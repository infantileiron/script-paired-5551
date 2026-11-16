import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

url=os.environ['DATABASE_URL']
options={}
if url.startswith('sqlite'):
    options['connect_args']={'check_same_thread':False}
    if ':memory:' in url:options['poolclass']=StaticPool
engine=create_engine(url,pool_pre_ping=True,**options)
Session=sessionmaker(bind=engine,expire_on_commit=False)
Base=declarative_base()
def db():
    with Session() as s: yield s
