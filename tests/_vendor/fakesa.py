"""仅用于无第三方依赖环境的极简 SQLAlchemy 垫片，支撑真实服务层在 sqlite 上集成测试。

不是生产代码；容器内仍使用真实 SQLAlchemy。覆盖本项目实际用到的声明式映射、
会话、filter_by/filter/in_/order_by/update、JSON 序列化与主键回填。
"""
import sqlite3,json,threading
def q(name):return '"'+str(name)+'"'
def _kind(spec):return type(spec.type).__name__
def _coerce(spec,v):
 if v is None:return None
 k=_kind(spec)
 if k=='Integer':return int(v)
 if k=='Float':return float(v)
 if k=='JSON':return json.dumps(v,ensure_ascii=False) if not isinstance(v,str) else v
 return v


class IntegrityError(Exception):pass
class _Type:
 def __init__(self,length=None):self.length=length
class Integer(_Type):sql='INTEGER'
class String(_Type):sql='TEXT'
class Text(_Type):sql='TEXT'
class Float(_Type):sql='REAL'
class JSON(_Type):sql='TEXT'
class ForeignKey:
 def __init__(self,target):self.target=target
class UniqueConstraint:
 def __init__(self,*cols,name=None):self.cols=cols;self.name=name
class Index:
 def __init__(self,name,*cols):self.name=name;self.cols=cols
class _ColSpec:
 def __init__(self,type_,pk=False,unique=False,nullable=True,default=None,FK=None):
  self.type=type_;self.pk=pk;self.unique=unique;self.nullable=nullable;self.default=default;self.FK=FK
def Column(*args,**kw):
 def is_type(a):return isinstance(a,_Type) or (isinstance(a,type) and issubclass(a,_Type))
 t=next((a for a in args if is_type(a)),Text)
 type_=t() if isinstance(t,type) else t
 FK=next((a for a in args if isinstance(a,ForeignKey)),None)
 return _ColSpec(type_,pk=kw.get('primary_key',False),unique=kw.get('unique',False),
  nullable=kw.get('nullable',True),default=kw.get('default'),FK=FK)
class Expr:
 def __init__(self,name,op,value):self.name,self.op,self.value=name,op,value
 def test(self,data):
  v=data.get(self.name)
  return v in self.value if self.op=='in' else v==self.value
class Order:
 def __init__(self,name,desc):self.name,self.desc=name,desc
class Col:
 def __init__(self,name,spec):self.name=name;self.spec=spec
 def __get__(self,obj,owner):
  if obj is None:return self
  return obj._data.get(self.name)
 def __set__(self,obj,value):obj._data[self.name]=value
 def __eq__(self,other):return Expr(self.name,'eq',other)
 def in_(self,values):return Expr(self.name,'in',list(values))
 def desc(self):return Order(self.name,True)
class _Table:
 def __init__(self,name,cols,uniques,indexes,cls):
  self.name=name;self.cols=cols
  self.columns=[Col(n,spec) for n,spec in cols.items()]
  self.uniques=uniques;self.indexes=indexes;self.cls=cls
class MetaData:
 def __init__(self):self.tables={}
 def create_all(self,engine):
  for t in self.tables.values():
   defs=[]
   for n,spec in t.cols.items():
    d=q(n)+' '+( 'INTEGER PRIMARY KEY AUTOINCREMENT' if spec.pk else spec.type.sql)
    if spec.unique and not spec.pk:d+=' UNIQUE'
    defs.append(d)
   engine.conn.execute(f'CREATE TABLE IF NOT EXISTS {q(t.name)} ({", ".join(defs)})')
   for u in t.uniques:
    engine.conn.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{t.name}_{u.name} ON {q(t.name)} ({", ".join(q(c) for c in u.cols)})')
   for ix in t.indexes:
    engine.conn.execute(f'CREATE INDEX IF NOT EXISTS {ix.name} ON {q(t.name)} ({", ".join(q(c) for c in ix.cols)})')
   engine.conn.commit()
 def drop_all(self,engine):
  for t in self.tables.values():
   engine.conn.execute(f'DROP TABLE IF EXISTS {q(t.name)}')
  row=engine.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone()
  if row:engine.conn.execute("DELETE FROM sqlite_sequence")
  engine.conn.commit()
class _BaseMeta(type):
 def __new__(mcs,name,bases,ns):
  tablename=ns.get('__tablename__')
  cls=super().__new__(mcs,name,bases,ns)
  if not tablename:return cls
  cols={};uniques=[];indexes=[]
  for attr,val in list(ns.items()):
   if isinstance(val,_ColSpec):cols[attr]=val;setattr(cls,attr,Col(attr,val))
   elif isinstance(val,UniqueConstraint):uniques.append(val)
   elif isinstance(val,Index):indexes.append(val)
  cls.__table__=_Table(tablename,cols,uniques,indexes,cls)
  cls.__tablename__=tablename
  for b in bases:
   if hasattr(b,'metadata'):b.metadata.tables[tablename]=cls.__table__
  return cls
def declarative_base():
 class Base(metaclass=_BaseMeta):
  metadata=MetaData()
  def __init__(self,**kw):
   self._data={}
   for k,v in kw.items():setattr(self,k,v)
 return Base
