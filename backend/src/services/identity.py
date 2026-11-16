"""身份别名归并的数据库服务：任务处理、版本控制、并发锁、快照与追查。"""
from datetime import datetime,timezone
from sqlalchemy import text
from src.models.entities import (Identity,IdentityMember,IdentityMerge,IdentityVersion,
 AliasJob,AliasJobItem,AliasLink,Event)
from src.services.identity_core import canonical_map,resolve_counts

MERGE_LOCK='trial_identity_merge'
LOCK_TIMEOUT=10

def now():return datetime.now(timezone.utc).isoformat()

def _dialect(s):return s.bind.dialect.name if s.bind else 'sqlite'

def acquire_lock(s):
 """串行化归并任务，避免并发任务交叉改身份关系。SQLite 写锁天然串行，跳过。"""
 if _dialect(s)=='mysql':
  ok=s.execute(text('SELECT GET_LOCK(:n,:t)'),{'n':MERGE_LOCK,'t':LOCK_TIMEOUT}).scalar()
  if not int(ok or 0):raise RuntimeError('其他归并任务正在执行，请稍后重试')

def release_lock(s):
 if _dialect(s)=='mysql':
  s.execute(text('SELECT RELEASE_LOCK(:n)'),{'n':MERGE_LOCK})

def current_version(s):
 row=s.query(IdentityVersion).filter_by(id=1).first()
 return row.version if row else 0

def ensure_version_row(s):
 if not s.query(IdentityVersion).filter_by(id=1).first():s.add(IdentityVersion(id=1,version=0))

def get_members(s):
 """当前 user_key -> canonical identity_id 全量映射。"""
 return {m.user_key:m.identity_id for m in s.query(IdentityMember).all()}

def _root(identity_id,roots):
 seen=set()
 while identity_id in roots and roots[identity_id] not in (identity_id,None) and identity_id not in seen:
  seen.add(identity_id);identity_id=roots[identity_id]
 return identity_id

def identity_root_map(s):
 return {i.id:(i.parent_id or i.id) for i in s.query(Identity).all()}

def root_of(s,identity_id):
 return _root(identity_id,identity_root_map(s))

def _create_identity(s):
 row=Identity(code='ID-'+now().replace('-','').replace(':','').replace('.','')+'-'+str(datetime.now(timezone.utc).microsecond%1000))
 s.add(row);s.flush()
 row.code=f'ID-{row.id:06d}';return row

def _apply_pair(s,a,b,job_id):
 """在当前事务内应用一条别名关联，返回 (state,message,merge_or_None)。"""
 if not a or not b:return 'failed','关联两侧标识均不能为空',None
 if a==b:return 'skipped','两侧标识相同，无需归并',None
 a,b=sorted((a,b))  # 归一化方向，(x,y)/(y,x) 视为同一关联
 existing=s.query(AliasLink).filter_by(a_key=a,b_key=b).first()
 if existing:return 'skipped','该关联已导入过（幂等跳过），不重复改变人数',None
 ma=s.query(IdentityMember).filter_by(user_key=a).first()
 mb=s.query(IdentityMember).filter_by(user_key=b).first()
 merge=None
 if ma is None and mb is None:
  ident=_create_identity(s)
  s.add(IdentityMember(identity_id=ident.id,user_key=a,source_job_id=job_id))
  s.add(IdentityMember(identity_id=ident.id,user_key=b,source_job_id=job_id))
 elif ma is None:
  s.add(IdentityMember(identity_id=root_of(s,mb.identity_id),user_key=a,source_job_id=job_id))
 elif mb is None:
  s.add(IdentityMember(identity_id=root_of(s,ma.identity_id),user_key=b,source_job_id=job_id))
 else:
  ra,rb=root_of(s,ma.identity_id),root_of(s,mb.identity_id)
  if ra==rb:return 'skipped','两个标识已属同一身份，跳过重试',None
  keep,drop=(ra,rb) if ra<=rb else (rb,ra)
  dropped=s.get(Identity,drop);dropped.parent_id=keep
  for m in s.query(IdentityMember).filter_by(identity_id=drop).all():m.identity_id=keep
  merge=(ra,rb,keep)
 s.add(AliasLink(alias_job_id=job_id,a_key=a,b_key=b,state='done',created=now()))
 return 'done','已归并',merge

