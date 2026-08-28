function result = topopt_main(config)
%TOPOPT_MAIN Integrated FE + sensitivity filter + OC optimization loop.
%   RESULT = TOPOPT_MAIN(CONFIG) runs one topology-optimization case.
%   Missing fields use documented defaults, so TOPOPT_MAIN() is runnable.

if nargin < 1 || isempty(config)
    config = struct();
end

config = set_default(config, 'bc_type', 'MBB');
isLBracket = strcmpi(char(string(config.bc_type)), 'L-bracket');
if isLBracket
    config = set_default(config, 'nelx', 40);
    config = set_default(config, 'nely', 40);
    config = set_default(config, 'max_iterations', 150);
    config = set_default(config, 'min_iterations', 30);
    config = set_default(config, 'change_tolerance', 0.005);
else
    config = set_default(config, 'nelx', 60);
    config = set_default(config, 'nely', 20);
    config = set_default(config, 'max_iterations', 100);
    config = set_default(config, 'min_iterations', 20);
    config = set_default(config, 'change_tolerance', 0.01);
end
config = set_default(config, 'volfrac', 0.5);
config = set_default(config, 'penal', 3.0);
config = set_default(config, 'rmin', 1.5);
config = set_default(config, 'E', 1.0);
config = set_default(config, 'nu', 0.3);
config = set_default(config, 'material_name', '归一化参考材料');
config = set_default(config, 'density_kg_m3', 1.0);
config = set_default(config, 'yield_strength_MPa', 1.0);
config = set_default(config, 'geometry', struct());
config = set_default(config, 'display', true);
config = set_default(config, 'verbose', true);
config = set_default(config, 'xmin', 1e-3);
config = set_default(config, 'filter_strategy', 'fixed');
config = set_default(config, 'rmin_start', 3.0);
config = set_default(config, 'rmin_end', config.rmin);
config = set_default(config, 'filter_schedule_power', 2.0);
config = set_default(config, 'move_start', 0.2);
config = set_default(config, 'move_end', config.move_start);
config = set_default(config, 'move_schedule_power', 1.0);
config = set_default(config, 'passive_solid', []);
config = set_default(config, 'passive_void', []);
config = set_default(config, 'iteration_callback', []);
config = set_default(config, 'live_stress_snapshots', false);
config = set_default(config, 'stress_measure', 'gauss_max');

if ~isempty(config.iteration_callback) && ...
        ~isa(config.iteration_callback, 'function_handle')
    error('topopt_main:InvalidIterationCallback', ...
        'iteration_callback must be a function handle.');
end

nelx = config.nelx;
nely = config.nely;
validateattributes(nelx, {'numeric'}, {'scalar','integer','positive'});
validateattributes(nely, {'numeric'}, {'scalar','integer','positive'});

if isfield(config, 'domain_mask') && ~isempty(config.domain_mask)
    domainMask = logical(config.domain_mask);
    validateattributes(domainMask, {'logical'}, {'size',[nely,nelx]});
else
    domainMask = build_domain_mask(nelx, nely, ...
        config.bc_type, config.geometry);
end

passiveVoid = read_mask(config.passive_void, [nely,nelx], false) | ~domainMask;
passiveSolid = read_mask(config.passive_solid, [nely,nelx], false);
if any(passiveVoid(:) & passiveSolid(:))
    error('topopt_main:OverlappingPassiveMasks', ...
        'passive_void and passive_solid must not overlap.');
end
if any(passiveSolid(:) & ~domainMask(:))
    error('topopt_main:SolidOutsideDomain', ...
        'passive_solid must be inside domainMask.');
end
activeMask = domainMask & ~passiveVoid & ~passiveSolid;

x = config.volfrac*ones(nely, nelx);
x(passiveVoid) = config.xmin;
x(passiveSolid) = 1.0;

bcConfig = struct('bc_type', config.bc_type);
if isfield(config, 'bc_config') && ~isempty(config.bc_config)
    bcConfig = config.bc_config;
    bcConfig.bc_type = config.bc_type;
end
bcConfig.domain_mask = domainMask;
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
filterConfig.bc_type = config.bc_type;

ocOptions = struct();
ocOptions.xmin = config.xmin;
ocOptions.tol_lambda = 1e-4;
ocOptions.max_bisect = 100;
ocOptions.active_mask = activeMask;
ocOptions.passive_void = passiveVoid;
ocOptions.passive_solid = passiveSolid;
ocOptions.volume_mask = domainMask;

KE = element_stiffness_matrix(config.E, config.nu);
objectiveHistory = zeros(config.max_iterations, 1);
changeHistory = zeros(config.max_iterations, 1);
radiusHistory = zeros(config.max_iterations, 1);
moveHistory = zeros(config.max_iterations, 1);

