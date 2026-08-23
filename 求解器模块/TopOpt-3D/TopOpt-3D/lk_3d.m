function KE = lk_3d(E, nu)
%LK_3D 返回单位立方体八节点六面体单元的 24×24 刚度矩阵。
%   材料采用三维各向同性线弹性模型：E=1，nu=0.3。使用 2×2×2
%   高斯积分，并将自然坐标单元 [-1,1]^3 映射至边长为 1 的物理单元。

if nargin < 1 || isempty(E), E = 1.0; end
if nargin < 2 || isempty(nu), nu = 0.3; end

% 三维各向同性弹性矩阵，工程剪切应变记号 [exx eyy ezz gxy gyz gzx]。
D = E / ((1 + nu) * (1 - 2 * nu)) * [ ...
    1-nu, nu,   nu,   0,              0,              0; ...
    nu,   1-nu, nu,   0,              0,              0; ...
    nu,   nu,   1-nu, 0,              0,              0; ...
    0,    0,    0,    (1-2*nu)/2,     0,              0; ...
    0,    0,    0,    0,              (1-2*nu)/2,     0; ...
    0,    0,    0,    0,              0,              (1-2*nu)/2];

% 节点顺序：
% 1(-,-,-), 2(+,-,-), 3(+,+,-), 4(-,+,-),
% 5(-,-,+), 6(+,-,+), 7(+,+,+), 8(-,+,+)。
nodeSigns = [-1 -1 -1; 1 -1 -1; 1 1 -1; -1 1 -1; ...
             -1 -1 1;  1 -1 1;  1 1 1;  -1 1 1];
gaussPoints = [-1, 1] / sqrt(3);

% 单位立方体的雅可比矩阵 J=0.5I，det(J)=1/8。
invJ = 2 * eye(3);
detJ = 1 / 8;
KE = zeros(24, 24);

for xi = gaussPoints
    for eta = gaussPoints
        for zeta = gaussPoints
            dNnatural = zeros(8, 3);
            for node = 1:8
                sx = nodeSigns(node, 1);
                sy = nodeSigns(node, 2);
                sz = nodeSigns(node, 3);
                dNnatural(node, 1) = sx * (1 + sy*eta) ...
                    * (1 + sz*zeta) / 8;
                dNnatural(node, 2) = sy * (1 + sx*xi) ...
                    * (1 + sz*zeta) / 8;
                dNnatural(node, 3) = sz * (1 + sx*xi) ...
                    * (1 + sy*eta) / 8;
            end

            dN = dNnatural * invJ;
            B = zeros(6, 24);
            for node = 1:8
                cols = 3*node-2 : 3*node;
                dNx = dN(node, 1);
                dNy = dN(node, 2);
                dNz = dN(node, 3);
                B(:, cols) = [dNx, 0,   0; ...
                              0,   dNy, 0; ...
                              0,   0,   dNz; ...
                              dNy, dNx, 0; ...
                              0,   dNz, dNy; ...
                              dNz, 0,   dNx];
            end
            KE = KE + B' * D * B * detJ;
        end
    end
end

% 消除浮点积分引起的极小非对称误差。
KE = (KE + KE') / 2;
end
