function test_topopt3d_smoke
%TEST_TOPOPT3D_SMOKE 三维主流程的短迭代冒烟测试。
%   覆盖代表性工况、三维掩码和增强 OC 的体积约束。

base = struct('nelx',8,'nely',4,'nelz',3, ...
    'max_iterations',3,'min_iterations',3, ...
    'display',false,'verbose',false);
cases = {'MBB','cantilever','simply_supported','L-bracket'};

for index = 1:numel(cases)
    config = base;
    config.bc_type = cases{index};
    result = topopt3d_main(config);
    assert(all(isfinite(result.x(:))));
    assert(isfinite(result.objective));
    assert(abs(result.volume_fraction-0.5) < 5e-3);
    if strcmp(cases{index}, 'L-bracket')
        assert(nnz(~result.domain_mask) > 0);
        assert(all(result.x(~result.domain_mask) == result.config.xmin));
    else
        assert(all(result.domain_mask(:)));
    end
end

% 自定义工况：左端面固支、右端面中心向下载荷。
config = base;
config.bc_type = 'custom';
config.bc_config = struct();
config.bc_config.fixeddofs = left_face_dofs(config.nelx, config.nely, config.nelz);
loadNode = round(config.nely/2) + 1 + (config.nely+1)*config.nelx ...
    + (config.nely+1)*(config.nelx+1)*round(config.nelz/2);
config.bc_config.loads = [loadNode, 2, -1];
result = topopt3d_main(config);
assert(all(isfinite(result.x(:))));
assert(isfinite(result.objective));
assert(abs(result.volume_fraction-0.5) < 5e-3);

fprintf('3D integrated smoke tests passed.\n');
end

function dofs = left_face_dofs(nelx, nely, nelz) %#ok<INUSD>
dofs = [];
for iz = 0:nelz
    for iy = 0:nely
        node = iy + 1 + (nely+1)*(nelx+1)*iz;
        dofs = [dofs, 3*node-2, 3*node-1, 3*node]; %#ok<AGROW>
    end
end
end
