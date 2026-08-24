function build_solver()
%BUILD_SOLVER Build the standalone TopOptSolver.exe with the installed MATLAB Compiler.
root = fileparts(mfilename('fullpath'));
solver = fullfile(root, 'TopOpt-3D');
output = fullfile(root, '..', 'dist', 'solver');
required = {'topopt3d_main.m', 'FE_solver_3d.m', 'OC_solver_3d.m'};
for i = 1:numel(required)
    if ~isfile(fullfile(solver, required{i}))
        error('iDeskTop:MissingSolverDependency', 'Missing TopOpt dependency: %s', required{i});
    end
end
if ~isfile(fullfile(root, 'run_topopt_job.m'))
    error('iDeskTop:MissingBridge', 'Missing bridge entry: run_topopt_job.m');
end
if ~isfile(fullfile(root, 'MCRSmoke.m'))
    error('iDeskTop:MissingSmoke', 'Missing Runtime smoke entry: MCRSmoke.m');
end
if ~isfolder(output), mkdir(output); end
smokeArgs = {'-m', fullfile(root, 'MCRSmoke.m'), '-o', 'MCRSmoke', '-d', output};
mcc(smokeArgs{:});
if ~isfile(fullfile(output, 'MCRSmoke.exe'))
    error('iDeskTop:IncompleteSmokeBuild', 'MCRSmoke.exe was not produced.');
end
files = dir(fullfile(solver, '*.m'));
additional = cell(1, numel(files));
for i = 1:numel(files)
    additional{i} = fullfile(solver, files(i).name);
end
args = {'-m', fullfile(root, 'run_topopt_job.m'), '-o', 'TopOptSolver', '-d', output};
for i = 1:numel(additional)
    args(end + 1:end + 2) = {'-a', additional{i}};
end
mcc(args{:});
if ~isfile(fullfile(output, 'TopOptSolver.exe'))
    error('iDeskTop:IncompleteBuild', 'TopOptSolver.exe was not produced.');
end
if ~isfile(fullfile(output, 'TopOptSolver.ctf'))
    fprintf('%s embedded the CTF archive in TopOptSolver.exe.\n', version('-release'));
end
compilerInfo = struct( ...
    'matlabVersion', version, ...
    'matlabRelease', version('-release'), ...
    'compiler', 'MATLAB Compiler', ...
    'builtAt', char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyy-MM-dd''T''HH:mm:ssXXX')));
infoFile = fopen(fullfile(output, 'compiler-info.json'), 'w');
if infoFile < 0, error('iDeskTop:BuildInfo', 'Cannot write compiler-info.json.'); end
cleanup = onCleanup(@() fclose(infoFile));
fprintf(infoFile, '%s', jsonencode(compilerInfo, PrettyPrint=true));
fprintf('TopOptSolver build output: %s\n', output);
end
