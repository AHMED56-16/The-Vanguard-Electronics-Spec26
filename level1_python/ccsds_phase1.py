#!/usr/bin/env python3
"""SPEC'26 Level 1: CCSDS telemetry frame synchronizer simulation.

The model uses the standard 32-bit uncoded Attached Sync Marker (ASM),
0x1ACFFC1D, a 64-octet TM-style transfer frame with a CCSDS TM primary header,
a simple Virtual Channel Access payload, and a CCSDS FECF CRC-16.  It
simulates BPSK through AWGN, makes hard bit decisions, scans EVERY bit phase,
measures missed markers/false alarms, and recovers verified telemetry.

References:
- CCSDS 131.0-B, TM Synchronization and Channel Coding, ASM section.
- CCSDS 132.0-B-3, TM Space Data Link Protocol, sections 4.1.2, 4.1.6.
This is an educational uncoded link, NOT an end-to-end spacecraft modem.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import struct

import numpy as np

ASM_HEX = 0x1ACFFC1D
ASM_BITS = np.unpackbits(np.frombuffer(ASM_HEX.to_bytes(4, "big"), dtype=np.uint8))
ASM_LEN = 32
FRAME_BYTES = 64
FRAME_BITS = FRAME_BYTES * 8
SCID = 0x155  # Illustrative spacecraft ID; NOT an assigned mission ID.
VC_NAMES = {0: "Housekeeping", 1: "Power", 2: "Attitude"}
PREFIX_BITS = 73
STATUS_WORD = 0x4000  # Synchronization flag = 1 (Virtual Channel Access service).


@dataclass
class TruthFrame:
    index: int
    start: int  # First bit of the ASM in the actual, possibly slipped, transmitted stream.
    vcid: int
    message: str
    slip: str


@dataclass
class Detection:
    bit_offset: int
    matches: int
    true_marker: bool  # Ground truth used ONLY to grade simulation; receiver never needs it.
    crc_ok: bool
    header_ok: bool
    vcid: int | None
    message: str

    @property
    def accepted(self) -> bool:
        return self.crc_ok and self.header_ok and bool(self.message)


@dataclass
class Metrics:
    frames_sent: int
    true_markers_detected: int
    missed_markers: int
    false_alarms: int
    tested_non_marker_positions: int
    channel_ber: float
    ber_theoretical: float
    verified_frames: int
    total_bits: int

    @property
    def detection_rate(self) -> float:
        return self.true_markers_detected / self.frames_sent if self.frames_sent else 0.0

    @property
    def usable_frame_rate(self) -> float:
        return self.verified_frames / self.frames_sent if self.frames_sent else 0.0

    @property
    def false_alarms_per_100k(self) -> float:
        return 100_000 * self.false_alarms / max(1, self.tested_non_marker_positions)


def crc16_ccitt(data: bytes) -> int:
    """CCSDS TM FECF: polynomial 0x1021, initial remainder 0xFFFF, no final xor."""
    crc = 0xFFFF
    for octet in data:
        crc ^= octet << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def make_message(frame_index: int, vcid: int) -> str:
    """Plain-text VCA service payload chosen to make decoding easy to understand."""
    if vcid == 0:
        return (f"TEMP={22.0 + (frame_index % 17) * 0.2:.1f}C;"
                f"BAT={88 - frame_index % 16}%;MODE=OK")
    if vcid == 1:
        return (f"BUS={3.68 + (frame_index % 7) * .02:.2f}V;"
                f"SOLAR={12 + frame_index % 6:.1f}W;LOAD=8.5W")
    return (f"PITCH={(frame_index % 9 - 4) * .3:+.1f};"
            f"ROLL={(frame_index % 7 - 3) * .2:+.1f};YAW={85 + frame_index % 20}")


def pack_frame(frame_index: int, vcid: int, vc_count: int,
               rng: np.random.Generator) -> tuple[bytes, str]:
    """6-byte CCSDS TM header + 56-byte VCA data + 2-byte CCSDS FECF.

    Header: version=0, scid=0x155, VCID=0..2, OCF flag=0,
    master count = frame_index mod 256; VC frame count increments per VC;
    sync flag=1 (VCA), other data-field-status bits unused and set to 0.
    The payload is a *teaching* application record: length, ASCII, random padding.
    There is no CCSDS Space Packet here, so do not parse it as one.
    """
    first_16 = (SCID << 4) | (vcid << 1)
    primary = struct.pack(">HBBH", first_16, frame_index % 256,
                          vc_count % 256, STATUS_WORD)
    message = make_message(frame_index, vcid)
    encoded = message.encode("ascii")
    if len(encoded) > 55:
        raise ValueError("Application message does not fit fixed frame")
    filler = rng.integers(0, 256, size=55 - len(encoded), dtype=np.uint8).tobytes()
    data_field = bytes((len(encoded),)) + encoded + filler
    raw_without_fecf = primary + data_field
    frame = raw_without_fecf + struct.pack(">H", crc16_ccitt(raw_without_fecf))
    assert len(frame) == FRAME_BYTES
    return frame, message


def build_stream(nframes: int, seed: int, slip_every: int = 0
                 ) -> tuple[np.ndarray, list[TruthFrame]]:
    """ASM + fixed 64-byte frame repeated; optional insert/delete slips INSIDE frames.

    The actual marker positions are tracked after slips, so a subsequent ASM
    remains discoverable by a bit-wise sliding correlator.
    """
    rng = np.random.default_rng(seed)
    bit_stream = rng.integers(0, 2, size=PREFIX_BITS, dtype=np.uint8).tolist()
    truth: list[TruthFrame] = []
    vc_counts = {0: 0, 1: 0, 2: 0}
    slip_number = 0

    for index in range(nframes):
        vcid = index % 3
        frame, message = pack_frame(index, vcid, vc_counts[vcid], rng)
        vc_counts[vcid] += 1
        body_bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8)).tolist()
        slip = "none"
        if slip_every and (index + 1) % slip_every == 0:
            slip_number += 1
            if slip_number % 2:
                body_bits.insert(180, int(rng.integers(0, 2)))
                slip = "1 inserted bit in frame data"
            else:
                del body_bits[180]
                slip = "1 deleted bit in frame data"
        truth.append(TruthFrame(index, len(bit_stream), vcid, message, slip))
        bit_stream.extend(ASM_BITS.tolist())
        bit_stream.extend(body_bits)

    return np.asarray(bit_stream, dtype=np.uint8), truth


def bpsk_awgn(tx: np.ndarray, ebn0_db: float,
              gaussians: np.ndarray) -> tuple[np.ndarray, float]:
    """Map 0=>+1 and 1=>-1; add real AWGN; hard-decision at amplitude=0.

    With energy per bit Eb=1 and one-sided N0, sigma=sqrt(N0/2),
    where Eb/N0 (linear) = 10^(Eb/N0[dB]/10).  No FEC or filtering is modeled.
    """
    ebn0 = 10.0 ** (ebn0_db / 10.0)
    sigma = math.sqrt(1.0 / (2.0 * ebn0))
    waveform = (1.0 - 2.0 * tx.astype(np.float64)) + sigma * gaussians
    hard_bits = (waveform < 0.0).astype(np.uint8)
    theoretical_ber = 0.5 * math.erfc(math.sqrt(ebn0))
    return hard_bits, theoretical_ber


def correlation_scores(rx: np.ndarray) -> np.ndarray:
    """For every 32-bit window count equal bits, using bipolar correlation.

    score = (32 + sum((1-2*rx[i+j])*(1-2*ASM[j]), j=0..31))/2.
    Therefore 32=perfect, 28=at most four wrong marker bits.
    """
    if len(rx) < ASM_LEN:
        return np.empty(0, dtype=np.uint8)
    bipolar_rx = 1 - 2 * rx.astype(np.int16)
    bipolar_marker = 1 - 2 * ASM_BITS.astype(np.int16)
    correlation = np.correlate(bipolar_rx, bipolar_marker, mode="valid")
    return ((correlation + ASM_LEN) // 2).astype(np.uint8)


def extract_frame(rx: np.ndarray, marker_offset: int) -> tuple[bool, bool, int | None, str]:
    """Decode 64 bytes after a CANDIDATE marker; never rely on known true positions."""
    begin, end = marker_offset + ASM_LEN, marker_offset + ASM_LEN + FRAME_BITS
    if end > len(rx):
        return False, False, None, ""
    frame = np.packbits(rx[begin:end], bitorder="big").tobytes()
    crc_ok = crc16_ccitt(frame[:-2]) == int.from_bytes(frame[-2:], "big")
    header_word = int.from_bytes(frame[:2], "big")
    version = (header_word >> 14) & 0b11
    scid = (header_word >> 4) & 0x3FF
    vcid = (header_word >> 1) & 0b111
    ocf_flag = header_word & 1
    status_word = int.from_bytes(frame[4:6], "big")
    header_ok = (version == 0 and scid == SCID and vcid in VC_NAMES
                 and ocf_flag == 0 and status_word == STATUS_WORD)
    # Only interpret telemetry after frame integrity and primary header checks.
    if not (crc_ok and header_ok):
        return crc_ok, header_ok, vcid, ""
    data_field = frame[6:-2]
    n = data_field[0]
    if n == 0 or n > 55:
        return crc_ok, False, vcid, ""
    try:
        message = data_field[1:1 + n].decode("ascii")
    except UnicodeDecodeError:
        return crc_ok, False, vcid, ""
    if "=" not in message:
        return crc_ok, False, vcid, ""
    return crc_ok, header_ok, vcid, message


def run_receiver(rx: np.ndarray, truth: list[TruthFrame], threshold: int,
                 channel_ber: float, theory_ber: float
                ) -> tuple[Metrics, np.ndarray, list[Detection]]:
    """Blind receiver plus simulation-only performance grading."""
    if not 1 <= threshold <= ASM_LEN:
        raise ValueError("threshold must be from 1 through 32")
    scores = correlation_scores(rx)
    candidates = np.flatnonzero(scores >= threshold)
    actual_positions = {f.start for f in truth}  # Only for evaluation metrics.
    detected_true = int(sum(scores[f.start] >= threshold for f in truth))
    false = int(sum(int(i) not in actual_positions for i in candidates))
    detections = []
    for i in candidates:
        i = int(i)
        crc_ok, header_ok, vcid, message = extract_frame(rx, i)
        detections.append(Detection(i, int(scores[i]), i in actual_positions,
                                    crc_ok, header_ok, vcid, message))
    # Count usable frames only when the receiver finds a true marker AND the
    # frame passes all validation.  Truth is used here for the ground-truth score.
    good = sum(d.true_marker and d.accepted for d in detections)
    metrics = Metrics(len(truth), detected_true, len(truth) - detected_true,
                      false, len(scores) - len(truth), channel_ber,
                      theory_ber, good, len(rx))
    return metrics, scores, detections


def one_run(nframes: int, seed: int, snr_db: float, threshold: int,
            slip_every: int = 0
           ) -> tuple[Metrics, np.ndarray, list[Detection], list[TruthFrame], np.ndarray, np.ndarray]:
    tx, truth = build_stream(nframes, seed=seed, slip_every=slip_every)
    rng = np.random.default_rng(seed + 101_337)
    gaussians = rng.standard_normal(len(tx))
    rx, theory = bpsk_awgn(tx, snr_db, gaussians)
    ber = float(np.count_nonzero(tx != rx) / len(tx))
    metrics, scores, detections = run_receiver(rx, truth, threshold, ber, theory)
    return metrics, scores, detections, truth, tx, rx


def sweep(nframes: int, seed: int, threshold: int, slips_every: int = 0
          ) -> list[dict]:
    """Same transmitted bits and unit-Gaussian samples at each Eb/N0: fair comparison."""
    tx, truth = build_stream(nframes, seed=seed, slip_every=slips_every)
    gaussians = np.random.default_rng(seed + 101_337).standard_normal(len(tx))
    rows = []
    for snr_db in [-4, -2, 0, 1, 2, 3, 4, 5, 6, 8, 10]:
        rx, theory = bpsk_awgn(tx, float(snr_db), gaussians)
        ber = float(np.count_nonzero(tx != rx) / len(tx))
        metrics, _, _ = run_receiver(rx, truth, threshold, ber, theory)
        rows.append({"ebn0_db": snr_db, "ber_measured": ber,
                     "ber_theory": theory,
                     "detected_markers": metrics.true_markers_detected,
                     "sent_markers": metrics.frames_sent,
                     "detection_rate": metrics.detection_rate,
                     "missed_markers": metrics.missed_markers,
                     "false_alarms": metrics.false_alarms,
                     "false_alarms_per_100k": metrics.false_alarms_per_100k,
                     "valid_frames": metrics.verified_frames,
                     "valid_frame_rate": metrics.usable_frame_rate})
    return rows


def write_csv(filename: Path, rows: list[dict], headings: list[str] | None = None) -> None:
    headings = headings or (list(rows[0]) if rows else [])
    with filename.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headings)
        writer.writeheader()
        writer.writerows(rows)


def expected_false_alarm_probability(threshold: int) -> float:
    """Ideal independent EQUIPROBABLE background bits: P(match >= T)."""
    return sum(math.comb(ASM_LEN, k) for k in range(threshold, ASM_LEN + 1)) / 2**ASM_LEN


def create_plots(output: Path, rows: list[dict], scores: np.ndarray,
                 truth: list[TruthFrame], threshold: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [max(row["ber_measured"], 1e-6) for row in rows]
    order = np.argsort(x)
    fig, axes = plt.subplots(2, 1, figsize=(10.4, 8.0), constrained_layout=True)
    ax = axes[0]
    ax.semilogx(np.asarray(x)[order], np.asarray([r["detection_rate"] for r in rows])[order],
                "o-", lw=2.1, label="Sync-marker detection rate")
    ax.semilogx(np.asarray(x)[order], np.asarray([r["valid_frame_rate"] for r in rows])[order],
                "s--", lw=1.7, label="CRC-verified telemetry frame rate")
    ax.set(xlabel="Measured bit error rate (BER) [log scale]", ylabel="Fraction of sent frames",
           title=f"Frame recovery vs channel errors | {ASM_LEN}-bit ASM, threshold {threshold}/32",
           ylim=(-0.04, 1.04))
    ax.grid(True, which="both", alpha=.25)
    ax.legend(loc="lower left")

    ax2 = axes[1]
    ax2.semilogx(np.asarray(x)[order],
                 np.asarray([r["false_alarms_per_100k"] for r in rows])[order],
                 "o-", lw=2, label="Observed candidate false alarms")
    expected = 100_000 * expected_false_alarm_probability(threshold)
    ax2.axhline(expected, ls=":", lw=1.7, color="gray",
                label=f"Random background approximation ({expected:.2f} per 100k)")
    ax2.set(xlabel="Measured bit error rate (BER) [log scale]",
            ylabel="False positives per 100,000 non-marker positions",
            title="False alarms: a random background can also resemble the marker")
    ax2.grid(True, which="both", alpha=.25)
    ax2.legend(loc="best")
    fig.savefig(output / "performance.png", dpi=165, facecolor="white")
    plt.close(fig)

    # Inspect scores around an actual marker, as if moving a 32-bit window.
    marker = truth[0].start
    low, high = max(0, marker - 45), min(len(scores), marker + 55)
    locations = np.arange(low, high)
    fig, ax = plt.subplots(figsize=(10.4, 4), constrained_layout=True)
    ax.plot(locations - marker, scores[low:high], "-o", markersize=3.2, lw=1.5)
    ax.axhline(threshold, ls="--", color="#d97706", lw=1.8,
               label=f"Detection threshold = {threshold}")
    ax.axvline(0, ls=":", color="#16a34a", lw=1.8,
               label=f"True ASM starts at bit {marker}")
    ax.set(xlabel="32-bit window start relative to true sync-marker start (bits)",
           ylabel="Matching bits out of 32", ylim=(-1, 33),
           title="Sliding correlator: the marker appears as a tall match peak")
    ax.grid(True, alpha=.2)
    ax.legend(loc="best")
    fig.savefig(output / "correlation_example.png", dpi=165, facecolor="white")
    plt.close(fig)


def save_report(path: Path, summary: Metrics, rows: list[dict], threshold: int,
                snr: float, nframes: int, slip_every: int) -> None:
    line = f"{summary.true_markers_detected}/{summary.frames_sent} ({summary.detection_rate:.1%})"
    rate = summary.false_alarms_per_100k
    report = f"""# SPEC'26 - Level 1 technical report (generated)

