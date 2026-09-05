from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from solver.stress import stress_unit_metadata, von_mises_2d, von_mises_3d
from topoptpilot.evaluator.evaluator import evaluate_result
from topoptpilot.executor.executor import build_solver_task
from topoptpilot.reports.generator import ResearchReportGenerator
from topoptpilot.service.research_service import _density_surface_triangles


def test_real_q4_and_hex8_stress_are_finite_and_shape_preserving() -> None:
    density_2d = np.ones((1, 1))
    displacement_2d = np.array([0, 0, 0, 0, 1, 0, 1, 0], dtype=float)
    stress_2d = von_mises_2d(
        density_2d, displacement_2d, penal=3,
        youngs_modulus=200_000, poisson_ratio=.3,
    )
    assert stress_2d.shape == density_2d.shape
    assert np.isfinite(stress_2d).all() and float(stress_2d.max()) > 0

    density_3d = np.ones((1, 1, 1))
    displacement_3d = np.zeros(24)
    for node, x_coordinate in enumerate((0, 1, 1, 0, 0, 1, 1, 0)):
        displacement_3d[3 * node] = x_coordinate
    stress_3d = von_mises_3d(
        density_3d, displacement_3d, penal=3,
        youngs_modulus=200_000, poisson_ratio=.3,
    )
    assert stress_3d.shape == density_3d.shape
    assert np.isfinite(stress_3d).all() and float(stress_3d.max()) > 0


def test_stress_units_and_allowable_check_require_a_complete_chain() -> None:
    experiment = {"id": "E01", "mesh_level": "coarse", "parameters": {"volfrac": .4}}
    trusted_research = {
        "geometry": {"unit": "mm", "cell_size_mm": 1},
        "material": {"E_MPa": 200_000, "E_unit": "MPa"},
        "loads": [{"magnitude": 1000, "unit": "N"}],
        "constraints": {"volume_fraction": .4},
    }
    trusted_task = build_solver_task(experiment, trusted_research)
    assert stress_unit_metadata(trusted_task)["stress_unit"] == "MPa"
    incomplete_task = build_solver_task(experiment, {**trusted_research, "geometry": {}})
    assert stress_unit_metadata(incomplete_task)["stress_unit"] == "normalized"

    base = {
        "status": "converged", "objective": {"compliance": 1},
        "constraints": {"volume_fraction": .4},
        "quality": {"gray_ratio": 0, "connected_components": 1,
                    "maximum_von_mises": 120, "stress_unit": "normalized",
                    "stress_unit_trusted": False},
    }
    rejected = evaluate_result(base, {"volume_fraction": .4, "allowable_stress_mpa": 150})
    assert rejected["checks"]["stress"] is False
    trusted = {**base, "quality": {**base["quality"], "stress_unit": "MPa", "stress_unit_trusted": True}}
    accepted = evaluate_result(trusted, {"volume_fraction": .4, "allowable_stress_mpa": 150})
    assert accepted["checks"]["stress"] is True
    assert accepted["stress_margin"] == 30


def test_f3_solver_grid_cannot_override_confirmed_research_dimensions() -> None:
    experiment = {
        "id": "E-F3", "fidelity": "F3 — MATLAB 3D Formal", "mesh_level": "formal",
        "parameters": {"grid3d": [99, 99, 99], "volfrac": .4},
    }
    task = build_solver_task(experiment, {
        "geometry": {"dimensions": [12, 4, 2], "unit": "mm", "nelx": 24, "nely": 8, "nelz": 4},
        "constraints": {"volume_fraction": .4},
    })
    assert task["geometry"]["dimensions"] == [12, 4, 2]
    assert task["params"]["grid3d"] == [24, 8, 4]


def test_f3_density_surface_is_triangulated_in_configured_physical_dimensions() -> None:
    density = np.zeros((4, 8, 3), dtype=float)
    density[1:3, 1:7, 1:3] = 1.0
    triangles = _density_surface_triangles(density, [12.0, 4.0, 2.0])
    assert triangles and all(len(face) == 3 for face in triangles)
    points = np.asarray(triangles).reshape(-1, 3)
    assert np.all(points >= 0)
    assert np.all(points <= np.asarray([12.0, 4.0, 2.0]) + 1e-12)


def _report_images(directory: Path) -> dict[str, Path]:
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties

    directory.mkdir(parents=True, exist_ok=True)
    paths = {kind: directory / name for kind, name in {
        "TOPOLOGY_IMAGE": "topology.png", "STRESS_IMAGE": "stress.png",
        "CONVERGENCE_IMAGE": "convergence.png",
    }.items()}
    solid = np.zeros((8, 5, 4), dtype=bool)
    solid[:, 1:4, :] = True
    solid[2:6, 2:, 1:3] = False
    figure = plt.figure(figsize=(6, 4), dpi=120, facecolor="white")
    axis = figure.add_subplot(111, projection="3d")
    axis.voxels(solid, facecolors="#bdbdbd", edgecolor="#222222", linewidth=.2)
    axis.view_init(elev=24, azim=-54); axis.set_axis_off(); figure.tight_layout()
    figure.savefig(paths["TOPOLOGY_IMAGE"], facecolor="white", bbox_inches="tight"); plt.close(figure)
    figure, axis = plt.subplots(figsize=(6, 2.5), dpi=120, facecolor="white")
    axis.imshow(np.linspace(0, 1, 160).reshape(10, 16), cmap="gray", aspect="auto")
    axis.set_axis_off(); figure.tight_layout()
    figure.savefig(paths["STRESS_IMAGE"], facecolor="white", bbox_inches="tight"); plt.close(figure)
    figure, axis = plt.subplots(figsize=(6, 2.5), dpi=120, facecolor="white")
    axis.plot([1, 5, 10, 15, 20], [30, 22, 17, 14, 12.5], color="#111111")
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = FontProperties(fname=str(font_path)) if font_path.is_file() else None
    axis.set_xlabel("迭代" if font else "Iteration", fontproperties=font)
    axis.set_ylabel("柔度" if font else "Compliance", fontproperties=font)
    axis.grid(color="#bbbbbb", alpha=.5)
    figure.tight_layout(); figure.savefig(paths["CONVERGENCE_IMAGE"], facecolor="white", bbox_inches="tight"); plt.close(figure)
    return paths


