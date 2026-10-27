"""Level-1 analysis + system-level performance sweeps (figures -> ../docs/*.png, numbers -> ../docs/results.txt)"""
import sys, os, time
import numpy as np
from math import comb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ccsds_model import *

DOCS = os.path.join(os.path.dirname(__file__), "..", "docs")
os.makedirs(DOCS, exist_ok=True)
out = open(os.path.join(DOCS, "results.txt"), "w")
def P(*a):
    s = " ".join(str(x) for x in a); print(s); out.write(s + "\n")

rng = np.random.default_rng(2026)
asm_bits = np.array(bytes_to_bits(ASM.to_bytes(4, "big")), dtype=np.int8)

def p_detect(T, p):          # marker accepted: <= T of 32 bits flipped
    return sum(comb(32, k) * p**k * (1-p)**(32-k) for k in range(T+1))
def p_false(T, both=True):   # random 32-bit window accepted (per bit position)
    return (2 if both else 1) * sum(comb(32, k) for k in range(T+1)) / 2**32

# ---------------------------------------------------------------- 1. detection / false alarm vs BER (theory + Monte Carlo)
P("== 1. 32-bit ASM correlator: theory vs Monte-Carlo (BER = raw channel bit error rate) ==")
bers = np.array([0.0, 0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.13, 0.16, 0.20])
Ts = [0, 1, 2, 3, 4, 6, 8]
NFR, SPACING = 20000, 200        # 20000 markers in random data, 200 bit spacing
def mc_detect(p, T):
    x = rng.integers(0, 2, NFR * SPACING).astype(np.int8)
    ends = np.arange(NFR) * SPACING + 100 + 31
    for e in ends: x[e-31:e+1] = asm_bits
    y = x ^ (rng.random(x.size) < p).astype(np.int8)
    corr = np.correlate(2*y.astype(np.int16)-1, 2*asm_bits.astype(np.int16)-1, mode="valid")   # +32 = perfect
    ham = (32 - corr) // 2                                  # index i -> window ending at i+31
    det = ham[ends - 31]
    return det
MC = {}
fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
cols = plt.cm.viridis(np.linspace(0, .9, len(Ts)))
tab = ["T   " + " ".join("BER=%.2f" % b for b in bers)]
for T, c in zip(Ts, cols):
    th = [p_detect(T, b) for b in bers]
    mc = []
    for b in bers:
        mc.append(float(np.mean(mc_detect(b, T) <= T)) if b > 0 else 1.0)
    ax[0].plot(bers, th, "-", color=c, label="T=%d" % T)
    ax[0].plot(bers, mc, "o", color=c, ms=4)
    tab.append("%-3d " % T + " ".join("%.4f " % t for t in th) + "  (theory)")
    tab.append("    " + " ".join("%.4f " % t for t in mc) + "  (Monte-Carlo)")
ax[0].set_xlabel("raw channel bit-error rate"); ax[0].set_ylabel("P(marker detected)")
ax[0].set_title("Detection probability  (line = theory, dots = simulation)"); ax[0].grid(alpha=.3); ax[0].legend(ncol=2)
P("\n".join(tab))

# false alarms on pure random data
P("\nFalse-alarm probability per bit position (random data):")
Tf = list(range(0, 9))
th_f = [p_false(T) for T in Tf]
mc_f = []
big = rng.integers(0, 2, 20_000_000).astype(np.int8)
corr = np.correlate(2*big.astype(np.int16)-1, 2*asm_bits.astype(np.int16)-1, mode="valid")
ham_all = (32 - corr) // 2
hist = np.bincount(ham_all, minlength=33)
for T in Tf:
    cnt = hist[:T+1].sum() + hist[32-T:].sum()          # both polarities
    mc_f.append(cnt / ham_all.size)
    P("  T=%d  theory %.3e   simulated %.3e  (%d hits in 2e7 bits)   expected false alarms per 1115-byte frame: %.2e"
      % (T, th_f[T], mc_f[-1], cnt, th_f[T]*(32+8*1115)))
ax[1].semilogy(Tf, th_f, "k-", label="theory (both polarities)")
ax[1].semilogy([t for t, m in zip(Tf, mc_f) if m > 0], [m for m in mc_f if m > 0], "ro", label="simulation (2e7 bits)")
ax[1].set_xlabel("tolerance T (max mismatching bits)"); ax[1].set_ylabel("false alarms per bit")
ax[1].set_title("False-alarm rate vs tolerance"); ax[1].grid(alpha=.3, which="both"); ax[1].legend()
plt.tight_layout(); plt.savefig(os.path.join(DOCS, "fig1_detect_false_alarm.png"), dpi=130); plt.close()

# ASM autocorrelation (why bit-slip windows are safe)
full = bytes_to_bits(ASM.to_bytes(4, "big"))
P("\nASM shift-distance (min Hamming distance between ASM and itself shifted by s, any data fill):")
for s in range(1, 8):
    best = 99
    for fill in range(2**s):
        fb = [(fill >> i) & 1 for i in range(s)]
        win = (fb + full)[:32]                      # window that has slid s bits early
        d = sum(a != b for a, b in zip(win, full))
        best = min(best, d)
    # window that is s bits late (ASM partially left)
    bestl = 99
    for fill in range(2**s):
        fb = [(fill >> i) & 1 for i in range(s)]
        win = (full + fb)[s:s+32]
        d = sum(a != b for a, b in zip(win, full))
        bestl = min(bestl, d)
    P("  shift %d: min distance early=%d late=%d  -> slip tolerance T_SLIP must stay below %d" % (s, best, bestl, min(best, bestl)))

