function [dcFiltered, info] = filter_solver(nelx, nely, rmin, x, dc, filter_config)
%FILTER_SOLVER Configurable entry point for the sensitivity-filter module.
%   [dcFiltered,info] = FILTER_SOLVER(nelx,nely,rmin,x,dc,filter_config)
%   follows the same configuration style as FE_solver.
%
%   Supported filter_config fields:
%     filter_type : 'sensitivity' (default) or 'none'
%     domain_mask : nely-by-nelx logical mask (default: all true)
%     bc_type     : optional label used only in returned diagnostic info
%     radius_strategy : 'fixed' (default) or 'adaptive'
%     iteration       : current optimization iteration (adaptive only)
%     max_iterations  : planned maximum iterations (adaptive only)
%     rmin_start      : initial, stronger filter radius (adaptive only)
%     rmin_end        : final, finer filter radius (default: input rmin)
%     schedule_power  : decay-curve exponent (default: 2)
%
%   Boundary-condition names do not change the filter formula. MBB,
%   cantilever and simply-supported cases normally use a full domain.
%   L-bracket and custom cases should supply domain_mask when they contain
%   void/non-design elements.

if nargin < 6 || isempty(filter_config)
    filter_config = struct();
end
if ~isstruct(filter_config)
    error('filter_solver:InvalidConfig', ...
        'filter_config must be a structure.');
end

filterType = read_config_field(filter_config, 'filter_type', 'sensitivity');
domainMask = read_config_field(filter_config, 'domain_mask', ...
    true(nely, nelx));
caseName = read_config_field(filter_config, 'bc_type', 'unspecified');
[effectiveRmin, radiusInfo] = adaptive_filter_radius(rmin, filter_config);

validateattributes(domainMask, {'logical','numeric'}, {'size',[nely,nelx]});
domainMask = logical(domainMask);
filterType = lower(char(string(filterType)));

switch filterType
    case {'sensitivity','check'}
        dcFiltered = check(nelx, nely, effectiveRmin, x, dc, domainMask);
        canonicalType = 'sensitivity';

    case {'none','off'}
        validateattributes(dc, {'numeric'}, ...
            {'real','finite','size',[nely,nelx]});
        dcFiltered = dc;
        dcFiltered(~domainMask) = 0;
        canonicalType = 'none';

    otherwise
        error('filter_solver:UnknownFilterType', ...
            'Unknown filter_type "%s". Supported values: sensitivity, none.', ...
            filterType);
end

info = struct();
info.filter_type = canonicalType;
info.bc_type = char(string(caseName));
info.active_elements = nnz(domainMask);
info.inactive_elements = numel(domainMask) - nnz(domainMask);
info.rmin = effectiveRmin;
info.rmin_input = rmin;
info.radius_strategy = radiusInfo.radius_strategy;
info.iteration = radiusInfo.iteration;
info.max_iterations = radiusInfo.max_iterations;
end

function value = read_config_field(config, fieldName, defaultValue)
if isfield(config, fieldName) && ~isempty(config.(fieldName))
    value = config.(fieldName);
else
    value = defaultValue;
end
end