def _report_research(images: dict[str, Path]) -> dict:
    result = {
        "objective": {"compliance": 12.5},
        "constraints": {"volume_fraction": .4},
        "quality": {"gray_ratio": .02, "connected_components": 1,
                    "maximum_von_mises": 120, "stress_unit": "MPa",
                    "stress_unit_trusted": True},
        "solver": {"iterations": 20, "solver_variant": "reference_cpu"},
        "evaluation": {"success": True, "checks": {"volume": True, "gray": True,
                                                      "connected": True, "stress": True}},
    }
    experiment = {"id": "E01", "round_number": 1, "status": "SUCCESS",
                  "fidelity": "F3", "parameters": {"volfrac": .4, "penal": 3,
                                                       "rmin": 1.5, "max_iter": 20},
                  "result": result}
    artifacts = []
    for kind in ("TOPOLOGY_IMAGE", "STRESS_IMAGE", "CONVERGENCE_IMAGE"):
        artifacts.append({"artifact_type": kind, "experiment_id": "E01",
                          "path": str(images[kind]), "sha256": "a" * 64})
    return {
        "id": "R-REPORT", "name": "三维结构优化", "goal": "在真实工况下最小化柔度",
        "hypothesis": "滤波与惩罚策略可降低灰度率", "locale": "zh-CN",
        "current_round": 1, "experiments": [experiment], "best_experiment": experiment,
        "hypotheses": [], "subagent_tasks": [], "artifact_lineage": artifacts,
        "contract": {
            "description": "在真实工况下优化三维结构", "geometry": {"dimension": "3d", "nelx": 8, "nely": 4, "nelz": 2},
            "material": {"name": "结构钢", "E_MPa": 200_000, "nu": .3},
            "loads": [{"type": "vertical", "magnitude": 1000, "unit": "N"}],
            "boundary_conditions": {"type": "cantilever"},
            "constraints": {"volume_fraction": .4, "gray_max": .1,
                            "connected": True, "allowable_stress_mpa": 150},
            "field_sources": {},
        },
    }


def test_report_follows_chapter_order_uses_chinese_fields_and_abnormal_branch(tmp_path: Path) -> None:
    images = _report_images(tmp_path / "figures")
    generator = ResearchReportGenerator(tmp_path)
    markdown = generator.render_markdown(_report_research(images))
    headings = [markdown.index(f"第{chapter}章") for chapter in ("一", "二", "三", "四")]
    assert headings == sorted(headings)
    for chapter in ("五", "六", "七"):
        assert f"第{chapter}章" not in markdown
    for chapter in (5, 6, 7):
        assert f"Chapter {chapter}" not in markdown
    assert "体积分数" in markdown and "灰度率" in markdown and "最大应力" in markdown
    html = generator._markdown_to_html(markdown, tmp_path)
    assert html.count("<figure") == 3 and html.count("<figcaption>") == 3
    assert html.count('class="figure-page-start"') == 1
    for raw_name in ("volfrac", "gray_ratio", "volume_fraction", "max_iter"):
        assert raw_name not in markdown

    failed = _report_research(images)
    failed["experiments"] = [{"id": "E-FAILED", "round_number": 1,
                              "status": "FAILED", "error": "FEA 求解器不收敛"}]
    failed["best_experiment"] = None
    abnormal = generator.render_markdown(failed)
    assert "### 4.7 异常情况" in abnormal
    assert "### 4.1 方案对比总表" not in abnormal
    assert "本次迭代异常终止" in abnormal


def test_report_export_is_atomic_relative_and_requires_explicit_overwrite(tmp_path: Path) -> None:
    images = _report_images(tmp_path / "figures")
    generator = ResearchReportGenerator(tmp_path / "internal")
    exported = generator.export(_report_research(images), name="专业科研报告",
                                output_directory=tmp_path / "reports",
                                formats=["markdown", "pdf"], overwrite=False)
    markdown = exported["markdown"].read_text(encoding="utf-8")
    assert "专业科研报告_assets/" in markdown
    assert "![Step4 拓扑构型]" in markdown
    assert exported["pdf"].is_file() and exported["pdf"].stat().st_size > 0
    assert len(list(exported["assets"].glob("*.png"))) == 3
    with pytest.raises(FileExistsError):
        generator.export(_report_research(images), name="专业科研报告",
                         output_directory=tmp_path / "reports",
                         formats=["markdown", "pdf"], overwrite=False)
    replaced = generator.export(_report_research(images), name="专业科研报告",
                                output_directory=tmp_path / "reports",
                                formats=["markdown", "pdf"], overwrite=True)
    assert replaced["markdown"].is_file() and replaced["pdf"].is_file()
    assert not list((tmp_path / "reports").glob(".专业科研报告.*-*"))


def test_report_includes_best_valid_result_from_each_available_step(tmp_path: Path) -> None:
    images = _report_images(tmp_path / "figures")
    research = _report_research(images)
    research["experiments"][0]["fidelity"] = "F2"
    markdown = ResearchReportGenerator(tmp_path).render_markdown(research)
    assert "尚无成功的 Step4 MATLAB 3D 最终优化结果" in markdown
    assert "![Step3 拓扑构型]" in markdown
    assert "![Step4 拓扑构型]" not in markdown
