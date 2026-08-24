function run_topopt_job(configPath, outputDir)
%RUN_TOPOPT_JOB Deployment bridge for iDeskTop v2.
%   TopOptSolver.exe <job_config.json> <output_directory>
if nargin < 2
    args = argv();
    if numel(args) < 2
        error('iDeskTop:Arguments', '需要 job_config.json 和 output_directory。');
    end
    configPath = args{1};
    outputDir = args{2};
end
if ~isfolder(outputDir), mkdir(outputDir); end
logPath = fullfile(outputDir, 'solver.log');
statusPath = fullfile(outputDir, 'status.json');
diary(logPath);
cleanup = onCleanup(@() diary('off')); %#ok<NASGU>
write_status(statusPath, 'running', '正在调用 TopOpt-3D');
try
    inputConfig = jsondecode(fileread(configPath));
    config = make_config(inputConfig);
    config.display = false;
    config.verbose = true;
    snapshotDir = fullfile(outputDir, 'snapshots');
    if ~isfolder(snapshotDir), mkdir(snapshotDir); end
    manifestPath = fullfile(snapshotDir, 'manifest.json');
    snapshotManifest = struct('version',1,'dtype','float32', ...
        'byte_order','little','order','F', ...
        'shape',double([config.nely,config.nelx,config.nelz]), ...
        'frames',struct([]));
    write_json_atomic(manifestPath, snapshotManifest);
    config.iteration_callback = @(frame) write_iteration_snapshot( ...
        frame, snapshotDir, manifestPath, statusPath);
    bridgePath = fileparts(mfilename('fullpath'));
    configuredSolverPath = getenv('IDESKTOP_SOLVER_PATH');
    if ~isempty(configuredSolverPath) && isfolder(configuredSolverPath)
        addpath(configuredSolverPath);
    end
    if isfolder(fullfile(bridgePath, 'TopOpt-3D'))
        addpath(fullfile(bridgePath, 'TopOpt-3D'));
    end
    result = topopt3d_main(config);
    if isfield(result, 'config') && isfield(result.config, 'iteration_callback')
        result.config = rmfield(result.config, 'iteration_callback');
    end
    save(fullfile(outputDir, 'result.mat'), '-struct', 'result', '-v7.3');
    write_single_payload(fullfile(outputDir, 'final_density.bin'), result.x);
    write_single_payload(fullfile(outputDir, 'final_von_mises.bin'), result.von_mises);
    resultManifest = struct('version',1,'dtype','float32', ...
        'byte_order','little','order','F','shape',double(size(result.x)), ...
        'density_file','final_density.bin', ...
        'stress_file','final_von_mises.bin');
    write_json_atomic(fullfile(outputDir, 'result_manifest.json'), resultManifest);
    summary = make_summary(result);
    summary.result_manifest = 'result_manifest.json';
    summary.snapshot_manifest = 'snapshots/manifest.json';
    write_json_atomic(fullfile(outputDir, 'result_summary.json'), summary);
    write_status(statusPath, 'completed', '求解完成');
catch err
    write_status(statusPath, 'failed', err.message);
    fprintf(2, '%s\n', getReport(err, 'extended', 'hyperlinks', 'off'));
    rethrow(err);
end
end

function write_iteration_snapshot(frame, snapshotDir, manifestPath, statusPath)
densityName = sprintf('iter_%04d_density.bin', frame.iteration);
write_single_payload(fullfile(snapshotDir, densityName), frame.x);
stressName = '';
if isfield(frame, 'von_mises') && ~isempty(frame.von_mises)
    stressName = sprintf('iter_%04d_von_mises.bin', frame.iteration);
    write_single_payload(fullfile(snapshotDir, stressName), frame.von_mises);
end
manifest = jsondecode(fileread(manifestPath));
entry = struct( ...
    'iteration',double(frame.iteration), ...
    'density_file',densityName, ...
    'stress_file',stressName, ...
    'objective',double(frame.objective), ...
    'change',double(frame.change), ...
    'volume_fraction',double(frame.volume_fraction), ...
    'rmin',double(frame.rmin), ...
    'penal',double(frame.penal));
if isempty(manifest.frames)
    manifest.frames = entry;
else
    manifest.frames(end+1) = entry;
end
write_json_atomic(manifestPath, manifest);
write_status(statusPath, 'running', ...
    sprintf('正在求解：第 %d/%d 轮', frame.iteration, frame.max_iterations), ...
    frame.iteration/frame.max_iterations);
end

function write_single_payload(path, values)
tempPath = [path, '.tmp'];
fid = fopen(tempPath, 'w', 'ieee-le');
if fid < 0
    error('iDeskTop:SnapshotWrite', '无法创建二进制制品：%s', tempPath);
end
cleanup = onCleanup(@() fclose(fid));
count = fwrite(fid, single(values), 'single');
clear cleanup
if count ~= numel(values)
    error('iDeskTop:SnapshotWrite', '二进制制品写入不完整：%s', path);
end
[moved, moveMessage] = movefile(tempPath, path, 'f');
if ~moved
    error('iDeskTop:SnapshotWrite', '无法提交二进制制品：%s', moveMessage);
end
end

function config = make_config(inputConfig)
config = struct();
names = fieldnames(inputConfig);
for i = 1:numel(names)
    name = names{i};
    if ~endsWith(name, '_path')
        config.(name) = inputConfig.(name);
    end
end
for names = {'domain_mask', 'passive_void', 'passive_solid'}
    field = names{1};
    pathField = [field, '_path'];
    if isfield(inputConfig, pathField) && ~isempty(inputConfig.(pathField))
        values = load(inputConfig.(pathField));
        fields = fieldnames(values);
        if isempty(fields), error('iDeskTop:Mask', '掩码 MAT 文件为空。'); end
        config.(field) = logical(values.(fields{1}));
    end
end
if isfield(config, 'bc_config') && isstruct(config.bc_config)
    config.bc_config.fixeddofs = double(config.bc_config.fixeddofs(:).');
    if isfield(config.bc_config, 'loads')
        config.bc_config.loads = double(config.bc_config.loads);
    end
end
end

function summary = make_summary(result)
summary = struct();
fields = {'iterations','objective','volume_fraction','objective_history', ...
    'change_history','volume_error_history','penal_history','radius_history','final_penal'};
for i = 1:numel(fields)
    if isfield(result, fields{i}), summary.(fields{i}) = result.(fields{i}); end
end
end

function write_status(path, state, message, progress)
status = struct('state', state, 'message', message, 'timestamp', char(datetime('now', 'Format', 'yyyy-MM-dd''T''HH:mm:ss')));
if nargin >= 4
    status.progress = progress;
end
write_json_atomic(path, status);
end

function write_json_atomic(path, value)
tempPath = [path, '.tmp'];
fid = fopen(tempPath, 'w', 'n', 'UTF-8');
if fid < 0
    error('iDeskTop:JsonWrite', '无法创建 JSON 文件：%s', tempPath);
end
fprintf(fid, '%s', jsonencode(value));
fclose(fid);
[moved, moveMessage] = movefile(tempPath, path, 'f');
if ~moved
    error('iDeskTop:JsonWrite', '无法提交 JSON 文件：%s', moveMessage);
end
end
