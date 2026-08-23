function topopt_run_task(task_json_path, result_json_path)
%TOPOPT_RUN_TASK Restricted JSON adapter for the official MATLAB MCP Server.

taskPath = canonical_path(task_json_path);
resultPath = canonical_path(result_json_path);
[taskDir,~,taskExt] = fileparts(taskPath);
[resultDir,~,resultExt] = fileparts(resultPath);
if ~strcmpi(taskExt, '.json') || ~strcmpi(resultExt, '.json') || ~strcmpi(taskDir, resultDir)
    error('TopOptPilot:UnsafePath', 'Task and result must be JSON files in the same job directory.');
end
jobRoot = getenv('TOPPILOT_MATLAB_JOB_ROOT');
if isempty(jobRoot)
    error('TopOptPilot:UnsafePath', 'The approved MATLAB job root is not configured.');
end
jobRoot = canonical_path(jobRoot);
prefix = [jobRoot filesep];
if ~startsWith(lower(taskPath), lower(prefix)) || ~startsWith(lower(resultPath), lower(prefix))
    error('TopOptPilot:UnsafePath', 'Task and result must remain under the approved research data root.');
end
if ~isfile(taskPath)
    error('TopOptPilot:MissingTask', 'Task JSON does not exist.');
end

payload = jsondecode(fileread(taskPath));
if ~isfield(payload, 'dimension') || ~ismember(double(payload.dimension), [2 3])
    error('TopOptPilot:InvalidDimension', 'dimension must be 2 or 3.');
end
capabilities = detect_capabilities();
operation = 'solve';
if isfield(payload, 'operation'), operation = char(string(payload.operation)); end
if strcmpi(operation, 'capabilities')
    probe = struct('status','ready','capabilities',capabilities, ...
        'matlab_version',version,'completed_at',timestamp_utc());
    write_json_result(resultPath, probe);
    fprintf('TOPPILOT_RESULT=%s\n', resultPath);
    return;
end
if ~isfield(payload, 'config') || ~isstruct(payload.config)
    error('TopOptPilot:InvalidConfig', 'config must be an object.');
end
config = payload.config;
config.display = false;
config.verbose = false;
preview = topopt_prepare_geometry(config, double(payload.dimension));
if strcmpi(operation, 'preview_geometry')
    preview.status = 'ready';
    preview.matlab_version = version;
    preview.completed_at = timestamp_utc();
    write_json_result(resultPath, preview);
    fprintf('TOPPILOT_RESULT=%s\n', resultPath);
    return;
end
config.domain_mask = preview.domain_mask;
solverTimer = tic;

adapterDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(adapterDir));
if payload.dimension == 2
    solverDir = fullfile(projectRoot, '求解器模块', '2D', 'TopOpt_integrated', 'TopOpt_integrated');
    addpath(solverDir);
    raw = topopt_main(config);
    solverName = 'topopt_main';
else
    solverDir = fullfile(projectRoot, '求解器模块', 'TopOpt-3D', 'TopOpt-3D');
    addpath(solverDir);
    raw = topopt3d_main(config);
    solverName = 'topopt3d_main';
end

result = struct();
result.status = 'converged';
result.density = raw.x;
result.compliance = raw.objective;
result.volume_fraction = raw.volume_fraction;
result.iterations = raw.iterations;
result.objective_history = raw.objective_history;
result.change_history = raw.change_history;
if isfield(raw, 'radius_history'), result.radius_history = raw.radius_history; end
if isfield(raw, 'move_history'), result.move_history = raw.move_history; end
if isfield(raw, 'von_mises'), result.von_mises = raw.von_mises; end
result.matlab_version = version;
result.solver_entry = solverName;
requestedVariant = 'auto';
if isfield(config, 'solver_variant'), requestedVariant = char(string(config.solver_variant)); end
if strcmpi(requestedVariant, 'reference_cpu')
    result.solver_variant = 'reference_cpu';
    result.acceleration_mode = 'cpu';
else
    % The controlled main functions use vectorized sparse assembly and
    % persistent mesh/filter topology caches while preserving the algorithm.
    result.solver_variant = 'optimized_cpu';
    result.acceleration_mode = 'vectorized_cpu';
end
result.capabilities = capabilities;
result.elapsed_seconds = toc(solverTimer);
result.completed_at = timestamp_utc();
write_json_result(resultPath, result);
fprintf('TOPPILOT_RESULT=%s\n', resultPath);
end

function capabilities = detect_capabilities()
parallelAvailable = false;
gpuAvailable = false;
try, parallelAvailable = license('test','Distrib_Computing_Toolbox'); catch, end
if parallelAvailable
    try, gpuAvailable = gpuDeviceCount('available') > 0; catch, end
end
mex2d = exist('topopt_assemble_2d_mex','file') == 3;
mex3d = exist('topopt_assemble_3d_mex','file') == 3;
variants = {'reference_cpu','optimized_cpu'};
if mex2d || mex3d, variants{end+1} = 'mex'; end %#ok<AGROW>
if gpuAvailable, variants{end+1} = 'gpu'; end %#ok<AGROW>
capabilities = struct('variants',{variants},'selected_variant','optimized_cpu', ...
    'acceleration_mode','vectorized_cpu','parallel_available',logical(parallelAvailable), ...
    'gpu_available',logical(gpuAvailable),'mex_2d_available',logical(mex2d), ...
    'mex_3d_available',logical(mex3d),'probed',true);
end

function write_json_result(resultPath, value)
fid = fopen(resultPath, 'w', 'n', 'UTF-8');
if fid < 0, error('TopOptPilot:ResultWrite', 'Cannot open result JSON.'); end
cleanup = onCleanup(@() fclose(fid)); %#ok<NASGU>
fwrite(fid, jsonencode(value), 'char');
end

function value = timestamp_utc()
value = char(datetime('now', 'TimeZone', 'UTC', ...
    'Format', 'yyyy-MM-dd''T''HH:mm:ssXXX'));
end

function value = canonical_path(inputPath)
value = char(java.io.File(char(inputPath)).getCanonicalPath());
end
