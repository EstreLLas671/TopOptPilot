function solidMask = build_boundary_solid_mask_3d( ...
        nelx, nely, nelz, bcType, domainMask)
%BUILD_BOUNDARY_SOLID_MASK_3D 为支撑和载荷处建立被动实体垫块。
%   密度法拓扑优化若直接在单节点施加载荷或约束，邻近单元可能被迭代
%   删除，从而形成不现实的“悬空受力点”。本函数在各代表性工况的支撑
%   与受力位置保留一层材料，使载荷和约束能通过有限尺寸区域传递。
%
%   custom 工况不自动猜测载荷/支撑位置；应由用户传入 passive_solid。

solidMask = false(nely, nelx, nelz);
bcType = lower(char(string(bcType)));

switch bcType
    case 'cantilever'
        % 左端固定连接板 + 自由端中心受力垫块。
        solidMask(:, 1, :) = true;
        solidMask = mark_node_patch(solidMask, nelx, ...
            round(nely/2), round(nelz/2));

    case 'mbb'
        % 对称面上的加载垫块，以及右端两个支承附近的连接垫块。
        solidMask = mark_node_patch(solidMask, 0, nely, round(nelz/2));
        solidMask = mark_node_patch(solidMask, nelx, 0, 0);
        solidMask = mark_node_patch(solidMask, nelx, nely, 0);

    case 'simply_supported'
        % 三个支承节点和顶部加载节点均保留小型实体区。
        solidMask = mark_node_patch(solidMask, 0, 0, 0);
        solidMask = mark_node_patch(solidMask, nelx, 0, 0);
        solidMask = mark_node_patch(solidMask, 0, 0, nelz);
        solidMask = mark_node_patch(solidMask, round(nelx/2), ...
            nely, round(nelz/2));

    case {'l-bracket','l_bracket'}
        % L 形竖臂的固定连接板 + 下方横臂端部受力垫块。
        solidMask(:, 1, :) = true;
        solidMask = mark_node_patch(solidMask, nelx, 0, round(nelz/2));

    case 'custom'
        % 自定义工况由调用方使用 config.passive_solid 明确指定。

    otherwise
        error('build_boundary_solid_mask_3d:UnknownBoundaryType', ...
            '未知工况类型：%s。', bcType);
end

% L 形缺角等非设计区域永远不能被错误设为实体。
solidMask = solidMask & logical(domainMask);
end

function mask = mark_node_patch(mask, nodeX, nodeY, nodeZ)
[nely, nelx, nelz] = size(mask);
elementsX = adjacent_elements(nodeX, nelx);
elementsY = adjacent_elements(nodeY, nely);
elementsZ = adjacent_elements(nodeZ, nelz);
mask(elementsY, elementsX, elementsZ) = true;
end

function indices = adjacent_elements(nodeCoordinate, elementCount)
% 节点坐标范围是 0:elementCount，返回与该节点相邻的单元编号。
indices = max(1, nodeCoordinate) : min(elementCount, nodeCoordinate+1);
end