class _Dialect:
 def __init__(self,name):self.name=name
class Engine:
 def __init__(self,url):
  self.dialect=_Dialect('sqlite')
  self.conn=sqlite3.connect(':memory:',check_same_thread=False)
  self.conn.row_factory=sqlite3.Row
 @property
 def bind(self):return self
 def text(self,sql,*a,**k):return sql
def create_engine(url,**kw):return Engine(url)
def text(sql):return sql
class Query:
 def __init__(self,session,model):
  self.session=session;self.model=model;self._exprs=[];self._orders=[];self._limit=None
 def filter_by(self,**kw):
  for k,v in kw.items():self._exprs.append(Expr(k,'eq',v))
  return self
 def filter(self,*exprs):
  self._exprs.extend(exprs);return self
 def order_by(self,*cols):
  for c in cols:self._orders.append(c if isinstance(c,Order) else Order(c.name,False))
  return self
 def limit(self,n):self._limit=n;return self
 def _rows(self):
  t=self.model.__table__
  cur=self.session.conn.execute(f'SELECT * FROM "{t.name}"')
  out=[]
  for r in cur.fetchall():
   data={}
   for n,spec in t.cols.items():
    v=r[n]
    k=type(spec.type).__name__
    if k=='JSON' and v is not None:v=json.loads(v)
    elif k=='Integer' and v is not None:v=int(v)
    elif k=='Float' and v is not None:v=float(v)
    data[n]=v
   obj=self.session._identity.get((self.model,r['id']))
   if obj is None:
    obj=self.model.__new__(self.model);obj._data={};self.session._identity[(self.model,r['id'])]=obj
   obj._data.update(data)
   if all(e.test(obj._data) for e in self._exprs):out.append(obj)
  for o in self._orders:out.sort(key=lambda x:(x._data.get(o.name) is None,x._data.get(o.name)),reverse=o.desc)
  return out[:self._limit] if self._limit else out
 def all(self):return self._rows()
 def first(self):
  rows=self._rows();return rows[0] if rows else None
 def count(self):return len(self._rows())
 def update(self,mapping):
  for row in self._rows():
   for k,v in mapping.items():setattr(row,k,v);self.session._dirty.add(row)
  return len(mapping)
class Session:
 _all=[]
 def __init__(self,engine):
  self.conn=engine.conn;self.engine=engine;self.bind=engine
  self._pending=[];self._dirty=set();self._identity={}
  Session._all.append(self)
 def add(self,obj):
  if not hasattr(obj,'_data'):obj._data={}
  self._pending.append(obj)
 def get(self,model,pk):
  cached=self._identity.get((model,pk))
  if cached is not None:return cached
  t=model.__table__
  cur=self.conn.execute(f'SELECT * FROM "{t.name}" WHERE id=?',(pk,))
  r=cur.fetchone()
  if not r:return None
  obj=model.__new__(model);obj._data={}
  for n,spec in t.cols.items():
   v=r[n];k=type(spec.type).__name__
   if k=='JSON' and v is not None:v=json.loads(v)
   elif k=='Integer' and v is not None:v=int(v)
   elif k=='Float' and v is not None:v=float(v)
   obj._data[n]=v
  self._identity[(model,pk)]=obj;return obj
 def query(self,model):
  if self._pending:self.flush()  # 模拟 SQLAlchemy autoflush，保证查询可见挂起对象
  return Query(self,model)
 def flush(self):
  while self._pending:
   obj=self._pending.pop(0)
   t=type(obj).__table__
   for n,spec in t.cols.items():
    if n not in obj._data and spec.default is not None:
     obj._data[n]=spec.default() if callable(spec.default) else spec.default
   cols=[n for n in t.cols if not t.cols[n].pk]
   vals=[]
   for n in cols:
    vals.append(_coerce(t.cols[n],obj._data.get(n)))
   try:
    cur=self.conn.execute(f'INSERT INTO {q(t.name)} ({", ".join(q(c) for c in cols)}) VALUES ({", ".join("?"*len(cols))})',vals)
   except sqlite3.IntegrityError as e:raise IntegrityError(str(e))
   obj._data['id']=cur.lastrowid;self._identity[(type(obj),cur.lastrowid)]=obj
  # 垫片简化：回写所有已跟踪对象，保证任意属性变更都持久化
  for (model,pk),obj in list(self._identity.items()):
   t=model.__table__;cols=[n for n in t.cols if not t.cols[n].pk]
   vals=[_coerce(t.cols[n],obj._data.get(n)) for n in cols]
   vals.append(pk)
   self.conn.execute(f'UPDATE {q(t.name)} SET {", ".join(q(c)+"=?" for c in cols)} WHERE id=?',vals)
  self._dirty.clear()
 def commit(self):
  self.flush();self.conn.commit()
 def rollback(self):
  self.conn.rollback();self._pending.clear();self._dirty.clear()
 def close(self):pass
 def __enter__(self):return self
 def __exit__(self,*a):self.close()
def sessionmaker(bind=None,**kw):
 def factory():return Session(bind)
 return factory
