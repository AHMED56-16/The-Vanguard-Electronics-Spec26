"""
SPEC'26 - CCSDS Telemetry Frame Synchronizer : bit-exact golden model (Level 1 + reference for Level 2/3)

* ASM (Attached Sync Marker) = 0x1ACFFC1D  (CCSDS 131.0-B, 32-bit ASM; its bitwise complement 0xE53003E2
  appears when a BPSK demodulator has a 180-degree phase ambiguity)
* TM Transfer Frame primary header (CCSDS 132.0-B): Version(2) SCID(10) VCID(3) OCF(1) MCFC(8) VCFC(8) Status(16)
* Optional: pseudo-randomizer (x^8+x^7+x^5+x^3+1, seed all-ones) and FECF CRC-16 (poly 0x1021, init 0xFFFF)

The FSM below is a line-by-line twin of rtl/ccsds_frame_sync.v (same tolerances, slip window, counters).
"""
import numpy as np

ASM = 0x1ACFFC1D
IASM = (~ASM) & 0xFFFFFFFF
SEARCH, CHECK, LOCK, FLY = 0, 1, 2, 3
STATE_NAMES = ["SEARCH", "CHECK", "LOCK", "FLYWHEEL"]


def popcount(x):
    return bin(x & 0xFFFFFFFF).count("1")


def crc16(data, init=0xFFFF):
    crc = init
    for byte in data:
        for i in range(7, -1, -1):
            fb = ((crc >> 15) & 1) ^ ((byte >> i) & 1)
            crc = (crc << 1) & 0xFFFF
            if fb:
                crc ^= 0x1021
    return crc


def prs_bits(n):
    """CCSDS pseudo-random sequence: a[n+8] = a[n+7]^a[n+5]^a[n+3]^a[n], seed = eight ones"""
    s = [1] * 8
    out = []
    for _ in range(n):
        out.append(s[0])
        new = s[7] ^ s[5] ^ s[3] ^ s[0]
        s = s[1:] + [new]
    return out


# ------------------------------------------------------------------ frame / stream generation
def bytes_to_bits(bs):
    return [(b >> i) & 1 for b in bs for i in range(7, -1, -1)]


def make_frame(rng, fb, scid, vcid, mcfc, vcfc, crc_en=True):
    hdr = [(0 << 6) | (scid >> 4), ((scid & 0xF) << 4) | (vcid << 1) | 0, mcfc & 255, vcfc & 255, 0, 0]
    pay_len = fb - 6 - (2 if crc_en else 0)
    body = hdr + [int(x) for x in rng.integers(0, 256, pay_len)]
    if crc_en:
        c = crc16(body)
        body += [c >> 8, c & 255]
    return bytes(body)


def cadu_bits(frame, derand=False):
    bits = bytes_to_bits(frame)
    if derand:
        r = prs_bits(len(bits))
        bits = [a ^ b for a, b in zip(bits, r)]
    return bytes_to_bits(ASM.to_bytes(4, "big")) + bits


def ber_from_esn0(esn0_db):
    from math import erfc, sqrt
    return 0.5 * erfc(sqrt(10 ** (esn0_db / 10)))      # BPSK hard decision: Q(sqrt(2 Es/N0))


