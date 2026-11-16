"""真实服务层（identity/analysis/controller）在 sqlite 内存库上的端到端测试。

通过 _vendor 下的极简垫片替代 sqlalchemy/scipy/fastapi，业务代码全部走真实实现。
"""
import os,sys,sysconfig,types,unittest
import sqlite3
from datetime import datetime,timedelta,timezone
BASE=os.path.join(os.path.dirname(__file__),'..','backend')
VENDOR=os.path.join(os.path.dirname(__file__),'_vendor')
sys.path.insert(0,os.path.abspath(VENDOR))
sys.path.insert(0,os.path.abspath(BASE))  # backend 目录（含 src 包）
# 注入第三方垫片，须在 import src.* 之前
import fakesa
sa=types.ModuleType('sqlalchemy')
for _k,_v in vars(fakesa).items():
 if not _k.startswith('__'):setattr(sa,_k,_v)
orm=types.ModuleType('sqlalchemy.orm');orm.sessionmaker=fakesa.sessionmaker;orm.declarative_base=fakesa.declarative_base
exc=types.ModuleType('sqlalchemy.exc');exc.IntegrityError=fakesa.IntegrityError
sa.orm=orm;sa.exc=exc
sys.modules['sqlalchemy']=sa;sys.modules['sqlalchemy.orm']=orm;sys.modules['sqlalchemy.exc']=exc
import fakescipy.stats as fakestats
sys.modules['scipy']=types.ModuleType('scipy');sys.modules['scipy.stats']=fakestats
import fakefastapi_pkg as fakefastapi
import fakefastapi_pkg.security as fakefastapi_security
sys.modules['fastapi']=fakefastapi
sys.modules['fastapi.security']=fakefastapi_security
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:///:memory:')
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('REDIS_URL','redis://unused/0')
from src.config.database import Base,engine,Session
from src.models import entities as E
from src.services.identity import (process_alias_job,identity_report,identity_detail,
 get_members,current_version,ensure_version_row,root_of)
from src.services.analysis import calculate
from src.services import identity as idsvc
from src.controllers.business import validate_event,snapshot
from src.models.entities import Experiment,Event,AliasJob,AliasJobItem,Decision


class In:
 def __init__(self,**kw):self.__dict__.update(kw)


def make_exp(s,code='EXP-1',ended=True):
 now=datetime.now(timezone.utc)
 exp=Experiment(code=code,name='测试实验',
  starts_at=(now-timedelta(days=2)).isoformat(),
  ends_at=(now+timedelta(days=(-1 if ended else 3))).isoformat(),
  a_ratio=.5,hypothesis='用于集成测试的预先假设不少于五字')
 s.add(exp);s.commit();return exp


def add_event(s,exp,key,group,kind,hours=12):
 stamp=(datetime.fromisoformat(exp.starts_at)+timedelta(hours=hours))
 e=Event(experiment_id=exp.id,user_key=key,group=group,kind=kind,occurred_at=stamp.isoformat())
 s.add(e);s.commit();return e


def make_job(s,pairs,note='集成测试任务'):
 job=AliasJob(state='queued',source='manual',note=note,created_by='analyst@demo.local',
  created=datetime.now(timezone.utc).isoformat())
 s.add(job);s.flush()
 for a,b in pairs:s.add(AliasJobItem(alias_job_id=job.id,a_key=a,b_key=b,state='pending'))
 s.commit();return job


