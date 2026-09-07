"""Bounded deterministic synthesis portfolio of monic integral octics."""
from __future__ import annotations
from fractions import Fraction
from functools import lru_cache
from math import comb, gcd, isqrt

MASK=(1<<64)-1
SHELLS=(1,2,3,5,8,12,17)
PRIMES=(3,5,7,11)
# generic, square-norm, radicand-norm, conjugate-pair towers; then supplements
# The first two lanes are the two archimedean forms of the Q8 construction.
# Keeping their quotas separate makes a weak sign regime visible to evaluation.
WEIGHTS=(26,26,10,10,12,6,4,3,3)

def _mix(x:int)->int:
    x=(x+0x9E3779B97F4A7C15)&MASK;x=((x^(x>>30))*0xBF58476D1CE4E5B9)&MASK
    x=((x^(x>>27))*0x94D049BB133111EB)&MASK;return x^(x>>31)
def _word(seed:int,lane:int,n:int,i:int)->int:
    return _mix((seed&MASK)^(lane+1)*0xD1B54A32D192ED03^(n+1)*0x94D049BB133111EB^(i+1)*0xBF58476D1CE4E5B9)
def _signed(seed:int,lane:int,n:int,i:int,h:int)->int:return _word(seed,lane,n,i)%(2*h+1)-h
def _trim(a:list[int])->list[int]:
    while len(a)>1 and not a[-1]:a.pop()
    return a
def _add(a:list[int],b:list[int])->list[int]:
    z=[0]*max(len(a),len(b))
    for i,x in enumerate(a):z[i]+=x
    for i,x in enumerate(b):z[i]+=x
    return _trim(z)
def _mul(a:list[int],b:list[int])->list[int]:
    z=[0]*(len(a)+len(b)-1)
    for i,x in enumerate(a):
        for j,y in enumerate(b):z[i+j]+=x*y
    return _trim(z)
def _compose(a:list[int],b:list[int])->list[int]:
    z=[0]
    for x in reversed(a):z=_add(_mul(z,b),[x])
    return z
def _canonical(a:list[int])->tuple[int,...]:return min(tuple(a),tuple((-1)**i*x for i,x in enumerate(a)))

# K=Q(u,v,w), u^2=a, v^2=b0+b1*u, w^2=c0+c1*u+c2*v+c3*u*v.
def _tower_product(x:int,y:int,p:tuple[int,...])->list[int]:
    a,b0,b1,c0,c1,c2,c3=p
    terms={((x&1)+(y&1),((x>>1)&1)+((y>>1)&1),((x>>2)&1)+((y>>2)&1)):1}
    rel=(((a,0,0),),((b0,0,0),(b1,1,0)),((c0,0,0),(c1,1,0),(c2,0,1),(c3,1,1)))
    for level in (2,1,0):
        while any(e[level]>=2 for e in terms):
            nxt={}
            for e,z in terms.items():
                if e[level]<2:nxt[e]=nxt.get(e,0)+z;continue
                q=list(e);q[level]-=2
                for r,du,dv in rel[level]:
                    k=(q[0]+du,q[1]+dv,q[2]);nxt[k]=nxt.get(k,0)+z*r
            terms=nxt
    out=[0]*8
    for (u,v,w),z in terms.items():out[u+2*v+4*w]+=z
    return out
def _tower_char(theta:list[int],p:tuple[int,...])->list[int]:
    m=[]
    for j in range(8):
        col=[0]*8
        for i,t in enumerate(theta):
            if t:
                q=_tower_product(i,j,p)
                for k,x in enumerate(q):col[k]+=t*x
        m.append(col)
    b=[r[:] for r in m];cs=[1]
    for k in range(1,9):
        tr=sum(b[i][i] for i in range(8))
        if tr%k:return []
        c=-tr//k;cs.append(c)
        if k<8:
            for i in range(8):b[i][i]+=c
            b=[[sum(m[r][t]*b[t][s] for t in range(8)) for s in range(8)] for r in range(8)]
    return list(reversed(cs))

def _biquad_product(x:list[Fraction],y:list[Fraction],a:int,b:int)->list[Fraction]:
    """Multiply in Q(sqrt(a), sqrt(b)), in the basis 1,u,v,uv."""
    z=[Fraction(0)]*4
    for i,r in enumerate(x):
        for j,s in enumerate(y):
            eu=(i&1)+(j&1);ev=(i>>1)+(j>>1)
            z[(eu&1)+2*(ev&1)]+=r*s*(a if eu>1 else 1)*(b if ev>1 else 1)
    return z

