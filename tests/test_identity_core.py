"""身份归并核心口径单测：并查集、去重、污染、冻结版本、幂等重试。

仅依赖 Python 标准库，直接运行：
  python -m unittest test_identity_core -v
"""
import os,sys,unittest
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','backend'))
# identity_core 本身不依赖第三方库，直接按文件路径加载，避免触发 src 包依赖
import importlib.util
_spec=importlib.util.spec_from_file_location('identity_core',
 os.path.join(os.path.dirname(__file__),'..','backend','src','services','identity_core.py'))
identity_core=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(identity_core)
resolve_counts=identity_core.resolve_counts
merge_plan=identity_core.merge_plan
canonical_map=identity_core.canonical_map
identity_conflict=identity_core.identity_conflict


def ev(key,group,kind):return {'user_key':key,'group':group,'kind':kind}


class TestResolve(unittest.TestCase):
 def test_raw_vs_dedup_same_group_alias(self):
  # C1 与 C1b 同人，均在 A 组曝光：原始2，去重1
  events=[ev('C1','A','exposure'),ev('C1b','A','exposure'),ev('C2','A','exposure'),
          ev('C4','B','exposure')]
  members={'C1':1,'C1b':1}
  c=resolve_counts(events,members)
  self.assertEqual(c['raw_exposed_a'],3)  # C1/C1b/C2 三个原始标识
  self.assertEqual(c['n_a'],2)  # C1/C1b 合成1人 + C2 = 2 干净身份
  self.assertEqual(c['n_b'],1)
  self.assertEqual(c['dedup_exposed_total'],3)
  self.assertEqual(c['polluted_count'],0)

 def test_cross_group_pollution_listed_and_excluded(self):
  events=[ev('C3','A','exposure'),ev('C3b','B','exposure'),
          ev('C1','A','exposure'),ev('C4','B','exposure')]
  members={'C3':7,'C3b':7}
  c=resolve_counts(events,members)
  self.assertEqual(c['polluted_count'],1)
  self.assertEqual(c['polluted'][0]['user_keys'],['C3','C3b'])
  self.assertEqual(c['polluted'][0]['groups'],['A','B'])
  # 污染身份不进入任一组干净人数，也不被悄悄计入
  self.assertEqual(c['n_a'],1);self.assertEqual(c['n_b'],1)
  self.assertEqual(c['raw_exposed_total'],4)

 def test_activation_uses_identity_and_pollution_excluded(self):
  # 同一人的激活落在别名 key 上，仍应归并计入
  events=[ev('C1','A','exposure'),ev('C1b','A','exposure'),
          ev('C1b','A','activation'),ev('C2','A','exposure')]
  members={'C1':1,'C1b':1}
  c=resolve_counts(events,members)
  self.assertEqual(c['activated_a'],1)
  self.assertEqual(c['n_a'],2)
  # 污染身份即使有激活也不计入
  events2=events+[ev('C3','A','exposure'),ev('C3b','B','exposure'),ev('C3b','B','activation')]
  members2=dict(members);members2.update({'C3':9,'C3b':9})
  c2=resolve_counts(events2,members2)
  self.assertEqual(c2['polluted_count'],1);self.assertEqual(c2['activated_b'],0)

 def test_unknown_key_is_its_own_identity(self):
  events=[ev('X','A','exposure'),ev('Y','B','exposure')]
  c=resolve_counts(events,{})
  self.assertEqual(c['n_a'],1);self.assertEqual(c['n_b'],1);self.assertEqual(c['polluted_count'],0)


class TestMergePlan(unittest.TestCase):
 def test_transitive_chain(self):
  # a-b, b-c 传递归并为同一人
  members,merges,_=merge_plan({},[('a','b'),('b','c')])
  self.assertEqual(len(set(members.values())),1)

 def test_retry_idempotent_no_new_merge(self):
  members,merges1,_=merge_plan({},[('a','b')])
  self.assertEqual(len(members),2)
  members2,merges2,skipped=merge_plan(members,[('a','b')])  # 重试同一关联
  self.assertEqual(merges2,[])
  self.assertEqual(len(skipped),1)
  self.assertEqual(members2,members)  # 人数映射不变

 def test_pair_direction_normalized(self):
  members,_,skipped=merge_plan({'a':1,'b':1},[('b','a')])
  self.assertEqual(len(skipped),1)  # 反向写法视为同一关联，幂等跳过

 def test_merge_two_existing_identities(self):
  members,merges,_=merge_plan({'a':1,'b':1,'c':2,'d':2},[('a','c')])
  self.assertEqual(len(set(members.values())),1)
  self.assertEqual(len(merges),1)

 def test_attach_orphan_key(self):
  members,merges,_=merge_plan({'a':1},[('a','new')])
  self.assertEqual(members['new'],1);self.assertEqual(merges,[])


class TestConflict(unittest.TestCase):
 def test_block_cross_group_ingest(self):
  events=[ev('C3','A','exposure')]
  members={'C3':7,'C3b':7}
  msg=identity_conflict(events,members,'C3b','B')
  self.assertIsNotNone(msg);self.assertIn('污染',msg)

 def test_allow_same_group_alias_event(self):
  events=[ev('C1','A','exposure')]
  members={'C1':1,'C1b':1}
  self.assertIsNone(identity_conflict(events,members,'C1b','A'))


class TestFreezeSemantics(unittest.TestCase):
 def test_frozen_map_unaffected_by_later_merge(self):
  # 冻结点的映射
  events=[ev('a','A','exposure'),ev('b','A','exposure')]
  members_at_freeze={}
  frozen=canonical_map(events,members_at_freeze)
  self.assertNotEqual(frozen['a'],frozen['b'])  # 冻结时是两个人
  # 之后归并 a、b
  later_members,_,_=merge_plan(members_at_freeze,[('a','b')])
  now_map=canonical_map(events,later_members)
  self.assertEqual(now_map['a'],now_map['b'])   # 现在是同一人
  # 旧冻结裁决仍保持两人，不被混用
  self.assertNotEqual(frozen['a'],frozen['b'])

 def test_old_alias_backfill_still_same_person(self):
  # 归并后补采的旧别名事件，经当前映射仍归同一人
  members,_,_=merge_plan({},[('a','b')])
  events=[ev('a','A','exposure'),ev('b','A','exposure'),ev('b','A','activation')]
  c=resolve_counts(events,members)
  self.assertEqual(c['n_a'],1);self.assertEqual(c['activated_a'],1)


if __name__=='__main__':
 unittest.main(verbosity=2)
