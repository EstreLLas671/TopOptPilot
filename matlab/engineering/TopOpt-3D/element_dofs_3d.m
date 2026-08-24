function edof = element_dofs_3d(elx, ely, elz, nely, nelx)
%ELEMENT_DOFS_3D 返回一个 8 节点六面体单元的 24 个全局自由度编号。
%   单元数组的存储顺序为 x(ely,elx,elz)，物理坐标中 y 为竖直方向。

n1 = node_id(elx-1, ely-1, elz-1, nely, nelx);
n2 = node_id(elx,   ely-1, elz-1, nely, nelx);
n3 = node_id(elx,   ely,   elz-1, nely, nelx);
n4 = node_id(elx-1, ely,   elz-1, nely, nelx);
n5 = node_id(elx-1, ely-1, elz,   nely, nelx);
n6 = node_id(elx,   ely-1, elz,   nely, nelx);
n7 = node_id(elx,   ely,   elz,   nely, nelx);
n8 = node_id(elx-1, ely,   elz,   nely, nelx);
nodes = [n1 n2 n3 n4 n5 n6 n7 n8];

edof = zeros(24, 1);
for index = 1:8
    edof(3*index-2 : 3*index) = 3*nodes(index)-2 : 3*nodes(index);
end
end

function node = node_id(ix, iy, iz, nely, nelx)
node = iy + 1 + (nely + 1)*ix + (nely + 1)*(nelx + 1)*iz;
end
