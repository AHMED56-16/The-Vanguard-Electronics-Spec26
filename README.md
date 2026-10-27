# The Vanguard — Electronics — SPEC'26
## CCSDS Telemetry Frame Synchronizer (Levels 1, 2 and 3)

**Team:** The Vanguard (NEDUET) | **Domain:** Electronics | **Event:** SPEC'26 Hackathon Module
**Members:** [Muhammad Ahmed Raza – Lead], [Muhammad Mahad Khan], [Syed M Yousha Hashmi ]   

A receiver sees one continuous stream of noisy bits. Every telemetry frame starts with the 32-bit CCSDS Attached Sync Marker `0x1ACFFC1D`.
This project finds those markers, survives bit slips, rejects false alarms, and extracts the frames per virtual channel.

| Level | What we built | Evidence in this repo |
|---|---|---|
| 1 – Model | Python BPSK/AWGN simulation, 32-bit correlator with threshold, CRC-verified frames, interactive offline lesson | `level1_python/`, `docs/test_logs/level1_python_*.txt`, `level1_python/results/performance.png` |
| 2 – RTL | Synthesizable Verilog: correlator, SEARCH/CHECK/LOCK/FLYWHEEL FSM, ±4-bit slip window, inverted-polarity handling, frame/header/CRC/VC extraction | `rtl/ccsds_frame_sync.v`, `tb/tb_ccsds_sync.v`, `docs/test_logs/rtl_regression_16_scenarios.txt`, `docs/waveform_lock_and_slip.png` |
| 3 – FPGA | Open-source synthesis + place-and-route (Yosys/nextpnr, Lattice iCE40 HX8K), Xilinx-7 mapping script, Vivado script included | `synth/`, `synth/nextpnr_ice40_seed1.log` |

## Headline results (all reproducible with the commands below)
* RTL testbench: **16/16 scenarios PASS** — bit errors up to 10 %, inserted/deleted bits, inverted polarity, burst loss, random clock gaps, real 1115-byte frames, and **both bit streams produced by our Level-1 Python model**.
* The testbench is *self-checking*: every output frame is compared byte-for-byte with a bit-exact Python golden model, and the golden model is itself checked against ground truth (frames that were really transmitted). Four deliberately injected RTL bugs were all caught.
* Bit-slip recovery: one 1-bit slip costs about 1 frame with the slip window vs about 4.5 frames and a full re-search without it (`docs/results.txt`).
* Level-1 numbers (8 dB Eb/N0, seed 2026): 120/120 markers found, 1 false candidate, 110/120 CRC-verified frames.
* FPGA (Lattice iCE40 HX8K, 1115-byte frames, open-source flow): 909 logic cells (11 %), post-route Fmax 69.9–80.2 MHz over 5 placement seeds; the 50 MHz target is met. Xilinx-7 resource estimate from Yosys: about 750 LUTs and 357 flip-flops (estimate only, no timing).
  The nextpnr log prints a pre-route estimate first and the post-route value last; we report the post-route (last) line.

## How to run (Windows: use `py` instead of `python3`)
```
# Level 1 (Python only)
cd level1_python
py -m pip install -r requirements.txt
py -m unittest -v test_phase1.py
py ccsds_phase1.py
# open level1_python/walkthrough.html in a browser for the interactive lesson

# Level 2 (needs Python + numpy + matplotlib + Icarus Verilog "iverilog")
cd level1_crosscheck ; py xcheck_level1.py      # feeds the Level-1 bit streams to the golden model
cd ../sim ; py gen_vectors.py ; py run_all.py   # expect: ALL PASS
cd ../model ; py analysis.py                    # figures + tables -> docs/

# Level 3 (needs yosys + nextpnr-ice40, e.g. OSS CAD Suite)
cd synth
yosys -q synth_ice40.ys
nextpnr-ice40 --hx8k --package ct256 --json ccsds_ice40.json --freq 50 --seed 1
# With Vivado: vivado -mode batch -source vivado_synth.tcl  (then add its timing report to docs/)
```

## Repo map
```
level1_python/      Level 1 model, tests, interactive walkthrough.html, results
model/              bit-exact golden model (ccsds_model.py) + analysis.py (curves, tolerance and slip studies)
rtl/                ccsds_frame_sync.v   (synthesizable)
tb/                 tb_ccsds_sync.v      (self-checking testbench)
sim/                gen_vectors.py, run_all.py, plot_waveform.py
level1_crosscheck/  Level-1 bit streams fed through the Level-2 model and RTL
synth/              Yosys / nextpnr scripts and logs, vivado_synth.tcl
docs/               technical document, figures, results.txt, waveform, test_logs/
presentation/
```

## Honest scope and limitations
Hard-decision input only; frame length is fixed per synthesis; the frame used to verify a candidate in CHECK is not delivered; no physical board or RF front end; no FEC decoder; Level-3 timing comes from an open-source flow on an iCE40 (`synth/vivado_synth.tcl` is provided for Vivado numbers); tolerance values were chosen by our own Monte-Carlo study, not copied from the CCSDS Green Book.

## Development note
The Level-1 package and the Level-2/3 design were developed with AI assistance (Claude). The team ran, tested and reviewed the repository contents and is responsible for them; every result above was regenerated from the code in this repo.

## References
CCSDS 131.0-B (TM Synchronization and Channel Coding) – ASM 0x1ACFFC1D; CCSDS 132.0-B (TM Space Data Link Protocol) – primary header and FECF; CCSDS 130.1-G (Green Book) – frame synchronization strategy.
"# The-Vanguard-Electronics-Spec26" 
