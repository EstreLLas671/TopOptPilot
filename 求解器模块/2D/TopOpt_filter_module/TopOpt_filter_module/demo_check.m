%DEMO_CHECK Visual demonstration of the extracted sensitivity filter.
clear;
clc;

nelx = 60;
nely = 20;
rmin = 2.5;
x = 0.5*ones(nely, nelx);

[rowIndex, columnIndex] = ndgrid(1:nely, 1:nelx);
dc = -1.0 - 0.8*mod(rowIndex + columnIndex, 2);
dcn = check(nelx, nely, rmin, x, dc);

figure('Color', 'w', 'Name', 'Sensitivity filter demo');
tiledlayout(1, 2, 'Padding', 'compact', 'TileSpacing', 'compact');

nexttile;
imagesc(dc);
axis image tight;
colorbar;
title('Original sensitivity');
xlabel('Element x');
ylabel('Element y');

nexttile;
imagesc(dcn);
axis image tight;
colorbar;
title(sprintf('Filtered sensitivity, r_{min}=%.1f', rmin));
xlabel('Element x');
ylabel('Element y');

colormap(parula);