def _biquad_conjugate(x:list[Fraction],flip_u:bool,flip_v:bool)->list[Fraction]:
    return [z*(-1 if flip_u and i&1 else 1)*(-1 if flip_v and i&2 else 1)
            for i,z in enumerate(x)]

def _null_vector(rows:list[list[Fraction]])->list[Fraction]|None:
    """Return one vector in a four-column rational nullspace, if nonzero."""
    rows=[row[:] for row in rows];pivot_row=0;pivots=[]
    for column in range(4):
        source=next((i for i in range(pivot_row,len(rows)) if rows[i][column]),None)
        if source is None:continue
        rows[pivot_row],rows[source]=rows[source],rows[pivot_row]
        divisor=rows[pivot_row][column]
        rows[pivot_row]=[x/divisor for x in rows[pivot_row]]
        for i in range(len(rows)):
            if i!=pivot_row and rows[i][column]:
                scale=rows[i][column]
                rows[i]=[x-scale*y for x,y in zip(rows[i],rows[pivot_row])]
        pivots.append(column);pivot_row+=1
    free=next((i for i in range(4) if i not in pivots),None)
    if free is None:return None
    answer=[Fraction(0)]*4;answer[free]=1
    for row,column in enumerate(pivots):answer[column]=-rows[row][free]
    return answer

