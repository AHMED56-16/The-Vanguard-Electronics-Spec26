"""Cross-check: feed the Level-1 team's own bit streams into the Level-2 golden model and write RTL test vectors.
Run from this folder:  python3 xcheck_level1.py   then   cd ../sim && python3 run_all.py"""
import sys, os, csv
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model")); sys.path.insert(0, os.path.join(HERE, "..", "sim"))
from ccsds_model import FrameSync
import gen_vectors as gv

def load(path):
    return np.array([int(l.strip()) for l in open(path) if l.strip() in ("0", "1")], dtype=np.uint8)

for tag, fn in (("x01_vanguard_8dB", "vanguard_rx_8dB.txt"), ("x02_vanguard_2dB_slips", "vanguard_rx_2dB_slips.txt")):
    bits = load(os.path.join(HERE, fn))
    m = FrameSync(FB=64, T_SEARCH=2, T_CHECK=4, T_LOCK=6, T_SLIP=2, W=4, CHECK_N=1, FLY_MAX=3)
    m.run(bits)
    good_crc = [f for f in m.frames if f["crc_ok"]]
    msgs = []
    for f in good_crc:
        d = f["data"]; n = d[6]
        msgs.append((f["vcid"], bytes(d[7:7+n]).decode("ascii", "replace")))
    s = m.summary()
    print("%-24s bits=%-6d frames out=%d (good=%d fly=%d slip=%d) CRC-valid=%d  acq=%d slips=%d lol=%d"
          % (tag, len(bits), s["nframes"], s["good"], s["fly"], s["slipf"], len(good_crc), s["acq"], s["slips"], s["lol"]))
    for v, t in msgs[:3]: print("      VC%d  %s" % (v, t))
    gv.write_vec(tag, bits, m, dict(FB=64))
