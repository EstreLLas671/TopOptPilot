# 工程文件遍历设计

本文定义桌面端 `project_list_summary` 的文件树遍历约束。它服务于
TopOptPilot 工程工作区的代码/结果浏览，不是通用文件索引器，也不提供任意
路径访问能力。

## 目标

打开含有 `node_modules`、MATLAB 输出、Rust `target` 或网络盘目录的工程时，
文件树必须保持可预测的资源上限，不得因为收集全部目录项而长期卡住界面。
同时，列出的文件不能通过符号链接或 Windows 重解析点逃出用户选择的工程根。

## 遍历模型

`desktop/src-tauri/src/project.rs` 使用下列模式：

1. 使用 Rust 标准库的 `fs::ReadDir`。它映射到操作系统的原生目录枚举接口，
   而非第三方递归 walker。
2. 每个 `ProjectDirectoryFrame` 保留一个惰性 `ReadDir`，每次只消费一个
   `next()` 结果；不将整个目录收集到 `Vec` 后再排序。
3. 使用显式 `Vec<ProjectDirectoryFrame>` 栈执行深度优先搜索（DFS）。没有递归
   调用，因此当前打开的枚举器数量始终可见、可限制。
4. 每个条目均通过 `symlink_metadata` 检查。符号链接和 Windows
   `FILE_ATTRIBUTE_REPARSE_POINT` 默认不跟随，而是安全跳过并计入
   `skippedLinks`。工程根本身也不能是此类入口。
5. `PROJECT_TRAVERSAL_GATE` 将所有窗口/网页视图同时进行的工程树扫描限制为
   **1**；单次遍历内部的文件系统操作也为串行。工程树浏览是交互路径，这可避免
   在慢磁盘或网络盘上用无界并发放大 I/O 争用；DFS 栈中的原生枚举器同时打开
   数量另有独立上限。

## 默认资源预算

| 项目 | 默认值 | 达到上限后的行为 |
| --- | ---: | --- |
| 支持文件数 | 2,000 | 停止遍历，返回 `truncated=true` |
| 目录深度 | 16 | 跳过更深子目录，返回 `truncated=true` |
| 单目录枚举项 | 4,096 | 剪枝该目录，返回 `truncated=true` |
| 已检查的目录项总数 | 10,000 | 停止遍历，返回 `truncated=true` |
| 同时打开的原生目录枚举器 | 17 | 剪枝下一层目录，返回 `truncated=true` |
| 同时进行的工程树扫描 / 文件系统操作 | 1 | 后续请求排队，不启动额外操作 |
| 编辑器读取文件大小 | 2 MiB | 拒绝读取，不加载到编辑器 |

生成/依赖目录（如 `.git`、`node_modules`、`.venv`、`target`、`dist`）在进入
前就被剪枝。只允许展示工程 API 白名单中的文本类扩展名。

已接收的文件会在返回前按相对路径排序，保证已列出的内容稳定展示；目录项本身
不预排序，以免破坏惰性枚举和剪枝效果。

## 用户可见结果

`ProjectListing` 除 `entries` 外返回：

- `truncated`：预算、深度或可读性限制令结果不完整；
- `skippedDirectories`：生成、依赖、过深、无法读取或受枚举器预算限制的目录；
- `skippedLinks`：被安全跳过的符号链接或 Windows 重解析点。

工程工作区会把这些状态显示为提示，不会将不完整扫描伪装成完整项目树。

## 回归保障

- Rust 单元测试覆盖支持文件上限、忽略目录、深度剪枝、总扫描项上限、打开
  枚举器上限、文件读取大小限制和 Windows junction 跳过。
- `tests/test_project_traversal_contract.py` 约束实现必须保留惰性原生枚举、显式
  DFS、链接防护和枚举器上限，防止以后又退回“先收集再递归”的实现。
- React 测试覆盖 `skippedLinks` 和受限扫描提示。
