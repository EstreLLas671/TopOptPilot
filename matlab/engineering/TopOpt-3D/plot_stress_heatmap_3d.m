function plot_stress_heatmap_3d(result, parentAxes)
%PLOT_STRESS_HEATMAP_3D 在最终材料等值面上绘制 Von Mises 应力热力图。
%   颜色只映射到 density >= iso_level 的材料表面；为了避免载荷点应力
%   奇异性主导颜色范围，颜色上限默认截断到材料区域应力的 95 百分位。

if nargin < 2 || isempty(parentAxes)
    figure('Color','w','Name','3D Von Mises stress heatmap');
    parentAxes = axes();
end
if ~isfield(result, 'von_mises')
    error('plot_stress_heatmap_3d:MissingStress', ...
        'result 中缺少 von_mises；请使用新版 topopt3d_main 运行。');
end

isoLevel = read_field(result.config, 'iso_level', 0.5);
density = result.x;
density(~result.domain_mask) = 0;
stress = result.von_mises;
[X, Y, Z] = meshgrid(1:size(density,2), 1:size(density,1), ...
    1:size(density,3));
[faces, vertices, colors] = isosurface(X, Y, Z, density, isoLevel, stress);
if isempty(vertices)
    text(parentAxes, 0.5, 0.5, '没有可显示的材料等值面。', ...
        'HorizontalAlignment','center');
    axis(parentAxes, 'off');
    return;
end

patch(parentAxes, 'Faces',faces, 'Vertices',vertices, ...
    'FaceVertexCData',colors, 'FaceColor','interp', 'EdgeColor','none');
axis(parentAxes, 'equal');
axis(parentAxes, 'tight');
xlabel(parentAxes, 'x'); ylabel(parentAxes, 'y'); zlabel(parentAxes, 'z');
view(parentAxes, 3); grid(parentAxes, 'on');
colormap(parentAxes, turbo(256));
stressColorbar = colorbar(parentAxes);
stressColorbar.Label.String = 'Von Mises stress';
validStress = stress(density >= isoLevel);
if ~isempty(validStress) && any(validStress > 0)
    limits = prctile(validStress(validStress > 0), [5, 95]);
    if limits(2) > limits(1)
        clim(parentAxes, limits);
    end
end
camlight(parentAxes, 'headlight');
lighting(parentAxes, 'gouraud');
title(parentAxes, sprintf('Von Mises stress heatmap (density >= %.2f)', ...
    isoLevel));
end

function value = read_field(config, name, defaultValue)
if isfield(config, name) && ~isempty(config.(name))
    value = config.(name);
else
    value = defaultValue;
end
end
