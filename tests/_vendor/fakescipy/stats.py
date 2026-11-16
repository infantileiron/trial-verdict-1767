"""scipy 垫片：仅提供 analysis.py 用到的正态/卡方生存函数，标准库 math 实现。"""
import math
class _Norm:
 @staticmethod
 def sf(x):return 0.5*math.erfc(x/math.sqrt(2))
 @staticmethod
 def ppf(p):
  # 97.5 分位反函数：Acklam 近似，足够测试口径
  a=[-3.969683028665376e+01,2.209460984245205e+02,-2.759285104469687e+02,
     1.383577518672690e+02,-3.066479806614716e+01,2.506628277459239e+00]
  b=[-5.447609879822406e+01,1.615858368580409e+02,-1.556989798598866e+02,
     6.680131188771972e+01,-1.328068155288572e+01]
  c=[-7.784894002430293e-03,-3.223964580411365e-01,-2.400758277161838e+00,
     -2.549732539343734e+00,4.374664141464968e+00,2.938163982698783e+00]
  d=[7.784695709041462e-03,3.224671290700398e-01,2.445134137142996e+00,
     3.754408661907416e+00]
  plow,phigh=0.02425,1-0.02425
  if p<plow:
   q=math.sqrt(-2*math.log(p));x=((( ((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
  elif p<=phigh:
   q=p-0.5;r=q*q
   num=(((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q
   den=(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
   x=num/den
  else:
   q=math.sqrt(-2*math.log(1-p));x=-((( ((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
  return x
class _Chi2:
 @staticmethod
 def sf(x,df):
  if df!=1:raise NotImplementedError('仅 df=1')
  return math.erfc(math.sqrt(x/2))
norm=_Norm();chi2=_Chi2()
