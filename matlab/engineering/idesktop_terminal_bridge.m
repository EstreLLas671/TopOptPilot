function idesktop_terminal_bridge(configPath)
% Hidden MATLAB command bridge for iDeskTop.
% The Electron controller owns the session directory and writes atomic JSON
% command files. This loop never opens a desktop command window.
try
    config = jsondecode(fileread(configPath));
    projectRoot = char(config.project_root);
    sessionRoot = char(config.session_root);
    commandsDir = fullfile(sessionRoot, 'commands');
    resultsDir = fullfile(sessionRoot, 'results');
    readyPath = fullfile(sessionRoot, 'ready');
    heartbeatPath = fullfile(sessionRoot, 'heartbeat');
    activePath = fullfile(sessionRoot, 'active.json');
    failurePath = fullfile(sessionRoot, 'failure.txt');
    stopPath = fullfile(sessionRoot, 'stop');
    if ~isfolder(projectRoot)
        error('项目目录不存在：%s', projectRoot);
    end
    cd(projectRoot);
    writeTextAtomic(readyPath, 'ready');
    while true
        writeTextAtomic(heartbeatPath, datestr(now, 30));
        if isfile(stopPath)
            break;
        end
        names = dir(fullfile(commandsDir, 'command_*.json'));
        if isempty(names)
            pause(0.12);
            continue;
        end
        [~, order] = sort({names.name});
        for idx = order
            commandPath = fullfile(commandsDir, names(idx).name);
            try
                command = jsondecode(fileread(commandPath));
                id = double(command.id);
                expression = char(command.command);
                active = struct('id', id, 'command', expression, 'startedAt', datestr(now, 30));
                writeJsonAtomic(activePath, active);
                output = evalc('evalin(''base'', expression)');
                result = struct('id', id, 'command', expression, 'status', 'complete', ...
                    'output', output, 'error', '');
            catch exception
                result = struct('id', id, 'command', expression, 'status', 'error', ...
                    'output', '', 'error', exception.message);
            end
            writeJsonAtomic(fullfile(resultsDir, sprintf('result_%08d.json', id)), result);
            if isfile(activePath)
                delete(activePath);
            end
            if isfile(commandPath)
                delete(commandPath);
            end
        end
    end
catch exception
    writeTextAtomic(failurePath, exception.message);
end
end

function writeJsonAtomic(target, value)
temporary = [target, '.', char(java.util.UUID.randomUUID()), '.tmp'];
fid = fopen(temporary, 'w');
if fid < 0, error('无法写入：%s', temporary); end
fwrite(fid, jsonencode(value), 'char');
fclose(fid);
movefile(temporary, target, 'f');
end

function writeTextAtomic(target, value)
temporary = [target, '.', char(java.util.UUID.randomUUID()), '.tmp'];
fid = fopen(temporary, 'w');
if fid < 0, error('无法写入：%s', temporary); end
fwrite(fid, value, 'char');
fclose(fid);
movefile(temporary, target, 'f');
end
