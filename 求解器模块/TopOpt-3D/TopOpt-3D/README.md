# TopOpt-3D：简要代码与运行说明

## 1. 功能概述

本程序用于三维密度拓扑优化：在给定材料体积分数下，使结构柔顺度最小，即获得更高刚度的材料分布。程序包含三维有限元分析、SIMP 材料插值、灵敏度滤波、增强最优性准则法（OC）更新，以及最终的 Von Mises 应力热力图。

支持的工况：

- `cantilever`：三维悬臂梁；
- `MBB`：三维半对称 MBB 梁；
- `simply_supported`：三维简支梁；
- `L-bracket`：沿 z 方向挤出的三维 L 形支架；
- `custom`：用户自行指定载荷和约束。

## 2. 主要文件

| 文件 | 功能 |
|---|---|
| `topopt3d_main.m` | 主程序：组织优化迭代、默认参数和结果输出 |
| `FE_solver_3d.m` | 三维有限元求解器，处理刚度组装、载荷和边界条件 |
| `lk_3d.m` | 八节点六面体单元刚度矩阵 |
| `filter_solver_3d.m`、`check_3d.m` | 三维球形邻域灵敏度滤波 |
| `OC_solver_3d.m` | 增强 OC 密度更新、体积约束和掩码控制 |
| `build_boundary_solid_mask_3d.m` | 保留支撑和加载位置的实体垫块 |
| `compute_von_mises_3d.m` | 计算八个高斯点处的 Von Mises 应力 |
| `plot_stress_heatmap_3d.m` | 绘制材料表面的应力热力图 |

## 3. 默认高精度三维悬臂梁运行

在 MATLAB 命令窗口输入：

```matlab
addpath('F:\Other\揭榜挂帅\code\拓扑优化\TopOpt-3D');

config = struct();
config.bc_type = 'cantilever';
config.accuracy = 'high';

result = topopt3d_main(config);
```

也可直接运行：

```matlab
result = topopt3d_main();
```

无参调用默认即为高精度三维悬臂梁。

## 4. 自定义参数示例

```matlab
config = struct();
config.bc_type = 'cantilever';
config.accuracy = 'high';

config.nelx = 48;       % x 方向单元数
config.nely = 16;       % y 方向单元数
config.nelz = 12;       % z 方向单元数
config.volfrac = 0.4;   % 材料体积分数
config.penal = 3.0;     % 最终惩罚因子
config.rmin = 1.5;      % 滤波半径
config.max_iterations = 180;

result = topopt3d_main(config);
```

已传入的字段优先于默认值。网格越细，结果和应力分布越精细，但内存占用和计算时间也会增加。

## 5. 输出结果

运行结束后，变量 `result` 包含：

```matlab
result.x              % 最终三维密度场
result.objective      % 最终柔顺度
result.volume_fraction% 实际体积分数
result.von_mises      % 单元 Von Mises 应力
result.stress         % 六个应力分量
result.U              % 节点位移向量
```

当 `config.display = true`（默认）时，程序会显示：

1. 三维材料密度等值面；
2. 同一构型表面的 Von Mises 受力热力图。

如需单独绘制热力图：

```matlab
plot_stress_heatmap_3d(result);
```

## 6. 快速验证

运行短迭代测试：

```matlab
test_topopt3d_smoke
```

该测试覆盖 MBB、悬臂梁、简支梁、L 形支架和自定义工况。
