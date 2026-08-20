"""
MEX Handle Manager — CUDA MEX 句柄生命周期管理

参照方案 §6.3 MEX 边界：
- create 分配显存并持久化
- analyze 按轮调用
- destroy 释放资源
- mexLock + mexAtExit 防止异常泄漏

句柄表结构：
{
    "h_001": {
        "created_at": "2026-07-22T10:00:00",
        "handle_ptr": 0x7f...,
        "mesh_size": 200000,
        "gpu_memory_mb": 2400,
        "status": "active"  # active / destroyed / crashed
    }
}

注意：实际实现时需要与 CUDA MEX C++ 代码的句柄表同步。
"""