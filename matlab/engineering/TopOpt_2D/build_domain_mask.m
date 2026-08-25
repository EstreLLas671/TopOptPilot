function domainMask = build_domain_mask(nelx, nely, bcType, geometryConfig)
%BUILD_DOMAIN_MASK Build the designable element region for each case.
%   Rectangular cases return an all-true mask. L-bracket uses a configurable
%   rectangular corner cutout. Element row 1 is the physical bottom row.

if nargin < 4 || isempty(geometryConfig)
    geometryConfig = struct();
end

domainMask = true(nely, nelx);
if ~strcmpi(char(string(bcType)), 'L-bracket')
    return;
end

corner = read_field(geometryConfig, 'cut_corner', 'upper_right');
widthRatio = read_field(geometryConfig, 'cut_width_ratio', 0.5);
heightRatio = read_field(geometryConfig, 'cut_height_ratio', 0.5);

validateattributes(widthRatio, {'numeric'}, ...
    {'scalar','real','finite','>',0,'<',1});
validateattributes(heightRatio, {'numeric'}, ...
    {'scalar','real','finite','>',0,'<',1});

cutWidth = max(1, min(nelx-1, round(widthRatio*nelx)));
cutHeight = max(1, min(nely-1, round(heightRatio*nely)));
corner = lower(char(string(corner)));

switch corner
    case 'upper_left'
        rows = 1:cutHeight;
        columns = 1:cutWidth;
    case 'upper_right'
        rows = 1:cutHeight;
        columns = nelx-cutWidth+1:nelx;
    case 'lower_left'
        rows = nely-cutHeight+1:nely;
        columns = 1:cutWidth;
    case 'lower_right'
        rows = nely-cutHeight+1:nely;
        columns = nelx-cutWidth+1:nelx;
    otherwise
        error('build_domain_mask:UnknownCorner', ...
            'cut_corner must be upper_left, upper_right, lower_left or lower_right.');
end

domainMask(rows, columns) = false;
end

function value = read_field(config, name, defaultValue)
if isfield(config, name) && ~isempty(config.(name))
    value = config.(name);
else
    value = defaultValue;
end
end
