"""Deterministic signed-cube and quadratic--quartic orbit generator.

Vectors use ascending coefficients.  The generator has no catalogue data and
all retries are bounded, so large requests remain inexpensive.
"""
from __future__ import annotations

from fractions import Fraction
from math import comb, gcd

MASK=(1<<64)-1
SHELLS=(2,3,5,8,12,17,23)
PRIMES=(3,5,7,11)

def _mix(x:int)->int:
    x=(x+0x9E3779B97F4A7C15)&MASK; x=((x^(x>>30))*0xBF58476D1CE4E5B9)&MASK
    x=((x^(x>>27))*0x94D049BB133111EB)&MASK; return x^(x>>31)
def _word(seed:int,lane:int,n:int,i:int)->int:
    return _mix((seed&MASK)^(lane+1)*0xD1B54A32D192ED03^(n+1)*0x94D049BB133111EB^(i+1)*0xBF58476D1CE4E5B9)
def _signed(seed:int,lane:int,n:int,i:int,h:int)->int: return _word(seed,lane,n,i)%(2*h+1)-h
def _trim(a:list[int])->list[int]:
    while len(a)>1 and not a[-1]: a.pop()
    return a
def _add(a:list[int],b:list[int])->list[int]:
    z=[0]*max(len(a),len(b))
    for i,x in enumerate(a): z[i]+=x
    for i,x in enumerate(b): z[i]+=x
    return _trim(z)
def _mul(a:list[int],b:list[int])->list[int]:
    z=[0]*(len(a)+len(b)-1)
    for i,x in enumerate(a):
        for j,y in enumerate(b): z[i+j]+=x*y
    return _trim(z)
def _eval(a:list[int],x:int)->int:
    z=0
    for v in reversed(a): z=z*x+v
    return z

def _cubic_irred(a:int,b:int,c:int)->bool:
    if not c:return False
    f=[c,b,a,1]
    return not any(c%d==0 and (_eval(f,d)==0 or _eval(f,-d)==0) for d in range(1,abs(c)+1))
def _mt(v:list[int],a:int,b:int,c:int)->list[int]: return [-c*v[2],v[0]-b*v[2],v[1]-a*v[2]]
def _sym(a:int,b:int,c:int,q:list[int])->tuple[int,int,int]:
    tq=_mt(q,a,b,c); t2=_mt(tq,a,b,c); m00,m10,m20=q; m01,m11,m21=tq; m02,m12,m22=t2
    e1=m00+m11+m22
    e2=m00*m11+m00*m22+m11*m22-m01*m10-m02*m20-m12*m21
    e3=m00*(m11*m22-m12*m21)-m01*(m10*m22-m12*m20)+m02*(m10*m21-m11*m20)
    return e1,e2,e3
def _cube(e1:int,e2:int,e3:int)->list[int]:
    return [(e1*e1-4*e2)**2,0,-4*e1**3+16*e1*e2-64*e3,0,6*e1*e1-8*e2,0,-4*e1,0,1]
