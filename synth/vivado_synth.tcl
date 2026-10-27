# Run:  vivado -mode batch -source vivado_synth.tcl      (Vivado WebPACK is enough; no board needed)
# Target: Artix-7 XC7A35T (Digilent Basys-3 / Arty-class low-cost board). Change -part for another device.
set part xc7a35tcpg236-1
read_verilog ../rtl/ccsds_frame_sync.v
synth_design -top ccsds_frame_sync -part $part -generic FB=1115 -generic DERAND_EN=1 -generic CRC_EN=1
create_clock -name clk -period 20.000 [get_ports clk]          ;# 50 MHz requirement
# I/O is not timed in this stand-alone report (module is meant to sit between on-chip blocks)
set_false_path -from [get_ports {rst_n bit_valid bit_in vc_sel}]
set_false_path -to   [get_ports -filter {DIRECTION == OUT}]
opt_design
place_design
route_design
report_utilization    -file util_post_route.rpt
report_timing_summary -file timing_post_route.rpt -delay_type min_max -max_paths 5
puts "=== look for 'WNS' >= 0 in timing_post_route.rpt (positive slack = 50 MHz met) ==="
