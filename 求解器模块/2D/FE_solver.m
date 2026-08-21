
function [U, K, freedofs, fixeddofs] = FE_solver(nelx, nely, x, penal, bc_config)

    % ===== 1. 计算单元刚度矩阵 =====
    [KE] = lk_matrix();                        % 四节点四边形单元的8×8刚度矩阵

    % ===== 2. 组装全局刚度矩阵 =====
    ndof = 2 * (nelx + 1) * (nely + 1);        % 总自由度数 = 节点数 × 2
    K = sparse(ndof, ndof);                    % 稀疏矩阵（大多数元素为零）
    F = sparse(ndof, 1);                       % 全局力向量
    U = zeros(ndof, 1);                        % 全局位移向量

    for elx = 1:nelx                           % 遍历x方向每个单元
        for ely = 1:nely                       % 遍历y方向每个单元
            % 当前单元左下和右下节点的编号
            n1 = (nely + 1) * (elx - 1) + ely;      % 左下节点
            n2 = (nely + 1) * elx       + ely;      % 右下节点

            % 该单元8个自由度的编号（每个节点x,y两个自由度）
            % 顺序：左下(x,y) 右下(x,y) 右上(x,y) 左上(x,y)
            edof = [2*n1-1; 2*n1; 2*n2-1; 2*n2; ...
                    2*n2+1; 2*n2+2; 2*n1+1; 2*n1+2];

            % SIMP插值：单元刚度按 x^penal 缩放后叠加进全局刚度矩阵
            K(edof, edof) = K(edof, edof) + x(ely, elx)^penal * KE;
        end
    end

    % ===== 3. 根据bc_type施加边界条件（载荷和约束） =====
    bc_type = bc_config.bc_type;

    switch bc_type
        case 'MBB'
            % ===== MBB梁（半对称模型）=====
            % 物理场景：两端支撑的梁，中点受力，利用左右对称只模拟右半部分
            % 边界条件设置：
            %   - 左边界（对称面）：只固定x方向（可上下滑动，不可左右移动，
            %     模拟对称面上的水平约束），即固定奇数编号自由度 1,3,5,...,
            %     共 nely+1 个节点
            %   - 右下角节点：只固定y方向（简支，不可上下移动），即固定
            %     最后一个自由度 2*(nelx+1)*(nely+1)
            %   - 载荷：左上角第二个节点（节点2）的y方向，向下，大小1
            % 节点编号：左上角节点=1（elx=1,ely=1时n1=1），
            % 其y自由度=2，F(2,1)=-1 即向下单位力
            fixeddofs = [1:2:2*(nely+1)];                  % 左边界x方向全部固定
            fixeddofs = union(fixeddofs, 2*(nelx+1)*(nely+1));  % 右下角y固定
            F(2, 1) = -1;                                  % 左上角向下单位力

        case 'cantilever'
            % ===== 悬臂梁 =====
            % 物理场景：一端固定在墙上、一端悬空的梁，如阳台、吊臂、机翼
            % 边界条件设置：
            %   - 左边界：所有自由度全部固定（x和y方向都锁死，
            %     模拟"焊死在墙上"），即固定自由度 1:2*(nely+1)，
            %     包括左边界全部节点的x和y自由度
            %   - 载荷：右下角节点（自由端）的y方向，向下，大小1
            % 节点编号：右下角节点 = (nelx+1)*(nely+1)（最后一列最底部），
            % 其y自由度 = 2*(nelx+1)*(nely+1) = 全局最后一个自由度
            fixeddofs = 1 : 2*(nely+1);                    % 左边界全部自由度固定
            load_dof = 2 * (nelx + 1) * (nely + 1);        % 右下角y自由度
            F(load_dof, 1) = -1;                           % 右下角向下单位力

        case 'L-bracket'
            % ===== L型支架 =====
            % 物理场景：L形角支架，顶部固定在墙上/天花板上，侧面承受水平力，
            % 如管道支架、设备安装座
            % 边界条件设置：
            %   - 顶部边界：全部节点的x和y自由度都固定（模拟螺栓固定）
            %   - 载荷：右侧边中点的x方向，向右，大小1
            % 注意：纯矩形网格无法直接表示L形！需配合非设计域使用：
            %   将左上角区域的密度固定为极小值（如0.001），优化时该区域
            %   永远不会变成实体，自然形成L形的空角。非设计域机制由
            %   主循环/滤波模块配合实现（原版99行代码没有，需新增）
            % 顶部节点编号：第i列顶部节点 = (nely+1)*i + (nely+1)，i=0..nelx
            fixeddofs = [];
            for i = 0:nelx
                node_top = (nely + 1) * i + (nely + 1);    % 第i+1列顶部节点
                fixeddofs = [fixeddofs, 2*node_top-1, 2*node_top];  % x和y都固定
            end
            % 右侧边中点：第nelx+1列（最右列），y方向正中间的节点
            right_mid_node = (nely + 1) * nelx + ceil((nely + 1) / 2);
            F(2*right_mid_node - 1, 1) = 1;                % 水平向右单位力

        case 'simply_supported'
            % ===== 简支梁 =====
            % 物理场景：梁两端搁在支座上，可自由转动，如楼板搭在承重墙上
            % 边界条件设置：
            %   - 左下角节点（节点1）：铰支座，x和y都固定
            %     （位置锁定但可转动）
            %   - 右下角节点：滚动支座，只固定y方向
            %     （不能上下掉下去，但允许x方向自由滑动，适应热胀冷缩）
            %   - 载荷：顶部中点节点的y方向，向下，大小1
            % 节点编号：右下角节点 = (nelx+1)*(nely+1)，
            % 其y自由度 = 2*(nelx+1)*(nely+1)
            % 顶部中点：x=nelx/2处（第nelx/2+1列）的顶部节点
            fixeddofs = [1, 2];                            % 左下角x和y都固定
            fixeddofs = [fixeddofs, 2*(nelx+1)*(nely+1)];  % 右下角只固定y
            top_mid_node = (nely+1)*round(nelx/2) + (nely+1);  % 顶部中点节点
            F(2 * top_mid_node, 1) = -1;                   % 顶部中点向下单位力

        case 'custom'
            % ===== 完全自定义工况 =====
            % 用户传入任意载荷和约束，可描述任意二维弹性力学问题
            % bc_config.loads:    [n×3] 每行 [节点号, 方向(1=x,2=y), 力值]
            % bc_config.fixeddofs: [1×m] 固定自由度编号列表
            % 示例：分布式载荷（右边界10个节点各施加向下0.1的力）
            %   bc.loads = [];
            %   for i = 1:10
            %       node_id = (nely+1)*nelx + i;
            %       bc.loads = [bc.loads; node_id, 2, -0.1];
            %   end
            fixeddofs = bc_config.fixeddofs;               % 直接使用用户传入的约束

            for i = 1:size(bc_config.loads, 1)
                node_id   = bc_config.loads(i, 1);         % 节点编号
                dof_dir   = bc_config.loads(i, 2);         % 方向（1=x, 2=y）
                force_val = bc_config.loads(i, 3);         % 力值
                dof_idx = 2 * (node_id - 1) + dof_dir;     % 节点编号转自由度编号
                F(dof_idx, 1) = force_val;                 % 施加力
            end

        otherwise
            error('未知的边界条件类型: %s。支持: MBB, cantilever, L-bracket, simply_supported, custom', bc_type);
    end

    % ===== 4. 求解线性系统 K*u = F =====
    alldofs  = 1 : ndof;                       % 全部自由度
    freedofs = setdiff(alldofs, fixeddofs);    % 自由自由度 = 全部 - 固定

    % 只对自由自由度求解（固定自由度的位移已知为零）
    U(freedofs, :) = K(freedofs, freedofs) \ F(freedofs, :);
    U(fixeddofs, :) = 0;                       % 固定自由度位移强制为零

end



function [KE] = lk_matrix()
    E  = 1.0;                                % 杨氏模量
    nu = 0.3;                                % 泊松比

    % 刚度矩阵的8个独立分量（利用单元几何和材料对称性）
    k = [1/2-nu/6,   1/8+nu/8,  -1/4-nu/12, -1/8+3*nu/8, ...
         -1/4+nu/12, -1/8-nu/8,   nu/6,       1/8-3*nu/8];

    % 组装完整的8×8单元刚度矩阵
    KE = E / (1 - nu^2) * [
        k(1) k(2) k(3) k(4) k(5) k(6) k(7) k(8);
        k(2) k(1) k(8) k(7) k(6) k(5) k(4) k(3);
        k(3) k(8) k(1) k(6) k(7) k(4) k(5) k(2);
        k(4) k(7) k(6) k(1) k(8) k(3) k(2) k(5);
        k(5) k(6) k(7) k(8) k(1) k(2) k(3) k(4);
        k(6) k(5) k(4) k(3) k(2) k(1) k(8) k(7);
        k(7) k(4) k(5) k(2) k(3) k(8) k(1) k(6);
        k(8) k(3) k(2) k(5) k(4) k(7) k(6) k(1)];
end
