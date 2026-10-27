import numpy as np
from ccsds_model import *
exec(open('quick_test.py').read().split("# 1. clean")[0])
bits, sent = build(30)
L = 32 + 8*FB
for kind in ("delete","insert"):
    b = list(bits); pos = 37+12*L+100
    if kind=="delete": del b[pos]
    else: b.insert(pos,1)
    s = FrameSync(FB=FB); s.run(b)
    print(kind, [(('G' if f['good'] else '')+('F' if f['fly'] else '')+('S' if f['slip'] else ''), f['crc_ok']) for f in s.frames])