for loop = 1:config.max_iterations
    [U, K] = FE_solver(nelx, nely, x, config.penal, bcConfig);
    [objective, dc] = compliance_and_sensitivity( ...
        nelx, nely, x, config.penal, U, KE);
    dc(~domainMask) = 0;

    filterConfig.iteration = loop;
    [dcFiltered, filterInfo] = filter_solver( ...
        nelx, nely, config.rmin, x, dc, filterConfig);

    progress = iteration_progress(loop, config.max_iterations);
    ocOptions.move = config.move_end + ...
        (config.move_start-config.move_end) ...
        *(1-progress)^config.move_schedule_power;
    [xNew, ocInfo] = OC_solver(x, dcFiltered, config.volfrac, ocOptions);
    change = max(abs(xNew(:)-x(:)));
    x = xNew;

    objectiveHistory(loop) = objective;
    changeHistory(loop) = change;
    radiusHistory(loop) = filterInfo.rmin;
    moveHistory(loop) = ocOptions.move;

    if config.verbose
        fprintf(['It.:%4d Obj.:%10.4f Vol.:%7.4f ', ...
            'ch.:%7.4f rmin:%5.2f move:%5.3f\n'], ...
            loop, objective, ocInfo.volume_fraction, change, ...
            filterInfo.rmin, ocOptions.move);
    end
    if ~isempty(config.iteration_callback)
        frame = struct();
        frame.iteration = loop;
        frame.max_iterations = config.max_iterations;
        frame.x = x;
        frame.domain_mask = domainMask;
        frame.objective = objective;
        frame.change = change;
        frame.volume_fraction = ocInfo.volume_fraction;
        frame.gray_ratio = gray_ratio(x, domainMask);
        frame.rmin = filterInfo.rmin;
        frame.penal = config.penal;
        if config.live_stress_snapshots
            [frame.von_mises, ~] = compute_von_mises_2d(nelx, nely, ...
                x, config.penal, U, config.stress_measure, config.E, config.nu);
        end
        config.iteration_callback(frame);
    end
    if loop >= config.min_iterations && change < config.change_tolerance
        break;
    end
end

objectiveHistory = objectiveHistory(1:loop);
changeHistory = changeHistory(1:loop);
radiusHistory = radiusHistory(1:loop);
moveHistory = moveHistory(1:loop);

% Re-analyze the final density so final stress and objective match the displayed topology.
[Ufinal, Kfinal] = FE_solver(nelx, nely, x, config.penal, bcConfig);
[finalObjective, ~] = compliance_and_sensitivity( ...
    nelx, nely, x, config.penal, Ufinal, KE);
[vonMises, stress] = compute_von_mises_2d( ...
    nelx, nely, x, config.penal, Ufinal, config.stress_measure, config.E, config.nu);
objectiveHistory(loop) = finalObjective;

result = struct();
result.x = x;
result.domain_mask = domainMask;
result.iterations = loop;
result.objective = finalObjective;
result.volume_fraction = mean(x(domainMask));
result.gray_ratio = gray_ratio(x, domainMask);
result.objective_history = objectiveHistory;
result.change_history = changeHistory;
result.radius_history = radiusHistory;
result.move_history = moveHistory;
result.U = Ufinal;
result.K = Kfinal;
result.von_mises = vonMises;
result.stress = stress;
result.config = config;

if config.display
    show_result(result);
end
end

function [objective, dc] = compliance_and_sensitivity( ...
    nelx, nely, x, penal, U, KE)
objective = 0;
dc = zeros(nely, nelx);
for elx = 1:nelx
    for ely = 1:nely
        n1 = (nely+1)*(elx-1)+ely;
        n2 = (nely+1)*elx+ely;
        edof = [2*n1-1;2*n1;2*n2-1;2*n2; ...
            2*n2+1;2*n2+2;2*n1+1;2*n1+2];
        elementEnergy = U(edof)'*KE*U(edof);
        objective = objective + x(ely,elx)^penal*elementEnergy;
        dc(ely,elx) = -penal*x(ely,elx)^(penal-1)*elementEnergy;
    end
end
end

function KE = element_stiffness_matrix(E, nu)
k = [1/2-nu/6,1/8+nu/8,-1/4-nu/12,-1/8+3*nu/8, ...
    -1/4+nu/12,-1/8-nu/8,nu/6,1/8-3*nu/8];
KE = E/(1-nu^2)* ...
    [k(1) k(2) k(3) k(4) k(5) k(6) k(7) k(8); ...
     k(2) k(1) k(8) k(7) k(6) k(5) k(4) k(3); ...
     k(3) k(8) k(1) k(6) k(7) k(4) k(5) k(2); ...
     k(4) k(7) k(6) k(1) k(8) k(3) k(2) k(5); ...
     k(5) k(6) k(7) k(8) k(1) k(2) k(3) k(4); ...
     k(6) k(5) k(4) k(3) k(2) k(1) k(8) k(7); ...
     k(7) k(4) k(5) k(2) k(3) k(8) k(1) k(6); ...
     k(8) k(3) k(2) k(5) k(4) k(7) k(6) k(1)];
end

function show_result(result)
figure('Color','w','Name','Integrated topology optimization');
% Use the original 99-line display convention: material is black.
densityDisplay = result.x;
densityDisplay(~result.domain_mask) = 0;
densityImage = imagesc(-densityDisplay, [-1,0]);
set(densityImage, 'Interpolation', 'nearest');
axis equal tight off;
colormap(gray);
title(sprintf('%s, iteration %d, objective %.3f', ...
    result.config.bc_type, result.iterations, result.objective));
end

function progress = iteration_progress(iteration, maxIterations)
if maxIterations <= 1
    progress = 1;
else
    progress = (iteration-1)/(maxIterations-1);
end
end

function value = gray_ratio(x, domainMask)
active = x(logical(domainMask));
if isempty(active)
    value = 0;
else
    value = mean(active > 0.1 & active < 0.9);
end
end

function config = set_default(config, name, value)
if ~isfield(config, name) || isempty(config.(name))
    config.(name) = value;
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
