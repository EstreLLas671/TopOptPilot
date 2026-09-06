function [rminNow, info] = adaptive_filter_radius_3d(rminInput, filterConfig)
%ADAPTIVE_FILTER_RADIUS_3D 选择固定或逐步缩小的三维滤波半径。
%   自适应模式使用 rminNow = rminEnd + (rminStart-rminEnd)
%   *(1-progress)^power；前期较强滤波有利于稳定，后期较小半径可保留
%   更细的结构特征。

if nargin < 2 || isempty(filterConfig)
    filterConfig = struct();
end
validateattributes(rminInput, {'numeric'}, ...
    {'scalar','real','finite','positive'});

strategy = lower(char(string(read_field( ...
    filterConfig, 'radius_strategy', 'fixed'))));
switch strategy
    case {'fixed','constant'}
        rminNow = rminInput;
        canonicalStrategy = 'fixed';
        iteration = NaN;
        maxIterations = NaN;

    case {'adaptive','scheduled'}
        iteration = read_field(filterConfig, 'iteration', []);
        maxIterations = read_field(filterConfig, 'max_iterations', []);
        rminEnd = read_field(filterConfig, 'rmin_end', rminInput);
        rminStart = read_field(filterConfig, 'rmin_start', ...
            max(rminEnd, 2*rminEnd));
        schedulePower = read_field(filterConfig, 'schedule_power', 2.0);
        validateattributes(iteration, {'numeric'}, ...
            {'scalar','real','finite','integer','positive'});
        validateattributes(maxIterations, {'numeric'}, ...
            {'scalar','real','finite','integer','positive'});
        validateattributes(rminStart, {'numeric'}, ...
            {'scalar','real','finite','positive'});
        validateattributes(rminEnd, {'numeric'}, ...
            {'scalar','real','finite','positive'});
        validateattributes(schedulePower, {'numeric'}, ...
            {'scalar','real','finite','positive'});
        if rminStart < rminEnd
            error('adaptive_filter_radius_3d:InvalidRadiusRange', ...
                'rmin_start 必须大于或等于 rmin_end。');
        end
        if maxIterations == 1
            progress = 1.0;
        else
            progress = (min(iteration,maxIterations)-1)/(maxIterations-1);
        end
        rminNow = rminEnd + (rminStart-rminEnd) ...
            * (1-progress)^schedulePower;
        canonicalStrategy = 'adaptive';

    otherwise
        error('adaptive_filter_radius_3d:UnknownStrategy', ...
            'radius_strategy 仅支持 fixed 或 adaptive。');
end

info = struct('radius_strategy', canonicalStrategy, ...
    'iteration', iteration, 'max_iterations', maxIterations, 'rmin', rminNow);
end

function value = read_field(config, fieldName, defaultValue)
if isfield(config, fieldName) && ~isempty(config.(fieldName))
    value = config.(fieldName);
else
    value = defaultValue;
end
end
