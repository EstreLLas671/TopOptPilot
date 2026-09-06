%% TopOptPilot 控制器接口基类
% 统一接口:
%   [newParams, decision] = controller.update(history, metrics, params)
%
% 参照方案 §5.2 统一接口
%
% 控制器类型:
%   - FixedController:         固定参数（不调整）
%   - PeriodicController:      固定轮次调度（如每N步提高beta）
%   - GrayFeedbackController:  灰度比例反馈
%   - JointFeedbackController: 联合反馈（灰度+柔度+连通+求解难度）
%
% 这是核心科学假设的主要实现位置（参照方案 §8.2 核心创新）

classdef (Abstract) ControllerInterface < handle

    properties (Abstract)
        name           % 控制器名称
        type           % 'fixed' | 'periodic' | 'gray_feedback' | 'joint_feedback'
    end

    methods (Abstract)

        %% 更新控制参数
        % [newParams, decision] = controller.update(history, metrics, params)
        %   history:  迭代历史（结构数组）
        %   metrics:  当前指标（灰度、柔度、连通等）
        %   params:   当前参数（beta, p等）
        %   newParams:更新后参数
        %   decision: 控制决策说明
        [newParams, decision] = update(obj, history, metrics, params);

    end

    methods

        function obj = ControllerInterface()
        end

        function isAdaptive = isAdaptive(obj)
            % 是否为自适应控制器
            isAdaptive = ~strcmp(obj.type, 'fixed');
        end

        function info = getControllerInfo(obj)
            info = struct('name', obj.name, 'type', obj.type, ...
                         'adaptive', obj.isAdaptive());
        end

    end
end