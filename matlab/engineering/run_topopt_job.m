function run_topopt_job(configPath, outputDir)
%RUN_TOPOPT_JOB Deployment bridge for TopOptPilot.
%   TopOptSolver.exe <job_config.json> <output_directory>
if nargin < 2
    args = argv();
    if numel(args) < 2
        error('TopOptPilot:Arguments', '需要 job_config.json 和 output_directory。');
    end
    configPath = args{1};
    outputDir = args{2};
end
if ~isfolder(outputDir), mkdir(outputDir); end
logPath = fullfile(outputDir, 'solver.log');
statusPath = fullfile(outputDir, 'status.json');
diary(logPath);
cleanup = onCleanup(@() diary('off')); %#ok<NASGU>
try
    inputConfig = jsondecode(fileread(configPath));
    config = make_config(inputConfig);
    dimension = lower(char(string(config.solver_dimension)));
    if ~ismember(dimension, {'2d','3d'})
        error('TopOptPilot:Dimension', 'solver_dimension 仅支持 2d 或 3d。');
    end
    is2D = strcmp(dimension, '2d');
    write_status(statusPath, 'running', ...
        sprintf('正在调用真实 TopOpt %s 源码', upper(dimension)));
    config.display = false;
    config.verbose = true;
    snapshotDir = fullfile(outputDir, 'snapshots');
    if ~isfolder(snapshotDir), mkdir(snapshotDir); end
    manifestPath = fullfile(snapshotDir, 'manifest.json');
    if is2D
        snapshotShape = double([config.nely,config.nelx]);
    else
        snapshotShape = double([config.nely,config.nelx,config.nelz]);
    end
    snapshotManifest = struct('version',1,'dtype','float32', ...
        'byte_order','little','order','F','dimension',dimension, ...
        'shape',snapshotShape,'frames',struct([]));
    write_json_atomic(manifestPath, snapshotManifest);
    config.iteration_callback = @(frame) write_iteration_snapshot( ...
        frame, config, dimension, snapshotDir, manifestPath, statusPath);
    bridgePath = fileparts(mfilename('fullpath'));
    configuredSolverPath = getenv('TOPOPTPILOT_SOLVER_PATH');
    if ~isempty(configuredSolverPath) && isfolder(configuredSolverPath)
        % 指定的求解器目录必须优先生效（科研 Step4 复用工程链路时指向
        % 求解器模块副本，携带投影/控制器参数），bridge 副本改为尾部追加。
        addpath(configuredSolverPath, '-begin');
    end
    if isfolder(fullfile(bridgePath, 'TopOpt_2D'))
        addpath(fullfile(bridgePath, 'TopOpt_2D'), '-end');
    end
    if isfolder(fullfile(bridgePath, 'TopOpt-3D'))
        addpath(fullfile(bridgePath, 'TopOpt-3D'), '-end');
    end
    if is2D
        result = topopt_main(config);
    else
        result = topopt3d_main(config);
    end
    if isfield(result, 'config') && isfield(result.config, 'iteration_callback')
        result.config = rmfield(result.config, 'iteration_callback');
    end
    save(fullfile(outputDir, 'result.mat'), '-struct', 'result', '-v7.3');
    write_single_payload(fullfile(outputDir, 'final_density.bin'), result.x);
    stressFile = '';
    if isfield(result, 'von_mises') && ~isempty(result.von_mises)
        stressFile = 'final_von_mises.bin';
        write_single_payload(fullfile(outputDir, stressFile), result.von_mises);
    end
    resultManifest = struct('version',1,'dtype','float32', ...
        'byte_order','little','order','F','dimension',dimension, ...
        'shape',double(size(result.x)), ...
        'density_file','final_density.bin','stress_file',stressFile);
    write_json_atomic(fullfile(outputDir, 'result_manifest.json'), resultManifest);
    visualization = write_result_visualizations(result, config, dimension, outputDir);
    summary = make_summary(result);
    summary.solver_dimension = dimension;
    if is2D
        summary.solver_entry = 'TopOpt_2D/topopt_main.m';
    else
        summary.solver_entry = 'TopOpt-3D/topopt3d_main.m';
    end
    summary.result_manifest = 'result_manifest.json';
    summary.snapshot_manifest = 'snapshots/manifest.json';
    summary.visualization = visualization;
    summary.material = struct( ...
        'preset', config.material_preset, ...
        'name', config.material_name, ...
        'E_GPa', config.E, ...
        'nu', config.nu, ...
        'density_kg_m3', config.density_kg_m3, ...
        'yield_strength_MPa', config.yield_strength_MPa);
    write_json_atomic(fullfile(outputDir, 'result_summary.json'), summary);
    write_status(statusPath, 'completed', '求解完成');
