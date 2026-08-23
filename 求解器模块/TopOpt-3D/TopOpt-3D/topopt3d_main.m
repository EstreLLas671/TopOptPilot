function result = topopt3d_main(config)
%TOPOPT3D_MAIN 三维整合式密度拓扑优化主程序。
%   RESULT = TOPOPT3D_MAIN(CONFIG) 依次执行三维有限元分析、SIMP
%   柔顺度灵敏度分析、球形灵敏度滤波和增强 OC 密度更新。
%
%   最小可运行示例：
%     result = topopt3d_main(struct('bc_type','cantilever'));
%
%   主要 CONFIG 字段：
%     nelx, nely, nelz, volfrac, penal, rmin
%     bc_type: MBB / cantilever / simply_supported / L-bracket / custom
%     geometry, domain_mask, passive_void, passive_solid
%     filter_strategy: fixed / adaptive
%     move_start, move_end, max_iterations, min_iterations
%     display, verbose, bc_config

if nargin < 1 || isempty(config)
    config = struct();
end
if ~isstruct(config)
    error('topopt3d_main:InvalidConfig', 'config 必须是结构体。');
end

config = set_default(config, 'bc_type', 'cantilever');
config = set_default(config, 'accuracy', 'high');
isLBracket = strcmpi(char(string(config.bc_type)), 'L-bracket');
accuracyDefaults = accuracy_defaults(config.accuracy, isLBracket);
config = set_default(config, 'nelx', accuracyDefaults.nelx);
config = set_default(config, 'nely', accuracyDefaults.nely);
config = set_default(config, 'nelz', accuracyDefaults.nelz);
config = set_default(config, 'volfrac', 0.5);
config = set_default(config, 'penal', 3.0);
config = set_default(config, 'penal_start', 1.0);
config = set_default(config, 'penal_schedule_power', 1.0);
config = set_default(config, 'Emin', 1e-9);
config = set_default(config, 'rmin', 1.5);
config = set_default(config, 'E', 1.0);
config = set_default(config, 'nu', 0.3);
config = set_default(config, 'xmin', 1e-3);
config = set_default(config, 'max_iterations', accuracyDefaults.max_iterations);
config = set_default(config, 'min_iterations', accuracyDefaults.min_iterations);
config = set_default(config, 'change_tolerance', accuracyDefaults.change_tolerance);
config = set_default(config, 'objective_tolerance', accuracyDefaults.objective_tolerance);
config = set_default(config, 'oc_tol_lambda', accuracyDefaults.oc_tol_lambda);
% Heaviside projection sharpness; beta=1 reduces to the SIMP filter-only limit.
config = set_default(config, 'beta', 1.0);
validateattributes(config.beta, {'numeric'}, {'scalar','real','finite','>=',1,'<=',64});
config = set_default(config, 'oc_max_bisect', accuracyDefaults.oc_max_bisect);
config = set_default(config, 'filter_strategy', 'fixed');
config = set_default(config, 'rmin_start', 3.0);
config = set_default(config, 'rmin_end', config.rmin);
config = set_default(config, 'filter_schedule_power', 2.0);
config = set_default(config, 'move_start', 0.2);
config = set_default(config, 'move_end', config.move_start);
config = set_default(config, 'move_schedule_power', 1.0);
config = set_default(config, 'geometry', struct());
config = set_default(config, 'passive_void', []);
config = set_default(config, 'passive_solid', []);
config = set_default(config, 'auto_boundary_solid', true);
config = set_default(config, 'iso_level', 0.5);
config = set_default(config, 'stress_measure', 'gauss_max');
config = set_default(config, 'display', true);
config = set_default(config, 'verbose', true);

validateattributes(config.nelx, {'numeric'}, {'scalar','integer','positive'});
validateattributes(config.nely, {'numeric'}, {'scalar','integer','positive'});
validateattributes(config.nelz, {'numeric'}, {'scalar','integer','positive'});
validateattributes(config.E, {'numeric'}, {'scalar','real','finite','positive'});
validateattributes(config.nu, {'numeric'}, {'scalar','real','finite','>=',0,'<',0.5});
validateattributes(config.volfrac, {'numeric'}, ...
    {'scalar','real','finite','>=',0,'<=',1});
validateattributes(config.penal, {'numeric'}, ...
    {'scalar','real','finite','>=',1});
validateattributes(config.penal_start, {'numeric'}, ...
    {'scalar','real','finite','>=',1,'<=',config.penal});
