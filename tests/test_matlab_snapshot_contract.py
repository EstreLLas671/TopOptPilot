from __future__ import annotations

from pathlib import Path


def test_matlab_iteration_snapshot_records_density_and_stress_payloads() -> None:
    source = (Path(__file__).parents[1] / "matlab" / "engineering" / "run_topopt_job.m").read_text(encoding="utf-8")
    assert "density_file" in source
    assert "stress_file" in source
    assert "frame.von_mises" in source
    assert "write_single_payload" in source
    assert "render_file" in source
    assert "render_iteration_frame" in source
    assert (Path(__file__).parents[1] / "matlab" / "engineering" / "render_iteration_frame.m").is_file()


def test_matlab_bridge_routes_to_user_2d_and_3d_solver_entries() -> None:
    root = Path(__file__).parents[1] / "matlab" / "engineering"
    source = (root / "run_topopt_job.m").read_text(encoding="utf-8")

    assert (root / "TopOpt_2D" / "topopt_main.m").is_file()
    assert (root / "TopOpt-3D" / "topopt3d_main.m").is_file()
    assert "result = topopt_main(config);" in source
    assert "result = topopt3d_main(config);" in source
    assert "solver_dimension" in source

def test_matlab_final_result_exports_viewer_payloads() -> None:
    source = (Path(__file__).parents[1] / "matlab" / "engineering" / "run_topopt_job.m").read_text(encoding="utf-8")
    assert "final_density.bin" in source
    assert "final_von_mises.bin" in source
    assert "result_manifest.json" in source


def test_step4_research_lane_watches_engineering_snapshots_and_publishes_3d_density() -> None:
    root = Path(__file__).parents[1]
    service = (root / "topoptpilot" / "service" / "research_service.py").read_text(encoding="utf-8")
    workspace = (root / "desktop" / "src" / "features" / "research" / "ResearchWorkspace.tsx").read_text(encoding="utf-8")
    assert 'run_matlab_batch(' in service
    assert 'snapshots_dir.glob("iter_*_density.bin")' in service
    assert '"density_3d_live": density_3d' in service
    assert "artifacts.density_3d_live ?? artifacts.density" in workspace
    assert 'const densityIs3d' in workspace
    assert '<InteractiveVolumeView density={resultView.liveVolume' in workspace


def test_matlab_binary_writer_closes_each_payload_exactly_once() -> None:
    source = (Path(__file__).parents[1] / "matlab" / "engineering" / "run_topopt_job.m").read_text(encoding="utf-8")
    writer = source.split("function write_single_payload", maxsplit=1)[1].split(
        "function config = make_config", maxsplit=1
    )[0]

    assert "cleanup = onCleanup(@() fclose(fid));" in writer
    assert "clear cleanup" in writer
    assert "\nfclose(fid);" not in writer


def test_2d_solver_emits_true_von_mises_for_live_and_final_views() -> None:
    root = Path(__file__).parents[1] / "matlab" / "engineering" / "TopOpt_2D"
    source = (root / "topopt_main.m").read_text(encoding="utf-8")
    stress_source = (root / "compute_von_mises_2d.m").read_text(encoding="utf-8")

    assert "frame.von_mises" in source
    assert "result.von_mises" in source
    assert "Ufinal" in source
    assert "gauss_max" in stress_source
    assert "Eeff = x(ely,elx)^penal" in stress_source
    assert "sigma(1)^2 - sigma(1)*sigma(2)" in stress_source

def test_matlab_2d_and_3d_publish_true_gray_ratio_every_iteration() -> None:
    root = Path(__file__).parents[1] / "matlab" / "engineering"
    bridge = (root / "run_topopt_job.m").read_text(encoding="utf-8")
    solver_2d = (root / "TopOpt_2D" / "topopt_main.m").read_text(encoding="utf-8")
    solver_3d = (root / "TopOpt-3D" / "topopt3d_main.m").read_text(encoding="utf-8")

    assert "'gray_ratio',double(frame.gray_ratio)" in bridge
    assert "'gray_ratio'" in bridge.split("function summary = make_summary", 1)[1]
    assert "frame.gray_ratio = gray_ratio(xPhysical, domainMask);" in solver_2d
    assert "result.gray_ratio = gray_ratio(finalPhysical, domainMask);" in solver_2d
    assert "active > 0.1 & active < 0.9" in solver_2d
    assert "frame.gray_ratio = gray_ratio_3d(xPhysical, domainMask);" in solver_3d
    assert "result.gray_ratio = gray_ratio_3d(finalPhysical, domainMask);" in solver_3d
    assert "active > 0.1 & active < 0.9" in solver_3d
