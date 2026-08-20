"""
MATLAB MCP Server — 占位接口

MCP 服务器负责桥接 Agent（Python）和 MATLAB 引擎。
提供标准化的工具调用接口，Agent 无需关心 MATLAB 内部细节。

工具列表（待实现）：
1. matlab.run_task(task_json)        — 运行实验任务，返回 result.json
2. matlab.compile_mex(source)        — 编译 CUDA MEX
3. matlab.validate_plugin(plugin_id) — 运行插件验证套件
4. matlab.gradient_check(plugin_id)  — 有限差分梯度检查
5. matlab.status()                   — 查询 MATLAB/CUDA 环境状态

使用方式（Agent视角）：
```python
result = await mcp.call_tool("matlab.run_task", {
    "task_json": "/path/to/task.json"
})
```

注意：当前为接口占位，实际调用需要 MATLAB Engine API。
"""