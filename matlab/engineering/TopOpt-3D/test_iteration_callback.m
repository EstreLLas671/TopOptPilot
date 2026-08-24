function test_iteration_callback
%TEST_ITERATION_CALLBACK 验证每轮回调来自真实 OC 更新后的密度场。
frames = {};
config = struct('bc_type','cantilever','nelx',8,'nely',4,'nelz',3, ...
    'max_iterations',3,'min_iterations',3,'display',false,'verbose',false, ...
    'iteration_callback',@capture_frame);
result = topopt3d_main(config);
assert(numel(frames) == result.iterations);
assert(isequal(size(frames{1}.x), [4,8,3]));
assert(frames{end}.iteration == result.iterations);
assert(max(abs(frames{end}.x(:)-result.x(:))) < 1e-12);
assert(all(isfinite([frames{end}.objective, frames{end}.change, ...
    frames{end}.volume_fraction, frames{end}.rmin, frames{end}.penal])));

config = rmfield(config, 'iteration_callback');
withoutCallback = topopt3d_main(config);
assert(withoutCallback.iterations == result.iterations);
fprintf('ITERATION_CALLBACK_TEST_PASSED\n');

    function capture_frame(frame)
        frames{end+1} = frame; %#ok<AGROW>
    end
end