## Problem and approach
Find the CCSDS **32-bit Attached Sync Marker (ASM)** `0x1ACFFC1D` in a
bit stream damaged by BPSK/AWGN.  This is a **software model**, not a
hardware/RTL implementation.  We use a 32-bit sliding match correlator.
A marker candidate is signaled if **at least {threshold} of 32** bits match.
Since every bit position is scanned, the algorithm is **not byte aligned**.

## Simulation configuration
- Eb/N0: **{snr:g} dB**, fixed-length TM transfer frames: **{FRAME_BYTES} bytes**.
- Number of generated frames: **{nframes}**; sync marker 4 bytes outside each frame.
- BPSK `0 -> +1`, `1 -> -1`; independent real AWGN sample per bit;
  hard receiver `bit = (noisy_sample < 0)`; no FEC or randomization.
- Optional bit slips inside frame data: **every {slip_every} frames**
  (`0` means disabled). Insertions/deletions shift later bit indices.
- The first 73 bits are random prefix to prove arbitrary starting phase.

## One-run results
| Metric | Result |
|---|---:|
| Empirical channel BER | {summary.channel_ber:.6f} |
| Theoretical BPSK/AWGN BER | {summary.ber_theoretical:.6f} |
| Found true ASM locations | {line} |
| Missed true ASM locations | {summary.missed_markers} |
| False marker candidates | {summary.false_alarms} |
| False candidates per 100k non-marker positions | {rate:.3f} |
| CRC-verified, decoded frames | {summary.verified_frames}/{summary.frames_sent} ({summary.usable_frame_rate:.1%}) |
| Received bit-stream length | {summary.total_bits:,} bits |

