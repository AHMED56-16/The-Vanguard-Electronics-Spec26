# From Python to Level 2: Verilog / VHDL implementation guide

The goal of Level 2 is to create a *clocked hardware receiver*, using the exact same principles as the Python simulation. A 50 MHz clock is a **timing target for the synthesized hardware**; it is not a bit rate that the Python code claims to sustain.

## Suggested system block diagram

```text
rx_bit, rx_valid
      |
      v
[32-bit serial shift register] --> [32 XNOR comparisons] --> [popcount 0..32]
      |                                                  |
      |                                      [score >= threshold]
      |                                                  |
      +---------------------------> [Acquisition / Verification / Locked FSM]
                                                         |
                                                         v
                                                  [64-byte extractor]
                                                         |
                                                   [CRC-16/FECF]
                                                         |
                                                [6-byte TM header]
                                                         |
                                          [VCID 0 / VCID 1 / VCID 2]
```

## 1. Correlator

At every `rx_valid` clock, shift in the new received bit. XOR the shift register with the constant `32'h1ACFFC1D`; count how many XOR outputs are zero (or XNOR outputs are one). A match score of `>= 28` means a candidate marker. Also track a `bit_index` so the receiver can report the marker's first-bit location as `bit_index - 31`.

**Important:** keep the bit ordering identical to Python. The first marker bit on wire is the most-significant bit of `0x1ACFFC1D`. A shift register that does `shift <= {shift[30:0], rx_bit}` holds the first bit in bit 31 after 32 samples. If you pipeline the correlator for timing, delay the position/valid signal by the matching pipeline latency.

## 2. Lock FSM

Use three conceptual states; the challenge specifically asks for acquisition, verification and loss of lock.

- `SEARCH`: scan **all bit positions** for a qualifying candidate. Upon detection, tentatively track the candidate's start position.
- `VERIFY`: at an expected next start (candidate start + **544** bits) or in a small optional slip-tolerance window `expected ± 1`, look for another qualifying ASM. After a configurable number of consistent markers (e.g. 2 consecutive), assert `LOCKED`.
- `LOCKED`: generate a frame-start pulse when a valid expected marker arrives; collect exactly 512 following bits, and route the frame if its CRC is valid. If expected marker checks fail too often, deassert lock and return to `SEARCH`.

The thresholds for verification and loss of lock are **implementation choices** for this educational design. Document them, test them, and do not claim they are a universal mandatory CCSDS FSM.

For the example payload, frame groups are **544 bits** when no slip is present. After an insertion or deletion inside the frame, the next ASM may be 545 or 543 bits after the preceding start. The correlator can still find it by scanning bit phases.

### Subtle frame-extraction point

Don't assume a frame is good only because the marker looks right. You must extract bytes and check CRC. A bit insertion can corrupt one frame and shift the expected next marker, but the subsequent marker can be recovered independently. Avoid using the simulation's hidden `truth` positions inside the RTL.

## 3. Extractor and CRC

- After a candidate ASM, capture `64 * 8 = 512` received bits in MSB-first order (or stream them through a 64-byte storage buffer).
- First 6 bytes are the CCSDS TM primary header. Bits 12–14 of the first 16 bits hold the 3-bit VCID.
- Data field is 56 bytes. It contains one educational length-prefixed ASCII record; the leading length is 1 byte.
- Last 2 bytes are the FECF (CRC-16-CCITT, polynomial `0x1021`, initial remainder `0xFFFF`). Calculate CRC over the first 62 bytes. Only assert `frame_good` when CRC and header checks pass.
- Our VCA mode uses status word `16'h4000`. The VCA payload is **not** a CCSDS Space Packet. This is consistent with the HTML/Python teaching example but not a full mission protocol stack.

## 4. Self-checking testbench plan

1. Load `results/rx_bits_readmemb.txt` into a 1-bit memory array in simulation. One row is one bit; the array should be sized to the line count in the file.
2. On each rising edge, present one bit with `rx_valid=1`.
3. Compare correlator match pulses and offsets against `results/transmitted_truth.csv`. Python's **simulation-only truth** is legitimate for checking the DUT, but must never drive the DUT itself.
4. Test success cases: clean markers, no noise, alternating VCID0/1/2, valid frame extraction, wraparound of counters.
5. Test error cases: 1–4 flipped marker bits, 5 flipped marker bits (should fail for threshold 28), corrupted body CRC, false positives, insertion/deletion, acquisition and deliberate loss of lock.
6. Account for the pipeline latency of your actual RTL when checking pulse positions.

Example *conceptual* testbench loading statement:

```verilog
reg rx_mem [0:MAX_BITS-1];
initial $readmemb("rx_bits_readmemb.txt", rx_mem);
// Drive rx_mem[i] on rising clocks; check DUT start/lock/frame outputs.
```

## 5. Level 3 synthesis and speed report

Create a project targeting a low-cost FPGA (AMD/Xilinx or Microchip, as in the challenge) in your tool. Add an actual timing constraint, for example an XDC clock constraint in Vivado:

```tcl
create_clock -name clk -period 20.000 [get_ports clk]
```

A period of 20 ns corresponds to **50 MHz**. Report LUT count, register count, worst data path, and worst slack after synthesis/implementation. Split the popcount calculation into a balanced adder tree or add pipeline registers if timing is poor. Physical board testing is a bonus, not a required Level 3 artifact.

## What to present to judges

A block diagram, a self-checking waveform showing the shift register / correlator / FSM / frame output, demonstrations of noisy markers and bit slips, recovered telemetry by VCID, plus 50 MHz timing and device-utilization reports for Level 3.
