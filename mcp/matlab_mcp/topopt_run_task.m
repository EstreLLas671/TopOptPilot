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
if ~isfield(payload, 'config') || ~isstruct(payload.config)
    error('TopOptPilot:InvalidConfig', 'config must be an object.');
end
config = payload.config;
config.display = false;
config.verbose = false;

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
result.completed_at = char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyy-MM-dd''T''HH:mm:ssXXX'));

fid = fopen(resultPath, 'w', 'n', 'UTF-8');
if fid < 0, error('TopOptPilot:ResultWrite', 'Cannot open result JSON.'); end
cleanup = onCleanup(@() fclose(fid));
fwrite(fid, jsonencode(result), 'char');
fprintf('TOPPILOT_RESULT=%s\n', resultPath);
end

function value = canonical_path(inputPath)
value = char(java.io.File(char(inputPath)).getCanonicalPath());
end
