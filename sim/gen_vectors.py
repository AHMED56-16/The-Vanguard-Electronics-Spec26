"""
Vector generator for the RTL testbench.  For every scenario it writes into sim/vectors/<name>/ :
    stream.txt  (one bit per line)  exp.hex  sum.hex  cfg.txt (+args for the simulator)
and checks the golden model against GROUND TRUTH (the frames that were really transmitted).
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "model"))
from ccsds_model import *

OUT = os.path.join(os.path.dirname(__file__), "vectors")


def build_stream(rng, fb, nfr, junk=53, derand=False, crc_en=True, vc_pool=range(8), tail=96):
    bits, sent, starts = list(map(int, rng.integers(0, 2, junk))), [], []
    mc, vcf = 0, [0] * 8
    for k in range(nfr):
        vc = int(rng.choice(list(vc_pool)))
        f = make_frame(rng, fb, 0x0AB, vc, mc, vcf[vc], crc_en)
        mc += 1
        vcf[vc] += 1
        starts.append(len(bits))
        sent.append(f)
        bits += cadu_bits(f, derand)
    bits += list(map(int, rng.integers(0, 2, tail)))
    return np.array(bits, dtype=np.uint8), sent, starts


def corrupt(bits, rng, ber=0.0, invert=False, dels=(), inss=(), garbage=()):
    b = bits.copy()
    if ber > 0:
        b ^= (rng.random(b.size) < ber).astype(np.uint8)
    for (a, c) in garbage:
        b[a:c] = rng.integers(0, 2, c - a)
    b = list(map(int, b))
    for pos in sorted(dels, reverse=True):
        del b[pos]
    for pos in sorted(inss, reverse=True):
        b.insert(pos, int(rng.integers(0, 2)))
    b = np.array(b, dtype=np.uint8)
    if invert:
        b ^= 1
    return b


def write_vec(name, bits, model, cfg, gap=0):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "stream.txt"), "w").write("\n".join(map(str, bits)) + "\n")
    with open(os.path.join(d, "exp.hex"), "w") as f:
        for fr in model.frames:
            flags = fr['good'] | (fr['fly'] << 1) | (fr['slip'] << 2) | (fr['crc_ok'] << 3)
            f.write("%02x\n%02x\n" % (flags, fr['vcid']))
            f.write("\n".join("%02x" % x for x in fr['data']) + "\n")
    with open(os.path.join(d, "sum.hex"), "w") as f:
        f.write("%04x\n%04x\n%04x\n%04x\n0000\n0000\n0000\n0000\n" % (model.acq, model.slips, model.lol, len(model.frames)))
    # layout: acq slips lol nframes pad[4] -> vc counts must be at index 4..11 -> rewrite properly
    vals = [model.acq, model.slips, model.lol, len(model.frames)] + list(model.vc_count)
    with open(os.path.join(d, "sum.hex"), "w") as f:
        f.write("\n".join("%04x" % v for v in vals) + "\n")
    json.dump(dict(cfg, nbits=len(bits), nexp=len(model.frames), gap=gap), open(os.path.join(d, "cfg.json"), "w"))
    return d


def truth_check(model, sent, label):
    """GROUND-TRUTH alignment check.  Every delivered frame is compared with all frames that were really sent
    (Hamming distance on the bits).  A frame is 'aligned' if it matches some sent frame within 30 % of bits
    (random misalignment gives ~50 %).  Frames flagged GOOD must be aligned, in increasing order."""
    sb = np.array([bytes_to_bits(f) for f in sent], dtype=np.uint8)
    n_good = n_good_ok = n_other = n_other_ok = 0
    last = -1
    in_order = True
    for fr in model.frames:
        bits = np.array(bytes_to_bits(fr['data']), dtype=np.uint8)
        hd = (sb != bits).sum(axis=1)
        k = int(hd.argmin())
        aligned = hd[k] < 0.30 * bits.size
        if fr['good']:
            n_good += 1
            n_good_ok += int(aligned)
            if aligned:
                in_order &= (k > last)
                last = k
        else:
            n_other += 1
            n_other_ok += int(aligned)
    return (n_good == n_good_ok) and in_order, n_good, n_good_ok, n_other, n_other_ok


def scenario(name, fb=64, nfr=40, seed=1, ber=0.0, invert=False, dels=(), inss=(), derand=False, garbage=(),
             gap=0, junk=53, **kw):
    rng = np.random.default_rng(seed)
    bits, sent, starts = build_stream(rng, fb, nfr, junk=junk, derand=derand)
    L = 32 + 8 * fb
    dels = [starts[a] + o for a, o in dels]
    inss = [starts[a] + o for a, o in inss]
    garbage = [(starts[a], starts[b]) for a, b in garbage]
    stream = corrupt(bits, rng, ber, invert, dels, inss, garbage)
    cfg = dict(dict(FB=fb, DERAND_EN=int(derand)), **kw)
    m = FrameSync(FB=fb, derand=derand, **{k: v for k, v in kw.items() if k in
                  ("T_SEARCH", "T_CHECK", "T_LOCK", "T_SLIP", "W", "CHECK_N", "FLY_MAX")})
    m.run(stream)
    ok, ng, ngok, no, nook = truth_check(m, sent, name)
    write_vec(name, stream, m, cfg, gap)
    s = m.summary()
    print("%-14s bits=%-7d model: frames=%-3d good=%-3d fly=%-2d slipF=%d acq=%d slips=%d lol=%d | truth: GOOD aligned %d/%d, other aligned %d/%d  %s"
          % (name, len(stream), s['nframes'], s['good'], s['fly'], s['slipf'], s['acq'], s['slips'], s['lol'], ngok, ng, nook, no, "OK" if ok else "MISALIGNED"))
    assert ok, "a frame flagged GOOD was not aligned with a transmitted frame!"
    return m


if __name__ == "__main__":
    scenario("t01_clean", seed=1)
    scenario("t02_inverted", seed=2, invert=True)
    scenario("t03_ber1pct", seed=3, ber=0.01)
    scenario("t04_ber5pct", seed=4, ber=0.05, nfr=60)
    scenario("t05_ber10pct", seed=5, ber=0.10, nfr=60)
    scenario("t06_slips", seed=6, ber=0.01, nfr=60, dels=[(10, 700), (20, 40), (30, 300)], inss=[(15, 500), (25, 100), (40, 330)])
    scenario("t07_bigslip", seed=7, nfr=40, dels=[(10, 400)] , inss=[(20, 100)] * 1)   # 1-bit again, plus below
    scenario("t08_burst", seed=8, nfr=50, ber=0.01, garbage=[(15, 21)])
    scenario("t09_derand", seed=9, ber=0.02, derand=True, DERAND_EN=1)
    scenario("t10_gaps", seed=10, ber=0.03, gap=1)
    scenario("t11_junk_long", seed=11, junk=5001, ber=0.02)
    scenario("t12_realFB1115", fb=1115, nfr=12, seed=12, ber=0.02, dels=[(6, 5000)], gap=1)
    scenario("t13_checkN2", seed=13, ber=0.03, CHECK_N=2)
    scenario("t14_noslipW0", seed=14, ber=0.01, dels=[(10, 700)], W=0)
