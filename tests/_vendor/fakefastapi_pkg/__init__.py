class HTTPException(Exception):
 def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail;super().__init__(detail)
class Depends:
 def __init__(self,*a,**k):self.dep=a[0] if a else None
class APIRouter:
 def __init__(self,*a,**k):self.routes=[]
 def _add(self,*a,**k):
  def deco(fn):return fn
  return deco
 get=post=put=delete=_add
class FastAPI:
 def __init__(self,*a,**k):self.title=k.get('title','');self.routes=[]
 def add_middleware(self,*a,**k):pass
 def include_router(self,*a,**k):pass
 def get(self,*a,**k):
  def deco(fn):return fn
  return deco
 def exception_handler(self,*a,**k):
  def deco(fn):return fn
  return deco
class Response:
 def __init__(self,content=None,media_type=None,headers=None):self.content=content;self.media_type=media_type;self.headers=headers
class Request:pass
