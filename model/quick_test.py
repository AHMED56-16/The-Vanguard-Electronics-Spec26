import numpy as np
from ccsds_model import *
rng = np.random.default_rng(1)
FB = 64
def build(nfr, junk=37, inv=False, derand=False):
    bits = list(rng.integers(0, 2, junk))
    sent = []
    for k in range(nfr):
        vc = int(rng.integers(0, 8))
        f = make_frame(rng, FB, 0x0AB, vc, k, k)
        sent.append(f); bits += cadu_bits(f, derand)
    bits += list(rng.integers(0, 2, 64))
    bits = np.array(bits, dtype=np.uint8)
    if inv: bits ^= 1
    return bits, sent

# 1. clean, normal polarity
bits, sent = build(30)
s = FrameSync(FB=FB); s.run(bits)
got = [f['data'] for f in s.frames]
print("clean  :", s.summary()['nframes'], "frames; first delivered idx =", sent.index(got[0]), "all match:", got == sent[sent.index(got[0]):][:len(got)], "crc ok:", all(f['crc_ok'] for f in s.frames))
# 2. inverted
bits, sent = build(30, inv=True)
s = FrameSync(FB=FB); s.run(bits)
got = [f['data'] for f in s.frames]
print("invert :", len(got), "all match:", got == sent[sent.index(got[0]):][:len(got)], "pol", s.pol)
# 3. derand
bits, sent = build(30, derand=True)
s = FrameSync(FB=FB, derand=True); s.run(bits)
got = [f['data'] for f in s.frames]
print("derand :", len(got), "all match:", got == sent[sent.index(got[0]):][:len(got)])
# 4. slip: delete a bit in the middle, insert a bit in the middle
bits, sent = build(30)
L = 32 + 8*FB
for kind in ("delete", "insert"):
    b = list(bits)
    pos = 37 + 12*L + 100
    if kind == "delete": del b[pos]
    else: b.insert(pos, 1)
    s = FrameSync(FB=FB); s.run(b)
    sm = s.summary()
    print(kind, ":", sm['nframes'], "frames, good", sm['good'], "fly", sm['fly'], "slipf", sm['slipf'], "slips", sm['slips'], "lol", sm['lol'], "acq", sm['acq'])
# 5. 40-bit slip -> loss of lock then reacquire
b = list(bits); del b[37+12*L+100: 37+12*L+140]
s = FrameSync(FB=FB); s.run(b); print("big slip:", s.summary())
