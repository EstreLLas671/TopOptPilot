function [xnew, info] = OC_solver(x, dc, volfrac, opts)
%OC_SOLVER 面向柔顺度拓扑优化的增强 OC 密度更新器。
%   [XNEW, INFO] = OC_SOLVER(X, DC, VOLFRAC, OPTS) 根据滤波后的
%   柔顺度灵敏度 DC 更新密度场 X。未提供 OPTS 时，其更新规则与经典
%   99 行代码的 OC 方法一致；同时增加以下能力：
%     - 可配置的数值参数和单步密度变化上限；
%     - 被动空域 / 被动实体域；
%     - 体积约束的可行性检查；
%     - 通过 INFO 返回迭代诊断信息。
%
%   OPTS 的可选字段：
%     xmin          密度下限，默认 1e-3
%     move          每次迭代允许的最大密度变化，默认 0.2
%     tol_lambda    拉格朗日乘子的二分搜索精度，默认 1e-4
%     max_bisect    最大二分搜索次数，默认 100
%     passive_void  逻辑/数值掩码：对应单元始终为 xmin
%     passive_solid 逻辑/数值掩码：对应单元始终为 1
%     active_mask   逻辑/数值掩码：允许由 OC 更新的单元
%     volume_mask   体积分数统计区域；默认全部单元。L型设计域应传入
%                   与滤波相同的 domainMask，使 volfrac 相对有效区域定义
%
%   默认情况下 VOLFRAC 相对于 X 的全部单元定义，与 top.m 一致。
%   提供 volume_mask 后，目标材料量仅相对于该区域定义。

    if nargin < 4 || isempty(opts)
        opts = struct();
    end

    opts = set_default(opts, 'xmin',       1e-3);
    opts = set_default(opts, 'move',       0.2);
    opts = set_default(opts, 'tol_lambda', 1e-4);
    opts = set_default(opts, 'max_bisect', 100);
    opts = set_default(opts, 'passive_void',  []);
    opts = set_default(opts, 'passive_solid', []);
    opts = set_default(opts, 'active_mask',  []);
    opts = set_default(opts, 'volume_mask',  []);

    validateattributes(x, {'numeric'}, {'real', 'finite', 'nonempty'}, ...
        mfilename, 'x', 1);
    validateattributes(dc, {'numeric'}, {'real', 'finite', 'size', size(x)}, ...
        mfilename, 'dc', 2);
    validateattributes(volfrac, {'numeric'}, {'real', 'finite', 'scalar', ...
        '>=', 0, '<=', 1}, mfilename, 'volfrac', 3);
    validateattributes(opts.xmin, {'numeric'}, {'real', 'finite', 'scalar', ...
        '>', 0, '<', 1}, mfilename, 'opts.xmin');
    validateattributes(opts.move, {'numeric'}, {'real', 'finite', 'scalar', ...
        '>', 0}, mfilename, 'opts.move');
    validateattributes(opts.tol_lambda, {'numeric'}, {'real', 'finite', 'scalar', ...
        '>', 0}, mfilename, 'opts.tol_lambda');
    validateattributes(opts.max_bisect, {'numeric'}, {'real', 'finite', 'scalar', ...
        'integer', 'positive'}, mfilename, 'opts.max_bisect');

    n = numel(x);
    passive_void = make_mask(opts.passive_void, size(x), false);
    passive_solid = make_mask(opts.passive_solid, size(x), false);
    if any(passive_void(:) & passive_solid(:))
        error('OC_solver:OverlappingPassiveRegions', ...
            'passive_void and passive_solid must not overlap.');
    end

    if isempty(opts.active_mask)
        active_mask = ~(passive_void | passive_solid);
    else
        active_mask = make_mask(opts.active_mask, size(x), true);
        if any(active_mask(:) & (passive_void(:) | passive_solid(:)))
            error('OC_solver:ConflictingMasks', ...
                'An element cannot be active and passive at the same time.');
        end
    end

    volume_mask = make_mask(opts.volume_mask, size(x), true);
    if ~any(volume_mask(:))
        error('OC_solver:EmptyVolumeMask', ...
            'volume_mask must contain at least one element.');
    end
    if any(active_mask(:) & ~volume_mask(:))
        error('OC_solver:ActiveOutsideVolumeMask', ...
            'Every active element must also belong to volume_mask.');
    end

    % 未被显式标记为可设计的单元，固定在其当前密度。这样 active_mask
    % 可安全用于限定设计域，而不会意外改变域外单元。
    fixed_mask = ~active_mask;
    fixed_values = min(1, max(opts.xmin, x));
    fixed_values(passive_void) = opts.xmin;
    fixed_values(passive_solid) = 1.0;

    target_volume = volfrac * nnz(volume_mask);
    fixed_volume = sum(fixed_values(fixed_mask & volume_mask));
    n_active = nnz(active_mask);
    min_volume = fixed_volume + n_active * opts.xmin;
    max_volume = fixed_volume + n_active;
    volume_tolerance = max(opts.tol_lambda, 1e-10) * max(1, n);

    if target_volume < min_volume - volume_tolerance || ...
            target_volume > max_volume + volume_tolerance
        error('OC_solver:InfeasibleVolume', ...
            ['The requested volume %.6g is infeasible. Feasible total ', ...
             'volume is [%.6g, %.6g] with the supplied masks.'], ...
            target_volume, min_volume, max_volume);
    end

    % 对数值上几乎可行的目标体积进行截断，避免边界处仅因舍入误差或
    % 二分精度而误报“不可行”。
    target_volume = min(max(target_volume, min_volume), max_volume);

    xnew = fixed_values;
    if n_active == 0
        info = build_info(NaN, 0, xnew, target_volume, active_mask, ...
            volume_mask, true);
        return;
    end

    % 最小柔顺度问题的滤波灵敏度通常为负。若改进模型导致某些灵敏度
    % 为零或非负，设置下限可保护 sqrt()，并使这些单元向受步长限制的
    % 较低密度方向更新。
    sensitivity_ratio = max(1e-30, -dc(active_mask));
    x_active = min(1, max(opts.xmin, x(active_mask)));

    l1 = 0.0;
    l2 = 1e5;
    lambda = NaN;
    bisect_iterations = 0;
    converged = false;

    for iter = 1:opts.max_bisect
        bisect_iterations = iter;
        lambda = 0.5 * (l1 + l2);
        candidate = x_active .* sqrt(sensitivity_ratio ./ lambda);
        candidate = max(opts.xmin, max(x_active - opts.move, ...
                    min(1.0, min(x_active + opts.move, candidate))));

        xnew(active_mask) = candidate;
        current_volume = sum(xnew(volume_mask));

        if current_volume > target_volume
            l1 = lambda;
        else
            l2 = lambda;
        end

        if (l2 - l1) <= opts.tol_lambda
            converged = true;
            break;
        end
    end

    % 使用最终二分区间的中点重新计算密度，确保报告的 lambda 与 xnew
    % 相互对应；即使循环因达到 max_bisect 而退出也是如此。
    lambda = 0.5 * (l1 + l2);
    candidate = x_active .* sqrt(sensitivity_ratio ./ lambda);
    candidate = max(opts.xmin, max(x_active - opts.move, ...
                min(1.0, min(x_active + opts.move, candidate))));
    xnew(active_mask) = candidate;
    xnew(passive_void) = opts.xmin;
    xnew(passive_solid) = 1.0;

    info = build_info(lambda, bisect_iterations, xnew, target_volume, ...
        active_mask, volume_mask, converged);
end


function opts = set_default(opts, name, value)
    if ~isfield(opts, name) || isempty(opts.(name))
        opts.(name) = value;
    end
end


function mask = make_mask(value, expected_size, default_value)
    if isempty(value)
        mask = repmat(default_value, expected_size);
        return;
    end
    if ~isequal(size(value), expected_size)
        error('OC_solver:InvalidMaskSize', ...
            'All masks must have the same size as x.');
    end
    if ~islogical(value) && (~isnumeric(value) || any(~isfinite(value(:))))
        error('OC_solver:InvalidMask', ...
            'Masks must be logical or finite numeric arrays.');
    end
    mask = logical(value);
end


function info = build_info(lambda, bisect_iterations, xnew, target_volume, ...
        active_mask, volume_mask, converged)
    info.lambda = lambda;
    info.bisect_iterations = bisect_iterations;
    info.volume = sum(xnew(volume_mask));
    info.volume_fraction = mean(xnew(volume_mask));
    info.target_volume = target_volume;
    info.volume_error = info.volume - target_volume;
    info.active_elements = nnz(active_mask);
    info.volume_elements = nnz(volume_mask);
    info.converged = converged;
end
