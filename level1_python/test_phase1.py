"""Run with: python -m unittest -v test_phase1.py"""
import unittest
import numpy as np

from ccsds_phase1 import (
    ASM_BITS, ASM_HEX, FRAME_BYTES, SCID, VC_NAMES,
    bpsk_awgn, build_stream, correlation_scores, crc16_ccitt,
    extract_frame, one_run, run_receiver,
)


class TestCCSDSPhase1(unittest.TestCase):
    def test_ccsds_asm_is_msb_first(self):
        self.assertEqual("".join(map(str, ASM_BITS.tolist())),
                         "00011010110011111111110000011101")
        self.assertEqual(int("".join(map(str, ASM_BITS.tolist())), 2), ASM_HEX)

    def test_crc_reference_vector(self):
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)
        self.assertNotEqual(crc16_ccitt(b"123456788"), 0x29B1)

    def test_noiseless_detect_and_decode_every_frame(self):
        tx, truth = build_stream(9, seed=11)
        scores = correlation_scores(tx)
        self.assertEqual([int(scores[f.start]) for f in truth], [32] * 9)
        metrics, _, detected = run_receiver(tx, truth, 32, 0.0, 0.0)
        self.assertEqual(metrics.true_markers_detected, 9)
        self.assertEqual(metrics.verified_frames, 9)
        self.assertEqual(metrics.false_alarms, 0)
        valid = [d for d in detected if d.accepted]
        self.assertEqual([d.vcid for d in valid], [0, 1, 2] * 3)
        self.assertTrue(all("=" in d.message for d in valid))

    def test_markers_are_found_after_an_insert_or_delete(self):
        tx, truth = build_stream(10, seed=42, slip_every=3)
        self.assertTrue(any(f.slip.startswith("1 inserted") for f in truth))
        self.assertTrue(any(f.slip.startswith("1 deleted") for f in truth))
        scores = correlation_scores(tx)
        self.assertTrue(all(scores[f.start] == 32 for f in truth))
        metrics, _, _ = run_receiver(tx, truth, 31, 0.0, 0.0)
        self.assertEqual(metrics.true_markers_detected, 10)
        self.assertEqual(metrics.verified_frames, 7)  # three slipped frames

    def test_bpsk_no_noise(self):
        bits = np.array([0, 1, 1, 0, 0, 1], dtype=np.uint8)
        decisions, theory = bpsk_awgn(bits, 10, np.zeros(len(bits)))
        np.testing.assert_array_equal(decisions, bits)
        self.assertTrue(0 <= theory < 1e-4)

    def test_bit_flip_tolerance(self):
        tx, truth = build_stream(1, 99)
        tx[truth[0].start + 2] ^= 1
        tx[truth[0].start + 6] ^= 1
        tx[truth[0].start + 11] ^= 1
        tx[truth[0].start + 30] ^= 1
        self.assertEqual(int(correlation_scores(tx)[truth[0].start]), 28)
        ok28, _, _ = run_receiver(tx, truth, 28, 0.0, 0.0)
        bad29, _, _ = run_receiver(tx, truth, 29, 0.0, 0.0)
        self.assertEqual(ok28.true_markers_detected, 1)
        self.assertEqual(bad29.true_markers_detected, 0)

    def test_incorrect_frame_fails_crc(self):
        tx, truth = build_stream(1, 2026)
        ok = extract_frame(tx, truth[0].start)
        self.assertTrue(ok[0] and ok[1] and ok[3])
        tx[truth[0].start + 32 + 119] ^= 1
        bad = extract_frame(tx, truth[0].start)
        self.assertFalse(bad[0])


if __name__ == "__main__":
    unittest.main()
