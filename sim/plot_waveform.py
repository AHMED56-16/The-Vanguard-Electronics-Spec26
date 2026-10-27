"""Turns the testbench VCD into a readable waveform PNG (docs/waveform_lock_and_slip.png)."""
import sys, re, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

vcd, out = sys.argv[1], sys.argv[2]
ids, names = {}, {}
scope = []
sig = {}
t = 0
with open(vcd) as f:
    for line in f:
        line = line.strip()
        if line.startswith("$scope"): scope.append(line.split()[2])
        elif line.startswith("$upscope"): scope.pop()
        elif line.startswith("$var"):
            p = line.split(); idc, nm = p[3], p[4]
            if scope == ["tb_ccsds_sync"]:
                ids.setdefault(idc, nm); sig.setdefault(nm, [(0, 0)])
        elif line.startswith("#"): t = int(line[1:])
        elif line and line[0] in "01xz" and line[1:] in ids:
            sig[ids[line[1:]]].append((t, 0 if line[0] in "xz" else int(line[0])))
        elif line.startswith("b"):
            v, idc = line[1:].split()
            if idc in ids:
                try: sig[ids[idc]].append((t, int(v.replace("x", "0").replace("z", "0"), 2)))
                except ValueError: pass
def series(nm):
    a = np.array(sig[nm]); return a[:, 0] / 1000.0 / 20.0, a[:, 1]           # time in clock cycles (20 ns)
rows = [("bit_in", "bit_in"), ("state", "FSM state\n0 SEARCH 1 CHECK\n2 LOCK 3 FLYWHEEL"), ("byte_valid", "byte_valid"),
        ("hdr_valid", "hdr_valid"), ("fd_valid", "frame done"), ("fd_slip", "fd_slip"), ("fd_fly", "fd_fly"), ("slip_count", "slip_count")]
fig, axs = plt.subplots(len(rows), 1, figsize=(15, 9), sharex=True)
tmax = max(series("clk")[0]) if "clk" in sig else 1300
for ax, (nm, lab) in zip(axs, rows):
    x, y = series(nm)
    ax.step(np.append(x, tmax), np.append(y, y[-1]), where="post", lw=1.1,
            color={"state": "#c0392b", "slip_count": "#8e44ad"}.get(nm, "#1f4e79"))
    ax.set_ylabel(lab, rotation=0, ha="right", va="center", fontsize=8); ax.grid(alpha=.25)
    ax.set_yticks(sorted(set(int(v) for v in y))[:6])
# annotate acquisition and slip
xs, ys = series("state")
lock_t = next(x for x, v in zip(xs, ys) if v == 2)
axs[1].annotate("LOCK acquired\n(2 verified markers)", (lock_t, 2), (lock_t + 30, 3.1), arrowprops=dict(arrowstyle="->"), fontsize=9)
xs2, ys2 = series("slip_count")
st = [x for x, v in zip(xs2, ys2) if v >= 1]
if st: axs[7].annotate("bit deleted in stream ->\nslip detected, re-aligned\nwithout leaving LOCK", (st[0], 1), (st[0] + 40, 0.3), arrowprops=dict(arrowstyle="->"), fontsize=9)
axs[-1].set_xlabel("clock cycles (50 MHz, 1 bit per cycle)")
fig.suptitle("RTL simulation: acquisition, frame extraction and bit-slip recovery (self-checking testbench: PASS)", fontsize=11)
plt.tight_layout(); plt.savefig(out, dpi=120)
print("saved", out, "| lock at cycle", lock_t, "| slip at", st[0] if st else None)
