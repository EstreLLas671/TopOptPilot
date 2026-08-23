# MATLAB 求解器参数与保真度

`volfrac` 是目标材料体积分数；`penal` 控制中间密度惩罚；`rmin` 是滤波半径；`beta` 用于投影锐化；`max_iter` 是迭代上限。参数必须由 Policy 在安全范围内编译。

F0 为 MATLAB 2D 粗网格，F1 为 MATLAB 2D 精细网格，F2 为 MATLAB 3D 粗网格，F3 为 MATLAB 3D 高精度。F3 必须人工批准。正式实验不允许 Python 求解回退。