# ------------------------------------------------------------------ the synchronizer (bit-exact twin of the RTL)
class FrameSync:
    def __init__(self, FB=64, T_SEARCH=2, T_CHECK=4, T_LOCK=6, T_SLIP=2, W=4, CHECK_N=1, FLY_MAX=3,
                 derand=False, crc_en=True):
        assert FB >= 6 and 0 <= W <= 7 and T_SEARCH < 16
        self.FB, self.T_SEARCH, self.T_CHECK, self.T_LOCK, self.T_SLIP = FB, T_SEARCH, T_CHECK, T_LOCK, T_SLIP
        self.W, self.CHECK_N, self.FLY_MAX, self.derand, self.crc_en = W, CHECK_N, FLY_MAX, derand, crc_en
        self.N = 32 + 8 * FB
        self.reset()

    def reset(self):
        self.sr = 0
        self.state = SEARCH
        self.pol = 0
        self.cnt = 1
        self.chk_ok = 0
        self.miss = 0
        self.late_ok = 0
        self.acq = 0
        self.slips = 0
        self.lol = 0
        self.vc_count = [0] * 8
        self.frames = []
        self.start_frame()
        self.i = 0

    # --- per-frame datapath (serial -> bytes, header, CRC, de-randomizer)
    def start_frame(self):
        self.bits_in = 0
        self.cur = bytearray()
        self.sh = 0
        self.crc = 0xFFFF
        self.lfsr = [1] * 8
        self.vcid = 0
        self.crc_ok = 0

    def data_bit(self, b):
        rnd = 0
        if self.derand:
            rnd = self.lfsr[0]
            new = self.lfsr[7] ^ self.lfsr[5] ^ self.lfsr[3] ^ self.lfsr[0]
            self.lfsr = self.lfsr[1:] + [new]
        d = b ^ self.pol ^ rnd
        fb = ((self.crc >> 15) & 1) ^ d
        self.crc = ((self.crc << 1) & 0xFFFF) ^ (0x1021 if fb else 0)
        self.sh = ((self.sh << 1) | d) & 0xFF
        self.bits_in += 1
        if self.bits_in % 8 == 0:
            self.cur.append(self.sh)
            if len(self.cur) == 2:
                self.vcid = (self.cur[1] >> 1) & 7
        if self.bits_in == 8 * self.FB:
            self.crc_ok = int(self.crc == 0)

    def frame_done(self, good, fly, slip):
        rec = dict(data=bytes(self.cur), vcid=self.vcid, good=good, fly=fly, slip=slip, crc_ok=self.crc_ok)
        self.frames.append(rec)
        if (not slip) and (self.crc_ok or not self.crc_en):
            self.vc_count[self.vcid] += 1

    def match(self, m, T):
        return (m >= 32 - T) if self.pol else (m <= T)

    # --- one FSM step per input bit; (b, m) = bit and Hamming distance of the 32-bit window ending at b
    def step(self, b, m):
        st, N, j = self.state, self.N, self.cnt
        if st == SEARCH:
            if m <= self.T_SEARCH or m >= 32 - self.T_SEARCH:
                self.pol = 0 if m <= self.T_SEARCH else 1
                self.state = CHECK
                self.cnt = 1
                self.chk_ok = 0
            return
        if st == CHECK:
            if j == N:
                if self.match(m, self.T_CHECK):
                    self.chk_ok += 1
                    self.cnt = 1
                    if self.chk_ok >= self.CHECK_N:
                        self.state = LOCK
                        self.miss = 0
                        self.late_ok = 0
                        self.acq += 1
                        self.start_frame()
                else:
                    self.state = SEARCH
            else:
                self.cnt += 1
            return
        # ---- LOCK / FLYWHEEL
        if 1 <= j <= 8 * self.FB:
            self.data_bit(b)
        if j == N:
            if self.match(m, self.T_LOCK):
                self.frame_done(1, 0, 0)
                self.miss = 0
                self.late_ok = 0
                self.state = LOCK
            else:
                self.frame_done(0, 1, 0)
                self.miss += 1
                if self.miss >= self.FLY_MAX:
                    self.state = SEARCH
                    self.lol += 1
                    self.late_ok = 0
                else:
                    self.state = FLY
                    self.late_ok = 1
            self.cnt = 1
            self.start_frame()
        elif self.W and (N - self.W <= j <= N - 1) and self.match(m, self.T_SLIP):     # early slip (deleted bit)
            self.frame_done(0, 0, 1)
            self.slips += 1
            self.state = LOCK
            self.miss = 0
            self.late_ok = 0
            self.cnt = 1
            self.start_frame()
        elif self.late_ok and self.W and j <= self.W and self.match(m, self.T_SLIP):   # late slip (inserted bit)
            self.slips += 1
            self.state = LOCK
            self.miss = 0
            self.late_ok = 0
            self.cnt = 1
            self.start_frame()
        else:
            self.cnt += 1

    def run(self, bits):
        for b in bits:
            b = int(b)
            self.sr = ((self.sr << 1) | b) & 0xFFFFFFFF
            self.step(b, popcount(self.sr ^ ASM))
            self.i += 1
        return self.frames

    def summary(self):
        return dict(acq=self.acq, slips=self.slips, lol=self.lol, nframes=len(self.frames),
                    good=sum(f['good'] for f in self.frames), fly=sum(f['fly'] for f in self.frames),
                    slipf=sum(f['slip'] for f in self.frames), vc=list(self.vc_count))
