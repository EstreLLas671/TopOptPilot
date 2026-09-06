%% TopOptPilot 投影接口基类
% 统一接口:
%   [xPhys, projectionDerivative] = projection.apply(xFiltered, projectionParams)
%
% 参照方案 §5.2 统一接口
%
% 投影类型:
%   - None:            直接使用滤波后密度
%   - Heaviside:       Heaviside投影（β控制陡峭度，η控制阈值）
%   - Continuation:    延续策略（多阶段参数调度）

classdef (Abstract) ProjectionInterface < handle

    properties (Abstract)
        name           % 投影名称
        type           % 'none' | 'heaviside' | 'continuation'
    end

    methods (Abstract)

        %% 应用投影
        % [xPhys, derivative] = projection.apply(xFiltered, projectionParams)
        %   xFiltered:        滤波后设计变量
        %   projectionParams: 投影参数（beta, eta等）
        %   xPhys:            物理密度（0-1清晰化）
        %   derivative:       链式导数（用于灵敏度修正）
        [xPhys, derivative] = apply(obj, xFiltered, projectionParams);

    end

    methods

        function obj = ProjectionInterface()
        end

        function requiresChainDerivative = hasChainDerivative(obj)
            % 是否返回链式导数（用于灵敏度修正）
            requiresChainDerivative = true;
        end

        function info = getProjectionInfo(obj)
            info = struct('name', obj.name, 'type', obj.type, ...
                         'hasDerivative', obj.hasChainDerivative());
        end

    end
end