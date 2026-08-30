function render_iteration_frame(frame, config, dimension, outputPath)
%RENDER_ITERATION_FRAME Export the solver's real per-iteration MATLAB view.
%   The PNG is written atomically so the sidecar never publishes a partial
%   frame while MATLAB is still rendering it.

dimension = lower(char(string(dimension)));
figureHandle = figure('Visible','off', 'Color','w', ...
    'Name','TopOptPilot live topology iteration', ...
    'Position',[100 100 1280 620]);
cleanup = onCleanup(@() close_if_valid(figureHandle)); %#ok<NASGU>

if strcmp(dimension, '3d')
    render_3d_frame(figureHandle, frame, config);
elseif strcmp(dimension, '2d')
    render_2d_frame(figureHandle, frame, config);
else
    error('TopOptPilot:RenderDimension', ...
        '迭代图像仅支持 2d 或 3d：%s', dimension);
end

drawnow;
tempPath = [outputPath, '.tmp.png'];
if isfile(tempPath), delete(tempPath); end
print(figureHandle, tempPath, '-dpng', '-r120');
if ~isfile(tempPath)
    error('TopOptPilot:RenderFrame', 'MATLAB 未生成迭代图像：%s', tempPath);
end
[moved, moveMessage] = movefile(tempPath, outputPath, 'f');
if ~moved
    error('TopOptPilot:RenderFrame', '无法提交迭代图像：%s', moveMessage);
end
end

function render_3d_frame(figureHandle, frame, config)
layout = tiledlayout(figureHandle, 1, 2, ...
    'Padding','compact', 'TileSpacing','compact');
topologyAxes = nexttile(layout);
density = frame.x;
if isfield(frame, 'domain_mask') && ~isempty(frame.domain_mask)
    density(~logical(frame.domain_mask)) = 0;
end
isoLevel = read_field(config, 'iso_level', 0.5);
[X, Y, Z] = meshgrid(1:size(density,2), 1:size(density,1), ...
    1:size(density,3));
surfaceData = isosurface(X, Y, Z, density, isoLevel);
if isempty(surfaceData.vertices)
    text(topologyAxes, 0.5, 0.5, '没有可显示的材料等值面。', ...
        'HorizontalAlignment','center');
    axis(topologyAxes, 'off');
else
    patch(topologyAxes, 'Vertices',surfaceData.vertices, ...
        'Faces',surfaceData.faces, 'FaceColor',[0.15 0.45 0.80], ...
        'EdgeColor','none', 'FaceAlpha',0.95);
    axis(topologyAxes, 'equal'); axis(topologyAxes, 'tight');
    xlabel(topologyAxes, 'x'); ylabel(topologyAxes, 'y');
    zlabel(topologyAxes, 'z'); view(topologyAxes, 3);
    grid(topologyAxes, 'on'); camlight(topologyAxes, 'headlight');
    lighting(topologyAxes, 'gouraud');
end
title(topologyAxes, sprintf('%s | iteration %d | objective %.3f', ...
    char(string(read_field(config, 'bc_type', 'cantilever'))), ...
    frame.iteration, frame.objective));

stressAxes = nexttile(layout);
if isfield(frame, 'von_mises') && ~isempty(frame.von_mises)
    result = struct('x',frame.x, 'von_mises',frame.von_mises, ...
        'config',config, 'domain_mask',true(size(frame.x)));
    if isfield(frame, 'domain_mask') && ~isempty(frame.domain_mask)
        result.domain_mask = logical(frame.domain_mask);
    end
    plot_stress_heatmap_3d(result, stressAxes);
else
    axis(stressAxes, 'off');
    text(stressAxes, 0.08, 0.68, sprintf('Iteration: %d / %d', ...
        frame.iteration, frame.max_iterations), 'FontSize',13);
    text(stressAxes, 0.08, 0.52, sprintf('Objective: %.6g', ...
        frame.objective), 'FontSize',13);
    text(stressAxes, 0.08, 0.36, sprintf('Volume fraction: %.4f', ...
        frame.volume_fraction), 'FontSize',13);
    text(stressAxes, 0.08, 0.20, sprintf('Change: %.4g', ...
        frame.change), 'FontSize',13);
    title(stressAxes, 'Live solver metrics');
end
end

function render_2d_frame(figureHandle, frame, config)
axesHandle = axes(figureHandle); %#ok<LAXES>
density = frame.x;
if isfield(frame, 'domain_mask') && ~isempty(frame.domain_mask)
    density(~logical(frame.domain_mask)) = 0;
end
densityImage = imagesc(axesHandle, -density, [-1,0]);
set(densityImage, 'Interpolation','nearest');
axis(axesHandle, 'equal'); axis(axesHandle, 'tight'); axis(axesHandle, 'off');
colormap(axesHandle, gray);
title(axesHandle, sprintf('%s | iteration %d | objective %.3f', ...
    char(string(read_field(config, 'bc_type', 'cantilever'))), ...
    frame.iteration, frame.objective));
end

function value = read_field(config, name, defaultValue)
if isfield(config, name) && ~isempty(config.(name))
    value = config.(name);
else
    value = defaultValue;
end
end

function close_if_valid(figureHandle)
if isgraphics(figureHandle)
    close(figureHandle);
end
end