validateattributes(config.Emin, {'numeric'}, ...
    {'scalar','real','finite','>=',0,'<',1});
validateattributes(config.change_tolerance, {'numeric'}, ...
    {'scalar','real','finite','positive'});
validateattributes(config.objective_tolerance, {'numeric'}, ...
    {'scalar','real','finite','positive'});
validateattributes(config.oc_tol_lambda, {'numeric'}, ...
    {'scalar','real','finite','positive'});
validateattributes(config.oc_max_bisect, {'numeric'}, ...
    {'scalar','integer','positive'});
validateattributes(config.max_iterations, {'numeric'}, ...
    {'scalar','integer','positive'});
validateattributes(config.min_iterations, {'numeric'}, ...
    {'scalar','integer','positive','<=',config.max_iterations});

nelx = config.nelx;
nely = config.nely;
nelz = config.nelz;
gridSize = [nely, nelx, nelz];

if isfield(config, 'domain_mask') && ~isempty(config.domain_mask)
    domainMask = read_mask(config.domain_mask, gridSize, true);
else
    domainMask = build_domain_mask_3d(nelx, nely, nelz, ...
        config.bc_type, config.geometry);
end
passiveVoid = read_mask(config.passive_void, gridSize, false) | ~domainMask;
passiveSolid = read_mask(config.passive_solid, gridSize, false);
if config.auto_boundary_solid
    passiveSolid = passiveSolid | build_boundary_solid_mask_3d( ...
        nelx, nely, nelz, config.bc_type, domainMask);
end
if any(passiveVoid(:) & passiveSolid(:))
    error('topopt3d_main:OverlappingPassiveMasks', ...
        'passive_void 与 passive_solid 不能重叠。');
end
if any(passiveSolid(:) & ~domainMask(:))
    error('topopt3d_main:SolidOutsideDomain', ...
        'passive_solid 必须位于 domain_mask 内。');
end
activeMask = domainMask & ~passiveVoid & ~passiveSolid;
if ~any(activeMask(:))
    error('topopt3d_main:EmptyActiveDomain', '可设计区域不能为空。');
end

% 初始材料仅放置于有效域；L 形缺角等区域从第一轮 FE 开始即为 void。
x = config.volfrac * ones(gridSize);
x(passiveVoid) = config.xmin;
x(passiveSolid) = 1.0;

bcConfig = struct('bc_type', config.bc_type);
if isfield(config, 'bc_config') && ~isempty(config.bc_config)
    bcConfig = config.bc_config;
    bcConfig.bc_type = config.bc_type;
end
bcConfig.domain_mask = domainMask;
bcConfig.Emin = config.Emin;
bcConfig.E = config.E;
bcConfig.nu = config.nu;

filterConfig = struct();
filterConfig.filter_type = 'sensitivity';
filterConfig.radius_strategy = config.filter_strategy;
filterConfig.rmin_start = config.rmin_start;
filterConfig.rmin_end = config.rmin_end;
filterConfig.schedule_power = config.filter_schedule_power;
filterConfig.max_iterations = config.max_iterations;
filterConfig.domain_mask = domainMask;

ocOptions = struct();
ocOptions.xmin = config.xmin;
ocOptions.tol_lambda = config.oc_tol_lambda;
ocOptions.max_bisect = config.oc_max_bisect;
ocOptions.active_mask = activeMask;
ocOptions.passive_void = passiveVoid;
ocOptions.passive_solid = passiveSolid;
ocOptions.volume_mask = domainMask;

KE = lk_3d(config.E, config.nu);
objectiveHistory = zeros(config.max_iterations, 1);
changeHistory = zeros(config.max_iterations, 1);
radiusHistory = zeros(config.max_iterations, 1);
moveHistory = zeros(config.max_iterations, 1);
volumeErrorHistory = zeros(config.max_iterations, 1);
penalHistory = zeros(config.max_iterations, 1);
relativeObjectiveHistory = inf(config.max_iterations, 1);

