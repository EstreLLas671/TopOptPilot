function dcn = check(nelx, nely, rmin, x, dc, domainMask)
%CHECK Mesh-independency sensitivity filter from the 99-line code.
%   dcn = CHECK(nelx,nely,rmin,x,dc) is backward compatible with the
%   original rectangular-domain implementation.
%
%   dcn = CHECK(nelx,nely,rmin,x,dc,domainMask) additionally supports an
%   irregular or custom design domain. Only elements for which domainMask
%   is true participate in the filter. Sensitivities outside the domain
%   are returned as zero.
%
%   For a full domain, the numerical formula is unchanged from Ole
%   Sigmund's educational 99-line topology optimization code.

if nargin < 6 || isempty(domainMask)
    domainMask = true(nely, nelx);
end

validateattributes(nelx, {'numeric'}, {'scalar','integer','positive'});
validateattributes(nely, {'numeric'}, {'scalar','integer','positive'});
validateattributes(rmin, {'numeric'}, {'scalar','real','finite','positive'});
validateattributes(x, {'numeric'}, {'real','finite','size',[nely,nelx]});
validateattributes(dc, {'numeric'}, {'real','finite','size',[nely,nelx]});
validateattributes(domainMask, {'logical','numeric'}, {'size',[nely,nelx]});
domainMask = logical(domainMask);

if any(x(domainMask) <= 0)
    error('check:NonPositiveActiveDensity', ...
        'Density x must be positive on every active design element.');
end

dcn = zeros(nely, nelx);
for i = 1:nelx
    for j = 1:nely
        if ~domainMask(j,i)
            continue;
        end

        weightSum = 0.0;
        for k = max(i-floor(rmin), 1):min(i+floor(rmin), nelx)
            for l = max(j-floor(rmin), 1):min(j+floor(rmin), nely)
                if ~domainMask(l,k)
                    continue;
                end

                fac = rmin - sqrt((i-k)^2 + (j-l)^2);
                weight = max(0, fac);
                weightSum = weightSum + weight;
                dcn(j,i) = dcn(j,i) + weight*x(l,k)*dc(l,k);
            end
        end

        dcn(j,i) = dcn(j,i)/(x(j,i)*weightSum);
    end
end
end
