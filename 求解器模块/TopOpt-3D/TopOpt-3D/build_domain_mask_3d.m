function domainMask = build_domain_mask_3d( ...
        nelx, nely, nelz, bcType, geometryConfig)
%BUILD_DOMAIN_MASK_3D 构建三维体素设计域。
%   常规工况返回完整长方体；L-bracket 返回沿 z 方向挤出的 L 形截面。
%   x(ely,elx,elz) 中 ely=1 是物理下侧，ely=nely 是物理上侧。

if nargin < 5 || isempty(geometryConfig)
    geometryConfig = struct();
end
domainMask = true(nely, nelx, nelz);
if ~strcmpi(char(string(bcType)), 'L-bracket')
    return;
end

corner = lower(char(string(read_field( ...
    geometryConfig, 'cut_corner', 'upper_right'))));
widthRatio = read_field(geometryConfig, 'cut_width_ratio', 0.5);
heightRatio = read_field(geometryConfig, 'cut_height_ratio', 0.5);
validateattributes(widthRatio, {'numeric'}, ...
    {'scalar','real','finite','>',0,'<',1});
validateattributes(heightRatio, {'numeric'}, ...
    {'scalar','real','finite','>',0,'<',1});

cutWidth = max(1, min(nelx-1, round(widthRatio*nelx)));
cutHeight = max(1, min(nely-1, round(heightRatio*nely)));
switch corner
    case 'upper_right'
        rows = nely-cutHeight+1:nely;
        columns = nelx-cutWidth+1:nelx;
    case 'upper_left'
        rows = nely-cutHeight+1:nely;
        columns = 1:cutWidth;
    case 'lower_right'
        rows = 1:cutHeight;
        columns = nelx-cutWidth+1:nelx;
    case 'lower_left'
        rows = 1:cutHeight;
        columns = 1:cutWidth;
    otherwise
        error('build_domain_mask_3d:UnknownCorner', ...
            ['cut_corner 仅支持 upper_right、upper_left、', ...
             'lower_right、lower_left。']);
end
domainMask(rows, columns, :) = false;
end

function value = read_field(config, name, defaultValue)
if isfield(config, name) && ~isempty(config.(name))
    value = config.(name);
else
    value = defaultValue;
end
end
