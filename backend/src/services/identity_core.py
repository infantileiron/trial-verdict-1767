"""身份归并的纯函数核心：不依赖 SQLAlchemy/Redis/scipy，可用标准库直接单测。

数据均以基础容器表达：
- members: dict[user_key, identity_id]          当前 user_key -> canonical 身份
- events : list[dict]，至少含 user_key/group/kind
归并采用并查集；所有“人数”口径在此统一，保证冻结裁决与在线页面同源。
"""
from collections import defaultdict


class UnionFind:
 """带持久化根编码的并查集。roots 中每个节点指向父节点，根指向自身。"""

 def __init__(self, roots=None):
  self.parent=dict(roots or {})

 def find(self,x):
  if x not in self.parent:self.parent[x]=x
  root=x
  while self.parent[root]!=root:root=self.parent[root]
  while self.parent[x]!=root:
   self.parent[x],x=root,self.parent[x]
  return root

 def union(self,a,b):
  ra,rb=self.find(a),self.find(b)
  if ra==rb:return ra,rb,ra,False
  # 确定性归并：保留较小 id 作为根，保证可重放、可追查
  keep,drop=(ra,rb) if ra<=rb else (rb,ra)
  self.parent[drop]=keep
  return keep,drop,keep,True

 def roots_snapshot(self):
  return {k:self.find(k) for k in self.parent}


def canonical_map(events,members):
 """返回 events 涉及的每个 user_key 的 canonical 标识（字符串）。

 未登记别名的 user_key 以自身为 canonical（独立访客标识）。
 members: dict[user_key, identity_id]
 """
 uf=UnionFind()
 by_identity=defaultdict(list)
 for key,ident in members.items():by_identity[ident].append(key)
 for ident,keys in by_identity.items():
  root=f'id:{ident}'
  uf.parent.setdefault(root,root)
  for k in keys:
   node=f'key:{k}'
   uf.parent.setdefault(node,root);uf.parent[node]=root
 canon={}
 # 同时覆盖事件 key 与已登记别名，保证“新别名首次上报”也能解析到既有身份
 all_keys={e['user_key'] for e in events}|set(members)
 for k in all_keys:
  node=f'key:{k}'
  if node in uf.parent:canon[k]=uf.find(node)
  else:canon[k]=f'key:{k}'  # 无别名记录：自身即身份
 return canon


def resolve_counts(events,members):
 """统一人数口径。返回原始人数、去重人数与污染身份。

 规则：
 - 原始曝光人数 = 曝光事件的不同 user_key 数（归并前口径，保留对照）。
 - 去重曝光人数 = 按 canonical 身份去重后的人数。
 - 同一 canonical 身份在同一实验同时出现在 A、B 两组 => 污染身份，单列，
   不允许任选一组或悄悄剔除；干净身份才进入 nA/nB 统计。
 - 激活身份必须是本组干净曝光身份的子集。
 """
 exposure=[e for e in events if e['kind']=='exposure']
 activation=[e for e in events if e['kind']=='activation']
 raw_exposed={g:{e['user_key'] for e in exposure if e['group']==g} for g in ('A','B')}
 canon=canonical_map(exposure+activation,members)
 groups_of=defaultdict(set);keys_of=defaultdict(set)
 for e in exposure:
  c=canon[e['user_key']];groups_of[c].add(e['group']);keys_of[c].add(e['user_key'])
 polluted=sorted(c for c,gs in groups_of.items() if len(gs)>1)
 clean={g:set() for g in ('A','B')}
 for c,gs in groups_of.items():
  if len(gs)==1:clean[next(iter(gs))].add(c)
 exposed_identities=set(groups_of)
 activated_identities=defaultdict(set)
 for e in activation:
  c=canon[e['user_key']]
  if c in exposed_identities and c not in polluted:
   g=next(iter(groups_of[c]));activated_identities[g].add(c)
 return {
  'raw_exposed_a':len(raw_exposed['A']),'raw_exposed_b':len(raw_exposed['B']),
  'raw_exposed_total':len(raw_exposed['A']|raw_exposed['B']),
  'n_a':len(clean['A']),'n_b':len(clean['B']),
  'activated_a':len(activated_identities['A']),'activated_b':len(activated_identities['B']),
  'dedup_exposed_total':len(exposed_identities),
  'polluted_count':len(polluted),
  'polluted':[{'identity':c,'groups':sorted(groups_of[c]),'user_keys':sorted(keys_of[c])} for c in polluted],
  'canonical':canon,
 }


def merge_plan(existing_members,pairs):
 """对一批 (a_key,b_key) 关联计算幂等归并计划。

 existing_members: dict[user_key, identity_id]（当前持久化映射）
 返回 (new_members, merges, skipped)：
 - merges: [(left_identity,right_identity,merged_identity)] 真正需要的归并
 - skipped: [(a,b,reason)] 已在同一身份，重试不重复改变人数
 new_members 为归并后的完整 user_key->identity_id 映射。
 """
 members=dict(existing_members)
 # identity 并查集（identity id 空间）
 uf=UnionFind()
 for ident in set(members.values()):uf.find(ident)
 next_id=(max(members.values())+1) if members else 1
 merges=[];skipped=[]
 def ident_of(key):
  return members[key] if key in members else None
 for a,b in pairs:
  ia,ib=ident_of(a),ident_of(b)
  if ia is None and ib is None:
   ident=next_id;next_id+=1;members[a]=ident;members[b]=ident;uf.find(ident)
   merges.append((None,None,ident))
  elif ia is not None and ib is None:
  # b 并入 a 所在身份，不产生 identity 间归并
   members[b]=uf.find(ia)
  elif ia is None and ib is not None:
   members[a]=uf.find(ib)
  else:
   ra,rb=uf.find(ia),uf.find(ib)
   if ra==rb:skipped.append((a,b,'两个标识已属同一身份，跳过重试'));continue
   keep,drop,_,changed=uf.union(ra,rb)
   if changed:merges.append((ra,rb,keep))
 # 应用 identity 归并到成员映射
 final_members={k:uf.find(i) for k,i in members.items()}
 return final_members,merges,skipped


def identity_conflict(events,members,user_key,group):
 """新事件入库前的身份级冲突检测。

 返回 None 表示可入库；返回字符串说明阻断原因（跨组污染/重复事件）。
 调用方需另行提供同实验事件与事件类型。
 """
 canon=canonical_map(events,members)
 new_c=canon.get(user_key,f'key:{user_key}')
 groups={canon[e['user_key']]:e['group'] for e in events if e['kind']=='exposure'}
 prior_groups={g for c,g in groups.items() if c==new_c}
 if group not in prior_groups and prior_groups:
  return f'该身份已在 {"、".join(sorted(prior_groups))} 组产生曝光，跨组会污染分流，已阻断'
 return None
