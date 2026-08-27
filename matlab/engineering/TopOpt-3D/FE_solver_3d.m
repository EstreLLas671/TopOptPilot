function [U, K, freedofs, fixeddofs, F] = FE_solver_3d( ...
        nelx, nely, nelz, x, penal, bc_config)
%FE_SOLVER_3D 三维 SIMP 有限元求解器。
%   采用 8 节点六面体单元、三维线弹性和批量稀疏刚度组装。X 的尺寸
%   必须是 nely × nelx × nelz；每个节点具有 x、y、z 三个自由度。
%   可通过 bc_config.Emin 设置最小刚度比例，默认 1e-9。
%
%   支持的 bc_config.bc_type：MBB、cantilever、simply_supported、
%   L-bracket、custom。custom 工况需要：
%     bc_config.fixeddofs  固定自由度编号
%     bc_config.loads      每行 [节点编号, 方向(1=x,2=y,3=z), 力值]

validateattributes(nelx, {'numeric'}, {'scalar','integer','positive'});
validateattributes(nely, {'numeric'}, {'scalar','integer','positive'});
validateattributes(nelz, {'numeric'}, {'scalar','integer','positive'});
validateattributes(x, {'numeric'}, {'real','finite','size',[nely,nelx,nelz]});
validateattributes(penal, {'numeric'}, {'real','finite','scalar','positive'});
if nargin < 6 || ~isstruct(bc_config) || ~isfield(bc_config, 'bc_type')
    error('FE_solver_3d:InvalidBoundaryConfig', ...
        'bc_config must be a structure containing bc_type.');
end
Emin = 1e-9;
if isfield(bc_config, 'Emin') && ~isempty(bc_config.Emin)
    Emin = bc_config.Emin;
end
validateattributes(Emin, {'numeric'}, ...
    {'real','finite','scalar','>=',0,'<',1});

ndof = 3 * (nelx+1) * (nely+1) * (nelz+1);
E = 1.0;
nu = 0.3;
if isfield(bc_config, 'E') && ~isempty(bc_config.E), E = bc_config.E; end
if isfield(bc_config, 'nu') && ~isempty(bc_config.nu), nu = bc_config.nu; end
validateattributes(E, {'numeric'}, {'real','finite','scalar','positive'});
validateattributes(nu, {'numeric'}, {'real','finite','scalar','>',-1,'<',0.5});
KE = lk_3d(E, nu);
edofMat = build_edof_matrix(nelx, nely, nelz);