For this threshold, **ideal independent unbiased background bits**
produce a per-position false-alarm probability of about
`{expected_false_alarm_probability(threshold):.4g}`.  This analytic
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
4. **Threshold:** accept any window scoring at least {threshold}.
5. **Extract:** read the next {FRAME_BYTES} bytes after a candidate ASM.
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
"""
    path.write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", type=int, default=120,
                        help="Number of frames for the main demonstration (default: 120)")
    parser.add_argument("--sweep-frames", type=int, default=240,
                        help="Number of frames per Eb/N0 sample (default: 240)")
    parser.add_argument("--snr-db", type=float, default=8.0,
                        help="Eb/N0 in dB for the main demonstration (default: 8)")
    parser.add_argument("--threshold", type=int, default=28,
                        help="Minimum matches among 32 marker bits (default: 28)")
    parser.add_argument("--slip-every", type=int, default=0,
                        help="Every Nth frame has an inserted/deleted data bit; 0 = none")
    parser.add_argument("--seed", type=int, default=2026, help="RNG seed (default: 2026)")
    parser.add_argument("--output-dir", type=Path, default=Path("results"),
                        help="Directory for reports, plots and CSV files")
    args = parser.parse_args()
    if args.frames < 1 or args.sweep_frames < 1:
        parser.error("--frames and --sweep-frames must be positive")
    if not 1 <= args.threshold <= 32:
        parser.error("--threshold must be 1..32")
    if args.slip_every < 0:
        parser.error("--slip-every must be >= 0")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summary, scores, hits, truth, tx, rx = one_run(
        args.frames, args.seed, args.snr_db, args.threshold, args.slip_every)
    write_csv(args.output_dir / "detections.csv", [
        {"bit_offset": h.bit_offset, "matching_bits": h.matches,
         "is_true_marker_simulation_only": h.true_marker,
         "crc_ok": h.crc_ok, "header_ok": h.header_ok,
         "accepted": h.accepted, "vcid": h.vcid,
         "decoded_message": h.message} for h in hits
    ], ["bit_offset", "matching_bits", "is_true_marker_simulation_only",
        "crc_ok", "header_ok", "accepted", "vcid", "decoded_message"])
    write_csv(args.output_dir / "recovered_frames.csv", [
        {"start_bit": h.bit_offset, "vcid": h.vcid, "virtual_channel": VC_NAMES[h.vcid],
         "telemetry": h.message, "sync_matches": h.matches} for h in hits if h.accepted
    ], ["start_bit", "vcid", "virtual_channel", "telemetry", "sync_matches"])
    write_csv(args.output_dir / "transmitted_truth.csv", [asdict(t) for t in truth])

    sweep_rows = sweep(args.sweep_frames, args.seed + 999, args.threshold, args.slip_every)
    write_csv(args.output_dir / "sweep_results.csv", sweep_rows)
    create_plots(args.output_dir, sweep_rows, scores, truth, args.threshold)
    save_report(args.output_dir / "TECHNICAL_REPORT.md", summary, sweep_rows,
                args.threshold, args.snr_db, args.frames, args.slip_every)
    # Minimal bit preview, to connect marker location with data bits.
    first = truth[0].start
    excerpt = (f"First true ASM starts at bit offset {first} (0-based).\n"
               f"Standard ASM: {''.join(map(str, ASM_BITS.tolist()))} = 0x{ASM_HEX:08X}\n"
               f"TX at offset: {''.join(map(str, tx[first:first+104].tolist()))}\n"
               f"RX at offset: {''.join(map(str, rx[first:first+104].tolist()))}\n"
               "Bits 0..31 in this window are ASM; next 48 are primary header.\n"
               "TX/RX here are aligned to the channel stream INCLUDING slips.\n")
    (args.output_dir / "stream_preview.txt").write_text(excerpt, encoding="utf-8")
    # One hard-decided bit per line: compatible with $readmemb in a Verilog testbench.
    (args.output_dir / "tx_bits_readmemb.txt").write_text(
        "\n".join(map(str, tx.tolist())) + "\n", encoding="ascii")
    (args.output_dir / "rx_bits_readmemb.txt").write_text(
        "\n".join(map(str, rx.tolist())) + "\n", encoding="ascii")
    print("\nSPEC'26 Level 1 - CCSDS Telemetry Frame Synchronizer\n" + "=" * 55)
    print(f"Standard ASM (MSB first): 0x{ASM_HEX:08X} | threshold: {args.threshold}/32")
    print(f"Eb/N0: {args.snr_db:g} dB | measured BER: {summary.channel_ber:.5f}"
          f" | BPSK theory: {summary.ber_theoretical:.5f}")
    print(f"True markers detected: {summary.true_markers_detected}/{summary.frames_sent}"
          f" ({summary.detection_rate:.1%}); missed: {summary.missed_markers}")
    print(f"False candidate positions: {summary.false_alarms}"
          f" ({summary.false_alarms_per_100k:.2f} per 100k background positions)")
    print(f"CRC-verified telemetry frames: {summary.verified_frames}/{summary.frames_sent}")
    for h in [hit for hit in hits if hit.accepted][:5]:
        print(f"  recovered @ bit {h.bit_offset:>6}  VC{h.vcid}: {h.message}")
    print(f"\nSaved results to: {args.output_dir.resolve()}")
    print("Open walkthrough.html (separate HTML lab) to explore interactively.")


if __name__ == "__main__":
    main()
