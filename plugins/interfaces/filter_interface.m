%% TopOptPilot 滤波接口基类
% 统一接口:
%   [xFiltered, filterState] = filter.apply(x, dc, model, filterParams)
%
% 参照方案 §5.2 统一接口
%
% 滤波类型:
%   - SensitivityFilter:   灵敏度滤波（经典棋盘格抑制）
%   - DensityFilter:        密度滤波
%   - PDE/HelmholtzFilter:  PDE滤波（各向同性、长度尺度控制）

classdef (Abstract) FilterInterface < handle

    properties (Abstract)
        name           % 滤波名称
        type           % 'sensitivity' | 'density' | 'pde'
        filterRadius   % 滤波半径
    end

    methods (Abstract)

        %% 应用滤波
        % [xFiltered, filterState] = filter.apply(x, dc, model, filterParams)
        %   x:            当前设计变量
        %   dc:           目标函数梯度
        %   model:        有限元模型
        %   filterParams: 滤波参数（半径等）
        [xFiltered, filterState] = apply(obj, x, dc, model, filterParams);

    end

    methods

        function obj = FilterInterface(filterRadius)
            if nargin > 0
                obj.filterRadius = filterRadius;
            end
        end

        function info = getFilterInfo(obj)
            info = struct('name', obj.name, 'type', obj.type, ...
                         'radius', obj.filterRadius);
        end

    end
end