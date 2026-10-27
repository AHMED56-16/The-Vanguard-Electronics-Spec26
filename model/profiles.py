import numpy as np, sys
sys.argv=['x']
src = open('analysis.py').read().split("# ---------------------------------------------------------------- 2. FSM level sweeps")[0]
# reuse only helper defs, avoid re-running section 1
exec("import numpy as np, os\nfrom math import comb\nfrom ccsds_model import *\nrng=np.random.default_rng(7)")
body = open('analysis.py').read()
a = body.index("FB = 128; L = 32 + 8*FB"); b = body.index("CFGS = {")
exec(body[a:b])
PROF = {"A  (2,4,6) CHECK_N=1": dict(T_SEARCH=2,T_CHECK=4,T_LOCK=6,T_SLIP=2,CHECK_N=1),
        "B  (4,6,8) CHECK_N=2": dict(T_SEARCH=4,T_CHECK=6,T_LOCK=8,T_SLIP=2,CHECK_N=2)}
print("%-22s %6s | delivered | frames-to-lock | LOL/1000" % ("profile","Es/N0"))
for n,c in PROF.items():
    for e in (-2,0,2):
        d=lk=nl=lol=0; NT=60
        for t in range(NT):
            s,al=trial(c,e,nfr=40)
            d+=len({k for (k,a,fr) in al if a and (fr['good'] or fr['fly'])}); lol+=s.lol
            g=[k for (k,a,fr) in al if a and fr['good']]
            if g: lk+=g[0]+1; nl+=1
        print("%-22s %6.1f |  %.3f     |  %.2f          | %.2f" % (n,e,d/(NT*40),lk/max(nl,1),1000*lol/(NT*40)))
