from sqlalchemy import Column,Integer,String,Float,JSON,Text,UniqueConstraint,ForeignKey,Index
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True);password=Column(String(200));role=Column(String(20))
class Experiment(Base):
 __tablename__='experiments'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True);name=Column(String(120));starts_at=Column(String(40));ends_at=Column(String(40));a_ratio=Column(Float);hypothesis=Column(Text)
class Event(Base):
 __tablename__='events'
 __table_args__=(UniqueConstraint('experiment_id','user_key','kind',name='uq_exp_user_kind'),)
 id=Column(Integer,primary_key=True);experiment_id=Column(Integer,ForeignKey('experiments.id'));user_key=Column(String(80));group=Column(String(1));kind=Column(String(20));occurred_at=Column(String(40))
class Decision(Base):
 __tablename__='decisions'
 id=Column(Integer,primary_key=True);experiment_id=Column(Integer,ForeignKey('experiments.id'));state=Column(String(20),default='queued');snapshot=Column(JSON);result=Column(JSON,nullable=True);error=Column(Text,default='');rationale=Column(Text,default='');action=Column(String(30),default='');published_by=Column(String(100),default='');published_at=Column(String(40),default='')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
# ===== 身份别名归并（identity resolution）=====
class Identity(Base):
 """并查集根节点：一个 canonical 身份一行；被合并的根保留为历史，parent_id 指向新根。"""
 __tablename__='identities'
 id=Column(Integer,primary_key=True);code=Column(String(100),unique=True);parent_id=Column(Integer,ForeignKey('identities.id'),nullable=True)
class IdentityMember(Base):
 """user_key -> canonical 身份的当前映射，user_key 全局唯一（一个别名只能归一个人）。"""
 __tablename__='identity_members'
 __table_args__=(UniqueConstraint('user_key',name='uq_member_user_key'),Index('ix_identity_member_identity','identity_id'))
 id=Column(Integer,primary_key=True);identity_id=Column(Integer,ForeignKey('identities.id'));user_key=Column(String(80));source_job_id=Column(Integer,ForeignKey('alias_jobs.id'),nullable=True)
class IdentityMerge(Base):
 """归并历史：left_id+right_id -> merged_id，记录依据任务与归并后的身份版本，支撑归并链追查。"""
 __tablename__='identity_merges'
 id=Column(Integer,primary_key=True);left_id=Column(Integer);right_id=Column(Integer);merged_id=Column(Integer);alias_job_id=Column(Integer,ForeignKey('alias_jobs.id'));identity_version=Column(Integer);created=Column(String(40))
class IdentityVersion(Base):
 """全局身份关系版本，单行 id=1；只有成功提交归并事务才递增。"""
 __tablename__='identity_versions'
 id=Column(Integer,primary_key=True);version=Column(Integer,default=0)
class AliasJob(Base):
 """别名关联导入任务：可中断恢复，重试幂等。"""
 __tablename__='alias_jobs'
 id=Column(Integer,primary_key=True);state=Column(String(20),default='queued');source=Column(String(40),default='manual');note=Column(String(300),default='');error=Column(Text,default='');created_by=Column(String(100));created=Column(String(40));finished=Column(String(40),default='');processed_items=Column(Integer,default=0);failed_items=Column(Integer,default=0);applied_merges=Column(Integer,default=0);identity_version_before=Column(Integer,default=0);identity_version_after=Column(Integer,default=0)
class AliasJobItem(Base):
 """任务内单条关联（a_key,b_key 视为同一人），独立状态，失败不影响其他关联。"""
 __tablename__='alias_job_items'
 __table_args__=(Index('ix_alias_item_job','alias_job_id'),)
 id=Column(Integer,primary_key=True);alias_job_id=Column(Integer,ForeignKey('alias_jobs.id'));a_key=Column(String(80));b_key=Column(String(80));state=Column(String(20),default='pending');message=Column(String(300),default='')
class AliasLink(Base):
 """原始关联依据留痕：每条已生效或被跳过的关联都保留，不覆盖原始事件。"""
 __tablename__='alias_links'
 __table_args__=(UniqueConstraint('a_key','b_key',name='uq_alias_pair'),Index('ix_alias_link_job','alias_job_id'))
 id=Column(Integer,primary_key=True);alias_job_id=Column(Integer,ForeignKey('alias_jobs.id'));a_key=Column(String(80));b_key=Column(String(80));state=Column(String(20),default='done');message=Column(String(300),default='');created=Column(String(40))
