# SPEC'26: Six-slide presentation outline (Level 1)

This is a slide **outline** rather than a generated PowerPoint file. Adapt it to your team's actual measurements and screenshots.

## Slide 1 — The problem

Satellite messages arrive as a continuous stream of 0s and 1s. Noise can flip bits, and insertions/deletions can shift frame boundaries. We need to recover where each message starts using the CCSDS Attached Sync Marker (ASM).

## Slide 2 — Basic idea

- Standard selected marker: **32 bits / 0x1ACFFC1D**.
- Frame group layout: **ASM (32) + TM frame (512)** bits.
- Scan each bit offset and count how many of the 32 marker bits match.
- Detect a candidate when the score reaches **28/32** (configurable).

Show `results/correlation_example.png` or the browser's moving-window visualization.

## Slide 3 — Channel model and example payload

- Transmit BPSK (`0→+1`, `1→−1`), add AWGN, make hard bit decisions.
- Three virtual channels: housekeeping, power, attitude.
- The 64-byte TM frame uses a 6-byte CCSDS header, 56-byte VCA teaching payload, and 2-byte FECF.
- Read data only when FECF/CRC and header checks pass.

Live demo: open `walkthrough.html`, inspect the bit rail, and show a recovered battery/power/attitude measurement.

## Slide 4 — Level 1 results

Show `results/performance.png` and report measured results from `results/TECHNICAL_REPORT.md`:

- BER vs real marker detection percentage.
- BER vs **usable CRC-verified** frame percentage.
- False candidate count per 100,000 tested non-marker positions.
- Demonstrate that marker detection succeeds in noise even when many long frames fail integrity checks.

## Slide 5 — Limitations and engineering decisions

- False alarms are possible; changing the threshold trades sensitivity for false alarms.
- A CRC identifies likely corruption but cannot correct wrong bits.
- This is a Level 1 software model: no complete RF modem or FEC decoder; VCA payload is intentionally educational ASCII rather than CCSDS Space Packets.
- The optional insert/delete experiment shows why a bit-wise scanner matters.

## Slide 6 — Level 2 and Level 3 plan

- Level 2: 32-bit shift register, XNOR + population count, lock acquisition/verify/loss FSM, 512-bit extraction, FECF and VCID routing, self-checking testbench.
- Level 3: FPGA synthesis, 20 ns (50 MHz) clock constraint, resource and timing reports, optional board demo.
- Use the exported `rx_bits_readmemb.txt` and `transmitted_truth.csv` to test HDL against known data.

**Presenter's closing line:** “Our receiver can find message boundaries even when noisy bits are present, and it only reports sensor measurements after confirming the complete frame's integrity.”
