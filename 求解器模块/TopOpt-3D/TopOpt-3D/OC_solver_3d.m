function [xnew, info] = OC_solver_3d(x, dc, volfrac, opts)
%OC_SOLVER_3D 三维拓扑优化的增强最优性准则（OC）密度更新器。
%   该函数保留经典 OC 的乘法更新和拉格朗日乘子二分法，同时支持三维
%   被动空域、被动实体域、可设计掩码、体积分数统计掩码和数值诊断。
%
%   可选 opts 字段：
%     xmin, move, tol_lambda, max_bisect
%     passive_void, passive_solid, active_mask, volume_mask

if nargin < 4 || isempty(opts)
    opts = struct();
end
opts = set_default(opts, 'xmin', 1e-3);
opts = set_default(opts, 'move', 0.2);
opts = set_default(opts, 'tol_lambda', 1e-4);
opts = set_default(opts, 'max_bisect', 100);
opts = set_default(opts, 'passive_void', []);
opts = set_default(opts, 'passive_solid', []);
opts = set_default(opts, 'active_mask', []);
opts = set_default(opts, 'volume_mask', []);
opts = set_default(opts, 'volume_projection_beta', 0);
opts = set_default(opts, 'volume_sensitivity', []);

validateattributes(x, {'numeric'}, {'real','finite','nonempty'});
validateattributes(dc, {'numeric'}, {'real','finite','size',size(x)});
validateattributes(volfrac, {'numeric'}, ...
    {'real','finite','scalar','>=',0,'<=',1});
validateattributes(opts.xmin, {'numeric'}, ...
    {'real','finite','scalar','>',0,'<',1});
validateattributes(opts.move, {'numeric'}, ...
    {'real','finite','scalar','>',0});
validateattributes(opts.tol_lambda, {'numeric'}, ...
    {'real','finite','scalar','>',0});
validateattributes(opts.max_bisect, {'numeric'}, ...
    {'real','finite','scalar','integer','positive'});

passiveVoid = make_mask(opts.passive_void, size(x), false);
passiveSolid = make_mask(opts.passive_solid, size(x), false);
if any(passiveVoid(:) & passiveSolid(:))
    error('OC_solver_3d:OverlappingPassiveRegions', ...
        '被动空域和被动实体域不能重叠。');
end

if isempty(opts.active_mask)
    activeMask = ~(passiveVoid | passiveSolid);
else
    activeMask = make_mask(opts.active_mask, size(x), true);
    if any(activeMask(:) & (passiveVoid(:) | passiveSolid(:)))
        error('OC_solver_3d:ConflictingMasks', ...
            '同一体素不能同时属于可设计域和被动区域。');
    end
end
volumeMask = make_mask(opts.volume_mask, size(x), true);
if ~any(volumeMask(:))
    error('OC_solver_3d:EmptyVolumeMask', ...
        'volume_mask 至少应包含一个体素。');
end
if any(activeMask(:) & ~volumeMask(:))
    error('OC_solver_3d:ActiveOutsideVolumeMask', ...
        '所有可设计体素必须位于 volume_mask 内。');
end

fixedMask = ~activeMask;
fixedValues = min(1, max(opts.xmin, x));
fixedValues(passiveVoid) = opts.xmin;
fixedValues(passiveSolid) = 1.0;

targetVolume = volfrac * nnz(volumeMask);
fixedVolume = sum(fixedValues(fixedMask & volumeMask));
nActive = nnz(activeMask);
minVolume = fixedVolume + nActive * opts.xmin;
maxVolume = fixedVolume + nActive;
volumeTolerance = max(opts.tol_lambda, 1e-10) * max(1, nnz(volumeMask));
if targetVolume < minVolume-volumeTolerance || ...
        targetVolume > maxVolume+volumeTolerance
    error('OC_solver_3d:InfeasibleVolume', ...
        ['目标体积 %.6g 不可行；当前掩码下可行范围为 ', ...
         '[%.6g, %.6g]。'], targetVolume, minVolume, maxVolume);
end
targetVolume = min(max(targetVolume, minVolume), maxVolume);

xnew = fixedValues;
if nActive == 0
    info = build_info(NaN, 0, xnew, targetVolume, activeMask, ...
        volumeMask, true);
    return;
end

% 标准柔顺度问题中 dc<0；下限防止非标准灵敏度造成 sqrt 数值异常。
xActive = min(1, max(opts.xmin, x(activeMask)));
if isempty(opts.volume_sensitivity)
    volumeGradient = ones(size(x));
else
    volumeGradient = opts.volume_sensitivity;
    validateattributes(volumeGradient, {'numeric'}, {'real','finite','size',size(x)});
end
sensitivityRatio = max(1e-30, -dc(activeMask) ./ max(volumeGradient(activeMask), 1e-12));
l1 = 0.0;
l2 = 1e5;
converged = false;
iterations = 0;

for iter = 1:opts.max_bisect
    iterations = iter;
    lambda = 0.5 * (l1+l2);
    candidate = update_candidate(xActive, sensitivityRatio, lambda, opts);
    xnew(activeMask) = candidate;
    physicalVolume = project_volume(xnew, opts.volume_projection_beta, opts.xmin);
    if sum(physicalVolume(volumeMask)) > targetVolume
        l1 = lambda;
    else
        l2 = lambda;
    end
    if l2-l1 <= opts.tol_lambda
        converged = true;
        break;
    end
end

lambda = 0.5 * (l1+l2);
xnew(activeMask) = update_candidate(xActive, sensitivityRatio, lambda, opts);
xnew(passiveVoid) = opts.xmin;
xnew(passiveSolid) = 1.0;
info = build_info(lambda, iterations, xnew, targetVolume, activeMask, ...
    volumeMask, converged);
end

function candidate = update_candidate(xActive, sensitivityRatio, lambda, opts)
candidate = xActive .* sqrt(sensitivityRatio ./ lambda);
candidate = max(opts.xmin, max(xActive-opts.move, ...
    min(1.0, min(xActive+opts.move, candidate))));
end

function values = project_volume(values, beta, xmin)
if beta > 1
    tanhHalf = tanh(0.5*beta);
    values = (tanhHalf + tanh(beta*(values-0.5))) / (2*tanhHalf);
end
values = max(xmin, values);
end

function opts = set_default(opts, name, value)
if ~isfield(opts, name) || isempty(opts.(name))
    opts.(name) = value;
end
end

function mask = make_mask(value, expectedSize, defaultValue)
if isempty(value)
    mask = repmat(defaultValue, expectedSize);
    return;
end
validateattributes(value, {'logical','numeric'}, {'size',expectedSize});
mask = logical(value);
end

function info = build_info(lambda, iterations, xnew, targetVolume, ...
        activeMask, volumeMask, converged)
info = struct();
info.lambda = lambda;
info.bisect_iterations = iterations;
info.volume = sum(xnew(volumeMask));
info.volume_fraction = mean(xnew(volumeMask));
info.target_volume = targetVolume;
info.volume_error = info.volume - targetVolume;
info.active_elements = nnz(activeMask);
info.volume_elements = nnz(volumeMask);
info.converged = converged;
end
