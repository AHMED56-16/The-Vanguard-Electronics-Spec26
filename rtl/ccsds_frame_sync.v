// =============================================================================
//  SPEC'26 - CCSDS Telemetry Frame Synchronizer  (Verilog-2001, synthesizable)
//
//  Input : serial hard-decision bit stream, one bit per clock where bit_valid=1
//  Finds : 32-bit ASM 0x1ACFFC1D (or its complement -> 180-degree polarity ambiguity, auto-corrected)
//  FSM   : SEARCH -> CHECK -> LOCK <-> FLYWHEEL -> SEARCH   (CCSDS 130.1-G style)
//  Slips : +-W bit window around the expected ASM position re-aligns the frame counter without a full re-search
//  Output: byte stream per transfer frame (ASM stripped, de-inverted, optional CCSDS de-randomizer),
//          decoded primary header (SCID / VCID / counters), per-frame status, per-VC frame counters.
//  Bit-exact twin of model/ccsds_model.py
// =============================================================================
module ccsds_frame_sync #(
    parameter FB        = 64,   // transfer-frame length in bytes (ASM NOT included). 1115 = RS(255,223), I=5
    parameter T_SEARCH  = 2,    // max ASM bit mismatches accepted in SEARCH
    parameter T_CHECK   = 4,    // ... in CHECK (verification)
    parameter T_LOCK    = 6,    // ... at the expected position in LOCK / FLYWHEEL
    parameter T_SLIP    = 2,    // ... for an off-position (slip) candidate
    parameter W         = 4,    // slip window (+-W bits, 0..7, 0 disables slip recovery)
    parameter CHECK_N   = 1,    // consecutive verified ASMs needed to declare LOCK
    parameter FLY_MAX   = 3,    // consecutive missed ASMs tolerated before loss of lock (SEARCH)
    parameter DERAND_EN = 0,    // 1: apply CCSDS pseudo-randomizer removal
    parameter CRC_EN    = 1     // 1: last 2 bytes of frame are FECF (CRC-16/CCITT-FALSE)
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        bit_valid,
    input  wire        bit_in,
    // frame byte stream
    output reg         byte_valid,
    output reg  [7:0]  byte_data,
    output reg         byte_sof,
    output reg         byte_eof,
    // decoded primary header (pulse after byte 3)
    output reg         hdr_valid,
    output reg  [1:0]  hdr_version,
    output reg  [9:0]  hdr_scid,
    output reg  [2:0]  hdr_vcid,
    output reg         hdr_ocf,
    output reg  [7:0]  hdr_mcfc,
    output reg  [7:0]  hdr_vcfc,
    // per-frame verdict (pulse at the position of the following ASM)
    output reg         fd_valid,
    output reg         fd_good,     // following ASM verified at the expected position
    output reg         fd_fly,      // ASM missed - frame delivered by flywheel
    output reg         fd_slip,     // frame ended early because of a detected bit slip (frame is invalid)
    output reg         fd_crc_ok,
    output reg  [2:0]  fd_vcid,
    // virtual-channel frame counters
    input  wire [2:0]  vc_sel,
    output wire [15:0] vc_count_out,
    // status
    output wire [1:0]  state,
    output wire        locked,
    output wire        pol_inv,
    output reg  [15:0] acq_count,
    output reg  [15:0] slip_count,
    output reg  [15:0] lol_count
);
    localparam [31:0] ASM = 32'h1ACFFC1D;
    localparam integer N  = 32 + 8*FB;              // bits per CADU (ASM + frame)
    localparam integer CW = $clog2(N + 2);
    localparam integer BW = $clog2(FB + 1);
    localparam [1:0] S_SEARCH = 2'd0, S_CHECK = 2'd1, S_LOCK = 2'd2, S_FLY = 2'd3;

    // ---------------- stage A : 32-bit shift register
    reg [31:0] sr;
    // ---------------- stage B : Hamming distance to ASM (registered => short critical path)
    reg [5:0]  m_q;
    reg        b_q;

    function [3:0] pop8(input [7:0] x);
        pop8 = x[0] + x[1] + x[2] + x[3] + x[4] + x[5] + x[6] + x[7];
    endfunction
    wire [31:0] diff = sr ^ ASM;
    wire [4:0]  s01  = pop8(diff[7:0])   + pop8(diff[15:8]);
    wire [4:0]  s23  = pop8(diff[23:16]) + pop8(diff[31:24]);
    wire [5:0]  pc   = s01 + s23;

    // ---------------- FSM / counters
    reg [1:0]    st;
    reg          pol;
    reg [CW-1:0] cnt;
    reg [3:0]    chk_ok, miss;
    reg          late_ok;

    assign state   = st;
    assign locked  = (st == S_LOCK) || (st == S_FLY);
    assign pol_inv = pol;

    // threshold comparators
    wire hit_pos_s  = (m_q <= T_SEARCH);
    wire hit_neg_s  = (m_q >= 32 - T_SEARCH);
    wire mt_check   = pol ? (m_q >= 32 - T_CHECK) : (m_q <= T_CHECK);
    wire mt_lock    = pol ? (m_q >= 32 - T_LOCK)  : (m_q <= T_LOCK);
    wire mt_slip    = pol ? (m_q >= 32 - T_SLIP)  : (m_q <= T_SLIP);
    wire early_win  = (W != 0) && (cnt >= N - W) && (cnt <= N - 1);
    wire late_win   = late_ok && (W != 0) && (cnt <= W);
    wire in_data    = (cnt <= 8*FB);

    // ---------------- per-frame datapath
    reg [2:0]    bph;
    reg [7:0]    sh;
    reg [BW-1:0] bytecnt;
    reg [15:0]   crc;
    reg [7:0]    lfsr;
    reg [7:0]    h0, h1, h2;
    reg [2:0]    vcid_q;
    reg          crc_ok_q;

    wire         rnd    = (DERAND_EN != 0) ? lfsr[0] : 1'b0;
    wire         d      = b_q ^ pol ^ rnd;
    wire         crc_fb = crc[15] ^ d;
    wire [15:0]  crc_nx = {crc[14:0], 1'b0} ^ (crc_fb ? 16'h1021 : 16'h0000);
    wire [7:0]   sh_nx  = {sh[6:0], d};
    wire         byte_done = (bph == 3'd7);

    reg [127:0]  vcc;
    assign vc_count_out = vcc[vc_sel*16 +: 16];

    // blocking temporaries (combinational decisions inside the clocked block)
    reg do_sf, do_fd, t_good, t_fly, t_slip;

    always @(posedge clk) begin
        if (!rst_n) begin
            sr <= 32'h0; m_q <= 6'd16; b_q <= 1'b0;
            st <= S_SEARCH; pol <= 1'b0; cnt <= {CW{1'b0}} + 1'b1; chk_ok <= 4'd0; miss <= 4'd0; late_ok <= 1'b0;
            bph <= 3'd0; sh <= 8'h0; bytecnt <= {BW{1'b0}}; crc <= 16'hFFFF; lfsr <= 8'hFF;
            h0 <= 8'h0; h1 <= 8'h0; h2 <= 8'h0; vcid_q <= 3'd0; crc_ok_q <= 1'b0;
            byte_valid <= 1'b0; byte_data <= 8'h0; byte_sof <= 1'b0; byte_eof <= 1'b0;
            hdr_valid <= 1'b0; hdr_version <= 2'd0; hdr_scid <= 10'd0; hdr_vcid <= 3'd0; hdr_ocf <= 1'b0;
            hdr_mcfc <= 8'd0; hdr_vcfc <= 8'd0;
            fd_valid <= 1'b0; fd_good <= 1'b0; fd_fly <= 1'b0; fd_slip <= 1'b0; fd_crc_ok <= 1'b0; fd_vcid <= 3'd0;
            acq_count <= 16'd0; slip_count <= 16'd0; lol_count <= 16'd0; vcc <= 128'd0;
        end else begin
            // one-clock pulses
            byte_valid <= 1'b0; byte_sof <= 1'b0; byte_eof <= 1'b0; hdr_valid <= 1'b0; fd_valid <= 1'b0;

            if (bit_valid) begin
                do_sf = 1'b0; do_fd = 1'b0; t_good = 1'b0; t_fly = 1'b0; t_slip = 1'b0;

                // pipeline: A -> B
                sr  <= {sr[30:0], bit_in};
                m_q <= pc;
                b_q <= sr[0];

                case (st)
                // ------------------------------------------------------------ SEARCH
                S_SEARCH: begin
                    if (hit_pos_s || hit_neg_s) begin
                        pol    <= ~hit_pos_s;
                        st     <= S_CHECK;
                        cnt    <= 1;
                        chk_ok <= 4'd0;
                    end
                end
                // ------------------------------------------------------------ CHECK
                S_CHECK: begin
                    if (cnt == N) begin
                        if (mt_check) begin
                            chk_ok <= chk_ok + 4'd1;
                            cnt    <= 1;
                            if ((chk_ok + 4'd1) >= CHECK_N) begin
                                st <= S_LOCK; miss <= 4'd0; late_ok <= 1'b0;
                                acq_count <= acq_count + 16'd1;
                                do_sf = 1'b1;
                            end
                        end else begin
                            st <= S_SEARCH;
                        end
                    end else begin
                        cnt <= cnt + 1'b1;
                    end
                end
                // ------------------------------------------------------------ LOCK / FLYWHEEL
                default: begin
                    // data path : bits 1 .. 8*FB after the ASM
                    if (in_data) begin
                        if (DERAND_EN != 0) lfsr <= {lfsr[7] ^ lfsr[5] ^ lfsr[3] ^ lfsr[0], lfsr[7:1]};
                        crc <= crc_nx;
                        sh  <= sh_nx;
                        bph <= bph + 3'd1;
                        if (byte_done) begin
                            byte_valid <= 1'b1;
                            byte_data  <= sh_nx;
                            byte_sof   <= (bytecnt == 0);
                            byte_eof   <= (bytecnt == FB - 1);
                            bytecnt    <= bytecnt + 1'b1;
                            if (bytecnt == 0) h0 <= sh_nx;
                            if (bytecnt == 1) begin h1 <= sh_nx; vcid_q <= sh_nx[3:1]; end
                            if (bytecnt == 2) h2 <= sh_nx;
                            if (bytecnt == 3) begin
                                hdr_valid   <= 1'b1;
                                hdr_version <= h0[7:6];
                                hdr_scid    <= {h0[5:0], h1[7:4]};
                                hdr_vcid    <= h1[3:1];
                                hdr_ocf     <= h1[0];
                                hdr_mcfc    <= h2;
                                hdr_vcfc    <= sh_nx;
                            end
                            if (bytecnt == FB - 1) crc_ok_q <= (crc_nx == 16'h0000);
                        end
                    end

                    if (cnt == N) begin                                   // expected ASM position
                        do_fd = 1'b1; do_sf = 1'b1; cnt <= 1;
                        if (mt_lock) begin
                            t_good = 1'b1; miss <= 4'd0; late_ok <= 1'b0; st <= S_LOCK;
                        end else begin
                            t_fly = 1'b1; miss <= miss + 4'd1;
                            if ((miss + 4'd1) >= FLY_MAX) begin
                                st <= S_SEARCH; lol_count <= lol_count + 16'd1; late_ok <= 1'b0;
                            end else begin
                                st <= S_FLY; late_ok <= 1'b1;
                            end
                        end
                    end else if (early_win && mt_slip) begin               // ASM early: a bit was deleted
                        do_fd = 1'b1; t_slip = 1'b1; do_sf = 1'b1;
                        slip_count <= slip_count + 16'd1;
                        st <= S_LOCK; miss <= 4'd0; late_ok <= 1'b0; cnt <= 1;
                    end else if (late_win && mt_slip) begin                // ASM late: a bit was inserted
                        do_sf = 1'b1;
                        slip_count <= slip_count + 16'd1;
                        st <= S_LOCK; miss <= 4'd0; late_ok <= 1'b0; cnt <= 1;
                    end else begin
                        cnt <= cnt + 1'b1;
                    end
                end
                endcase

                // frame verdict
                if (do_fd) begin
                    fd_valid  <= 1'b1;
                    fd_good   <= t_good;
                    fd_fly    <= t_fly;
                    fd_slip   <= t_slip;
                    fd_crc_ok <= crc_ok_q;
                    fd_vcid   <= vcid_q;
                    if (!t_slip && (crc_ok_q || (CRC_EN == 0)))
                        vcc[vcid_q*16 +: 16] <= vcc[vcid_q*16 +: 16] + 16'd1;
                end
                // start a fresh frame (overrides the datapath updates above)
                if (do_sf) begin
                    bph <= 3'd0; sh <= 8'h0; bytecnt <= {BW{1'b0}}; crc <= 16'hFFFF; lfsr <= 8'hFF;
                    vcid_q <= 3'd0; crc_ok_q <= 1'b0;
                end
            end
        end
    end
endmodule
