function generate_case_previews(outputRoot)
%GENERATE_CASE_PREVIEWS Generate authentic small MATLAB case preview assets.
% The generated files are consumed by the desktop parameter dialog.  Every
% frame is produced by the same solver bridge used for engineering runs.
if nargin < 1 || isempty(outputRoot)
    outputRoot = fullfile(fileparts(mfilename('fullpath')), 'case-previews');
end
if ~isfolder(outputRoot), mkdir(outputRoot); end
cases = {'2d','3d'};
bcTypes = {'cantilever','MBB','simply_supported','L-bracket'};
entries = {};
for d = 1:numel(cases)
    for b = 1:numel(bcTypes)
        dimension = cases{d}; bc = bcTypes{b};
        name = sprintf('%s-%s', dimension, lower(strrep(bc, '-', '_')));
        target = fullfile(outputRoot, name);
        if ~isfolder(target), mkdir(target); end
        cfg = struct('solver_dimension',dimension,'bc_type',bc,'accuracy','standard', ...
            'nelx',16,'nely',6,'nelz',4,'volfrac',0.4,'penal',3,'rmin',1.5, ...
            'min_iterations',8,'max_iterations',24,'display',false,'verbose',false, ...
            'render_iteration_frames',true,'live_stress_snapshots',true, ...
            'material_preset','normalized','material_name','归一化参考材料', ...
            'E',1,'nu',0.3,'density_kg_m3',1,'yield_strength_MPa',1);
        cfgPath = fullfile(target, 'config.json');
        fid = fopen(cfgPath,'w','n','UTF-8'); fprintf(fid,'%s',jsonencode(cfg)); fclose(fid);
        run_topopt_job(cfgPath, target);
        snap = jsondecode(fileread(fullfile(target,'snapshots','manifest.json')));
        frame = snap.frames(end);
        copyfile(fullfile(target,'snapshots',frame.density_file), fullfile(target,'density.bin'));
        if ~isempty(frame.stress_file)
            copyfile(fullfile(target,'snapshots',frame.stress_file), fullfile(target,'stress.bin'));
        else
            copyfile(fullfile(target,'density.bin'), fullfile(target,'stress.bin'));
        end
        renderPath = '';
        if ~isempty(frame.render_file)
            renderPath = fullfile(target, frame.render_file);
            copyfile(fullfile(target,'snapshots',frame.render_file), renderPath);
        end
        meta = struct('dimension',dimension,'bcType',bc,'shape',snap.shape, ...
            'order','F','dtype','float32','source','MATLAB TopOptPilot case preview', ...
            'config',cfg,'configDigest',simple_digest(jsonencode(cfg)), ...
            'densityPath',sprintf('%s/density.bin',name), ...
            'stressPath',sprintf('%s/stress.bin',name), ...
            'renderPath',sprintf('%s/%s',name,frame.render_file));
        mf = fopen(fullfile(target,'metadata.json'),'w','n','UTF-8'); fprintf(mf,'%s',jsonencode(meta)); fclose(mf);
        entries{end+1} = meta; %#ok<AGROW>
    end
end
fid = fopen(fullfile(outputRoot,'manifest.json'),'w','n','UTF-8'); fprintf(fid,'%s',jsonencode(struct('version',1,'source','MATLAB TopOptPilot case preview','cases',{entries}))); fclose(fid);
end

function digest = simple_digest(text)
% Stable non-cryptographic fallback used only as a preview identifier.
v = uint32(2166136261); bytes = uint8(text);
for i=1:numel(bytes), v = bitxor(v,uint32(bytes(i))); v = uint32(mod(uint64(v)*16777619,2^32)); end
digest = lower(dec2hex(v,8));
end