for iteration = 1:config.max_iterations
    % Heaviside projection sharpened by config.beta; the FE solve and the
    % objective/sensitivity chain use the projected physical density.
    [xProj, dProj] = project_heaviside_3d(x, config.beta);
    penalNow = scheduled_penal(iteration, config.max_iterations, config);
    U = FE_solver_3d(nelx, nely, nelz, xProj, penalNow, bcConfig);
    [objective, dc] = compliance_and_sensitivity_3d( ...
        nelx, nely, nelz, xProj, penalNow, config.Emin, U, KE);
    dc = dc .* dProj;
    dc(~domainMask) = 0;

    filterConfig.iteration = iteration;
    [dcFiltered, filterInfo] = filter_solver_3d( ...
        nelx, nely, nelz, config.rmin, x, dc, filterConfig);

    progress = iteration_progress(iteration, config.max_iterations);
    ocOptions.move = config.move_end + ...
        (config.move_start-config.move_end) ...
        * (1-progress)^config.move_schedule_power;
    [xNew, ocInfo] = OC_solver_3d(x, dcFiltered, config.volfrac, ocOptions);

    change = max(abs(xNew(:)-x(:)));
    x = xNew;
    objectiveHistory(iteration) = objective;
    changeHistory(iteration) = change;
    radiusHistory(iteration) = filterInfo.rmin;
    moveHistory(iteration) = ocOptions.move;
    volumeErrorHistory(iteration) = ocInfo.volume_error;
    penalHistory(iteration) = penalNow;
    if iteration > 1
        previousObjective = objectiveHistory(iteration-1);
        relativeObjectiveHistory(iteration) = abs(objective-previousObjective) ...
            / max(abs(previousObjective), eps);
    end

    if config.verbose
        fprintf(['It.:%4d Obj.:%12.5f Vol.:%7.4f ch.:%7.4f ', ...
                 'p:%4.2f rmin:%5.2f move:%5.3f Verr:%+.2e\n'], ...
            iteration, objective, ocInfo.volume_fraction, change, ...
            penalNow, filterInfo.rmin, ocOptions.move, ocInfo.volume_error);
    end
    if iteration >= config.min_iterations && change < config.change_tolerance ...
            && relativeObjectiveHistory(iteration) < config.objective_tolerance
        break;
    end
end

% 用最终密度重新分析，使应力图和 result.objective 与最终构型一致。
finalProj = project_heaviside_3d(x, config.beta);
finalPenal = penalHistory(iteration);
[Ufinal, Kfinal] = FE_solver_3d(nelx, nely, nelz, finalProj, finalPenal, bcConfig);
[finalObjective, ~] = compliance_and_sensitivity_3d( ...
    nelx, nely, nelz, finalProj, finalPenal, config.Emin, Ufinal, KE);
[vonMises, stress] = compute_von_mises_3d( ...
    nelx, nely, nelz, finalProj, finalPenal, config.Emin, Ufinal, ...
    config.stress_measure, config.E, config.nu);
objectiveHistory(iteration) = finalObjective;

result = struct();
result.x = finalProj;
result.raw_x = x;
result.domain_mask = domainMask;
result.iterations = iteration;
result.objective = finalObjective;
result.volume_fraction = mean(x(domainMask));
result.projected_volume_fraction = mean(finalProj(domainMask));
result.objective_history = objectiveHistory(1:iteration);
result.change_history = changeHistory(1:iteration);
result.radius_history = radiusHistory(1:iteration);
result.move_history = moveHistory(1:iteration);
result.volume_error_history = volumeErrorHistory(1:iteration);
result.penal_history = penalHistory(1:iteration);
result.relative_objective_history = relativeObjectiveHistory(1:iteration);
result.final_penal = finalPenal;
result.U = Ufinal;
result.K = Kfinal;
result.von_mises = vonMises;
result.stress = stress;
result.config = config;

if config.display
    show_result_3d(result);
end
end

function [objective, dc] = compliance_and_sensitivity_3d( ...
        nelx, nely, nelz, x, penal, Emin, U, KE)
persistent cachedNelx cachedNely cachedNelz cachedEdof
if isempty(cachedNelx) || cachedNelx ~= nelx || cachedNely ~= nely || cachedNelz ~= nelz
    cachedEdof = zeros(nelx*nely*nelz, 24);
    index = 0;
    for elz = 1:nelz
        for elx = 1:nelx
            for ely = 1:nely
                index = index + 1;
                cachedEdof(index,:) = element_dofs_3d(elx, ely, elz, nely, nelx).';
            end
        end
    end
    cachedNelx = nelx;
    cachedNely = nely;
    cachedNelz = nelz;
end
Ue = U(cachedEdof);
energy = sum((Ue*KE).*Ue, 2);
density = x(:);
effectiveE = Emin + (1-Emin)*density.^penal;
objective = sum(effectiveE.*energy);
dc = reshape(-(1-Emin)*penal*density.^(penal-1).*energy, nely, nelx, nelz);
end

