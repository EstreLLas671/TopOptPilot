"""
CUDA MEX Solver MCP Server — 占位接口

封装 CUDA MEX 求解器的完整生命周期（参照方案 §6.3）：

1. solver.create(model, boundary, options)  — 创建求解上下文（网格常驻显存）
2. solver.analyze(handle, density, material) — 执行一轮 Matrix-free FEA
3. solver.destroy(handle)                     — 释放显存

handle 管理（方案 §6.3）：
- create 只执行一次，网格/节点映射/多重网格层级常驻显存
- analyze 每轮仅传入密度与材料
- 完整位移场仅在指定轮次返回，避免不必要数据搬运

MCP 工具接口（待实现）：
```python
# 创建
handle = await mcp.call_tool("solver.create", {
    "model": {...}, "boundary": {...}, "options": {...}
})

# 分析
result = await mcp.call_tool("solver.analyze", {
    "handle_id": "h_001", "density": [...], "material": {...}
})

# 销毁
await mcp.call_tool("solver.destroy", {"handle_id": "h_001"})
```
"""