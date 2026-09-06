function [rminNow, info] = adaptive_filter_radius(rminInput, filterConfig)
%ADAPTIVE_FILTER_RADIUS Select a fixed or iteration-dependent radius.
%   Fixed mode preserves the original 99-line behavior exactly.
%
%   Adaptive mode uses
%     rminNow = rminEnd + (rminStart-rminEnd)*(1-progress)^power
%   where progress runs from 0 at iteration 1 to 1 at maxIterations.

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
            error('adaptive_filter_radius:InvalidRadiusRange', ...
                'rmin_start must be greater than or equal to rmin_end.');
        end

        clampedIteration = min(iteration, maxIterations);
        if maxIterations == 1
            progress = 1.0;
        else
            progress = (clampedIteration-1)/(maxIterations-1);
        end
        rminNow = rminEnd + (rminStart-rminEnd) ...
            *(1-progress)^schedulePower;
        canonicalStrategy = 'adaptive';

    otherwise
        error('adaptive_filter_radius:UnknownStrategy', ...
            'Unknown radius_strategy "%s". Use fixed or adaptive.', ...
            strategy);
end

info = struct();
info.radius_strategy = canonicalStrategy;
info.iteration = iteration;
info.max_iterations = maxIterations;
info.rmin = rminNow;
end

function value = read_field(config, fieldName, defaultValue)
if isfield(config, fieldName) && ~isempty(config.(fieldName))
    value = config.(fieldName);
else
    value = defaultValue;
end
end