function show_result_3d(result)
figure('Color','w','Name','3D topology optimization');
tiledlayout(1,2,'Padding','compact','TileSpacing','compact');

topologyAxes = nexttile;
density = result.x;
density(~result.domain_mask) = 0;
[X, Y, Z] = meshgrid(1:size(density,2), 1:size(density,1), ...
    1:size(density,3));
surfaceData = isosurface(X, Y, Z, density, result.config.iso_level);
if isempty(surfaceData.vertices)
    text(topologyAxes, 0.5, 0.5, '没有可显示的材料等值面。', ...
        'HorizontalAlignment','center');
    axis(topologyAxes, 'off');
    return;
end
patch(topologyAxes, 'Vertices',surfaceData.vertices, 'Faces',surfaceData.faces, ...
    'FaceColor',[0.15 0.45 0.80], 'EdgeColor','none', 'FaceAlpha',0.95);
axis(topologyAxes, 'equal'); axis(topologyAxes, 'tight');
xlabel(topologyAxes, 'x'); ylabel(topologyAxes, 'y'); zlabel(topologyAxes, 'z');
view(topologyAxes, 3); grid(topologyAxes, 'on');
camlight(topologyAxes, 'headlight'); lighting(topologyAxes, 'gouraud');
title(topologyAxes, sprintf('%s | iteration %d | objective %.3f', ...
    result.config.bc_type, result.iterations, result.objective));

stressAxes = nexttile;
plot_stress_heatmap_3d(result, stressAxes);
end

function penalNow = scheduled_penal(iteration, maxIterations, config)
progress = iteration_progress(iteration, maxIterations);
penalNow = config.penal_start + (config.penal-config.penal_start) ...
    * progress^config.penal_schedule_power;
end

function progress = iteration_progress(iteration, maxIterations)
if maxIterations <= 1
    progress = 1;
else
    progress = (iteration-1)/(maxIterations-1);
end
end

function config = set_default(config, name, value)
if ~isfield(config, name) || isempty(config.(name))
    config.(name) = value;
end
end

function [xProj, dProj] = project_heaviside_3d(x, beta)
%Smooth Heaviside projection (beta-continuation); see project_heaviside (2D).
if beta <= 1.0
    xProj = x;
    dProj = ones(size(x));
    return;
end
tanhHalf = tanh(0.5*beta);
xProj = (tanhHalf + tanh(beta*(x - 0.5))) / (2*tanhHalf);
sech2 = 1 - tanh(beta*(x - 0.5)).^2;
dProj = (beta * sech2) / (2*tanhHalf);
end

function defaults = accuracy_defaults(accuracy, isLBracket)
% 高精度默认网格保持单元近似立方，并兼顾普通桌面 MATLAB 的运行时间。
accuracy = lower(char(string(accuracy)));
switch accuracy
    case {'high','accurate'}
        if isLBracket
            defaults = struct('nelx',32,'nely',32,'nelz',8, ...
                'max_iterations',180,'min_iterations',45, ...
                'change_tolerance',0.003,'objective_tolerance',5e-4, ...
                'oc_tol_lambda',1e-6,'oc_max_bisect',150);
        else
            defaults = struct('nelx',40,'nely',14,'nelz',10, ...
                'max_iterations',160,'min_iterations',40, ...
                'change_tolerance',0.003,'objective_tolerance',5e-4, ...
                'oc_tol_lambda',1e-6,'oc_max_bisect',150);
        end
    case {'standard','fast'}
        if isLBracket
            defaults = struct('nelx',20,'nely',20,'nelz',6, ...
                'max_iterations',100,'min_iterations',20, ...
                'change_tolerance',0.01,'objective_tolerance',2e-3, ...
                'oc_tol_lambda',1e-4,'oc_max_bisect',100);
        else
            defaults = struct('nelx',24,'nely',8,'nelz',6, ...
                'max_iterations',100,'min_iterations',20, ...
                'change_tolerance',0.01,'objective_tolerance',2e-3, ...
                'oc_tol_lambda',1e-4,'oc_max_bisect',100);
        end
    otherwise
        error('topopt3d_main:UnknownAccuracy', ...
            'accuracy 仅支持 high 或 standard。');
end
end

function mask = read_mask(value, expectedSize, defaultValue)
if isempty(value)
    mask = repmat(defaultValue, expectedSize);
else
    validateattributes(value, {'logical','numeric'}, {'size',expectedSize});
    mask = logical(value);
end
end
