function dcn = check_3d(nelx, nely, nelz, rmin, x, dc, domainMask)
%CHECK_3D 三维球形邻域灵敏度滤波。
%   采用经典 99 行代码的加权灵敏度滤波形式，并只在 domainMask 的
%   有效设计域内传播灵敏度，从而避免 L 形缺角等非设计区域的影响。

if nargin < 7 || isempty(domainMask)
    domainMask = true(nely, nelx, nelz);
end
validateattributes(rmin, {'numeric'}, {'scalar','real','finite','positive'});
validateattributes(x, {'numeric'}, {'real','finite','size',[nely,nelx,nelz]});
validateattributes(dc, {'numeric'}, {'real','finite','size',[nely,nelx,nelz]});
validateattributes(domainMask, {'logical','numeric'}, ...
    {'size',[nely,nelx,nelz]});
domainMask = logical(domainMask);

dcn = zeros(nely, nelx, nelz);
radiusFloor = floor(rmin);

for iz = 1:nelz
    for ix = 1:nelx
        for iy = 1:nely
            if ~domainMask(iy, ix, iz)
                continue;
            end

            weightSum = 0.0;
            weightedSensitivity = 0.0;
            for kz = max(1, iz-radiusFloor):min(nelz, iz+radiusFloor)
                for kx = max(1, ix-radiusFloor):min(nelx, ix+radiusFloor)
                    for ky = max(1, iy-radiusFloor):min(nely, iy+radiusFloor)
                        if ~domainMask(ky, kx, kz)
                            continue;
                        end
                        distance = sqrt((ix-kx)^2 + (iy-ky)^2 + ...
                            (iz-kz)^2);
                        weight = max(0.0, rmin-distance);
                        if weight <= 0
                            continue;
                        end
                        weightSum = weightSum + weight;
                        weightedSensitivity = weightedSensitivity + ...
                            weight * x(ky,kx,kz) * dc(ky,kx,kz);
                    end
                end
            end
            dcn(iy,ix,iz) = weightedSensitivity / ...
                max(x(iy,ix,iz) * weightSum, eps);
        end
    end
end
end
