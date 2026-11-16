import os
import tempfile
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ['REDIS_URL']='redis://localhost:6379/0'
_dbdir=tempfile.mkdtemp(prefix='paired-tests-')
os.environ['DATABASE_URL']='sqlite:///'+os.path.join(_dbdir,'test.db')

import pytest


@pytest.fixture(scope='session')
def app():
    from src.main import app as fastapi_app
    from src.config.database import Base,engine
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    return fastapi_app


@pytest.fixture(autouse=True)
def clean(app,monkeypatch):
    from src.config.database import Base,engine,Session
    from src.models.entities import User
    from src.utils.security import hash_password
    import fakeredis,redis
    fake=fakeredis.FakeRedis()
    monkeypatch.setattr(redis.Redis,'from_url',classmethod(lambda cls,*a,**k:fake))
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    with Session() as s:
        for role in ('admin','analyst','viewer'):
            s.add(User(email=role+'@demo.local',role=role,password=hash_password('Demo123!')))
        s.commit()
    yield fake


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:yield c


def auth(client,role):
    r=client.post('/auth/login',json={'email':f'{role}@demo.local','password':'Demo123!'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}


def add_pair(client,headers,code,team,before,after):
    return client.post('/pairs',json={'code':code,'team':team,'before':before,'after':after,'note':'7日窗口'},
                       headers=headers)


def seeded_pairs(client,headers,team='企业一组',deltas=None,before=70.0):
    deltas=deltas if deltas is not None else [3,3,3,3,3,3,3,3,3,3]
    for i,d in enumerate(deltas,1):
        r=add_pair(client,headers,f'{team}-{i:02d}',team,before,before+d)
        assert r.status_code==200,r.text
