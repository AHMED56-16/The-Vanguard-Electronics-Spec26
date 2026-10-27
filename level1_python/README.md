# SPEC'26 CCSDS Telemetry Frame Synchronizer — Complete Level 1

This project is a **working, explainable Level 1 solution** for the SPEC'26 electronics problem, plus a standalone interactive browser lesson and starter material for Levels 2 and 3.

## Start here (no prior satellite experience required)

1. **Double-click `walkthrough.html`**. It works without the internet and without installing Python. Change the signal quality and threshold, inspect individual bits, and try to recover readable temperature, battery, power and attitude measurements.
2. Install Python 3.10+ if you don't have it. Open a terminal in this folder.
3. Install the two packages:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Run the complete simulation:

   ```bash
   python ccsds_phase1.py
   ```

   This creates a `results/` directory containing graphs, CSV tables, a generated short report, and text bit-stream vectors for future Verilog testbenches. Example output from the bundled default run is already in `results/`.

5. Run the tests:

   ```bash
   python -m unittest -v test_phase1.py
   ```

6. For a more difficult noisy experiment with artificial bit slips:

   ```bash
   python ccsds_phase1.py --snr-db 2 --threshold 27 --slip-every 5 --output-dir results_noisy
   ```

**On Windows:** If `python` does not work, try `py`. On macOS/Linux, `python3` may be the command for Python 3.

## Very simple explanation

Suppose you receive a single continuous sequence of `0` and `1` bits. You don't know where any message begins. Every message is prefixed by a **known 32-bit Attached Sync Marker (ASM)**, analogous to a `START` sign.

```
random prefix ... | 1ACFFC1D | 64-byte frame | 1ACFFC1D | 64-byte frame | ...
                    START        MESSAGE       START        MESSAGE
```

Your detector moves a 32-bit window along the stream **one bit at a time**. At each position, it counts how many bits match the known marker. For example, a **28/32** score means that up to **4 marker bits** were incorrect, but it can still recognize the pattern.

Then it must check the **frame checksum** before treating the bits as genuine sensor measurements. This distinction is essential: finding a marker is easier than receiving a complete error-free frame.

## What counts as CCSDS and what is a teaching simplification?

- **Standard CCSDS ASM**: `0x1ACFFC1D`, 32 bits, most-significant-bit first. This marker applies to the selected uncoded/compatible channel setup. Other CCSDS channel coding options use other marker formats.
- **TM transfer frame primary header**: 6 bytes, including 10-bit spacecraft ID, 3-bit virtual channel ID (VCID), and 8-bit master and virtual-channel frame counters. The example spacecraft ID is `0x155`, which is **illustrative, not an assigned mission spacecraft ID**.
- **Virtual Channel Access (VCA)**: TM synchronization flag = 1, so the data field carries a fixed-size application record and does not pretend to be a CCSDS Space Packet. VC0 = housekeeping, VC1 = power, VC2 = attitude.
- **FECF**: the optional CCSDS TM 16-bit CRC using polynomial `0x1021` with an initial remainder of `0xFFFF`. Here it is enabled for every frame.
- **Teaching simplification**: the VCA payload starts with a 1-byte length followed by ASCII `KEY=VALUE` readings and random padding. Real missions have their own data formats, coding and physical-layer arrangements.

The software does **not** implement carrier/symbol synchronization, pseudo-randomization, FEC decoding, inverted phase handling, packet segmentation, or the full CCSDS protocol. It is a correct **Level 1 signal/frame synchronization model**, not a complete flight-ready receiver.

### Complete on-the-wire layout

| Part | Bits | Bytes | Meaning |
|---|---:|---:|---|
| Attached Sync Marker | 32 | 4 | Recognizable frame START pattern (outside frame) |
| CCSDS TM Primary Header | 48 | 6 | Frame version, spacecraft ID, VCID, frame counters, status flags |
| Fixed-length VCA Data Field | 448 | 56 | One illustrative application telemetry record + padding |
| CCSDS Frame Error Control Field (FECF) | 16 | 2 | CRC-16 for the preceding 62 bytes of frame |
| **Total on wire** | **544** | **68** | 4 bytes ASM + 64 bytes transfer frame |

A 73-bit random prefix is added before the first marker to prove the synchronizer does not need byte alignment.

## The Python algorithm: what happens at each stage?

