%RUN_INTEGRATED_DEMO Run the default MBB case.
clear;
clc;

config = struct();
config.bc_type = 'MBB';
config.filter_strategy = 'fixed';
config.move_start = 0.2;
config.move_end = 0.2;
config.display = true;
result = topopt_main(config); %#ok<NASGU>
