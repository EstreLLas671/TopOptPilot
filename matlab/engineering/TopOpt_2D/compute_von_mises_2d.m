function [vonMises, stress] = compute_von_mises_2d( ...
        nelx, nely, x, penal, U, measure, E, nu)
%COMPUTE_VON_MISES_2D Compute true plane-stress von Mises values per element.
%   The stress uses the same SIMP effective modulus as FE_solver. Values are
%   evaluated at the four Gauss points of each unit bilinear quadrilateral.

if nargin < 6 || isempty(measure), measure = 'gauss_max'; end
if nargin < 7 || isempty(E), E = 1.0; end
if nargin < 8 || isempty(nu), nu = 0.3; end
validateattributes(E, {'numeric'}, {'real','finite','scalar','positive'});
validateattributes(nu, {'numeric'}, {'real','finite','scalar','>',-1,'<',0.5});
validateattributes(x, {'numeric'}, {'real','finite','size',[nely,nelx]});
measure = lower(char(string(measure)));
if ~ismember(measure, {'gauss_max','gauss_mean'})
    error('compute_von_mises_2d:UnknownMeasure', ...
        'stress_measure 仅支持 gauss_max 或 gauss_mean。');
end

D0 = E / (1-nu^2) * [1, nu, 0; nu, 1, 0; 0, 0, (1-nu)/2];
gauss = [-1, 1] / sqrt(3);
Bmatrices = cell(4,1);
index = 0;
for xi = gauss
    for eta = gauss
        index = index + 1;
        Bmatrices{index} = B_at_natural_coordinate(xi, eta);
    end
end
vonMises = zeros(nely, nelx);
stress = zeros(nely, nelx, 3);
for elx = 1:nelx
    for ely = 1:nely
        n1 = (nely+1)*(elx-1) + ely;
        n2 = (nely+1)*elx + ely;
        edof = [2*n1-1; 2*n1; 2*n2-1; 2*n2; ...
                2*n2+1; 2*n2+2; 2*n1+1; 2*n1+2];
        Eeff = x(ely,elx)^penal;
        sigmaAtGauss = zeros(3,4);
        vmAtGauss = zeros(4,1);
        for point = 1:4
            sigma = Eeff * D0 * Bmatrices{point} * U(edof);
            sigmaAtGauss(:,point) = sigma;
            vmAtGauss(point) = sqrt(sigma(1)^2 - sigma(1)*sigma(2) ...
                + sigma(2)^2 + 3*sigma(3)^2);
        end
        switch measure
            case 'gauss_max'
                [vonMises(ely,elx), selected] = max(vmAtGauss);
                stress(ely,elx,:) = reshape(sigmaAtGauss(:,selected),1,1,3);
            case 'gauss_mean'
                stress(ely,elx,:) = reshape(mean(sigmaAtGauss,2),1,1,3);
                vonMises(ely,elx) = mean(vmAtGauss);
        end
    end
end
end

function B = B_at_natural_coordinate(xi, eta)
% Unit square node order: lower-left, lower-right, upper-right, upper-left.
dNdx = 0.5 * [-(1-eta), (1-eta), (1+eta), -(1+eta)];
dNdy = 0.5 * [-(1-xi), -(1+xi), (1+xi), (1-xi)];
B = zeros(3,8);
for node = 1:4
    cols = 2*node-1 : 2*node;
    B(:,cols) = [dNdx(node), 0; 0, dNdy(node); dNdy(node), dNdx(node)];
end
end