def _integer_vector(x:list[Fraction])->tuple[int,...]:
    denominator=1
    for value in x:denominator=denominator*value.denominator//gcd(denominator,value.denominator)
    answer=[int(value*denominator) for value in x];common=0
    for value in answer:common=gcd(common,abs(value))
    return tuple(value//common for value in answer)

def _quadratic_sign(x:int,y:int,d:int)->int:
    """Exact sign of x+y sqrt(d), for positive nonsquare d."""
    if not y:return (x>0)-(x<0)
    if not x or (x>0)==(y>0):return (y>0)-(y<0) if not x else (x>0)-(x<0)
    comparison=x*x-d*y*y
    return ((x>0)-(x<0))*((comparison>0)-(comparison<0))

def _squarefree(value:int)->bool:
    divisor=2
    while divisor*divisor<=value:
        if value%(divisor*divisor)==0:return False
        divisor+=1 if divisor==2 else 2
    return True

def _biquad_sign(c:tuple[int,...],a:int,b:int,sign_u:int,sign_v:int)->int:
    """Exact sign of a chosen real conjugate of a biquadratic element."""
    x0,x1=c[0],sign_u*c[1]
    y0,y1=sign_v*c[2],sign_u*sign_v*c[3]
    sx=_quadratic_sign(x0,x1,a);sy=_quadratic_sign(y0,y1,a)
    if not sy:return sx
    if not sx:return sy
    if sx==sy:return sx
    square0=x0*x0+a*x1*x1-b*(y0*y0+a*y1*y1)
    square1=2*(x0*x1-b*y0*y1)
    comparison=_quadratic_sign(square0,square1,a)
    return comparison if sx>0 else -comparison

def _q8_radicand(a:int,b:int,h_u:list[Fraction],h_v:list[Fraction])->tuple[int,...]|None:
    """Solve c^s=h_s^2 c for both lifts, then check the Q8 cocycle."""
    rows=[]
    for flip_u,flip_v,h in ((True,False,h_u),(False,True,h_v)):
        square=_biquad_product(h,h,a,b);columns=[]
        for j in range(4):
            unit=[Fraction(int(i==j)) for i in range(4)]
            left=_biquad_conjugate(unit,flip_u,flip_v)
            right=_biquad_product(square,unit,a,b)
            columns.append([x-y for x,y in zip(left,right)])
        rows.extend([[columns[j][i] for j in range(4)] for i in range(4)])
    c=_null_vector(rows)
    if c is None:return None
    c=_integer_vector(c)
    rational_c=[Fraction(x) for x in c]
    # These are precisely the lift-square and anticommutation identities.
    if _biquad_conjugate(rational_c,True,False)!=_biquad_product(_biquad_product(h_u,h_u,a,b),rational_c,a,b):return None
    if _biquad_conjugate(rational_c,False,True)!=_biquad_product(_biquad_product(h_v,h_v,a,b),rational_c,a,b):return None
    if _biquad_conjugate(h_v,True,False)!=[-x for x in h_v]:return None
    return c

@lru_cache(maxsize=1)
def _q8_templates()->tuple[tuple[int,...],...]:
    """Bounded rational-point search for Witt quaternion embedding data.

    h_u has norm -1 over Q(sqrt(b)); h_v has norm -1 over Q(sqrt(a)) and
    changes sign under u.  Their verified anticommutation is the non-split
    central cocycle, rather than an ordinary quadratic tower relation.
    """
    found=[];seen=set()
    for p in range(1,13):
        for q in range(1,7):
            if (p*p+1)%(q*q):continue
            a=(p*p+1)//(q*q)
            if a<2 or not _squarefree(a):continue
            h_u=[Fraction(p),Fraction(q),Fraction(0),Fraction(0)]
            for denominator in range(1,7):
                for x in range(1,8):
                    for y in range(1,5):
                        numerator=a*x*x+denominator*denominator
                        divisor=a*y*y
                        if numerator%divisor:continue
                        b=numerator//divisor
                        if b<2 or not _squarefree(b) or b==a or isqrt(a*b)**2==a*b:continue
                        h_v=[Fraction(0),Fraction(x,denominator),Fraction(0),Fraction(y,denominator)]
                        if _biquad_product(h_u,_biquad_conjugate(h_u,True,False),a,b)!=[Fraction(-1)]*1+[Fraction(0)]*3:continue
                        if _biquad_product(h_v,_biquad_conjugate(h_v,False,True),a,b)!=[Fraction(-1)]*1+[Fraction(0)]*3:continue
                        c=_q8_radicand(a,b,h_u,h_v)
                        if c is None:continue
                        if not all(_biquad_sign(c,a,b,su,sv)>0 for su in (-1,1) for sv in (-1,1)):continue
                        key=(a,b,c)
                        if key not in seen:seen.add(key);found.append((a,b,*c))
                        if len(found)>=24:return tuple(found)
    return tuple(found)

def _q8(seed:int,lane:int,n:int,h:int)->list[int]|None:
    templates=_q8_templates()
    if not templates:return None
    a,b,c0,c1,c2,c3=templates[_word(seed,lane,n,0)%len(templates)]
    if lane==1:c0,c1,c2,c3=-c0,-c1,-c2,-c3
    # Capping primitive-element coordinates prevents one large shell from
    # dominating characteristic-polynomial and Sturm costs.
    s=lambda i:_signed(seed,lane,n,i,min(3,max(2,h)))
    # A primitive element with a nonzero w coefficient generates the Q8 field.
    theta=[s(1),s(2) or 1,s(3) or 1,s(4),1,s(5),s(6),s(7)]
    return _tower_char(theta,(a,b,0,c0,c1,c2,c3))
def _tower(seed:int,lane:int,n:int,h:int)->list[int]|None:
    s=lambda i:_signed(seed,lane,n,i,h);r=s(0) or 1;t=s(1) or 1
    if lane==1:
        x,y=2*r+(n&1),2*t+(n&1);a,b0,b1=x*y,(x+y)//2,1
    elif lane==2:a,b0,b1=r*r+t*t,r*r+t*t,r
    else:a,b0,b1=s(0) or 2,s(1),s(2) or 1
    if a in (0,1) or isqrt(abs(a))**2==abs(a) or b0*b0==a*b1*b1:return None
    if lane==3:
        c0,c1,c2=s(3) or 1,0,s(4) or 1;c3=c2 if n&1 else -c2
    else:c0,c1,c2,c3=s(3) or 1,s(4),s(5),s(6)
    if not(c2 or c3):return None
    return _tower_char([0,s(8),s(7),s(9),1,0,0,0],(a,b0,b1,c0,c1,c2,c3))

def _tree(seed:int,n:int,h:int)->list[int]:
    q=[]
    for j in range(3):
        b=_signed(seed,20+j,n,0,h);c=_signed(seed,20+j,n,1,h)
        if (n+j)%4==0:c=b*b//4+1+abs(_signed(seed,20+j,n,2,h))
        q.append([c,b,1])
    f=_compose(q[0],_compose(q[1],q[2]));f[0]-=_signed(seed,24,n,0,h) or 1;return f
def _quartic(seed:int,n:int,h:int)->list[int]:
    s=lambda i:_signed(seed,30,n,i,h);k=n&3
    if k==1:return [s(0) or 1,0,s(1),0,1]
    if k==2:return [1,s(0),s(1),s(0),1]
    if k==3:
        p=(2,3,5)[n%3];u=s(0) or 1
        if u%p==0:u+=1
        return [p*u,p*s(1),p*s(2),p*s(3),1]
    return [s(0) or 1,s(1),s(2),s(3),1]
def _relative(seed:int,n:int,h:int)->list[int]|None:
    b=_signed(seed,31,n,0,h);mag=1+_word(seed,31,n,1)%(h+2);c=-mag if n&1 else b*b//4+mag+1
    if b*b==4*c:return None
    f=_quartic(seed,n,h);shift=(1,-1,2,-2)[n&3];powers=[(1,0)]
    for _ in range(4):
        u,v=powers[-1];powers.append((-c*v,u-b*v))
    a,d=[0],[0]
    for degree,coef in enumerate(f):
        for j in range(degree+1):
            u,v=powers[j];term=[0]*(degree-j+1);term[-1]=coef*comb(degree,j)*(-shift)**j
            if u:a=_add(a,[u*x for x in term])
            if v:d=_add(d,[v*x for x in term])
    return _add(_add(_mul(a,a),[-b*x for x in _mul(a,d)]),[c*x for x in _mul(d,d)])
def _reciprocal(seed:int,n:int,h:int)->list[int]:
    s=lambda i:_signed(seed,40,n,i,h);g=[s(0) or 1,s(1),s(2),s(3),1];z=[0]*9
    for d,x in enumerate(g):
        for j in range(d+1):z[4+d-2*j]+=x*comb(d,j)
    return z
def _critical(seed:int,n:int,h:int)->list[int]:
    s=lambda i:_signed(seed,50,n,i,h);q=[5*(s(0) or 1),0,21*s(1),1];qq=_mul(q,q);f=[0]*9
    for i,x in enumerate(qq):f[i+2]=8*x//(i+2)
    f[0]=(1+_word(seed,51,n,0)%(h+3))**2;return f
def _eisenstein(seed:int,n:int,h:int)->list[int]:
    p=(2,3,5)[n%3];a=[p*_signed(seed,60,n,i,h) for i in range(8)]+[1];u=_signed(seed,61,n,0,h) or 1
    if u%p==0:u+=1
    a[0]=p*u;return a

def _mp(a:list[int],p:int)->list[int]:return _trim([x%p for x in a])
def _dr(a:list[int],b:list[int],p:int)->tuple[list[int],list[int]]:
    a=_mp(a[:],p);b=_mp(b[:],p);q=[0]*max(1,len(a)-len(b)+1);inv=pow(b[-1],-1,p)
    while len(a)>=len(b) and a!=[0]:
        d=len(a)-len(b);x=a[-1]*inv%p;q[d]=x
        for i,y in enumerate(b):a[i+d]=(a[i+d]-x*y)%p
        _trim(a)
    return _trim(q),a
def _gp(a:list[int],b:list[int],p:int)->list[int]:
    while b!=[0]:a,b=b,_dr(a,b,p)[1]
    inv=pow(a[-1],-1,p);return [x*inv%p for x in a]
def _power(a:list[int],n:int,f:list[int],p:int)->list[int]:
    z=[1]
    while n:
        if n&1:z=_dr(_mp(_mul(z,a),p),f,p)[1]
        a=_dr(_mp(_mul(a,a),p),f,p)[1];n//=2
    return z
def _degrees(poly:list[int],p:int)->tuple[int,...]|None:
    f=_mp(poly,p);d=[i*f[i] for i in range(1,len(f))]
    if len(f)!=9 or f[-1]==0 or _gp(f,d,p)!=[1]:return None
    ans=[];old=0
    for degree in range(1,5):
        total=len(_gp(f,_add(_power([0,1],p**degree,f,p),[-1]),p))-1
        ans += [degree]*((total-old)//degree);old=total
    if sum(ans)<8:ans.append(8-sum(ans))
    return tuple(ans)
def _screen(poly:list[int])->tuple[bool,tuple[tuple[int,...],...]]:
    possible=set(range(1,8));patterns=[]
    for p in PRIMES:
        ds=_degrees(poly,p)
        if ds is None:continue
        sums={0}
        for d in ds:sums|={x+d for x in tuple(sums)}
        possible&=sums;patterns.append(ds)
    return bool(patterns) and not possible,tuple(patterns)
def _sturm(poly:list[int])->int:
    seq=[_trim(poly[:]),_trim([i*poly[i] for i in range(1,len(poly))])]
    while len(seq[-1])>1:
        a=[Fraction(x) for x in seq[-2]];b=[Fraction(x) for x in seq[-1]]
        while len(a)>=len(b):
            q=a[-1]/b[-1];off=len(a)-len(b)
            for i,x in enumerate(b):a[i+off]-=q*x
            _trim(a)
        den=1
        for x in a:den=den*x.denominator//gcd(den,x.denominator)
        seq.append(_trim([-int(x*den) for x in a]))
    plus=[1 if q[-1]>0 else -1 for q in seq]
    minus=[(1 if q[-1]>0 else -1)*(-1)**(len(q)-1) for q in seq]
    return sum(x!=y for x,y in zip(minus,minus[1:]))-sum(x!=y for x,y in zip(plus,plus[1:]))
def _det(m:list[list[int]])->int:
    old=1;sign=1
    for k in range(len(m)-1):
        if not m[k][k]:
            r=next((r for r in range(k+1,len(m)) if m[r][k]),None)
            if r is None:return 0
            m[k],m[r]=m[r],m[k];sign=-sign
        pivot=m[k][k]
        for r in range(k+1,len(m)):
            for c in range(k+1,len(m)):m[r][c]=(m[r][c]*pivot-m[r][k]*m[k][c])//old
        old=pivot
        for r in range(k+1,len(m)):m[r][k]=0
    return sign*m[-1][-1]
def _discriminant(f:list[int])->int:
    d=[i*f[i] for i in range(1,9)];m=[]
    for r in range(7):m.append([0]*r+list(reversed(f))+[0]*(6-r))
    for r in range(8):m.append([0]*r+list(reversed(d))+[0]*(7-r))
    return abs(_det(m))

def _quotas(n:int)->list[int]:
    q=[n*w//100 for w in WEIGHTS]
    for i in sorted(range(9),key=lambda i:(-(n*WEIGHTS[i]%100),i))[:n-sum(q)]:q[i]+=1
    return q
def _schedule(n:int)->list[int]:
    q=_quotas(n);used=[0]*9;out=[]
    for pos in range(n):
        lane=max((i for i in range(9) if used[i]<q[i]),key=lambda i:(q[i]*(pos+1)-used[i]*n,-i))
        used[lane]+=1;out.append(lane)
    return out
def _make(seed:int,lane:int,n:int,h:int)->list[int]|None:
    if lane<2:return _q8(seed,lane,n,h)
    if lane<4:return _tower(seed,lane,n,h)
    if lane==4:return _tree(seed,n,h)
    if lane==5:return _relative(seed,n,h)
    if lane==6:return _reciprocal(seed,n,h)
    if lane==7:return _critical(seed,n,h)
    return _eisenstein(seed,n,h)
def _completion(seed:int,serial:list[int],seen:set[tuple[int,...]],position:int)->list[int]:
    # Strict bounded spill from a failed protected quota.
    for lane,limit in ((0,18),(8,18)):
        for j in range(limit):
            n=serial[lane];serial[lane]+=1;f=_make(seed,lane,n,SHELLS[(n+j)%len(SHELLS)])
            if not f or len(f)!=9 or f[-1]!=1 or not f[0] or _canonical(f) in seen:continue
            good,pat=_screen(f)
            if pat and (good or lane==8):return f
    # A final, collision-free Eisenstein control: its 101-divisible constant
    # term distinguishes it from the normal 2/3/5 Eisenstein lanes.
    u=2*position+1
    if u%101==0:u+=2
    return [101*u,101,0,0,0,0,0,0,1]

def generate_candidates(seed:int,budget:int)->list[list[int]]:
    """Return exactly budget unique, certified monic degree-eight vectors."""
    if isinstance(budget,bool) or not isinstance(budget,int):raise TypeError("budget must be an integer")
    if budget<0:raise ValueError("budget must be nonnegative")
    seen=set();occupancy={};serial=[0]*9;out=[];record_start=budget-budget*5//100
    for position,lane in enumerate(_schedule(budget)):
        proposals=[]
        for attempt in range(3):
            n=serial[lane];serial[lane]+=1
            # Tower characteristic polynomials grow quickly; their low-height
            # shells remain broad while keeping exact Sturm arithmetic cheap.
            shells=SHELLS[:5] if lane<4 else SHELLS
            h=shells[(n//3+attempt+_word(seed,lane,position,0))%len(shells)]
            f=_make(seed,lane,n,h)
            if not f or len(f)!=9 or f[-1]!=1 or not f[0]:continue
            key=_canonical(f)
            if key in seen:continue
            good,patterns=_screen(f)
            # Eisenstein is a separate proof of irreducibility; every accepted
            # candidate nevertheless has a squarefree good-prime fingerprint.
            if not patterns or not(good or lane==8):continue
            roots=_sturm(f);cell=(lane,roots,patterns[:2]);used=occupancy.get(cell,0)
            height=max(abs(x) for x in f[:-1]);sparse=sum(x!=0 for x in f[:-1])
            disc=_discriminant(f) if position>=record_start and used else 0
            proposals.append(((used,disc,height,sparse),f,key,cell))
        if proposals:
            _,chosen,key,cell=min(proposals,key=lambda x:x[0]);occupancy[cell]=occupancy.get(cell,0)+1
        else:chosen=_completion(seed,serial,seen,position);key=_canonical(chosen)
        seen.add(key);out.append(chosen)
    return out
