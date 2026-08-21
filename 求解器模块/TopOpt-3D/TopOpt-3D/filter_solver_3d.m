function [dcFiltered, info] = filter_solver_3d( ...
        nelx, nely, nelz, rmin, x, dc, filterConfig)
%FILTER_SOLVER_3D 三维灵敏度滤波模块入口。
%   filter_type 支持 sensitivity（默认）和 none；radius_strategy 支持
%   fixed（默认）和 adaptive。domain_mask 用于排除非设计体素。

if nargin < 7 || isempty(filterConfig)
    filterConfig = struct();
end
if ~isstruct(filterConfig)
    error('filter_solver_3d:InvalidConfig', ...
        'filterConfig 必须是结构体。');
end

filterType = lower(char(string(read_field( ...
    filterConfig, 'filter_type', 'sensitivity'))));
domainMask = read_field(filterConfig, 'domain_mask', ...
    true(nely, nelx, nelz));
validateattributes(domainMask, {'logical','numeric'}, ...
    {'size',[nely,nelx,nelz]});
domainMask = logical(domainMask);
[rminNow, radiusInfo] = adaptive_filter_radius_3d(rmin, filterConfig);

switch filterType
    case {'sensitivity','check'}
        dcFiltered = check_3d(nelx, nely, nelz, rminNow, x, dc, domainMask);
        canonicalType = 'sensitivity';
    case {'none','off'}
        validateattributes(dc, {'numeric'}, ...
            {'real','finite','size',[nely,nelx,nelz]});
        dcFiltered = dc;
        dcFiltered(~domainMask) = 0;
        canonicalType = 'none';
    otherwise
        error('filter_solver_3d:UnknownFilterType', ...
            'filter_type 仅支持 sensitivity 或 none。');
end

info = struct();
info.filter_type = canonicalType;
info.rmin = rminNow;
info.rmin_input = rmin;
info.radius_strategy = radiusInfo.radius_strategy;
info.iteration = radiusInfo.iteration;
info.max_iterations = radiusInfo.max_iterations;
info.active_elements = nnz(domainMask);
info.inactive_elements = numel(domainMask) - nnz(domainMask);
end

function value = read_field(config, name, defaultValue)
if isfield(config, name) && ~isempty(config.(name))
    value = config.(name);
else
    value = defaultValue;
end
end
