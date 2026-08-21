%DEMO_CASE_COMPATIBILITY Filter behavior for full and irregular domains.
clear;
clc;

nelx = 60;
nely = 20;
rmin = 2.5;
x = 0.5*ones(nely, nelx);
[rowIndex, columnIndex] = ndgrid(1:nely, 1:nelx);
dc = -1.0 - 0.8*mod(rowIndex + columnIndex, 2);

% MBB, cantilever and simply-supported cases use the full rectangle.
fullConfig = struct('filter_type','sensitivity','bc_type','cantilever');
[dcFull, infoFull] = filter_solver( ...
    nelx, nely, rmin, x, dc, fullConfig);

% Example L-shaped domain. The exact cutout orientation and size should be
% agreed with the main-program owner; the filter only consumes this mask.
lMask = true(nely, nelx);
lMask(1:round(nely/2), round(nelx/2)+1:end) = false;
lConfig = struct('filter_type','sensitivity', ...
    'bc_type','L-bracket','domain_mask',lMask);
[dcL, infoL] = filter_solver(nelx, nely, rmin, x, dc, lConfig);

figure('Color','w','Name','Case-compatible sensitivity filter');
tiledlayout(2,2,'Padding','compact','TileSpacing','compact');
sensitivityLimits = [min(dc(:)), max(dc(:))];

nexttile;
imagesc(dc, sensitivityLimits);
axis image tight;
colorbar;
title('Original sensitivity');

nexttile;
imagesc(dcFull, sensitivityLimits);
axis image tight;
colorbar;
title(sprintf('%s: %d active elements', ...
    infoFull.bc_type, infoFull.active_elements));

nexttile;
imagesc(lMask);
axis image tight;
colorbar;
title('Example L-domain mask');

nexttile;
displayL = dcL;
displayL(~lMask) = NaN;
imagesc(displayL, sensitivityLimits);
axis image tight;
colorbar;
title(sprintf('%s: %d inactive elements', ...
    infoL.bc_type, infoL.inactive_elements));

colormap(parula);
