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


def test_matlab_binary_writer_closes_each_payload_exactly_once() -> None:
    source = (Path(__file__).parents[1] / "matlab" / "engineering" / "run_topopt_job.m").read_text(encoding="utf-8")
    writer = source.split("function write_single_payload", maxsplit=1)[1].split(
        "function config = make_config", maxsplit=1
    )[0]

    assert "cleanup = onCleanup(@() fclose(fid));" in writer
    assert "clear cleanup" in writer
    assert "\nfclose(fid);" not in writer
