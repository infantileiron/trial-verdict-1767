import math,hashlib,json
from datetime import datetime,timezone
from scipy.stats import norm,chi2
VERSION='two-proportion-srm-identity-2.0'
def calculate(snapshot):
 """基于裁决冻结快照计算。身份关系与人数口径在快照生成时已冻结，

 归并产生的新版本不影响旧裁决；污染身份单列并阻断发布，不任选组、不悄悄剔除。"""
 exp=snapshot['experiment'];events=snapshot['events']
 frozen=snapshot.get('identity') or {}
 counts=frozen.get('counts') or {}
 n0,n1=counts.get('n_a',0),counts.get('n_b',0)
 c0,c1=counts.get('activated_a',0),counts.get('activated_b',0)
 polluted=counts.get('polluted',[])
 if min(n0,n1)<2:raise ValueError('每组至少需2名干净曝光用户，无法计算当前比例差异')
 p0,p1=c0/n0,c1/n1;delta=p1-p0;pooled=(c0+c1)/(n0+n1)
 se0=math.sqrt(pooled*(1-pooled)*(1/n0+1/n1))
 z=delta/se0 if se0 else 0.0;pv=float(2*norm.sf(abs(z))) if se0 else 1.0
 se=math.sqrt(p0*(1-p0)/n0+p1*(1-p1)/n1);margin=float(norm.ppf(.975))*se
 expected=[(n0+n1)*exp['a_ratio'],(n0+n1)*(1-exp['a_ratio'])]
 srm=sum((a-b)**2/b for a,b in zip([n0,n1],expected)) if expected[1] else 0.0;srm_p=float(chi2.sf(srm,1))
 approximate=min(n0,n1)>=20 and min(c0,n0-c0,c1,n1-c1)>=5
 matured=datetime.now(timezone.utc)>=datetime.fromisoformat(exp['ends_at'])
 reasons=[]
 if polluted:reasons.append(f'{len(polluted)}个身份同时落入A/B两组（污染），须先剔除分流污染源并重新裁决，禁止任选一组发布')
 if not matured:reasons.append('实验未到预定结束时间，禁止提前发布')
 if srm_p<.01:reasons.append('SRM p<0.01，先排查随机分流与事件采集')
 if not approximate:reasons.append('每组至少20名干净身份且成功/失败各至少5人，当前不满足正态近似')
 return dict(n_a=n0,n_b=n1,activated_a=c0,activated_b=c1,rate_a=p0,rate_b=p1,difference=delta,relative_lift=delta/p0 if p0 else None,z=z,p_value=pv,ci_low=max(-1,delta-margin),ci_high=min(1,delta+margin),srm_chi2=srm,srm_p=srm_p,expected_a=expected[0],expected_b=expected[1],matured=matured,approximation_valid=approximate,release_eligible=not reasons,block_reasons=reasons,significant_positive=delta>0 and pv<.05,identity_version=frozen.get('identity_version',0),raw_exposed_a=counts.get('raw_exposed_a',n0),raw_exposed_b=counts.get('raw_exposed_b',n1),raw_exposed_total=counts.get('raw_exposed_total',n0+n1),dedup_exposed_total=counts.get('dedup_exposed_total',n0+n1),polluted_count=counts.get('polluted_count',0),polluted=polluted,version=VERSION,checksum=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),method='双侧双比例z检验；95%绝对提升Wald区间；SRM卡方df=1；按冻结身份映射去重，污染身份单列并阻断发布；激活为干净曝光子集；差异方向B−A')