catch err
    write_status(statusPath, 'failed', err.message);
    fprintf(2, '%s\n', getReport(err, 'extended', 'hyperlinks', 'off'));
    rethrow(err);
end
end

function write_iteration_snapshot(frame, config, dimension, snapshotDir, manifestPath, statusPath)
densityName = sprintf('iter_%04d_density.bin', frame.iteration);
write_single_payload(fullfile(snapshotDir, densityName), frame.x);
stressName = '';
if isfield(frame, 'von_mises') && ~isempty(frame.von_mises)
    stressName = sprintf('iter_%04d_von_mises.bin', frame.iteration);
    write_single_payload(fullfile(snapshotDir, stressName), frame.von_mises);
end
renderName = '';
if ~isfield(config, 'render_iteration_frames') || config.render_iteration_frames
    renderName = sprintf('iter_%04d_matlab.png', frame.iteration);
    render_iteration_frame(frame, config, dimension, ...
        fullfile(snapshotDir, renderName));
end
% 帧元数据写唯一名文件（新建文件无覆盖竞争），进度消费方直接扫描目录。
metaPath = fullfile(snapshotDir, sprintf('iter_%04d_meta.json', frame.iteration));
meta = struct( ...
    'iteration',double(frame.iteration), ...
    'max_iterations',double(frame.max_iterations), ...
    'objective',double(frame.objective), ...
    'volume_fraction',double(frame.volume_fraction), ...
    'density_file',densityName);
try
    write_json_atomic(metaPath, meta);
catch
    % 元数据瞬时写入失败不中断求解；轮询方以下一个帧为准。
end
% 清单/状态为覆盖型文件，可能被外部进程瞬时占用：容错写入，
% 失败只跳过清单维护，帧数据与元数据已落盘，绝不中断求解。
% 求解器内核未提供 gray_ratio 时（如求解器模块副本）以 NaN 占位，
% 由 Python 侧自行计算，避免快照写入中断。
if ~isfield(frame, 'gray_ratio') || isempty(frame.gray_ratio)
    frame.gray_ratio = NaN;
end
try
    manifest = jsondecode(fileread(manifestPath));
    entry = struct( ...
        'iteration',double(frame.iteration), ...
        'density_file',densityName, ...
        'stress_file',stressName, ...
        'render_file',renderName, ...
        'objective',double(frame.objective), ...
        'change',double(frame.change), ...
        'volume_fraction',double(frame.volume_fraction), ...
        'gray_ratio',double(frame.gray_ratio), ...
        'rmin',double(frame.rmin), ...
        'penal',double(frame.penal));
    if isempty(manifest.frames)
        manifest.frames = entry;
    else
        manifest.frames(end+1) = entry;
    end
    write_json_atomic(manifestPath, manifest);
catch
end
try
    write_status(statusPath, 'running', ...
        sprintf('正在求解：第 %d/%d 轮', frame.iteration, frame.max_iterations), ...
        frame.iteration/frame.max_iterations);
catch
end
end

function write_single_payload(path, values)
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
if ~commit_file_with_retry(tempPath, path)
    error('TopOptPilot:SnapshotWrite', '无法提交二进制制品：%s', path);
end
end

function committed = commit_file_with_retry(tempPath, path)
% Windows 下若目标清单正被进度轮询进程读取，movefile 会瞬时失败；
% 短暂重试即可避开冲突，避免快照写入中断整个求解。
committed = false;
for attempt = 1:20
    [moved, ~] = movefile(tempPath, path, 'f');
    if moved
        committed = true;
        return;
    end
    pause(0.05);
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
        if isempty(fields), error('TopOptPilot:Mask', '掩码 MAT 文件为空。'); end
        config.(field) = logical(values.(fields{1}));
    end
end
if ~isfield(config, 'solver_dimension') || isempty(config.solver_dimension)
    config.solver_dimension = '3d';
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
fields = {'iterations','objective','volume_fraction','gray_ratio','objective_history', ...
    'change_history','volume_error_history','penal_history','radius_history','final_penal', ...
    'beta_history','final_beta','final_change','converged'};
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
    error('TopOptPilot:JsonWrite', '无法创建 JSON 文件：%s', tempPath);
end
fprintf(fid, '%s', jsonencode(value));
fclose(fid);
if ~commit_file_with_retry(tempPath, path)
    error('TopOptPilot:JsonWrite', '无法提交 JSON 文件：%s', path);
end
end