# ---------------------------------------------------------------- 2. FSM level sweeps
FB = 128; L = 32 + 8*FB
def trial(cfg, esn0_db, nfr=40, slips=0, seed=None, W=None, rngl=None):
    r = rngl if rngl is not None else rng
    ber = ber_from_esn0(esn0_db)
    junk = int(r.integers(0, 3*L))
    bits, sent, starts = [], [], []
    bits = list(r.integers(0, 2, junk))
    for k in range(nfr):
        f = make_frame(r, FB, 0x0AB, int(r.integers(0, 8)), k, k)
        starts.append(len(bits)); sent.append(f); bits += cadu_bits(f)
    bits += list(r.integers(0, 2, 64))
    b = np.array(bits, dtype=np.uint8)
    b ^= (r.random(b.size) < ber).astype(np.uint8)
    b = list(b)
    for pos in sorted(r.integers(starts[8], starts[nfr-6], slips), reverse=True) if slips else []:
        if r.random() < .5: del b[pos]
        else: b.insert(pos, int(r.integers(0, 2)))
    s = FrameSync(FB=FB, **cfg); s.run(b)
    sb = np.array([bytes_to_bits(f) for f in sent], dtype=np.uint8)
    aligned = []
    for fr in s.frames:
        bb = np.array(bytes_to_bits(fr['data']), dtype=np.uint8)
        hd = (sb != bb).sum(axis=1); k = int(hd.argmin())
        aligned.append((k, hd[k] < 0.3*bb.size, fr))
    return s, aligned

CFGS = {"strict (0,2,4)": dict(T_SEARCH=0, T_CHECK=2, T_LOCK=4, T_SLIP=1),
        "default (2,4,6)": dict(T_SEARCH=2, T_CHECK=4, T_LOCK=6, T_SLIP=2),
        "loose (4,6,8)":  dict(T_SEARCH=4, T_CHECK=6, T_LOCK=8, T_SLIP=3)}
esn0s = [-2, -1, 0, 1, 2, 3, 4, 6]
NT = 60
P("\n== 2. FSM performance vs Es/N0 (hard-decision BPSK/AWGN),  %d trials x 40 frames of %d bytes each ==" % (NT, FB))
P("%-16s %7s %7s | %-22s %-22s %-18s" % ("config", "Es/N0", "rawBER", "frames delivered&aligned", "mean frames to lock", "loss-of-lock /1000fr"))
res = {}
for name, cfg in CFGS.items():
    res[name] = []
    for e in esn0s:
        deliv = lock_lat = lol = tot = nlock = 0
        for t in range(NT):
            s, al = trial(cfg, e)
            ok_frames = [k for (k, a, fr) in al if a and (fr['good'] or fr['fly'])]
            deliv += len(set(ok_frames)); tot += 40
            lol += s.lol
            goods = [k for (k, a, fr) in al if a and fr['good']]
            if goods: lock_lat += goods[0] + 1; nlock += 1
        res[name].append((deliv/tot, lock_lat/max(nlock, 1), 1000*lol/tot))
        P("%-16s %7.1f %7.4f | %-22.3f %-22.2f %-18.2f" % (name, e, ber_from_esn0(e), deliv/tot, lock_lat/max(nlock, 1), 1000*lol/tot))
fig, ax = plt.subplots(1, 3, figsize=(14, 4))
for name in CFGS:
    r_ = np.array(res[name])
    ax[0].plot(esn0s, r_[:, 0], "o-", label=name); ax[1].plot(esn0s, r_[:, 1], "o-", label=name); ax[2].semilogy(esn0s, r_[:, 2] + 1e-3, "o-", label=name)
ax[0].set_title("Frames correctly delivered (fraction of 40)"); ax[1].set_title("Frames until first verified lock")
ax[2].set_title("Loss-of-lock events per 1000 frames (+1e-3 for log axis)")
for a in ax: a.set_xlabel("Es/N0 (dB)"); a.grid(alpha=.3)
ax[0].legend(); plt.tight_layout(); plt.savefig(os.path.join(DOCS, "fig2_fsm_vs_esn0.png"), dpi=130); plt.close()

# false candidate rate of search (monte carlo) vs analytic false lock
P("\n== 3. False lock on pure noise ==")
for name, cfg in CFGS.items():
    ps = p_false(cfg['T_SEARCH']); pc = p_false(cfg['T_CHECK'], both=False)
    P("%-16s candidate rate/bit %.2e, verification pass prob. at wrong place %.2e -> false locks per 1e9 bits: %.3g (CHECK_N=1), %.3g (CHECK_N=2)"
      % (name, ps, pc, ps*pc*1e9, ps*pc*pc*1e9))

# ---------------------------------------------------------------- 4. bit-slip recovery
P("\n== 4. Bit-slip recovery: frames NOT delivered after one random 1-bit slip (deletion/insertion), BER 1%% ==")
for name, W, FLY in [("W=0 (no slip window)", 0, 3), ("W=4 (our design)", 4, 3)]:
    lost = []; reacq = 0; NS = 150
    for t in range(NS):
        s, al = trial(dict(T_SEARCH=2, T_CHECK=4, T_LOCK=6, T_SLIP=2, W=W, FLY_MAX=FLY), -0.0 + 4.3, slips=1)
        good_ok = {k for (k, a, fr) in al if a and fr['good']}
        lost.append(40 - 1 - len(good_ok)); reacq += s.acq - 1
    P("  %-22s mean frames lost per slip incl. 1 startup frame: %.2f  | re-acquisitions (full searches) per slip: %.2f" % (name, np.mean(lost), reacq/NS))
out.close()
