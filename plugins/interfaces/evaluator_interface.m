%% TopOptPilot 评价器接口基类
% 统一接口:
%   metrics = evaluator.evaluate(result, xPhys, history, model)
%
% 参照方案 §5.2 统一接口
%
% 评价指标（参照方案 §9.2）:
%   - compliance:          柔度（整体刚度）
%   - volumeFraction:      体积分数（约束满足）
%   - grayRatio:           灰度比例（0-1清晰度）
%   - connectedComponents: 连通分量数（结构完整性）
%   - maxDisplacement:     最大位移
%   - solverResidual:      求解残差
%   - cgIterations:        PCG迭代次数
%   - solveTime:           求解时间

classdef (Abstract) EvaluatorInterface < handle

    properties (Abstract)
        name           % 评价器名称
        metrics        % 支持的指标列表
    end

    methods (Abstract)

        %% 评价结果
        % metrics = evaluator.evaluate(result, xPhys, history, model)
        metrics = evaluate(obj, result, xPhys, history, model);

    end

    methods

        function obj = EvaluatorInterface()
        end

        function supported = supportsMetric(obj, metricName)
            supported = any(strcmp(obj.metrics, metricName));
        end

        function info = getEvaluatorInfo(obj)
            info = struct('name', obj.name, 'metrics', {obj.metrics});
        end

    end
end