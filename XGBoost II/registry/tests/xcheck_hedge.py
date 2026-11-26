# Независимая проверка: Hedge + симуляция сделок на Python (код отдельный от C++)
# Использование: python xcheck_hedge.py <папка BAZA> <результат тестера .json>
import math, json, sys, os
import xcheck_common as X
res=json.load(open(sys.argv[2],encoding='utf-8')); pair=res['pair']; tf=res['timeframe']
over=dict(kv.split('=') for kv in res['rules'][0]['overrides'].split())
thr=float(over.get('confidence',0.2)); don_incl=float(over.get('donchian_include_current',1))!=0
assert set(over)<={'confidence','donchian_include_current'}, 'эта проверка не знает параметры: '+str(over)
B=X.load(os.path.join(sys.argv[1],pair,f'{pair}_{tf}.bin'),X.DEV_CUT)
O,H,L,C=B['O'],B['H'],B['L'],B['C']; n=len(C)
def sma(x,p):
    o=[None]*n; s=0
    for i in range(n):
        s+=x[i]
        if i>=p: s-=x[i-p]
        if i>=p-1: o[i]=s/p
    return o
def ema(x,p):
    k=2/(p+1); e=x[0]; o=[e]
    for i in range(1,n): e=x[i]*k+e*(1-k); o.append(e)
    return o
mf,ms=sma(C,10),sma(C,50); m20=sma(C,20)
sd=[None]*n
for i in range(19,n):
    w=C[i-19:i+1]; mu=sum(w)/20; sd[i]=math.sqrt(max(0,sum(v*v for v in w)/20-mu*mu))
rsi=[None]*n; ag=al=0
for i in range(1,15):
    d=C[i]-C[i-1]; ag+=max(d,0); al+=max(-d,0)
ag/=14; al/=14; rsi[14]=100 if al==0 else 100-100/(1+ag/al)
for i in range(15,n):
    d=C[i]-C[i-1]; ag=(ag*13+max(d,0))/14; al=(al*13+max(-d,0))/14; rsi[i]=100 if al==0 else 100-100/(1+ag/al)
ef,es=ema(C,12),ema(C,26); macd=[a-b for a,b in zip(ef,es)]; sg=ema(macd,9); hist=[a-b for a,b in zip(macd,sg)]
def votes(i):
    v=[0]*5
    if mf[i] is not None and ms[i] is not None: v[0]=1 if mf[i]>ms[i] else (-1 if mf[i]<ms[i] else 0)
    if rsi[i] is not None: v[1]=1 if rsi[i]<30 else (-1 if rsi[i]>70 else 0)
    if m20[i] is not None:
        up=m20[i]+2*sd[i]; lo=m20[i]-2*sd[i]; v[2]=1 if C[i]>up else (-1 if C[i]<lo else 0)
    v[3]=1 if hist[i]>0 else (-1 if hist[i]<0 else 0)
    a0,a1=(i-19,i+1) if don_incl else (i-20,i)
    if a0>=0:
        mx=max(H[a0:a1]); mn=min(L[a0:a1]); v[4]=1 if C[i]>=mx else (-1 if C[i]<=mn else 0)
    return v
eta=math.sqrt(8*math.log(5)/2000); w=[0.2]*5; pv=[0]*5; sig=[0]*n
for i in range(n):
    if i>=1 and any(pv):
        s=1 if C[i]>C[i-1] else (-1 if C[i]<C[i-1] else 0)
        w=[wi*math.exp(-eta*(0.5-0.5*pv[k]*s)) for k,wi in enumerate(w)]; t=sum(w); w=[x/t for x in w]
    v=votes(i); pv=v
    if i>=59:
        e=sum(w[k]*v[k] for k in range(5)); sig[i]=1 if e>=thr else (-1 if e<=-thr else 0)
sys.exit(X.compare(res, X.trades(B,sig,pair,X.dev_windows(B['T'][0])[0][1]), B['T'][0]))
