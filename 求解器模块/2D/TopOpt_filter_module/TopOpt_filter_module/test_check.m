function test_check
%TEST_CHECK Independent and integration-oriented filter tests.

fprintf('Running filter-module tests...\n');

test_original_formula_equivalence();
test_identity_when_radius_below_one();
test_constant_field_is_preserved();
test_center_value_against_hand_calculation();
test_output_shape_and_finiteness();
test_irregular_domain_excludes_void_elements();
test_case_config_compatibility();
test_fixed_radius_backward_compatibility();
test_adaptive_radius_schedule();
test_adaptive_filter_integration();
test_invalid_active_density_is_rejected();

fprintf('All filter-module tests passed.\n');
end

function test_fixed_radius_backward_compatibility
config = struct('radius_strategy','fixed');
[actual, info] = adaptive_filter_radius(1.7, config);
assert(abs(actual-1.7) < 1e-12);
assert(strcmp(info.radius_strategy, 'fixed'));
end

function test_adaptive_radius_schedule
config = struct('radius_strategy','adaptive', ...
    'iteration',1,'max_iterations',100, ...
    'rmin_start',3.0,'rmin_end',1.5,'schedule_power',2.0);
[firstRadius, ~] = adaptive_filter_radius(1.5, config);
config.iteration = 50;
[middleRadius, ~] = adaptive_filter_radius(1.5, config);
config.iteration = 100;
[lastRadius, ~] = adaptive_filter_radius(1.5, config);

assert(abs(firstRadius-3.0) < 1e-12);
assert(firstRadius > middleRadius && middleRadius > lastRadius);
assert(abs(lastRadius-1.5) < 1e-12);
end

