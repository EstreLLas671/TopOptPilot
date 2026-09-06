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
% 可选逐轮快照：progress_dir 必须停留在已批准的作业根目录内。
if isfield(config, 'progress_dir') && ~isempty(config.progress_dir)
    progressDir = canonical_path(char(string(config.progress_dir)));
    if ~startsWith(lower(progressDir), lower(prefix))
        error('TopOptPilot:UnsafePath', 'progress_dir must remain under the approved job root.');
    end
    if ~isfolder(progressDir), mkdir(progressDir); end
    manifestPath = fullfile(progressDir, 'manifest.json');
    statusPath = fullfile(progressDir, 'status.json');
    snapshotManifest = struct('version',1,'dtype','float32','byte_order','little','order','F', ...
        'dimension',char(string(payload.dimension) + 'd'), ...
        'shape',double(size(config.domain_mask)), ...
        'max_iterations',double(config.max_iterations),'frames',struct([]));
    write_json_atomic_local(manifestPath, snapshotManifest);
    config.iteration_callback = @(frame) write_progress_snapshot( ...
        frame, progressDir, manifestPath, statusPath);
end
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
if isfield(raw, 'converged') && raw.converged
    result.status = 'converged';
else
    result.status = 'max_iter';
end
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

function write_progress_snapshot(frame, snapshotDir, manifestPath, statusPath)
densityName = sprintf('iter_%04d_density.bin', frame.iteration);
write_single_payload_local(fullfile(snapshotDir, densityName), frame.x);
manifest = jsondecode(fileread(manifestPath));
entry = struct( ...
    'iteration',double(frame.iteration), ...
    'density_file',densityName, ...
    'objective',double(frame.objective), ...
    'change',double(frame.change), ...
    'volume_fraction',double(frame.volume_fraction), ...
    'rmin',double(frame.rmin), ...
    'penal',double(frame.penal), ...
    'beta',double(frame.beta));
if isempty(manifest.frames)
    manifest.frames = entry;
else
    manifest.frames(end+1) = entry;
end
write_json_atomic_local(manifestPath, manifest);
write_status_local(statusPath, 'running', ...
    sprintf('正在求解：第 %d/%d 轮', frame.iteration, frame.max_iterations), ...
    frame.iteration/frame.max_iterations);
end

function write_status_local(path, status, message, progress)
payload = struct('status',char(string(status)),'message',char(string(message)), ...
    'progress',double(progress),'updated_at',timestamp_utc());
write_json_atomic_local(path, payload);
end

function write_json_atomic_local(path, value)
tempPath = [path, '.tmp'];
fid = fopen(tempPath, 'w');
if fid < 0
    error('TopOptPilot:SnapshotWrite', '无法创建 JSON 制品：%s', tempPath);
end
cleanup = onCleanup(@() fclose(fid));
fwrite(fid, jsonencode(value), 'char');
clear cleanup
movefile(tempPath, path, 'f');
end

function write_single_payload_local(path, values)
tempPath = [path, '.tmp'];
fid = fopen(tempPath, 'w', 'ieee-le');
if fid < 0
    error('TopOptPilot:SnapshotWrite', '无法创建二进制制品：%s', tempPath);
end
cleanup = onCleanup(@() fclose(fid));
count = fwrite(fid, single(values), 'single');
clear cleanup
if count ~= numel(values)
    error('TopOptPilot:SnapshotWrite', '二进制制品写入不完整：%s', path);
end
movefile(tempPath, path, 'f');
end
