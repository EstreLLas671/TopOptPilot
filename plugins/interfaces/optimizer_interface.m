%% TopOptPilot 优化器接口基类
% 统一接口:
%   [xNew, optimizerState] = optimizer.update(x, objective, gradient, ...
%                                              constraints, optimizerState, params)
%
% 参照方案 §5.2 统一接口
%
% 优化器类型:
%   - OC (Optimality Criteria):    单体积约束最小柔度（成熟高效）
%   - MMA (Method of Moving Asymptotes): 多约束扩展（需梯度检查）

classdef (Abstract) OptimizerInterface < handle

    properties (Abstract)
        name           % 优化器名称
        type           % 'oc' | 'mma'
        maxIterations  % 最大迭代次数
    end

    methods (Abstract)

        %% 更新设计变量
        % [xNew, optimizerState] = optimizer.update(x, objective, gradient, ...
        %                                            constraints, optimizerState, params)
        [xNew, optimizerState] = update(obj, x, objective, gradient, ...
                                         constraints, optimizerState, params);

    end

    methods

        function obj = OptimizerInterface(maxIterations)
            if nargin > 0
                obj.maxIterations = maxIterations;
            end
        end

        function supportsMultiConstraint = hasMultiConstraintSupport(obj)
            % 是否支持多约束
            supportsMultiConstraint = strcmp(obj.type, 'mma');
        end

        function info = getOptimizerInfo(obj)
            info = struct('name', obj.name, 'type', obj.type, ...
                         'maxIter', obj.maxIterations, ...
                         'multiConstraint', obj.hasMultiConstraintSupport());
        end

    end
end