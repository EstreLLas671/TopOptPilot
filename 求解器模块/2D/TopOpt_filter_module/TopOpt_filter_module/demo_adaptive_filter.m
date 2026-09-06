%DEMO_ADAPTIVE_FILTER Visualize the proposed adaptive-radius innovation.
clear;
clc;

nelx = 60;
nely = 20;
x = 0.5*ones(nely, nelx);
[rowIndex, columnIndex] = ndgrid(1:nely, 1:nelx);
dc = -1.0 - 0.8*mod(rowIndex + columnIndex, 2);

config = struct();
config.filter_type = 'sensitivity';
config.radius_strategy = 'adaptive';
config.max_iterations = 100;
config.rmin_start = 3.0;
config.rmin_end = 1.5;
config.schedule_power = 2.0;

sampleIterations = [1, 50, 100];
filtered = cell(size(sampleIterations));
radiusValues = zeros(size(sampleIterations));
for idx = 1:numel(sampleIterations)
    config.iteration = sampleIterations(idx);
    [filtered{idx}, info] = filter_solver( ...
        nelx, nely, config.rmin_end, x, dc, config);
    radiusValues(idx) = info.rmin;
end

figure('Color','w','Name','Adaptive sensitivity-filter radius');
tiledlayout(2,2,'Padding','compact','TileSpacing','compact');
colorLimits = [min(dc(:)), max(dc(:))];

nexttile;
imagesc(dc, colorLimits);
axis image tight;
colorbar;
title('Raw sensitivity');

for idx = 1:numel(sampleIterations)
    nexttile;
    imagesc(filtered{idx}, colorLimits);
    axis image tight;
    colorbar;
    title(sprintf('Iteration %d: r_{min}=%.2f', ...
        sampleIterations(idx), radiusValues(idx)));
end
colormap(parula);

fprintf('Adaptive-radius demo: %.2f -> %.2f -> %.2f\n', ...
    radiusValues(1), radiusValues(2), radiusValues(3));
