import json, os, subprocess, sys
root = os.path.dirname(os.path.abspath(__file__))
rtl = os.path.join(root, "..", "rtl", "ccsds_frame_sync.v")
tb  = os.path.join(root, "..", "tb", "tb_ccsds_sync.v")
names = sorted(os.listdir(os.path.join(root, "vectors")))
allpass = True
for n in names:
    d = os.path.join(root, "vectors", n)
    cfg = json.load(open(os.path.join(d, "cfg.json")))
    exe = os.path.join(d, "sim.vvp")
    params = ["-Ptb_ccsds_sync.%s=%s" % (k, v) for k, v in cfg.items() if k not in ("nbits", "nexp", "gap")]
    r = subprocess.run(["iverilog", "-g2005", "-o", exe, "-s", "tb_ccsds_sync"] + params + [rtl, tb], capture_output=True, text=True)
    if r.returncode:
        print(n, "COMPILE ERROR\n", r.stderr); allpass = False; continue
    args = ["vvp", exe, "+stream=%s/stream.txt" % d, "+exp=%s/exp.hex" % d, "+sum=%s/sum.hex" % d,
            "+nbits=%d" % cfg["nbits"], "+nexp=%d" % cfg["nexp"], "+gap=%d" % cfg["gap"]]
    r = subprocess.run(args, capture_output=True, text=True)
    res = [l for l in r.stdout.splitlines() if l.startswith("RESULT") or l.startswith("ERROR")]
    print("%-14s" % n, " | ".join(res[:4]) if res else r.stdout[-300:] + r.stderr[-300:])
    allpass &= any("PASS" in l for l in res)
print("\nALL PASS" if allpass else "\nFAILURES")
