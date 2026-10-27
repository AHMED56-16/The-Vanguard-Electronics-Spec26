# SPEC'26 - Level 1 technical report (generated)

## Problem and approach
Find the CCSDS **32-bit Attached Sync Marker (ASM)** `0x1ACFFC1D` in a
bit stream damaged by BPSK/AWGN.  This is a **software model**, not a
hardware/RTL implementation.  We use a 32-bit sliding match correlator.
A marker candidate is signaled if **at least 28 of 32** bits match.
Since every bit position is scanned, the algorithm is **not byte aligned**.

## Simulation configuration
- Eb/N0: **8 dB**, fixed-length TM transfer frames: **64 bytes**.
- Number of generated frames: **120**; sync marker 4 bytes outside each frame.
- BPSK `0 -> +1`, `1 -> -1`; independent real AWGN sample per bit;
  hard receiver `bit = (noisy_sample < 0)`; no FEC or randomization.
- Optional bit slips inside frame data: **every 0 frames**
  (`0` means disabled). Insertions/deletions shift later bit indices.
- The first 73 bits are random prefix to prove arbitrary starting phase.

## One-run results
| Metric | Result |
|---|---:|
| Empirical channel BER | 0.000168 |
| Theoretical BPSK/AWGN BER | 0.000191 |
| Found true ASM locations | 120/120 (100.0%) |
| Missed true ASM locations | 0 |
| False marker candidates | 1 |
| False candidates per 100k non-marker positions | 1.534 |
| CRC-verified, decoded frames | 110/120 (91.7%) |
| Received bit-stream length | 65,353 bits |

For this threshold, **ideal independent unbiased background bits**
produce a per-position false-alarm probability of about
`9.651e-06`.  This analytic
approximation does not promise exactly that number in a finite test and
may not match structured CCSDS payloads.

## Results from changing Eb/N0
See `sweep_results.csv` and `performance.png`.  The figure places
**sync-marker detection**, **valid frame recovery** and **false alarm
counts** against measured BER.  A detected marker is **not** proof that
the entire frame was received correctly: check FECF and frame header.

## Receiver architecture
1. **Channel:** generate fixed-length TM frames with a CCSDS ASM before each.
2. **Noisy input:** BPSK symbols + Gaussian noise, then hard-bit decisions.
3. **Correlator:** for each possible 32-bit window, count matching bits.
4. **Threshold:** accept any window scoring at least 28.
5. **Extract:** read the next 64 bytes after a candidate ASM.
6. **Validate:** require a valid 16-bit CCSDS TM FECF CRC and sensible header.
7. **Interpret:** demultiplex by VCID; parse readable example telemetry strings.

## What is CCSDS here, and what is simplified?
The **ASM**, 6-byte **TM Transfer Frame Primary Header**, **Virtual
Channel ID** and 2-byte **FECF** follow the indicated CCSDS layouts.
We set **Synchronization Flag = 1**, indicating the Virtual Channel
Access service, and fill its fixed-size data field with one pedagogical
length-prefixed ASCII sensor record plus random padding.  This application
record is **not a CCSDS Space Packet**.  We omit spacecraft RF effects,
carrier recovery, differential/inverted phase, pseudo-randomization,
forward-error correction (e.g. Reed-Solomon/LDPC) and full protocol
management.  We do **not** claim end-to-end CCSDS interoperability.

## Level 2 and Level 3 follow-on
- **Level 2:** build a 32-bit shift-register correlator using 32 XNORs
  and a population count; threshold result; lock acquisition, verify
  and loss-of-lock FSM; 512-bit frame extraction; CRC checking; VCID
  demultiplexing.  Verify with a self-checking simulation including slips.
- **Level 3:** synthesize RTL in Vivado/other FPGA tool, add a 50 MHz
  timing constraint (20 ns period), and export LUT/FF usage and worst-case
  timing.  Include virtual-channel extraction.  A physical board is optional.

## References
- Challenge handout: SPEC'26 Electronics Problem, pages 1-3.
- CCSDS 131.0-B-6, *TM Synchronization and Channel Coding*, Apr 2026,
  section on ASM.  Historical freely accessible reference showing this
  specific pattern: CCSDS 131.0-B-2, sec. 8.3,
  https://ccsds.org/Pubs/131x0b2ec1s.pdf .
- CCSDS 132.0-B-3, *TM Space Data Link Protocol*, Oct 2021,
  sections 4.1.2 and 4.1.6,
  https://ccsds.org/Pubs/132x0b3.pdf .