def _cube_try(seed:int,lane:int,n:int,h:int)->tuple[list[int],tuple]|None:
    if lane==1: # Shanks cubics: square discriminant
        m=_signed(seed,lane,n,0,h); a,b,c=-m,-m-3,-1; q=[_signed(seed,lane,n,1,h),1,_signed(seed,lane,n,2,h) or 1]
    elif lane==2: # sparse / trace normalized
        a=_signed(seed,lane,n,0,h) if n&1 else 0; b=_signed(seed,lane,n,1,h) if not n&1 else 0; c=_signed(seed,lane,n,2,h) or 1
        q=[_signed(seed,lane,n,3,h),_signed(seed,lane,n,4,h) or 1,0]
    else:
        a,b,c=(_signed(seed,lane,n,i,h) for i in range(3)); c=c or 1
        q=[_signed(seed,lane,n,3,h),_signed(seed,lane,n,4,h) or 1,_signed(seed,lane,n,5,max(1,h//2)) if lane==3 else 0]
    if not _cubic_irred(a,b,c): return None
    e=_sym(a,b,c,q)
    if e[2]==0 or e[0]*e[0]==4*e[1]: return None
    return _cube(*e),("cube",lane,e)

def _quartic(seed:int,lane:int,n:int,h:int)->list[int]:
    s=lambda i:_signed(seed,lane+10,n,i,h)
    if lane==5:return [s(0) or 1,s(1),s(2),s(3),1]
    if lane==6:return [s(0) or 1,0,s(1),0,1]
    if lane==7:return [s(2) or 1,s(1),s(0),s(3),1]
    if lane==8:return [1,s(0),s(1),s(0),1]
    p=(2,3,5)[n%3]; u=s(0) or 1
    if u%p==0:u+=1
    mid=[0,0,0]; mid[_word(seed,lane,n,1)%3]=p*(s(2) or 1)
    return [p*u,*mid,1]
def _quad(seed:int,lane:int,n:int,h:int)->tuple[int,int]:
    b=_signed(seed,lane+30,n,0,h); mag=1+_word(seed,lane+30,n,1)%(h+2)
    return (b,-mag) if (lane+n)&1 else (b,b*b//4+mag+1)
def _comp(f:list[int],b:int,c:int,k:int)->list[int]:
    powers=[(1,0)]
    for _ in range(4):
        u,v=powers[-1];powers.append((-c*v,u-b*v))
    A,B=[0],[0]
    for d,coef in enumerate(f):
        for j in range(d+1):
            u,v=powers[j]; t=[0]*(d-j+1);t[-1]=coef*comb(d,j)*(-k)**j
            if u:A=_add(A,[u*x for x in t])
            if v:B=_add(B,[v*x for x in t])
    return _add(_add(_mul(A,A),[-b*x for x in _mul(A,B)]),[c*x for x in _mul(B,B)])

# Small finite-field factor-degree engine.  A rational factor degree must occur
# as a subset sum at every good prime; this is much less biased than demanding
# an irreducible reduction (which loses many signed-cube groups).
def _mp(a:list[int],p:int)->list[int]:return _trim([x%p for x in a])
def _mulp(a:list[int],b:list[int],p:int)->list[int]:return _trim([x%p for x in _mul(a,b)])
def _dr(a:list[int],b:list[int],p:int)->tuple[list[int],list[int]]:
    a=_mp(a[:],p);b=_mp(b[:],p);q=[0]*max(1,len(a)-len(b)+1);inv=pow(b[-1],-1,p)
    while len(a)>=len(b) and a!=[0]:
        d=len(a)-len(b);z=a[-1]*inv%p;q[d]=z
        for i,x in enumerate(b):a[i+d]=(a[i+d]-z*x)%p
        _trim(a)
    return _trim(q),a
def _gp(a:list[int],b:list[int],p:int)->list[int]:
    while b!=[0]:a,b=b,_dr(a,b,p)[1]
    inv=pow(a[-1],-1,p);return [x*inv%p for x in a]
def _power(a:list[int],n:int,f:list[int],p:int)->list[int]:
    z=[1]
    while n:
        if n&1:z=_dr(_mulp(z,a,p),f,p)[1]
        a=_dr(_mulp(a,a,p),f,p)[1];n//=2
    return z
def _degrees(poly:list[int],p:int)->list[int]|None:
    f=_mp(poly,p)
    if len(f)!=9 or f[-1]==0 or _gp(f,[i*f[i] for i in range(1,len(f))],p)!=[1]:return None
    ans=[];prev=0
    for d in range(1,5):
        xp=_power([0,1],p**d,f,p); g=_gp(f,_add(xp,[-1]),p); total=len(g)-1
        ans += [d]*((total-prev)//d);prev=total
    if sum(ans)<8:ans.append(8-sum(ans))
    return ans
def _sieve(poly:list[int])->tuple[bool,tuple]:
    poss=set(range(1,5));pat=[]
    for p in PRIMES:
        ds=_degrees(poly,p)
        if ds is None:continue
        sums={0}
        for d in ds:sums|={x+d for x in tuple(sums)}
        poss&=sums;pat.append(tuple(ds))
    return (not poss or len(pat)>=3),tuple(pat)

def _sturm(a:list[int],positive:bool=False)->int:
    seq=[_trim(a[:]),_trim([i*a[i] for i in range(1,len(a))])]
    while len(seq[-1])>1:
        x=[Fraction(v) for v in seq[-2]];y=[Fraction(v) for v in seq[-1]]
        while len(x)>=len(y):
            z=x[-1]/y[-1];d=len(x)-len(y)
            for i,v in enumerate(y):x[i+d]-=z*v
            while len(x)>1 and not x[-1]:x.pop()
        den=1
        for v in x:den=den*v.denominator//gcd(den,v.denominator)
        seq.append(_trim([-int(v*den) for v in x]))
    changes=lambda s:sum(x!=y for x,y in zip(s,s[1:]))
    inf=[1 if q[-1]>0 else -1 for q in seq]
    if positive:
        zero=[]
        for q in seq:
            v=next((x for x in q if x),1);zero.append(1 if v>0 else -1)
        return changes(zero)-changes(inf)
    neg=[(1 if q[-1]>0 else -1)*((-1)**(len(q)-1)) for q in seq]
    return changes(neg)-changes(inf)
def _canonical(p:list[int])->tuple[int,...]:return min(tuple(p),tuple((-1)**i*x for i,x in enumerate(p)))
def _quotas(n:int,w:list[int])->list[int]:
    t=sum(w);q=[n*x//t for x in w]
    for i in sorted(range(len(w)),key=lambda i:(-(n*w[i]%t),i))[:n-sum(q)]:q[i]+=1
    return q
def _schedule(n:int)->list[tuple[int,int,int]]:
    cube,comp=_quotas(n,[60,40]); reserve=_quotas(n,[8,8,84])[:2]; sigs=[2]*reserve[0]+[6]*reserve[1]
    rest=cube-len(sigs);sigs += ([0,4,8]*(rest//3)+[0,4,8][:rest%3])
    q=_quotas(cube,[15,20,15,10]);used=[0]*4;out=[]
    for sig in sigs:
        j=next(i for i in range(4) if used[i]<q[i]);used[j]+=1;out.append((0,j,sig))
    q=_quotas(comp,[10,9,8,7,6]);used=[0]*5
    for i in range(comp):
        j=next(k for k in range(5) if used[k]<q[k]);used[j]+=1;out.append((1,j,[0,4,8][i%3]))
    return sorted(enumerate(out),key=lambda z:(z[1][0],z[0]%7,z[1][1])) and [x for _,x in sorted(enumerate(out),key=lambda z:(z[0]%7,z[1][0],z[1][1]))]
def _fallback(n:int)->list[int]:return [2*(2*n+1),2,0,0,0,0,0,0,1]

def generate_candidates(seed:int,budget:int)->list[list[int]]:
    """Return exactly ``budget`` distinct monic integral octics."""
    if isinstance(budget,bool) or not isinstance(budget,int):raise TypeError("budget must be an integer")
    if budget<0:raise ValueError("budget must be nonnegative")
    seen=set();inv=set();occ={};counts=[0]*10;answer=[]
    for pos,(fam,local,target) in enumerate(_schedule(budget)):
        picks=[]; loose=[]
        for attempt in range(6 if fam==0 else 4):
            lane=local if fam==0 else local+5;n=counts[lane];counts[lane]+=1;h=SHELLS[(pos+attempt+n//7)%len(SHELLS)]
            if fam==0:
                made=_cube_try(seed,lane,n,h)
                if made is None:continue
                poly,key=made
                if key in inv:continue
                sig=2*_sturm([poly[2*i] for i in range(5)],True)
            else:
                f=_quartic(seed,lane,n,h);b,c=_quad(seed,lane,n,h)
                if b*b-4*c==0:continue
                poly=_comp(f,b,c,(1,-1,2,-2)[(n+pos)%4]);key=("comp",lane,n)
                sig=_sturm(f)*(2 if b*b-4*c>0 else 0)
            if len(poly)!=9 or poly[-1]!=1 or not poly[0] or _canonical(poly) in seen:continue
            ok,pat=_sieve(poly)
            if not ok:continue
            bucket=(fam,lane,sig,pat);score=(occ.get(bucket,0),max(abs(x) for x in poly[:-1]),sum(x!=0 for x in poly[:-1]))
            (picks if sig==target else loose).append((score,poly,key,bucket))
        # A failed signature cell transfers to its least-filled compatible
        # bucket; this is preferable to consuming fallback capacity.
        if not picks: picks=loose
        if picks:
            _,poly,key,bucket=min(picks,key=lambda x:x[0]);inv.add(key);occ[bucket]=occ.get(bucket,0)+1
        else:
            serial=pos+1;poly=_fallback(serial)
            while _canonical(poly) in seen:serial+=budget+1;poly=_fallback(serial)
        seen.add(_canonical(poly));answer.append(poly)
    return answer

# Local-global diversity portfolio.  This definition intentionally replaces the
# earlier orbit round-robin above while retaining its small finite-field engine.
def _portfolio_compose(a:list[int],b:list[int])->list[int]:
    z=[0]
    for c in reversed(a):z=_add(_mul(z,b),[c])
    return z
def _portfolio_recip(seed:int,n:int,h:int)->list[int]:
    s=lambda i:_signed(seed,71,n,i,h);g=[s(0) or 1,s(1),s(2),s(3),1];z=[0]*9
    for d,c in enumerate(g):
        for j in range(d+1):z[4+d-2*j]+=c*comb(d,j)
    return z
def _portfolio_tree(seed:int,n:int,h:int)->list[int]:
    qs=[]
    for j in range(3):
        b=_signed(seed,80+j,n,0,max(1,h//2));c=_signed(seed,80+j,n,1,h)
        if (n+j)%5==0:c=b*b//4+1+abs(_signed(seed,84+j,n,2,h))
        qs.append([c,b,1])
    f=_portfolio_compose(qs[1],qs[2]);f=_portfolio_compose(qs[0],f)
    f[0]-=_signed(seed,88,n,0,h) or 1
    return f
def _portfolio_critical(seed:int,n:int,h:int)->list[int]:
    # f'=8*x*q^2.  A cubic q is required for a degree-eight integral f.
    # q=[5u,0,21v,1] meets every denominator condition in the integral:
    # 3|q0*q1, 5|(q0+q1*q2), 3|(q2^2+2q1), and 7|q2.
    s=lambda i:_signed(seed,90,n,i,h);q=[5*(s(0) or 1),0,21*s(2),1];qq=_mul(q,q);f=[0]*9
    for i,v in enumerate(qq):
        d=i+2
        if 8*v%d:return []
        f[d]=8*v//d
    # Res(f',f)=8^8*f(0)*Norm_q(f)^2.  Thus this square integration
    # constant makes the (nonzero) polynomial discriminant a square.
    u=1+_word(seed,91,n,0)%(h+3);f[0]=u*u
    return f
def _portfolio_eis(seed:int,n:int,h:int)->list[int]:
    p=(2,3,5)[n%3];s=lambda i:_signed(seed,100,n,i,h);a=[p*s(i) for i in range(8)]+[1]
    u=s(0) or 1
    if u%p==0:u+=1
    a[0]=p*u;return a
def _portfolio_det(m:list[list[int]])->int:
    old=1;sign=1
    for k in range(len(m)-1):
        if not m[k][k]:
            r=next((r for r in range(k+1,len(m)) if m[r][k]),None)
            if r is None:return 0
            m[k],m[r]=m[r],m[k];sign=-sign
        piv=m[k][k]
        for i in range(k+1,len(m)):
            for j in range(k+1,len(m)):m[i][j]=(m[i][j]*piv-m[i][k]*m[k][j])//old
        old=piv
        for i in range(k+1,len(m)):m[i][k]=0
    return sign*m[-1][-1]
def _portfolio_disc(f:list[int])->int:
    d=[i*f[i] for i in range(1,9)];m=[]
    for r in range(7):m.append([0]*r+list(reversed(f))+[0]*(6-r))
    for r in range(8):m.append([0]*r+list(reversed(d))+[0]*(7-r))
    return abs(_portfolio_det(m))
def _portfolio_v(n:int,p:int)->int:
    k=0
    while n and n%p==0:k+=1;n//=p
    return k
def _portfolio_fp(f:list[int],lane:int,disc:int)->tuple:
    parts=tuple(tuple(x) if x is not None else () for x in (_degrees(f,p) for p in PRIMES))
    return (_sturm(f),parts,tuple(min(5,_portfolio_v(disc,p)) for p in (2,3,5,7,11)),lane)
def _portfolio_distance(a:tuple,b:tuple)->int:
    return 3*(a[0]!=b[0])+sum(2 for x,y in zip(a[1],b[1]) if x!=y)+sum(x!=y for x,y in zip(a[2],b[2]))+(a[3]!=b[3])
def _portfolio_quotas(n:int)->list[int]:
    w=[30,30,25,15];q=[n*x//100 for x in w]
    for i in sorted(range(4),key=lambda i:(-(n*w[i]%100),i))[:n-sum(q)]:q[i]+=1
    return q
def _tower_product(x:int,y:int,a:int,b0:int,b1:int,c0:int,c1:int,c2:int,c3:int)->list[int]:
    """Product of two basis monomials in [1,u,v,uv,w,uw,vw,uvw]."""
    # Terms are exponent triples (u,v,w).  Reducing w, then v, then u is a
    # particularly small exact implementation of the integral tower basis.
    terms={( (x&1)+(y&1), ((x>>1)&1)+((y>>1)&1), ((x>>2)&1)+((y>>2)&1)):1}
    rel=(((a,0,0),), ((b0,0,0),(b1,1,0)),
         ((c0,0,0),(c1,1,0),(c2,0,1),(c3,1,1)))
    for level in (2,1,0):
        while any(e[level]>=2 for e in terms):
            nxt={}
            for e,z in terms.items():
                if e[level]<2:
                    nxt[e]=nxt.get(e,0)+z;continue
                base=list(e);base[level]-=2
                for r,du,dv in rel[level]:
                    q=(base[0]+du,base[1]+dv,base[2])
                    nxt[q]=nxt.get(q,0)+z*r
            terms=nxt
    out=[0]*8
    for (eu,ev,ew),z in terms.items():out[eu+2*ev+4*ew]+=z
    return out

def _tower_char(theta:list[int],pars:tuple[int,int,int,int,int,int,int])->list[int]:
    a,b0,b1,c0,c1,c2,c3=pars
    m=[]
    for j in range(8):
        col=[0]*8
        for i,t in enumerate(theta):
            if t:
                q=_tower_product(i,j,a,b0,b1,c0,c1,c2,c3)
                for k,v in enumerate(q):col[k]+=t*v
        m.append(col)
    # Faddeev--LeVerrier, using columns.  All divisions are exact over Z.
    b=[r[:] for r in m];cs=[1]
    for k in range(1,9):
        tr=sum(b[i][i] for i in range(8));c=-tr//k
        if tr%k:return []
        cs.append(c)
        if k<8:
            for i in range(8):b[i][i]+=c
            b=[[sum(m[r][t]*b[t][s] for t in range(8)) for s in range(8)] for r in range(8)]
    return list(reversed(cs))

def _tower_tuple(seed:int,lane:int,n:int,h:int)->tuple[tuple[int,...],list[int]]|None:
    s=lambda i:_signed(seed,140+lane,n,i,h)
    # The two norm lanes are parametrised, rather than rejected into rarity.
    # In lane 1: b0^2-a*b1^2 is a square; in lane 2 it is a times a square.
    r=s(0) or 1; t=s(1) or 1
    if lane==1:
        x=2*r+(n&1); y=2*t+(n&1); a=x*y; b0=(x+y)//2; b1=1
    elif lane==2:
        a=r*r+t*t; b0=a; b1=r
    else:
        a=s(0) or 2; b0=s(1); b1=s(2) or 1
    if a in (0,1) or int(abs(a)**0.5)**2==abs(a):return None
    if b0*b0-a*b1*b1==0:return None
    # The fourth lane fixes simple trace/conjugate-pair relations in K1;
    # the other lanes retain generic final radicands.
    if lane==3:
        c0=s(3) or 1;c1=0;c2=s(4) or 1;c3=-c2 if n&1 else c2
    else:
        c0=s(3) or 1;c1=s(4);c2=s(5);c3=s(6)
    # Keep the third extension genuinely over K2, rather than silently
    # collapsing the final radicand back into K1.
    if c0==c1==c2==c3==0 or (c2==0 and c3==0):return None
    lam=s(7);mu=s(8);nu=s(9)
    theta=[0,mu,lam,nu,1,0,0,0] # w + lambda v + mu u + nu uv
    return (a,b0,b1,c0,c1,c2,c3),theta

def _tower_no_rational_factor(poly:list[int])->bool:
    """Reject when all usable good-prime patterns allow a proper Q-factor."""
    possible=set(range(1,5));usable=0
    for p in PRIMES:
        ds=_degrees(poly,p)
        if ds is None:continue
        usable+=1;sums={0}
        for d in ds:sums|={x+d for x in tuple(sums)}
        possible&=sums
    return usable>0 and not possible

def generate_candidates(seed:int,budget:int)->list[list[int]]:
    """Exactly ``budget`` deterministic, distinct monic octics from towers."""
    if isinstance(budget,bool) or not isinstance(budget,int):raise TypeError("budget must be an integer")
    if budget<0:raise ValueError("budget must be nonnegative")
    answer=[];seen=set();serial=[0]*4
    # Round-robin gives four equal sublanes to within one element.
    for pos in range(budget):
        lane=pos%4; chosen=None
        # Fixed work cap: shells expand geometrically, and every retry is fresh.
        for attempt in range(28):
            n=serial[lane];serial[lane]+=1
            h=SHELLS[min(len(SHELLS)-1,(n//4+attempt//9)%len(SHELLS))]
            made=_tower_tuple(seed,lane,n,h)
            if made is None:continue
            pars,theta=made;poly=_tower_char(theta,pars)
            if len(poly)!=9 or poly[-1]!=1 or not poly[0] or _canonical(poly) in seen:continue
            # Squarefree good-prime reductions certify nonzero discriminant;
            # require their factor degrees to rule out every rational degree.
            if not _tower_no_rational_factor(poly):continue
            chosen=poly;break
        # A constrained cell may be sparse.  Its documented completion is a
        # fresh unconstrained tower tuple, never a catalogue polynomial.
        if chosen is None:
            for attempt in range(48):
                n=serial[0];serial[0]+=1;made=_tower_tuple(seed,0,n,SHELLS[(n+attempt)%len(SHELLS)])
                if made is None:continue
                pars,theta=made;poly=_tower_char(theta,pars)
                if len(poly)==9 and poly[-1]==1 and poly[0] and _canonical(poly) not in seen:
                    chosen=poly;break
        if chosen is None: # unreachable in normal shells, retains totality.
            k=pos+1
            chosen=[2*k+1,0,0,0,0,0,0,0,1]
            while _canonical(chosen) in seen:k+=budget+1;chosen=[2*k+1,0,0,0,0,0,0,0,1]
        seen.add(_canonical(chosen));answer.append(chosen)
    return answer
