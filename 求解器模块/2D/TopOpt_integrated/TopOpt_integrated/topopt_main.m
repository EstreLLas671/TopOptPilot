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
% Heaviside projection sharpness; beta=1 reduces to the SIMP filter-only limit.
config = set_default(config, 'beta', 1.0);
config = set_default(config, 'beta_max', config.beta);
config = set_default(config, 'projection', 'none');
config = set_default(config, 'controller', 'fixed_controller');
validateattributes(config.beta, {'numeric'}, {'scalar','real','finite','>=',1,'<=',64});

nelx = config.nelx;
nely = config.nely;
validateattributes(nelx, {'numeric'}, {'scalar','integer','positive'});
validateattributes(nely, {'numeric'}, {'scalar','integer','positive'});
validateattributes(config.E, {'numeric'}, {'scalar','real','finite','positive'});
validateattributes(config.nu, {'numeric'}, {'scalar','real','finite','>=',0,'<',0.5});

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
betaHistory = ones(config.max_iterations, 1);

for loop = 1:config.max_iterations
    % Heaviside projection sharpened by config.beta; the FE solve and the
    % objective/sensitivity chain use the projected physical density.
    betaNow = scheduled_beta(loop, config);
    [xProj, dProj] = project_heaviside(x, betaNow);
    xProj = max(config.xmin, xProj);
    [U, K] = FE_solver(nelx, nely, xProj, config.penal, bcConfig);
    [objective, dc] = compliance_and_sensitivity( ...
        nelx, nely, xProj, config.penal, U, KE);
    dc = dc .* dProj;
    dc(~domainMask) = 0;

    filterConfig.iteration = loop;
    [dcFiltered, filterInfo] = filter_solver( ...
        nelx, nely, config.rmin, x, dc, filterConfig);

    progress = iteration_progress(loop, config.max_iterations);
    ocOptions.move = config.move_end + ...
        (config.move_start-config.move_end) ...
        *(1-progress)^config.move_schedule_power;
    if strcmp(config.projection, 'heaviside_projection')
        ocOptions.move = min(ocOptions.move, projection_move_cap(betaNow));
    end
    ocOptions.volume_projection_beta = betaNow * strcmp(config.projection, 'heaviside_projection');
    ocOptions.volume_sensitivity = dProj;
    [xNew, ocInfo] = OC_solver(x, dcFiltered, config.volfrac, ocOptions);
    change = max(abs(xNew(:)-x(:)));
    x = xNew;

    objectiveHistory(loop) = objective;
    changeHistory(loop) = change;
    radiusHistory(loop) = filterInfo.rmin;
    moveHistory(loop) = ocOptions.move;

    betaHistory(loop) = betaNow;
    if config.verbose
        fprintf(['It.:%4d Obj.:%10.4f Vol.:%7.4f ', ...
            'ch.:%7.4f rmin:%5.2f move:%5.3f\n'], ...
            loop, objective, ocInfo.volume_fraction, change, ...
            filterInfo.rmin, ocOptions.move);
    end
    if loop >= config.min_iterations && change < config.change_tolerance ...
            && betaNow >= target_beta(config)
        break;
    end
end

objectiveHistory = objectiveHistory(1:loop);
changeHistory = changeHistory(1:loop);
radiusHistory = radiusHistory(1:loop);
moveHistory = moveHistory(1:loop);

betaHistory = betaHistory(1:loop);
finalBeta = scheduled_beta(loop, config);
[xProj, ~] = project_heaviside(x, finalBeta);
xProj = max(config.xmin, xProj);
[Ufinal, ~] = FE_solver(nelx, nely, xProj, config.penal, bcConfig);
[finalObjective, ~] = compliance_and_sensitivity( ...
    nelx, nely, xProj, config.penal, Ufinal, KE);
objectiveHistory(end) = finalObjective;

result = struct();
result.x = xProj;
result.raw_x = x;
result.domain_mask = domainMask;
result.iterations = loop;
result.objective = finalObjective;
result.volume_fraction = mean(xProj(domainMask));
result.projected_volume_fraction = mean(xProj(domainMask));
result.objective_history = objectiveHistory;
result.change_history = changeHistory;
result.radius_history = radiusHistory;
result.move_history = moveHistory;
result.config = config;
result.beta_history = betaHistory;
result.final_beta = finalBeta;
result.final_change = changeHistory(end);
result.converged = loop < config.max_iterations && result.final_change < config.change_tolerance ...
    && finalBeta >= target_beta(config);

if config.display
    show_result(result);
end
end

function [objective, dc] = compliance_and_sensitivity( ...
    nelx, nely, x, penal, U, KE)
persistent cachedNelx cachedNely cachedEdof
if isempty(cachedNelx) || cachedNelx ~= nelx || cachedNely ~= nely
    cachedEdof = zeros(nelx*nely, 8);
    index = 0;
    for elx = 1:nelx
        for ely = 1:nely
            index = index + 1;
            n1 = (nely+1)*(elx-1)+ely;
            n2 = (nely+1)*elx+ely;
            cachedEdof(index,:) = [2*n1-1,2*n1,2*n2-1,2*n2, ...
                2*n2+1,2*n2+2,2*n1+1,2*n1+2];
        end
    end
    cachedNelx = nelx;
    cachedNely = nely;
end
Ue = U(cachedEdof);
elementEnergy = sum((Ue*KE).*Ue, 2);
density = x(:);
objective = sum((density.^penal).*elementEnergy);
dc = reshape(-penal*density.^(penal-1).*elementEnergy, nely, nelx);
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

function config = set_default(config, name, value)
if ~isfield(config, name) || isempty(config.(name))
    config.(name) = value;
end
end

function value = projection_move_cap(beta)
if beta <= 2
    value = 0.2;
elseif beta <= 4
    value = 0.1;
elseif beta <= 8
    value = 0.05;
else
    value = 0.02;
end
end

function betaNow = scheduled_beta(iteration, config)
if strcmp(config.projection, 'heaviside_projection') && ...
        strcmp(config.controller, 'periodic_controller')
    betaNow = min(config.beta_max, config.beta*2^floor((iteration-1)/10));
else
    betaNow = config.beta;
end
end

function value = target_beta(config)
if strcmp(config.projection, 'heaviside_projection') && ...
        strcmp(config.controller, 'periodic_controller')
    value = config.beta_max;
else
    value = config.beta;
end
end

function [xProj, dProj] = project_heaviside(x, beta)
%Smooth Heaviside projection (beta-continuation): beta=1 approaches the SIMP
%limit, larger beta sharpens the 0/1 transition and lowers gray ratio.
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

function mask = read_mask(value, expectedSize, defaultValue)
if isempty(value)
    mask = repmat(defaultValue, expectedSize);
else
    validateattributes(value, {'logical','numeric'}, {'size',expectedSize});
    mask = logical(value);
end
end
