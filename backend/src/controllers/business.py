from fastapi import HTTPException
from datetime import datetime,timezone
from src.models.entities import Experiment,Event,Decision
from src.services.business import dump,utc
from src.services.analysis import calculate
from src.services.identity import get_members,build_identity_snapshot
from src.services.identity_core import canonical_map
def experiment(s,i):
 r=s.get(Experiment,i)
 if not r:raise HTTPException(404,'实验不存在')
 return r
def decision(s,i):
 r=s.get(Decision,i)
 if not r:raise HTTPException(404,'裁决记录不存在')
 return r
def _canonical_events(s,exp):
 rows=s.query(Event).filter_by(experiment_id=exp.id).all()
 members=get_members(s)
 events=[{'user_key':e.user_key,'group':e.group,'kind':e.kind,'occurred_at':e.occurred_at} for e in rows]
 canon=canonical_map(events,members)
 return rows,events,members,canon
def validate_event(s,data):
 exp=experiment(s,data.experiment_id);stamp=utc(data.occurred_at)
 if not (exp.starts_at<=stamp<=exp.ends_at):raise HTTPException(422,'事件时间必须落在实验预定区间内')
 if data.occurred_at>datetime.now(timezone.utc):raise HTTPException(422,'不能录入未来事件')
 rows,events,members,canon=_canonical_events(s,exp)
 new_c=canon.get(data.user_key,f'key:{data.user_key}')
 same_identity=[e for e in events if canon.get(e['user_key'],f"key:{e['user_key']}")==new_c]
 # 身份级跨组污染：同一 canonical 身份已在别组曝光 -> 阻断，不能任选一组
 groups={e['group'] for e in same_identity if e['kind']=='exposure'}
 if groups and data.group not in groups:
  raise HTTPException(409,f'同一身份已在 {"、".join(sorted(groups))} 组产生曝光（别名归并后同人），跨组会污染分流，已阻断')
 if any(e['kind']==data.kind for e in same_identity):
  raise HTTPException(409,'重复事件：同一身份/实验/事件类型只记一次（含别名归并后的同一人）')
 if data.kind=='activation':
  exposure=next((e for e in same_identity if e['kind']=='exposure'),None)
  if not exposure:raise HTTPException(422,'先录入该身份曝光，再录入激活')
  if stamp<exposure['occurred_at']:raise HTTPException(422,'激活时间不能早于曝光')
 return stamp
def snapshot(s,exp):
 rows=s.query(Event).filter_by(experiment_id=exp.id).order_by(Event.id).all()
 event_dicts=[dump(e) for e in rows]
 frozen=build_identity_snapshot(s,[{'user_key':e.user_key,'group':e.group,'kind':e.kind} for e in rows])
 return {'experiment':dump(exp),'events':event_dicts,'identity':frozen}
def publish(s,item,action,user):
 if item.state!='done':raise HTTPException(409,'计算完成后才可发布')
 if item.published_at:raise HTTPException(409,'该裁决已发布，记录不可覆盖')
 if len(item.rationale)<10:raise HTTPException(409,'请先补充至少10字裁决理由')
 # 只用冻结快照重算，当前身份关系/新事件不会混入旧裁决
 result=calculate(item.snapshot)
 if not result['release_eligible']:raise HTTPException(409,'；'.join(result['block_reasons']))
 if action=='publish_b' and not result['significant_positive']:raise HTTPException(409,'上线B需B−A为正且双侧p<0.05')
 item.action=action;item.published_by=user.email;item.published_at=datetime.now(timezone.utc).isoformat();s.commit();return item
