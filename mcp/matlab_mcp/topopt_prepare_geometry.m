function preview = topopt_prepare_geometry(config, dimension)
%TOPOPT_PREPARE_GEOMETRY Build the design mask and UI node mapping in MATLAB.
% This controlled helper is shared by geometry preview and solve dispatch so
% the desktop never invents support/load locations independently.

bcType = lower(strrep(char(string(config.bc_type)), '_', '-'));
geometry = struct();
if isfield(config, 'geometry') && isstruct(config.geometry), geometry = config.geometry; end
loadScale = 1.0;
if isfield(config, 'bc_config') && isfield(config.bc_config, 'load_scale')
    loadScale = double(config.bc_config.load_scale);
end

if dimension == 2
    nelx = double(config.nelx); nely = double(config.nely);
    mask = make_mask_2d(nelx, nely, bcType, geometry, config);
    [supportNodes, loadNodes] = map_nodes_2d(nelx, nely, bcType, mask, loadScale);
    grid = [nelx nely];
else
    nelx = double(config.nelx); nely = double(config.nely); nelz = double(config.nelz);
    mask = make_mask_3d(nelx, nely, nelz, bcType, geometry, config);
    [supportNodes, loadNodes] = map_nodes_3d(nelx, nely, nelz, bcType, mask, loadScale);
    grid = [nelx nely nelz];
end
if ~any(mask(:)), error('TopOptPilot:EmptyMask', 'The MATLAB design mask is empty.'); end
preview = struct('dimension',dimension,'grid',grid,'domain_mask',logical(mask), ...
    'support_nodes',supportNodes,'load_nodes',loadNodes,'bc_type',bcType, ...
    'generated_by','MATLAB','coordinate_convention','zero_based_grid_coordinates');
end

function mask = make_mask_2d(nelx, nely, bcType, geometry, config)
if isfield(config,'domain_mask') && ~isempty(config.domain_mask)
    mask = logical(config.domain_mask);
    validateattributes(mask, {'logical'}, {'size',[nely nelx]}); return;
end
mask = true(nely,nelx);
kind = geometry_kind(geometry, bcType);
if any(strcmp(kind, {'l-bracket','l-shaped','l'}))
    mask(1:ceil(nely/2), floor(nelx/2)+1:end) = false;
elseif strcmp(kind,'bridge')
    [xx,yy] = meshgrid(linspace(-1,1,nelx),linspace(0,1,nely));
    opening = yy > (0.22 + 0.48*(1-xx.^2));
    mask(opening & abs(xx)<0.78) = false;
end
end

function mask = make_mask_3d(nelx, nely, nelz, bcType, geometry, config)
if isfield(config,'domain_mask') && ~isempty(config.domain_mask)
    mask = logical(config.domain_mask);
    validateattributes(mask, {'logical'}, {'size',[nely nelx nelz]}); return;
end
base = make_mask_2d(nelx,nely,bcType,geometry,struct());
mask = repmat(base,1,1,nelz);
end

function kind = geometry_kind(geometry, fallback)
kind = fallback;
if isfield(geometry,'type') && ~isempty(geometry.type)
    kind = lower(strrep(char(string(geometry.type)),'_','-'));
end
end

function [supports, loads] = map_nodes_2d(nelx,nely,bcType,mask,scale)
node = @(ix,iy) iy+1+(nely+1)*ix;
switch bcType
    case 'mbb'
        ids = arrayfun(@(iy) node(0,iy),0:nely);
        supports = [node_rows_2d(ids,0:nely,zeros(size(ids))); node_rows_2d(node(nelx,nely),nely,nelx)];
        loads = load_row_2d(node(0,0),0,0,2,-scale);
    case 'cantilever'
        ids = arrayfun(@(iy) node(0,iy),0:nely);
        supports = node_rows_2d(ids,0:nely,zeros(size(ids)));
        loads = load_row_2d(node(nelx,nely),nelx,nely,2,-scale);
    case 'simply-supported'
        supports = [node_rows_2d(node(0,0),0,0); node_rows_2d(node(nelx,nely),nelx,nely)];
        loads = load_row_2d(node(round(nelx/2),nely),round(nelx/2),nely,2,-scale);
    case 'l-bracket'
        topCols = find(mask(1,:)); topCols = unique([topCols-1 topCols]);
        supports = node_rows_2d(arrayfun(@(ix) node(ix,0),topCols),zeros(size(topCols)),topCols);
        rightRows = find(mask(:,end)); iy = min(rightRows)-1;
        loads = load_row_2d(node(nelx,iy),nelx,iy,2,-scale);
    otherwise
        error('TopOptPilot:PreviewCustomBC', 'Custom boundary preview requires explicit controlled node data.');
end
end

function rows = node_rows_2d(ids,iy,ix)
ids=ids(:); ix=ix(:); iy=iy(:);
if isscalar(ix), ix=repmat(ix,size(ids)); end
if isscalar(iy), iy=repmat(iy,size(ids)); end
rows=[double(ids) double(ix) double(iy)];
end
function row = load_row_2d(id,ix,iy,direction,value), row=[double(id) ix iy direction value]; end

function [supports, loads] = map_nodes_3d(nelx,nely,nelz,bcType,~,scale)
node = @(ix,iy,iz) iy+1+(nely+1)*ix+(nely+1)*(nelx+1)*iz;
switch bcType
    case {'mbb','cantilever','l-bracket'}
        supports=[];
        for iz=0:nelz, for iy=0:nely, supports(end+1,:)=[node(0,iy,iz) 0 iy iz]; end, end %#ok<AGROW>
        if strcmp(bcType,'mbb'), ix=0; iy=nely; else, ix=nelx; iy=round(nely/2); end
        loads=[node(ix,iy,round(nelz/2)) ix iy round(nelz/2) 2 -scale];
    case 'simply-supported'
        supports=[node(0,0,0) 0 0 0; node(nelx,0,0) nelx 0 0; node(0,0,nelz) 0 0 nelz];
        loads=[node(round(nelx/2),nely,round(nelz/2)) round(nelx/2) nely round(nelz/2) 2 -scale];
    otherwise
        error('TopOptPilot:PreviewCustomBC', 'Custom boundary preview requires explicit controlled node data.');
end
end
