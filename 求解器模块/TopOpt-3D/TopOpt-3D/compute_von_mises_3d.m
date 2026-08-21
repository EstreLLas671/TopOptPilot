function [vonMises, stress] = compute_von_mises_3d( ...
        nelx, nely, nelz, x, penal, Emin, U, measure)
%COMPUTE_VON_MISES_3D 计算每个六面体单元高斯点处的 Von Mises 应力。
%   应力采用与 FE_solver_3d 相同的 SIMP 有效模量：
%   Eeff = Emin + (1-Emin)*x^penal。
%   输出 stress 的最后一维依次为 [sxx syy szz txy tyz tzx]。
%   measure 可为 gauss_max（默认，8 个高斯点最大值）或 gauss_mean。

if nargin < 8 || isempty(measure)
    measure = 'gauss_max';
end
validateattributes(x, {'numeric'}, {'real','finite','size',[nely,nelx,nelz]});
validateattributes(Emin, {'numeric'}, {'real','finite','scalar','>=',0,'<',1});

D0 = elastic_matrix_unit_modulus();
gauss = [-1, 1] / sqrt(3);
Bmatrices = cell(8,1);
index = 0;
for xi = gauss
    for eta = gauss
        for zeta = gauss
            index = index + 1;
            Bmatrices{index} = B_at_natural_coordinate(xi, eta, zeta);
        end
    end
end
measure = lower(char(string(measure)));
if ~ismember(measure, {'gauss_max','gauss_mean'})
    error('compute_von_mises_3d:UnknownMeasure', ...
        'stress_measure 仅支持 gauss_max 或 gauss_mean。');
end
vonMises = zeros(nely, nelx, nelz);
stress = zeros(nely, nelx, nelz, 6);

for elz = 1:nelz
    for elx = 1:nelx
        for ely = 1:nely
            edof = element_dofs_3d(elx, ely, elz, nely, nelx);
            Eeff = Emin + (1-Emin) * x(ely,elx,elz)^penal;
            sigmaAtGauss = zeros(6, 8);
            vmAtGauss = zeros(8, 1);
            for point = 1:8
                sigma = Eeff * D0 * Bmatrices{point} * U(edof);
                sigmaAtGauss(:,point) = sigma;
                vmAtGauss(point) = von_mises_from_stress(sigma);
            end
            switch measure
                case 'gauss_max'
                    [vonMises(ely,elx,elz), selected] = max(vmAtGauss);
                    stress(ely,elx,elz,:) = reshape( ...
                        sigmaAtGauss(:,selected), 1, 1, 1, 6);
                case 'gauss_mean'
                    stress(ely,elx,elz,:) = reshape( ...
                        mean(sigmaAtGauss, 2), 1, 1, 1, 6);
                    vonMises(ely,elx,elz) = mean(vmAtGauss);
            end
        end
    end
end
end

function D = elastic_matrix_unit_modulus()
nu = 0.3;
D = 1 / ((1+nu)*(1-2*nu)) * [ ...
    1-nu, nu,   nu,   0,              0,              0; ...
    nu,   1-nu, nu,   0,              0,              0; ...
    nu,   nu,   1-nu, 0,              0,              0; ...
    0,    0,    0,    (1-2*nu)/2,     0,              0; ...
    0,    0,    0,    0,              (1-2*nu)/2,     0; ...
    0,    0,    0,    0,              0,              (1-2*nu)/2];
end

function B = B_at_natural_coordinate(xi, eta, zeta)
% 单位立方体内指定自然坐标处的物理坐标 B 矩阵。
signs = [-1 -1 -1; 1 -1 -1; 1 1 -1; -1 1 -1; ...
         -1 -1 1; 1 -1 1; 1 1 1; -1 1 1];
B = zeros(6, 24);
for node = 1:8
    sx = signs(node,1);
    sy = signs(node,2);
    sz = signs(node,3);
    dNx = sx * (1+sy*eta) * (1+sz*zeta) / 4;
    dNy = sy * (1+sx*xi) * (1+sz*zeta) / 4;
    dNz = sz * (1+sx*xi) * (1+sy*eta) / 4;
    cols = 3*node-2 : 3*node;
    B(:,cols) = [dNx, 0,   0; ...
                 0,   dNy, 0; ...
                 0,   0,   dNz; ...
                 dNy, dNx, 0; ...
                 0,   dNz, dNy; ...
                 dNz, 0,   dNx];
end
end

function value = von_mises_from_stress(sigma)
value = sqrt(0.5*((sigma(1)-sigma(2))^2 + ...
    (sigma(2)-sigma(3))^2 + (sigma(3)-sigma(1))^2) + ...
    3*(sigma(4)^2 + sigma(5)^2 + sigma(6)^2));
end
