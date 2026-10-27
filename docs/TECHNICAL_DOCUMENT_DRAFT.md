# SPEC'26 Hackathon - CCSDS Telemetry Frame Synchronizer (Team technical document - DRAFT, fill team names)

## 1. Problem and level reached
Lock onto the 32-bit CCSDS attached sync marker in a noisy serial stream, survive bit slips, and extract virtual-channel frames.
We completed **Level 1 (model), Level 2 (RTL + self-checking testbench with bit slips), and Level 3 (synthesis with timing report)**,
and added virtual-channel frame extraction as required for Level 3. No physical board was used.

## 2. Sync marker (cite the standard)
* ASM = 0x1ACFFC1D (32 bit), CCSDS 131.0-B (TM Synchronization and Channel Coding). Complement 0xE53003E2 appears when the demodulator has a 180-degree ambiguity; our design detects both and un-inverts the data.
* Frame format: CCSDS 132.0-B (TM Space Data Link Protocol): version(2) SCID(10) VCID(3) OCF(1) MCFC(8) VCFC(8) status(16); optional FECF = CRC-16 (x^16+x^12+x^5+1, init 0xFFFF).
* Optional pseudo-randomizer x^8+x^7+x^5+x^3+1, seed all-ones (sequence starts FF 48 0E C0 ... - verified).
* Synchronization strategy follows the Search/Check/Lock/Flywheel structure of CCSDS 130.1-G (Green Book). The numeric tolerances in our design were chosen by our own Monte-Carlo study (section 5), not copied from the standard.

## 3. Architecture
Shift register (32 b) -> registered Hamming-distance (balanced popcount tree, 1 pipeline stage) -> threshold comparators -> FSM + frame-position counter -> serial-to-byte datapath (de-randomizer, CRC-16, header decode) -> per-frame verdict and per-VC counters. One bit per clock when bit_valid=1; at 50 MHz this sustains 50 Mbit/s with one bit per clock.
Slip handling: around the expected ASM position (+-W bits) a strict (T_SLIP) match re-aligns the frame counter immediately (deleted bit: early window; inserted bit: late window after a miss). The ASM's minimum shift-distance is 11 bits, so T_SLIP=2 cannot be confused with a shifted marker.

## 4. Verification
* Golden Python model, bit-exact twin of the RTL. 14 scenarios: clean, inverted polarity, BER 1/5/10 %, single-bit insertions and deletions, burst loss, de-randomizer, random clock-enable gaps, 5001-bit junk prefix, real frame length 1115 bytes, CHECK_N=2, slip window disabled.
* Self-checking testbench compares every frame byte, flags, VCID, counters and header decode against the model: **16/16 PASS** (14 designed scenarios + the 2 Level-1 streams).
* Ground-truth check: frames flagged GOOD were verified to align with frames that were really transmitted (Hamming-distance test).
* Cross-validation: the independent Level-1 Python package (BPSK/AWGN, 64-byte frames) produced two bit streams - 8 dB, and 2 dB with 23 injected bit slips. Both were run through the golden model and the RTL testbench: PASS. At 8 dB the RTL delivers 118 frames of which 110 pass CRC, the same 110 CRC-verified frames the Level-1 model reports.
* Mutation test: 4 deliberately injected RTL bugs (polarity, slip window, CRC polynomial, flywheel counter) were all caught.

## 5. Results (see docs/results.txt, fig1, fig2)
* Detection probability and false-alarm rate: theory (binomial) and 2e7-bit Monte-Carlo agree (fig1).
* FSM vs Es/N0 (hard-decision BPSK/AWGN): profile A (T 2/4/6) delivers 94 % of frames at 0 dB, 97 % at 2 dB; profile B (4/6/8, CHECK_N=2) delivers 92 % at -2 dB with no loss-of-lock events in the test.
* Bit-slip recovery: one random 1-bit slip costs about 1.0 frame with the slip window vs about 4.5 frames and a full re-acquisition without it.
* False lock on noise: profile A with CHECK_N=1 about 2.4e-3 per 1e9 bits; profile B about 1.4e-3 per 1e9 bits.

## 6. FPGA implementation (Level 3)   <<< replace/add Vivado numbers if you ran vivado_synth.tcl
Open-source flow (Yosys + nextpnr), FB = 1115 bytes: Lattice iCE40 HX8K - 909 logic cells (11 %), post-route Fmax 69.9-80.2 MHz over 5 placement seeds (target 50 MHz: met).
Yosys technology mapping for Xilinx 7-series (resource estimate only, no timing): about 750 LUTs, 357 flip-flops, 45 CARRY4.

## 7. Limitations (state these honestly)
Hard-decision input only; frame length fixed per instance (parameter); the frame being verified in CHECK is not delivered; no physical board; I/O timing not constrained in the open-source report; false-lock figures are analytic/simulated, not measured on hardware.
