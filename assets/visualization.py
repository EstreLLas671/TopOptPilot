"""
可视化工具

参照方案 §9.2 指标呈现建议：
- 收敛曲线 + 相对变化
- 灰度比例随迭代曲线
- PCG次数/残差曲线
- 结构前后对比
- 位移/应力云图（独立FEM复核）
"""

from pathlib import Path


class Visualizer:
    """结果可视化器（接口占位，实际使用 matplotlib + NIfTI 渲染）"""

    def __init__(self, output_dir: str = "experiments/output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def plot_convergence(self, history: list, title: str = "收敛曲线",
                         save_path: str = None):
        """绘制收敛曲线"""
        try:
            import matplotlib.pyplot as plt
            plt.figure(figsize=(8, 5))
            plt.plot(history, linewidth=1.5)
            plt.xlabel("Iteration")
            plt.ylabel("Compliance")
            plt.title(title)
            plt.grid(True, alpha=0.3)
            save_path = save_path or str(self.output_dir / "convergence.png")
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            plt.close()
            return save_path
        except ImportError:
            return "[matplotlib not installed]"

    def plot_metrics(self, iterations: list, gray_ratios: list,
                     cg_counts: list, save_path: str = None):
        """多指标对比图"""
        try:
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(1, 3, figsize=(15, 4))

            axes[0].plot(iterations, gray_ratios)
            axes[0].set_xlabel("Iteration")
            axes[0].set_ylabel("Gray Ratio")
            axes[0].set_title("灰度比例")
            axes[0].grid(True, alpha=0.3)

            axes[1].plot(iterations, cg_counts)
            axes[1].set_xlabel("Iteration")
            axes[1].set_ylabel("CG Iterations")
            axes[1].set_title("求解难度")
            axes[1].grid(True, alpha=0.3)

            axes[2].axis('off')
            axes[2].text(0.5, 0.5, "3D结构渲染\n(待实现)", ha='center', va='center')

            plt.tight_layout()
            save_path = save_path or str(self.output_dir / "metrics.png")
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            plt.close()
            return save_path
        except ImportError:
            return "[matplotlib not installed]"

    def render_3d_structure(self, density_field, threshold=0.5):
        """3D结构渲染（接口占位，实际使用 NIfTI + VTK）"""
        return {"status": "placeholder", "message": "3D渲染 - 待集成VTK/Mayavi"}