class RedisError(Exception):pass
class Redis:
 def __init__(self,*a,**k):self.items={}
 def rpush(self,k,v):self.items.setdefault(k,[]).append(v);return len(self.items[k])
 def blpop(self,keys,timeout=0):
  for k in (keys if isinstance(keys,list) else [keys]):
   if self.items.get(k):return k.encode() if isinstance(k,str) else k,self.items[k].pop(0)
  return None
 def ping(self):return True
 @staticmethod
 def from_url(url,**k):return Redis()