class IdentityIntegration(unittest.TestCase):
 def setUp(self):
  # 每个用例清空重建内存 schema，并清掉各会话的对象身份缓存，保证隔离
  Base.metadata.drop_all(engine)
  for sess in fakesa.Session._all:sess._identity.clear();sess._pending.clear();sess._dirty.clear()
  Base.metadata.create_all(engine)
  with Session() as s:ensure_version_row(s);s.commit()

 def test_alias_job_merges_same_group_and_counts(self):
  with Session() as s:
   exp=make_exp(s)
   add_event(s,exp,'C1','A','exposure');add_event(s,exp,'C1b','A','exposure')
   add_event(s,exp,'C2','A','exposure');add_event(s,exp,'C4','B','exposure')
   job=make_job(s,[('C1','C1b')]);process_alias_job(s,job.id)
   r=identity_report(s,exp.id)
   self.assertEqual(r['raw_exposed_a'],3)       # 原始3个标识
   self.assertEqual(r['n_a'],2)                 # 去重后 C1同人 + C2
   self.assertEqual(r['polluted_count'],0)
   self.assertEqual(r['identity_version'],1)    # 生效关联 => 新版本
   self.assertEqual(s.get(AliasJob,job.id).state,'done')

 def test_retry_same_job_is_idempotent(self):
  with Session() as s:
   exp=make_exp(s)
   add_event(s,exp,'C1','A','exposure');add_event(s,exp,'C1b','A','exposure')
   job=make_job(s,[('C1','C1b')]);process_alias_job(s,job.id)
   v1=current_version(s)
   # 再次处理同一任务（模拟重试/worker 重复投递）
   process_alias_job(s,job.id)
   self.assertEqual(current_version(s),v1)     # 版本不变
   self.assertEqual(s.get(AliasJob,job.id).applied_merges,0)
   # 再建一个内容相同的任务：关联唯一约束语义 -> 全部跳过，人数不变
   job2=make_job(s,[('C1','C1b')],note='重复关联')
   process_alias_job(s,job2.id)
   self.assertEqual(current_version(s),v1)
   r=identity_report(s,exp.id);self.assertEqual(r['n_a'],1)

 def test_cross_group_pollution_blocks_publish(self):
  with Session() as s:
   exp=make_exp(s)
   # 污染对 C3/C3b 跨 A/B；另补足每组干净身份到 >=2，使 z 检验可计算
   rows=[('C3','A'),('C3b','B'),('C1','A'),('C2','A'),('C4','B'),('C5','B')]
   for k,g in rows:add_event(s,exp,k,g,'exposure')
   job=make_job(s,[('C3','C3b')]);process_alias_job(s,job.id)
   r=identity_report(s,exp.id)
   self.assertEqual(r['polluted_count'],1)
   self.assertEqual(r['polluted'][0]['groups'],['A','B'])
   self.assertEqual(r['n_a'],2);self.assertEqual(r['n_b'],2)   # 污染身份不进任一组
   # 冻结裁决 -> 计算结果带污染阻断
   snap=snapshot(s,exp);result=calculate(snap)
   self.assertEqual(result['polluted_count'],1)
   self.assertFalse(result['release_eligible'])
   self.assertTrue(any('污染' in x for x in result['block_reasons']))

 def test_frozen_decision_unchanged_by_later_merge(self):
  with Session() as s:
   exp=make_exp(s)
   add_event(s,exp,'a','A','exposure');add_event(s,exp,'b','A','exposure')
   add_event(s,exp,'c','B','exposure');add_event(s,exp,'d','B','exposure')
   before=snapshot(s,exp)  # 归并前冻结：a、b 是两人
   self.assertEqual(before['identity']['counts']['n_a'],2)
   job=make_job(s,[('a','b')]);process_alias_job(s,job.id)
   after=snapshot(s,exp)   # 归并后：a、b 一人
   self.assertEqual(after['identity']['counts']['n_a'],1)
   # 旧快照不受影响，重算旧裁决结果不变
   old_result=calculate(before);self.assertEqual(old_result['n_a'],2)
   self.assertEqual(old_result['identity_version'],before['identity']['identity_version'])
   self.assertNotEqual(before['identity']['identity_version'],after['identity']['identity_version'])

 def test_new_event_ingest_blocked_for_cross_group_alias(self):
  with Session() as s:
   exp=make_exp(s)
   add_event(s,exp,'C3','A','exposure')
   job=make_job(s,[('C3','C3b')]);process_alias_job(s,job.id)
   # 同身份另一标识想进 B 组曝光 -> 409 阻断
   with self.assertRaises(Exception) as cm:
    validate_event(s,In(experiment_id=exp.id,user_key='C3b',group='B',
     kind='exposure',occurred_at=datetime.fromisoformat(exp.starts_at)+timedelta(hours=13)))
   self.assertEqual(cm.exception.status_code,409);self.assertIn('污染',cm.exception.detail)
   # 同身份在 A 组已有曝光：别名再报同组曝光属重复，仍 409
   with self.assertRaises(Exception) as cm2:
    validate_event(s,In(experiment_id=exp.id,user_key='C3b',group='A',
     kind='exposure',occurred_at=datetime.fromisoformat(exp.starts_at)+timedelta(hours=13)))
   self.assertEqual(cm2.exception.status_code,409)
   # 同组补采激活（落在别名 key 上）校验放行，落库后仍归同一人
   base=datetime.fromisoformat(exp.starts_at)
   stamp=validate_event(s,In(experiment_id=exp.id,user_key='C3b',group='A',
    kind='activation',occurred_at=base+timedelta(hours=14)))
   s.add(Event(experiment_id=exp.id,user_key='C3b',group='A',kind='activation',occurred_at=stamp));s.commit()
   self.assertEqual(identity_report(s,exp.id)['activated_a'],1)

 def test_backfill_old_alias_still_same_person(self):
  with Session() as s:
   exp=make_exp(s)
   job=make_job(s,[('a','b')]);process_alias_job(s,job.id)  # 先有关联
   # 之后补采两个标识的事件（含别名上的激活）
   add_event(s,exp,'a','A','exposure')
   add_event(s,exp,'b','A','exposure')
   add_event(s,exp,'b','A','activation')
   r=identity_report(s,exp.id)
   self.assertEqual(r['n_a'],1);self.assertEqual(r['activated_a'],1)

 def test_identity_lookup_chain_and_evidence(self):
  with Session() as s:
   make_exp(s)
   j1=make_job(s,[('x','y')],note='链1');process_alias_job(s,j1.id)   # 建立身份1{x,y}
   j2=make_job(s,[('z','w')],note='链2');process_alias_job(s,j2.id)   # 建立身份2{z,w}
   j3=make_job(s,[('y','z')],note='链3');process_alias_job(s,j3.id)   # 两个既有身份归并
   detail=identity_detail(s,'z')
   self.assertEqual(set(detail['aliases']),{'x','y','z','w'})
   self.assertEqual(len(detail['merges']),1)  # 第三次产生 identity 间归并
   self.assertEqual(detail['merges'][0]['identity_version'],3)
   self.assertTrue(any(l['a_key']=='x' and l['b_key']=='y' for l in detail['links']))
   # 未登记标识
   lone=identity_detail(s,'nobody');self.assertEqual(lone['identity'],None)

 def test_interrupted_job_recovers_and_remains_idempotent(self):
  with Session() as s:
   exp=make_exp(s)
   add_event(s,exp,'p','A','exposure');add_event(s,exp,'q','A','exposure')
   job=make_job(s,[('p','q')])
   # 模拟 worker 处理中崩溃：状态停在 running
   job.state='running';s.commit()
   # 恢复逻辑等价于重新入队处理
   job.state='queued';s.commit();process_alias_job(s,job.id)
   self.assertEqual(s.get(AliasJob,job.id).state,'done')
   self.assertEqual(identity_report(s,exp.id)['n_a'],1)
   # 再次恢复处理已完成任务，不重复改变
   v=current_version(s);process_alias_job(s,job.id);self.assertEqual(current_version(s),v)

 def test_transitive_multi_pair_single_job(self):
  with Session() as s:
   exp=make_exp(s)
   for k in ('a','b','c'):add_event(s,exp,k,'A','exposure')
   job=make_job(s,[('a','b'),('b','c')]);process_alias_job(s,job.id)
   r=identity_report(s,exp.id)
   self.assertEqual(r['raw_exposed_a'],3);self.assertEqual(r['n_a'],1)
   detail=identity_detail(s,'a');self.assertEqual(len(detail['aliases']),3)


if __name__=='__main__':
 unittest.main(verbosity=2)
