%RUN_L_BRACKET_DEMO Run an L-bracket with default or custom cutout values.
clear;
clc;

config = struct();
config.bc_type = 'L-bracket';
config.geometry.cut_corner = 'upper_right';
config.geometry.cut_width_ratio = 0.5;
config.geometry.cut_height_ratio = 0.5;
config.filter_strategy = 'adaptive';
config.move_start = 0.2;
config.move_end = 0.05;
config.display = true;
result = topopt_main(config); %#ok<NASGU>