function test_adaptive_filter_integration
nelx = 8;
nely = 4;
x = 0.5*ones(nely, nelx);
dc = -1.0 - 0.8*mod((1:nely)' + (1:nelx), 2);
config = struct('filter_type','sensitivity', ...
    'radius_strategy','adaptive','iteration',1, ...
    'max_iterations',50,'rmin_start',3.0,'rmin_end',1.5);
[actual, info] = filter_solver(nelx, nely, 1.5, x, dc, config);
expected = check(nelx, nely, 3.0, x, dc);
assert(max(abs(actual(:)-expected(:))) < 1e-12);
assert(abs(info.rmin-3.0) < 1e-12);
assert(strcmp(info.radius_strategy, 'adaptive'));
end

function test_original_formula_equivalence
rng(7);
nelx = 9;
nely = 5;
rmin = 2.2;
x = 0.1 + 0.9*rand(nely, nelx);
dc = -rand(nely, nelx);

expected = original_check_reference(nelx, nely, rmin, x, dc);
actual = check(nelx, nely, rmin, x, dc);
assert(max(abs(actual(:)-expected(:))) < 1e-12, ...
    'The full-domain result must equal the original 99-line formula.');
end

function test_identity_when_radius_below_one
rng(42);
nelx = 7;
nely = 4;
x = 0.2 + 0.8*rand(nely, nelx);
dc = -rand(nely, nelx);

actual = check(nelx, nely, 0.5, x, dc);
assert(max(abs(actual(:)-dc(:))) < 1e-12, ...
    'For rmin < 1, only the element itself should contribute.');
end

function test_constant_field_is_preserved
nelx = 8;
nely = 5;
x = 0.5*ones(nely, nelx);
dc = -2.0*ones(nely, nelx);

actual = check(nelx, nely, 1.5, x, dc);
assert(max(abs(actual(:)+2.0)) < 1e-12, ...
    'A constant density and sensitivity field should remain constant.');
end

function test_center_value_against_hand_calculation
nelx = 3;
nely = 3;
x = ones(nely, nelx);
dc = reshape(1:9, nely, nelx);
rmin = 1.5;

actual = check(nelx, nely, rmin, x, dc);

selfWeight = 1.5;
edgeWeight = 0.5;
cornerWeight = 1.5 - sqrt(2);
weightedTotal = selfWeight*dc(2,2) ...
    + edgeWeight*(dc(2,1)+dc(2,3)+dc(1,2)+dc(3,2)) ...
    + cornerWeight*(dc(1,1)+dc(1,3)+dc(3,1)+dc(3,3));
weightTotal = selfWeight + 4*edgeWeight + 4*cornerWeight;
expectedCenter = weightedTotal/weightTotal;

assert(abs(actual(2,2)-expectedCenter) < 1e-12, ...
    'The center value does not match the hand-calculated weighted average.');
end

function test_output_shape_and_finiteness
nelx = 6;
nely = 4;
x = 0.5*ones(nely, nelx);
dc = reshape(-(1:(nelx*nely)), nely, nelx);

actual = check(nelx, nely, 1.8, x, dc);
assert(isequal(size(actual), [nely, nelx]), ...
    'The output dimensions must match the input density field.');
assert(all(isfinite(actual(:))), ...
    'The filtered sensitivities must be finite for valid positive densities.');
end

function test_irregular_domain_excludes_void_elements
nelx = 6;
nely = 6;
x = 0.5*ones(nely, nelx);
dc = -ones(nely, nelx);
domainMask = true(nely, nelx);
domainMask(1:3, 4:6) = false;

% An extreme value outside the domain must not leak into active elements.
dcWithVoidNoise = dc;
dcWithVoidNoise(~domainMask) = -1e9;

baseline = check(nelx, nely, 2.2, x, dc, domainMask);
actual = check(nelx, nely, 2.2, x, dcWithVoidNoise, domainMask);

assert(all(actual(~domainMask) == 0), ...
    'Sensitivities outside the design domain must be zero.');
assert(max(abs(actual(domainMask)-baseline(domainMask))) < 1e-12, ...
    'Void elements must not affect neighboring active elements.');
assert(all(isfinite(actual(domainMask))), ...
    'Active irregular-domain sensitivities must remain finite.');
end

function test_case_config_compatibility
nelx = 8;
nely = 4;
x = 0.5*ones(nely, nelx);
dc = -ones(nely, nelx);

fullDomainCases = {'MBB','cantilever','simply_supported'};
for idx = 1:numel(fullDomainCases)
    config = struct('filter_type','sensitivity', ...
        'bc_type',fullDomainCases{idx});
    [actual, info] = filter_solver(nelx, nely, 1.5, x, dc, config);
    assert(all(isfinite(actual(:))));
    assert(info.active_elements == nelx*nely);
    assert(strcmp(info.bc_type, fullDomainCases{idx}));
end

lMask = true(nely, nelx);
lMask(1:2, 5:8) = false;
lConfig = struct('filter_type','sensitivity', ...
    'bc_type','L-bracket','domain_mask',lMask);
[lResult, lInfo] = filter_solver(nelx, nely, 1.5, x, dc, lConfig);
assert(all(lResult(~lMask) == 0));
assert(lInfo.inactive_elements == nnz(~lMask));

customConfig = struct('filter_type','none', ...
    'bc_type','custom','domain_mask',lMask);
[customResult, customInfo] = filter_solver( ...
    nelx, nely, 1.5, x, dc, customConfig);
assert(all(customResult(~lMask) == 0));
assert(strcmp(customInfo.filter_type, 'none'));
end

function test_invalid_active_density_is_rejected
nelx = 3;
nely = 3;
x = ones(nely, nelx);
dc = -ones(nely, nelx);
x(2,2) = 0;

didThrow = false;
try
    check(nelx, nely, 1.5, x, dc);
catch exception
    didThrow = strcmp(exception.identifier, ...
        'check:NonPositiveActiveDensity');
end
assert(didThrow, ...
    'A zero density inside the active domain must produce a clear error.');
end

function dcn = original_check_reference(nelx, nely, rmin, x, dc)
% Exact reference structure of the filter in the educational 99-line code.
dcn = zeros(nely, nelx);
for i = 1:nelx
    for j = 1:nely
        localSum = 0.0;
        for k = max(i-floor(rmin),1):min(i+floor(rmin),nelx)
            for l = max(j-floor(rmin),1):min(j+floor(rmin),nely)
                fac = rmin-sqrt((i-k)^2+(j-l)^2);
                localSum = localSum+max(0,fac);
                dcn(j,i) = dcn(j,i) ...
                    + max(0,fac)*x(l,k)*dc(l,k);
            end
        end
        dcn(j,i) = dcn(j,i)/(x(j,i)*localSum);
    end
end
end
