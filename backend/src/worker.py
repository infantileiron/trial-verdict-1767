import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session,Base,engine
from src.models import entities
from src.models.entities import Decision,AliasJob
from src.services.analysis import calculate
from src.services.identity import process_alias_job,ensure_version_row
r=redis.Redis.from_url(os.environ['REDIS_URL'])
def recover():
 """启动回收：queued/running 的裁决与别名任务重新入队，中断后可恢复。"""
 Base.metadata.create_all(engine)
 with Session() as recovery:
  ensure_version_row(recovery);recovery.commit()
  for pending in recovery.query(Decision).filter(Decision.state.in_(['queued','running'])).all():
   pending.state='queued';r.rpush('trial:decisions',pending.id)
  for pending in recovery.query(AliasJob).filter(AliasJob.state.in_(['queued','running'])).all():
   pending.state='queued';r.rpush('trial:alias_jobs',pending.id)
  recovery.commit()
def handle_decision(item_id):
 with Session() as s:
  row=s.get(Decision,int(item_id))
  if not row or row.state!='queued':return
  row.state='running';s.commit()
  try:
   row.result=calculate(row.snapshot);row.state='done'
   Path('/artifacts/trial-verdict-'+str(row.id)+'.json').write_text(json.dumps(row.result,ensure_ascii=False))
  except Exception as e:row.state='failed';row.error=str(e)
  s.commit()
def handle_alias(item_id):
 with Session() as s:
  row=s.get(AliasJob,int(item_id))
  if not row or row.state=='done':return  # 幂等：完成任务不重复处理
  if row.state not in ('queued','running','failed'):return
  try:process_alias_job(s,int(item_id))
  except Exception:logging.exception('alias job failed %s',item_id)
def main():
 recover()
 while True:
  Path('/tmp/heartbeat').touch()
  try:
   # 双队列轮询：别名归并与裁决计算互不阻塞
   item=r.blpop(['trial:alias_jobs','trial:decisions'],timeout=3)
   if not item:continue
   queue,item_id=item[0].decode() if isinstance(item[0],bytes) else item[0],item[1]
   if queue=='trial:alias_jobs':handle_alias(item_id)
   else:handle_decision(item_id)
  except Exception:logging.exception('worker');time.sleep(2)
if __name__=='__main__':main()
