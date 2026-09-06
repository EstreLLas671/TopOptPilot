# MATLAB 求解器参数与保真度

`volfrac` 是目标材料体积分数；`penal` 控制中间密度惩罚；`rmin` 是滤波半径；`beta` 用于投影锐化；`max_iter` 是迭代上限。参数必须由 Policy 在安全范围内编译。

Step1 为 Python 2D 粗网络，Step2 为 Python 2D 自适应粗网络，Step3 为 Python 3D 粗网络，Step4 为 MATLAB 3D 真实网络。每次只运行一个实验并在结果弹窗等待人工选择；Step4 不允许 Python 求解回退。
