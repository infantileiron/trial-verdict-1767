import os,json
from datetime import timezone
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import (User,Experiment,Event,Decision,Audit,
 AliasJob,AliasJobItem,AliasLink)
from src.schemas.business import (Login,ExperimentInput,EventInput,RunInput,RationaleInput,
 PublishInput,AliasJobInput)
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump,utc
from src.services.identity import (process_alias_job,identity_report,identity_detail,
 get_members,current_version)
from src.services.identity_core import canonical_map
from src.controllers.business import experiment,decision,validate_event,snapshot,publish
router=APIRouter()
ALIAS_QUEUE='trial:alias_jobs'
def _redis():return redis.Redis.from_url(os.environ['REDIS_URL'])
def _job_detail(s,r):
 d=dump(r);d['items']=[dump(i) for i in s.query(AliasJobItem).filter_by(alias_job_id=r.id).order_by(AliasJobItem.id).all()]
 return d
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/experiments')
def experiments(u=Depends(current),s=Depends(db)):
 out=[]
 for e in s.query(Experiment).order_by(Experiment.id.desc()).all():
  d={**dump(e),'exposures':s.query(Event).filter_by(experiment_id=e.id,kind='exposure').count()}
  d['identity']=identity_report(s,e.id)
  out.append(d)
 return out
@router.post('/experiments')
def create_experiment(data:ExperimentInput,u=Depends(editor),s=Depends(db)):
 d=data.model_dump();d['starts_at']=utc(data.starts_at);d['ends_at']=utc(data.ends_at);r=Experiment(**d);s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'实验编号已存在')
 audit(s,u,'建立实验 '+r.code);return dump(r)
@router.put('/experiments/{i}')
def edit_experiment(i:int,data:ExperimentInput,u=Depends(editor),s=Depends(db)):
 r=experiment(s,i)
 if s.query(Event).filter_by(experiment_id=i).first():raise HTTPException(409,'已有事件，禁止事后修改实验定义；请建立新实验')
 d=data.model_dump();d['starts_at']=utc(data.starts_at);d['ends_at']=utc(data.ends_at)
 for k,v in d.items():setattr(r,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'实验编号已存在')
 audit(s,u,'修订实验 '+str(i));return dump(r)
@router.get('/events')
def events(experiment_id:int|None=None,u=Depends(current),s=Depends(db)):
 q=s.query(Event)
 if experiment_id:q=q.filter_by(experiment_id=experiment_id)
 rows=q.order_by(Event.id.desc()).all()
 members=get_members(s)
 canon=canonical_map([{'user_key':e.user_key,'group':e.group,'kind':e.kind} for e in rows],members)
 return [{**dump(e),'identity':canon.get(e.user_key,f'key:{e.user_key}')} for e in rows]
@router.post('/events')
def create_event(data:EventInput,u=Depends(editor),s=Depends(db)):
 stamp=validate_event(s,data);d=data.model_dump();d['occurred_at']=stamp;r=Event(**d);s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'该用户事件已存在')
 audit(s,u,'采集事件 '+str(r.id));return dump(r)
@router.get('/decisions')
def decisions(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Decision).order_by(Decision.id.desc())]
@router.post('/decisions')
def run(data:RunInput,u=Depends(editor),s=Depends(db)):
 exp=experiment(s,data.experiment_id)
 if s.query(Decision).filter(Decision.state.in_(['queued','running'])).count()>=10:raise HTTPException(429,'队列已满，请等待任务完成')
 # 冻结当前身份关系版本与人数；后续归并/补采不改变本裁决
 r=Decision(experiment_id=exp.id,snapshot=snapshot(s,exp));s.add(r);s.commit()
 try:_redis().rpush('trial:decisions',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，恢复后重新提交';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交实验裁决 '+str(r.id)+' 身份版本v'+str(r.snapshot['identity']['identity_version']));return dump(r)
@router.get('/decisions/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(decision(s,i))
@router.put('/decisions/{i}/rationale')
def rationale(i:int,data:RationaleInput,u=Depends(editor),s=Depends(db)):
 r=decision(s,i)
 if r.published_at:raise HTTPException(409,'已发布裁决不可覆盖，请重新创建裁决')
 if r.state!='done':raise HTTPException(409,'计算完成后再填写裁决理由')
 r.rationale=data.rationale;s.commit();audit(s,u,'保存裁决理由 '+str(i));return dump(r)
@router.post('/decisions/{i}/publish')
def release(i:int,data:PublishInput,u=Depends(admin),s=Depends(db)):
 r=publish(s,decision(s,i),data.action,u);audit(s,u,'发布裁决 '+str(i)+' '+data.action);return dump(r)
@router.get('/decisions/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=decision(s,i)
 if r.state!='done':raise HTTPException(409,'尚无成功结果')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="trial-verdict-{i}.json"'})
# ===== 别名关联归并 =====
@router.get('/identity/jobs')
def alias_jobs(u=Depends(current),s=Depends(db)):
 return [_job_detail(s,r) for r in s.query(AliasJob).order_by(AliasJob.id.desc()).all()]
@router.post('/identity/jobs')
def create_alias_job(data:AliasJobInput,u=Depends(editor),s=Depends(db)):
 from datetime import datetime,timezone
 r=AliasJob(state='queued',source=data.source,note=data.note,created_by=u.email,
  created=datetime.now(timezone.utc).isoformat())
 s.add(r);s.flush()
 for p in data.pairs:
  s.add(AliasJobItem(alias_job_id=r.id,a_key=p.a_key.strip(),b_key=p.b_key.strip(),state='pending'))
 s.commit()
 try:_redis().rpush(ALIAS_QUEUE,r.id)
 except redis.RedisError:
  # 队列不可用时同步处理，保证关联不丢；失败留状态可重试
  try:process_alias_job(s,r.id)
  except Exception:pass
 audit(s,u,'导入别名关联任务 '+str(r.id)+' 共'+str(len(data.pairs))+'条')
 return _job_detail(s,r)
@router.post('/identity/jobs/{i}/retry')
def retry_alias_job(i:int,u=Depends(editor),s=Depends(db)):
 r=s.get(AliasJob,i)
 if not r:raise HTTPException(404,'关联任务不存在')
 if r.state=='done':raise HTTPException(409,'任务已完成，重试不会重复改变人数')
 # failed/running(中断) 重置为 queued 重新入队；已 done/skipped 的条目在处理时自动跳过
 r.state='queued';r.error='';s.commit()
 try:_redis().rpush(ALIAS_QUEUE,i)
 except redis.RedisError:
  try:process_alias_job(s,i)
  except Exception:pass
 audit(s,u,'重试别名关联任务 '+str(i));return _job_detail(s,r)
@router.get('/identity/jobs/{i}')
def alias_job(i:int,u=Depends(current),s=Depends(db)):
 r=s.get(AliasJob,i)
 if not r:raise HTTPException(404,'关联任务不存在')
 return _job_detail(s,r)
@router.get('/identity/report')
def report(experiment_id:int,u=Depends(current),s=Depends(db)):
 experiment(s,experiment_id);return identity_report(s,experiment_id)
@router.get('/identity/lookup')
def lookup(user_key:str,u=Depends(current),s=Depends(db)):
 if not user_key.strip():raise HTTPException(422,'请提供要追查的标识')
 return identity_detail(s,user_key.strip())
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
