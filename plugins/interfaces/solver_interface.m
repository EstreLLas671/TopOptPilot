%% TopOptPilot 求解器接口基类
% 必须实现的统一接口：
%   result = solver.analyze(model, density, material, solveOptions)
%
% 参照方案 §5.2 统一接口 + §6.3 MEX边界
%
% 实现者需提供：
%   - analyze():  Matrix-free K·u, PCG/MGCG, 单元柔度, 灵敏度
%   - result 包含: compliance, elementCompliance, sensitivity, residual,
%                  cgIterations, solveTime, converged

classdef (Abstract) SolverInterface < handle

    properties (Abstract)
        name           % 求解器名称标识
        version        % 版本号
        backend        % 'cpu' | 'cuda_mex' | 'custom'
    end

    methods (Abstract)

        %% 创建求解上下文
        % 只在启动时执行一次：将网格、节点映射、边界条件常驻显存
        % handle = solver.create(model, boundary, options)
        handle = create(obj, model, boundary, options);

        %% 执行一轮有限元分析
        % 每轮仅传入密度与材料，CUDA内完成Matrix-free K·u、PCG、灵敏度和单元柔度
        % [result, state] = solver.analyze(handle, density, material, initialState)
        [result, state] = analyze(obj, handle, density, material, initialState);

        %% 销毁求解上下文
        % 释放GPU显存 / CPU内存
        destroy(obj, handle);

    end

    methods

        function obj = SolverInterface()
            % 构造器：初始化日志
        end

        function valid = validateResult(obj, result)
            % 验证结果完整性
            requiredFields = {'compliance', 'elementCompliance', ...
                              'sensitivity', 'residual', ...
                              'cgIterations', 'solveTime', 'converged'};
            valid = all(isfield(result, requiredFields));
            if ~valid
                warning('求解器结果缺少必要字段');
            end
        end

        function status = checkStatus(obj)
            % 检查求解器状态
            status = struct('ready', false, 'gpuAvailable', false, ...
                           'memoryMB', 0);
        end

    end
end