def process_alias_job(s,job_id):
 """处理一个别名任务。单事务；中断由 worker 启动恢复重新入队，重试幂等。"""
 job=s.get(AliasJob,job_id)
 if not job:raise ValueError('关联任务不存在')
 if job.state=='done':return job  # 幂等：完成任务重复执行不改变人数
 acquire_lock(s)
 try:
  ensure_version_row(s)
  version_before=current_version(s)
  job.identity_version_before=version_before
  job.state='running';s.flush()
  items=s.query(AliasJobItem).filter_by(alias_job_id=job_id).order_by(AliasJobItem.id).all()
  applied_merges=0;processed=0;failed=0;applied_links=0;pending_merges=[]
  for item in items:
   if item.state in ('done','skipped'):continue  # 恢复时跳过已完成项
   try:
    state,message,merge=_apply_pair(s,item.a_key.strip(),item.b_key.strip(),job_id)
    item.state='done' if state=='done' else 'skipped';item.message=message
    if state=='done':applied_links+=1
    if merge:pending_merges.append(merge)
   except Exception as e:  # 单条失败不拖垮整批，留痕可查
    item.state='failed';item.message=str(e)[:300];failed+=1
   processed+=1
  # 版本语义：一个任务作为一次原子批次，生效任意新关联即占用一个新版本；
  # 纯重试/全部跳过（applied_links=0）不动版本，保证同一关联重试不重复改变人数。
  if pending_merges:
   new_version=version_before+1
   for left,right,keep in pending_merges:
    s.add(IdentityMerge(left_id=left,right_id=right,merged_id=keep,alias_job_id=job_id,
     identity_version=new_version,created=now()))
    applied_merges+=1
  if applied_links and not pending_merges:
   new_version=version_before+1
  if not applied_links:
   new_version=version_before
  if new_version!=version_before:
   s.query(IdentityVersion).filter_by(id=1).update({'version':new_version})
  job.state='done';job.error='';job.finished=now()
  job.processed_items=processed;job.failed_items=failed
  job.applied_merges=applied_merges
  job.identity_version_after=new_version
  s.commit()
  return job
 except Exception as e:
  s.rollback();job=s.get(AliasJob,job_id)
  if job:
   job.state='failed';job.error=str(e)[:1000];s.commit()
  raise
 finally:
  try:release_lock(s)
  except Exception:s.rollback()

def build_identity_snapshot(s,events):
 """裁决冻结点：身份版本 + user_key->canonical 映射 + 全部人数口径。"""
 members=get_members(s)
 counts=resolve_counts(events,members)
 canon=counts.pop('canonical')
 return {'identity_version':current_version(s),'identity_map':canon,'counts':counts}

def identity_report(s,experiment_id):
 """页面口径：原始人数与去重人数、污染身份明细、当前版本。"""
 events=[{'user_key':e.user_key,'group':e.group,'kind':e.kind} for e in
  s.query(Event).filter_by(experiment_id=experiment_id).all()]
 members=get_members(s)
 counts=resolve_counts(events,members)
 counts.pop('canonical',None)
 counts['identity_version']=current_version(s)
 return counts

def identity_detail(s,user_key):
 """追查一个标识的归并链：当前身份、全部别名、归并历史、原始关联依据。"""
 member=s.query(IdentityMember).filter_by(user_key=user_key).first()
 if not member:
  return {'query':user_key,'identity':None,'aliases':[user_key],
   'note':'该标识未参与任何别名关联，自身即为独立身份','merges':[],'links':[]}
 root=root_of(s,member.identity_id)
 roots=identity_root_map(s)
 # 一次性解析全部根，避免逐成员重查
 aliases=sorted(m.user_key for m in s.query(IdentityMember).all()
  if _root(m.identity_id,roots)==root)
 # 归并链：收集并入同一根的全部历史身份节点
 chain_ids={i for i,r in roots.items() if r==root}
 merges=[{'left_id':m.left_id,'right_id':m.right_id,'merged_id':m.merged_id,
   'identity_version':m.identity_version,'alias_job_id':m.alias_job_id,'created':m.created}
  for m in s.query(IdentityMerge).order_by(IdentityMerge.id).all()
  if m.left_id in chain_ids or m.right_id in chain_ids or m.merged_id in chain_ids]
 alias_set=set(aliases)
 links=[{'a_key':l.a_key,'b_key':l.b_key,'state':l.state,'alias_job_id':l.alias_job_id,
   'created':l.created,'message':l.message} for l in s.query(AliasLink).order_by(AliasLink.id).all()
  if l.a_key in alias_set or l.b_key in alias_set]
 return {'query':user_key,'identity':f'ID-{root:06d}','aliases':aliases,
  'identity_version':current_version(s),'merges':merges,'links':links}
