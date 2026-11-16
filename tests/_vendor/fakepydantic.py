"""极简 pydantic 垫片：支持 BaseModel/Field/model_validator 与 typing.Literal 校验。"""
import typing
class ValidationError(ValueError):pass
def Field(default=None,**kw):return (default,kw)
def model_validator(mode='after'):
 def deco(fn):fn.__model_validator__=mode;return fn
 return deco
class _FieldInfo:
 def __init__(self,default,kw):
  self.default=default;self.required=default is _MISSING;self.kw=kw
_MISSING=object()
class BaseModel:
 def __init__(self,**data):
  ann=getattr(self,'__annotations__',{})
  vals={}
  for name,typ in ann.items():
  # 类属性可能是 Field() 元组
   cls_val=getattr(type(self),name,_MISSING)
   if isinstance(cls_val,tuple) and len(cls_val)==2 and isinstance(cls_val[1],dict):
    fi=_FieldInfo(cls_val[0],cls_val[1])
   else:
    fi=_FieldInfo(cls_val if cls_val is not _MISSING else _MISSING,{})
   if name in data:vals[name]=data[name]
   elif not fi.required:vals[name]=fi.default
   else:raise ValidationError(f'缺少必填字段 {name}')
   self._check(name,vals[name],typ,fi)
  for k,v in vals.items():setattr(self,k,v)
  # 模型级校验器
  for attr in dir(type(self)):
   fn=getattr(type(self),attr)
   if callable(fn) and getattr(fn,'__model_validator__',None):
    fn(self)
 def _check(self,name,value,typ,fi):
  kw=fi.kw
  if 'min_length' in kw and value is not None and len(value)<kw['min_length']:raise ValidationError(f'{name} 长度不足')
  if 'max_length' in kw and value is not None and len(value)>kw['max_length']:raise ValidationError(f'{name} 超长')
  if 'gt' in kw and not value>kw['gt']:raise ValidationError(f'{name} 须大于 {kw["gt"]}')
  if 'ge' in kw and not value>=kw['ge']:raise ValidationError(f'{name} 过小')
  if 'le' in kw and not value<=kw['le']:raise ValidationError(f'{name} 过大')
  if value is not None and typing.get_origin(typ) is typing.Literal and value not in typing.get_args(typ):
   raise ValidationError(f'{name} 取值非法')
  if value is not None and typing.get_origin(typ) is list:
   if not isinstance(value,list):raise ValidationError(f'{name} 须为列表')
   args=typing.get_args(typ)
   if args and isinstance(args[0],type) and issubclass(args[0],BaseModel):
    value=[v if isinstance(v,BaseModel) else args[0](**v) for v in value]
   if 'min_length' in kw and len(value)<kw['min_length']:raise ValidationError(f'{name} 条目不足')
   if 'max_length' in kw and len(value)>kw['max_length']:raise ValidationError(f'{name} 条目超限')
 def model_dump(self):
  return {k:getattr(self,k) for k in self.__annotations__}
