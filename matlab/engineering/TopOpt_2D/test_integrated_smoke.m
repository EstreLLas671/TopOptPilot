function test_integrated_smoke
%TEST_INTEGRATED_SMOKE Short checks for rectangular and L-shaped cases.
base = struct('nelx',20,'nely',10,'max_iterations',3, ...
    'min_iterations',3,'display',false,'verbose',false);

cases = {'MBB','cantilever','simply_supported','L-bracket'};
for index = 1:numel(cases)
    config = base;
    config.bc_type = cases{index};
    result = topopt_main(config);
    assert(all(isfinite(result.x(:))));
    assert(isfinite(result.objective));
    assert(abs(result.volume_fraction-0.5) < 5e-3);
    if strcmp(cases{index}, 'L-bracket')
        assert(nnz(~result.domain_mask) > 0);
        assert(all(result.x(~result.domain_mask) == 1e-3));
    else
        assert(all(result.domain_mask(:)));
    end
end
fprintf('Integrated smoke tests passed.\n');
end
