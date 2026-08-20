"""
MATLAB Engine Connector — MATLAB Engine API 封装

职责：
- 启动/关闭 MATLAB 会话
- 保持常驻会话（避免每轮启动开销）
- 统一异常处理（MEX崩溃 = MATLAB进程死 → 自动重启 + 日志）
- 路径转换（Python C:/path ↔ MATLAB C:\\path）

使用流程：
1. connector = MatlabConnector()
2. connector.start()          # 启动 MATLAB
3. connector.run("top3d_main", task_json)  # 调用主函数
4. result = connector.fetch_results()      # 获取结果
5. connector.stop()           # 关闭 MATLAB

注意：当前为占位，具体实现依赖 matlabengine pip 包。
"""