1. **Generate:** create 120 frames containing a real ASM, header, three virtual channels, sensor readings, and CRC.
2. **Transmit:** encode bits as BPSK symbols, `0 → +1` and `1 → −1`. Add independent Gaussian noise to each symbol (AWGN). Decide whether each received symbol is a `0` or `1` based on its sign. This produces **measured BER**, not arbitrary manually flipped bits.
3. **Find:** for each 32-bit window, count matching bits (hard-decision correlation). Score range is `0..32`. Signal a candidate when score ≥ configurable threshold.
4. **Grade:** use the known transmitted start positions to count true detections and false alarms. This truth information is used **only to evaluate the simulation**, never by the receiver.
5. **Extract:** read exactly 512 bits after every candidate ASM; reconstruct 64 bytes; check the CCSDS CRC and header; interpret the application payload **only if validation passes**.
6. **Compare:** repeat at many signal qualities (Eb/N0) and plot detection rate, usable-frame rate and false candidate rate against measured BER.

At the default 8 dB Eb/N0, the included seeded example produced **120/120 markers detected**, **1 false positive candidate**, and **110/120 verified telemetry frames**. Your results will repeat with the same Python seed and NumPy version.

## Which output files are important?

| File | Why you need it |
|---|---|
| `walkthrough.html` | Interactive teaching demo (works offline, requires no libraries) |
| `ccsds_phase1.py` | Main runnable simulation to submit for Level 1 |
| `test_phase1.py` | Automated tests for marker bits, CRC, bit errors, bit slips, decoding |
| `results/performance.png` | Primary competition result: detection, frame recovery and false alarms vs BER |
| `results/correlation_example.png` | Shows a high score when the 32-bit window aligns to a real ASM |
| `results/sweep_results.csv` | BER sweep data for your graphs and presentation |
| `results/detections.csv` | All ASM candidates, match scores, CRC results and simulation-only truth |
| `results/recovered_frames.csv` | Verified frames and meaningful decoded readings, arranged by VCID |
| `results/TECHNICAL_REPORT.md` | Generated short technical report, including assumptions and limitations |
| `results/tx_bits_readmemb.txt` | One transmitted bit per line for Verilog `$readmemb` |
| `results/rx_bits_readmemb.txt` | One noisy received bit per line for Verilog `$readmemb` |
| `results/transmitted_truth.csv` | Expected start-bit positions and injected slips for testbench checking |
| `PRESENTATION_OUTLINE.md` | A ready-to-adapt 6-slide talk track |
| `LEVEL2_HANDOFF.md` | Concrete FPGA architecture and basic testbench plan |

The HTML also lets you generate and download your own `rx_bits_readmemb.txt`, `tx_bits_readmemb.txt` and frame-truth CSV after changing settings.

## How to interpret the graphs

The horizontal axis is **measured bit error rate (BER)**. A larger BER means more received bits are wrong.

- **Marker detection rate** = number of true markers whose correlation score passed threshold / number of transmitted markers.
- **False alarms** = passing marker candidates at positions that were **not** real starts. We report them per **100,000 non-marker window positions**. A detector cannot know which candidates are false during actual operation; the simulation can.
- **Usable frame rate** = number of actual frames that passed marker, CRC and header checks / number transmitted.

Lowering the match threshold typically makes marker recovery more tolerant of bit errors **but** allows more false alarms. Conversely, demanding 32/32 matches reduces false alarms but rejects slightly noisy markers.

A 32-bit marker can survive several errors, but even one bad data bit can make the **64-byte frame fail CRC**. This is why usable-frame rate drops before marker detection rate.

## Try three meaningful experiments

| Scenario | Setting | What to observe |
|---|---|---|
| Easy recovery | 8–10 dB Eb/N0, threshold 28 | Most markers and most sensor readings recover |
| Noisy satellite link | 0–2 dB Eb/N0, threshold 28 | Markers often found but very few full frames pass CRC |
| False detections | Threshold 24 vs 32, same seed | Low threshold produces more random lookalikes; high threshold misses markers |

A fourth experiment: use `--slip-every 5` or turn on **Inject bit slips** in the HTML. Some individual frames will fail CRC because a bit was inserted or deleted, yet the next real ASM can still be discovered by a bit-wise scanner.

## References

- Competition brief: *SPEC'26 Electronics Problem: CCSDS Telemetry Frame Synchronizer*, pp. 1–3.
- Current CCSDS synchronization/coding catalogue includes **CCSDS 131.0-B-6** (April 2026): https://ccsds.org/publications/sls/
- Published definition of `0x1ACFFC1D` (historical issue), **CCSDS 131.0-B-2**, section 8.3: https://ccsds.org/Pubs/131x0b2ec1s.pdf
- CCSDS transfer frame primary header + FECF, **CCSDS 132.0-B-3**, sections 4.1.2 and 4.1.6: https://ccsds.org/Pubs/132x0b3.pdf
