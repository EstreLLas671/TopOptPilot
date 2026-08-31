function visualization = write_result_visualizations(result, config, dimension, outputDir)
%WRITE_RESULT_VISUALIZATIONS Produce final images only from solver evidence.
%   The bridge already writes live MATLAB frames.  This function additionally
%   exports the final density topology and the exact objective-history curve so
%   a headless API/CLI can present scientifically traceable images without
%   synthesizing a chart from simulated values.

visualization = struct('status','completed', ...
    'convergence_png','convergence.png', ...
    'density_png','density.png');
try
    write_convergence(result, fullfile(outputDir, visualization.convergence_png));
    write_final_density(result, config, dimension, fullfile(outputDir, visualization.density_png));
catch err
    % A numerical result remains evidence even if the optional graphical
    % renderer is unavailable on a headless MATLAB host.  Record that fact in
    % result_summary.json rather than claiming images that do not exist.
    visualization.status = 'failed';
    visualization.error = err.message;
    if isfile(fullfile(outputDir, visualization.convergence_png))
        delete(fullfile(outputDir, visualization.convergence_png));
    end
    if isfile(fullfile(outputDir, visualization.density_png))
        delete(fullfile(outputDir, visualization.density_png));
    end
end
end

function write_convergence(result, outputPath)
history = double(result.objective_history(:));
if isempty(history) || any(~isfinite(history))
    error('TopOptPilot:VisualizationHistory', ...
        '无法从真实求解器 objective_history 生成收敛曲线。');
end
figureHandle = figure('Visible','off', 'Color','w', ...
    'Name','TopOptPilot real MATLAB convergence', ...
    'Position',[100 100 960 560]);
cleanup = onCleanup(@() close_if_valid(figureHandle)); %#ok<NASGU>
axesHandle = axes(figureHandle); %#ok<LAXES>
iterations = (1:numel(history)).';
plot(axesHandle, iterations, history, '-o', ...
    'LineWidth',1.6, 'MarkerSize',4, 'Color',[0.11 0.34 0.67]);
grid(axesHandle, 'on'); box(axesHandle, 'on');
xlabel(axesHandle, 'Iteration');
ylabel(axesHandle, 'Compliance');
title(axesHandle, sprintf('Real MATLAB convergence (%d iterations)', numel(history)));
write_png_atomic(figureHandle, outputPath);
end

function write_final_density(result, config, dimension, outputPath)
frame = struct();
frame.iteration = result.iterations;
frame.max_iterations = result.iterations;
frame.x = result.x;
frame.objective = result.objective;
frame.volume_fraction = result.volume_fraction;
frame.change = read_last(result, 'change_history', NaN);
if isfield(result, 'domain_mask'), frame.domain_mask = result.domain_mask; end
if isfield(result, 'von_mises'), frame.von_mises = result.von_mises; end
render_iteration_frame(frame, config, dimension, outputPath);
end

function value = read_last(result, name, fallback)
if isfield(result, name) && ~isempty(result.(name))
    values = result.(name);
    value = values(end);
else
    value = fallback;
end
end

function write_png_atomic(figureHandle, outputPath)
temporary = [outputPath, '.tmp.png'];
if isfile(temporary), delete(temporary); end
print(figureHandle, temporary, '-dpng', '-r150');
if ~isfile(temporary)
    error('TopOptPilot:VisualizationWrite', ...
        'MATLAB 未生成收敛曲线 PNG：%s', temporary);
end
[moved, message] = movefile(temporary, outputPath, 'f');
if ~moved
    error('TopOptPilot:VisualizationWrite', ...
        '无法提交收敛曲线 PNG：%s', message);
end
end

function close_if_valid(figureHandle)
if isgraphics(figureHandle)
    close(figureHandle);
end
end