% 元素排序与 x(:) 一致：ely 最快，其次 elx，最后 elz。
densityScale = Emin + (1-Emin) * x(:) .^ penal;
iK = reshape(repmat(edofMat, 1, 24).', [], 1);
jK = reshape(repelem(edofMat, 1, 24).', [], 1);
sK = reshape(KE(:) * densityScale.', [], 1);
K = sparse(iK, jK, sK, ndof, ndof);
K = (K + K.') / 2;

F = sparse(ndof, 1);
U = zeros(ndof, 1);
bcType = lower(char(string(bc_config.bc_type)));

switch bcType
    case 'mbb'
        % 半对称 MBB 梁：左侧面对称约束，左上中部向下加载。
        fixeddofs = dofs_on_plane_x(0, 1, nelx, nely, nelz);
        supportA = node_id(nelx, 0, 0, nely, nelx);
        supportB = node_id(nelx, nely, 0, nely, nelx);
        fixeddofs = [fixeddofs, 3*supportA-1, 3*supportA, 3*supportB];
        loadNode = node_id(0, nely, round(nelz/2), nely, nelx);
        F(3*loadNode-1) = -1;

    case 'cantilever'
        % 左端面完全固支；自由端截面中心施加 y 向下单位力。
        fixeddofs = dofs_on_plane_x(0, [1 2 3], nelx, nely, nelz);
        loadNode = node_id(nelx, round(nely/2), round(nelz/2), ...
            nely, nelx);
        F(3*loadNode-1) = -1;

    case 'simply_supported'
        % 左前下角为铰支座，右前下角为滚动支座，增加左后下角约束以
        % 消除三维刚体转动；顶部中点向下加载。
        leftNode = node_id(0, 0, 0, nely, nelx);
        rightNode = node_id(nelx, 0, 0, nely, nelx);
        backNode = node_id(0, 0, nelz, nely, nelx);
        fixeddofs = [3*leftNode-2, 3*leftNode-1, 3*leftNode, ...
                      3*rightNode-1, 3*rightNode, 3*backNode-1];
        loadNode = node_id(round(nelx/2), nely, round(nelz/2), ...
            nely, nelx);
        F(3*loadNode-1) = -1;

    case {'l-bracket','l_bracket'}
        % L 形设计域由主程序的 domain_mask 控制；固定左侧竖臂端面，
        % 在下方横臂最右端的中部深度施加竖直向下载荷。
        fixeddofs = dofs_on_plane_x(0, [1 2 3], nelx, nely, nelz);
        loadNode = node_id(nelx, 0, round(nelz/2), nely, nelx);
        F(3*loadNode-1) = -1;

    case 'custom'
        [fixeddofs, F] = custom_boundary_conditions(bc_config, F, ndof);

    otherwise
        error('FE_solver_3d:UnknownBoundaryType', ...
            ['Unsupported bc_type "%s". Use MBB, cantilever, ', ...
             'simply_supported, L-bracket or custom.'], bc_config.bc_type);
end

fixeddofs = unique(fixeddofs(:).');
if any(fixeddofs < 1) || any(fixeddofs > ndof)
    error('FE_solver_3d:InvalidFixedDofs', ...
        'Fixed degree-of-freedom indices are outside the valid range.');
end
alldofs = 1:ndof;
freedofs = setdiff(alldofs, fixeddofs);
U(freedofs) = K(freedofs, freedofs) \ F(freedofs);
U(fixeddofs) = 0;
end

function edofMat = build_edof_matrix(nelx, nely, nelz)
nele = nelx * nely * nelz;
edofMat = zeros(nele, 24);
index = 0;
for elz = 1:nelz
    for elx = 1:nelx
        for ely = 1:nely
            index = index + 1;
            edofMat(index, :) = element_dofs_3d(elx, ely, elz, ...
                nely, nelx).';
        end
    end
end
end

function dofs = dofs_on_plane_x(ix, directions, nelx, nely, nelz)
dofs = [];
for iz = 0:nelz
    for iy = 0:nely
        node = node_id(ix, iy, iz, nely, nelx);
        dofs = [dofs, 3*(node-1)+directions]; %#ok<AGROW>
    end
end
end

function [fixeddofs, F] = custom_boundary_conditions(config, F, ndof)
if ~isfield(config, 'fixeddofs') || ~isfield(config, 'loads')
    error('FE_solver_3d:MissingCustomData', ...
        'custom 工况需要 bc_config.fixeddofs 和 bc_config.loads。');
end
fixeddofs = config.fixeddofs;
loads = config.loads;
validateattributes(fixeddofs, {'numeric'}, {'real','finite','vector'});
validateattributes(loads, {'numeric'}, {'real','finite','ncols',3});
for index = 1:size(loads, 1)
    node = loads(index, 1);
    direction = loads(index, 2);
    value = loads(index, 3);
    if node ~= round(node) || direction ~= round(direction) || ...
            node < 1 || direction < 1 || direction > 3
        error('FE_solver_3d:InvalidCustomLoad', ...
            'loads 的节点编号必须为正整数，方向必须为 1、2 或 3。');
    end
    dof = 3*(node-1) + direction;
    if dof > ndof
        error('FE_solver_3d:InvalidCustomLoad', ...
            'custom 载荷节点编号超出网格范围。');
    end
    F(dof) = F(dof) + value;
end
end

function node = node_id(ix, iy, iz, nely, nelx)
node = iy + 1 + (nely+1)*ix + (nely+1)*(nelx+1)*iz;
end
