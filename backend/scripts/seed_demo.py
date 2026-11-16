from datetime import datetime,timezone,timedelta
from src.config.database import Base,engine,Session
from src.models.entities import (User,Experiment,Event,AliasJob,AliasJobItem)
from src.services.identity import process_alias_job
from src.utils.security import hash_password

def seed():
 Base.metadata.create_all(engine)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  s.commit()
  today=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
  for code,name,ends in [('LJ-1115-A','首次引导文案 / 成熟对照',today-timedelta(days=1)),('LJ-1115-B','快捷模板入口 / 观察中',today+timedelta(days=3))]:
   exp=s.query(Experiment).filter_by(code=code).first()
   if not exp:
    exp=Experiment(code=code,name=name,starts_at=(today-timedelta(days=7)).isoformat(),ends_at=ends.isoformat(),a_ratio=.5,hypothesis='更清晰的首次引导能提升首次激活率，预先固定观察期与分流比例');s.add(exp);s.flush()
   if code.endswith('-A'):
    stamp=(datetime.fromisoformat(exp.starts_at)+timedelta(hours=12)).isoformat()
    for i in range(1200):
     group='A' if i<600 else 'B';key=f'LJ-U{i+1:04}';activated=(i<120 if group=='A' else i-600<180)
     for kind in ['exposure']+(['activation'] if activated else []):
      if not s.query(Event).filter_by(experiment_id=exp.id,user_key=key,kind=kind).first():s.add(Event(experiment_id=exp.id,user_key=key,group=group,kind=kind,occurred_at=stamp))
  s.commit()
  _seed_alias_demo(s,today)
  s.commit();print({'users':s.query(User).count(),'experiments':s.query(Experiment).count(),'events':s.query(Event).count(),'alias_jobs':s.query(AliasJob).count()})

def _seed_alias_demo(s,today):
 """别名归并演示实验：同一访客换标识被重复计数，导入别名后去重；另含一组跨组污染。"""
 code='LJ-1115-C'
 exp=s.query(Experiment).filter_by(code=code).first()
 if not exp:
  exp=Experiment(code=code,name='访客标识归并 / 污染拦截演示',
   starts_at=(today-timedelta(days=7)).isoformat(),ends_at=(today-timedelta(days=1)).isoformat(),
   a_ratio=.5,hypothesis='访客登录前后标识不同导致重复计数，导入别名关联后按人去重，并暴露跨组污染')
  s.add(exp);s.flush()
 stamp=(datetime.fromisoformat(exp.starts_at)+timedelta(hours=12)).isoformat()
 # (user_key, 组, 事件) ：C1 与 C1b 是同人换标识（同组A，去重）；C3/C3b 跨 A/B（污染）
 rows=[('LJ-C1','A','exposure'),('LJ-C1','A','activation'),('LJ-C1b','A','exposure'),
  ('LJ-C2','A','exposure'),('LJ-C3','A','exposure'),
  ('LJ-C4','B','exposure'),('LJ-C4','B','activation'),('LJ-C5','B','exposure'),
  ('LJ-C3b','B','exposure')]
 for key,group,kind in rows:
  if not s.query(Event).filter_by(experiment_id=exp.id,user_key=key,kind=kind).first():
   s.add(Event(experiment_id=exp.id,user_key=key,group=group,kind=kind,occurred_at=stamp))
 s.flush()
 def make_job(note,pairs):
  job=s.query(AliasJob).filter_by(note=note).first()
  if job:return job
  job=AliasJob(state='queued',source='demo-import',note=note,created_by='analyst@demo.local',
   created=datetime.now(timezone.utc).isoformat())
  s.add(job);s.flush()
  for a,b in pairs:s.add(AliasJobItem(alias_job_id=job.id,a_key=a,b_key=b,state='pending'))
  s.commit()
  process_alias_job(s,job.id)  # 直接处理，保证演示环境开箱即见归并结果
  return job
 make_job('演示：登录后换标识归并（同组去重）',[('LJ-C1','LJ-C1b')])
 make_job('演示：跨组身份污染（阻断发布）',[('LJ-C3','LJ-C3b')])
if __name__=='__main__':seed()
