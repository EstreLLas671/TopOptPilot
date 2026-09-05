from __future__ import annotations

from concurrent.futures import Future
import json
import os
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from topoptpilot.api import fastapi_app
from topoptpilot.executor.queue import ExperimentQueue, _atomic_json, _run_solver
from topoptpilot.memory import ResearchStateStore
from topoptpilot.schemas import ExperimentCreate, ResearchCreate
from topoptpilot.service import research_service as research_service_module
from topoptpilot.service import ResearchService


@pytest.fixture
def service(tmp_path):
    value = ResearchService(tmp_path / "research-state", max_workers=1)
    yield value
    value.close()


def _research(service: ResearchService) -> dict:
    return service.create_research(ResearchCreate(
        name="execution safety",
        mode="CONTROLLED",
        budget_total=4,
    ))

def test_research_archive_is_reversible_and_filtered_from_active_list(
    service: ResearchService,
) -> None:
    research = _research(service)

    archived = service.archive_research(research["id"])

    assert archived["archived_at"] is not None
    assert research["id"] not in {item["id"] for item in service.list_research()}
    assert research["id"] in {
        item["id"] for item in service.list_research(archived=True)
    }

    restored = service.restore_research(research["id"])
    assert restored["archived_at"] is None
    assert research["id"] in {item["id"] for item in service.list_research()}


def test_research_archive_cancels_running_state_and_pending_work_without_blocking(
    service: ResearchService,
) -> None:
    research = _research(service)
    service.store.update_research(research["id"], status="RUNNING")
    started = time.perf_counter()
    archived = service.archive_research(research["id"])
    assert time.perf_counter() - started < 1
    assert archived["archived_at"] is not None
    assert archived["status"] == "STOPPED"

    pending_research = _research(service)
    experiment = service.create_experiment(
        pending_research["id"], ExperimentCreate(requires_approval=True),
    )
    archived = service.archive_research(pending_research["id"])
    assert archived["archived_at"] is not None
    assert service.store.get_experiment(experiment["id"])["status"] == "CANCELLED"
    assert service.store.get_decision(experiment["decision_id"])["status"] == "REJECTED"


def test_stop_autonomous_cancels_full_chain_and_next_start_archives_active_run(
    service: ResearchService, monkeypatch,
) -> None:
    research = _research(service)
    service.store.update_research(
        research["id"], goal="保留目标", hypothesis="保留假设", status="RUNNING", budget_used=2,
    )
    service.store.update_research_json(
        research["id"], defaults={"optimization_config": {"penal": 3.0},
                                  "engineering_scheme_baseline": {"schemeId": "scheme-1"}},
    )
    experiment = service.create_experiment(
        research["id"], ExperimentCreate(fidelity="F0 — Python 2D", backend="python"),
    )
    service.store.update_experiment(experiment["id"], status="RUNNING", run_id="run-python-stop")
    task = service.store.create_subagent_task({
        "id": "TASK-STOP", "research_id": research["id"], "role": "HYPOTHESIS",
        "objective": "bounded review", "status": "RUNNING",
    })
    cancelled: list[str] = []
    monkeypatch.setattr(service.queue, "cancel", lambda run_id: cancelled.append(run_id) or True)
    monkeypatch.setattr(service.queue, "wait_for_stop", lambda _run_id, timeout=10: True)

    class _Pi:
        def __init__(self): self.calls: list[str] = []
        def cancel(self, research_id): self.calls.append("cancel:" + research_id); return True
        def release(self, research_id): self.calls.append("release:" + research_id)
        def close(self): return None

    pi = _Pi()
    service.pi_runtime = pi
    stopped = service.stop_autonomous_research(research["id"])
    assert stopped["status"] == "STOPPING"
    assert service.stop_autonomous_research(research["id"])["status"] in {"STOPPING", "STOPPED"}
    deadline = time.monotonic() + 3
    while service.get_research(research["id"])["status"] == "STOPPING" and time.monotonic() < deadline:
        time.sleep(.02)
    stopped = service.get_research(research["id"])
    assert stopped["status"] == "STOPPED"
    assert stopped["termination_reason"] == "USER_STOPPED"
    assert cancelled == ["run-python-stop"]
    assert pi.calls == ["cancel:" + research["id"], "release:" + research["id"]]
    assert service.store.get_experiment(experiment["id"])["status"] == "CANCELLED"
    assert service.store.get_subagent_task(task["id"])["status"] == "CANCELLED"

    old_run = stopped["active_run_id"]
    monkeypatch.setattr(service, "_send_pi_or_fallback", lambda *_args, **_kwargs: None)
    restarted = service.start_autonomous_research(research["id"])
    assert restarted["active_run_id"] != old_run
    assert restarted["experiments"] == []
    assert restarted["budget_used"] == 0
    assert restarted["current_round"] == 0
    assert restarted["goal"] == "保留目标"
    assert restarted["hypothesis"] == "保留假设"
    assert restarted["defaults"]["engineering_scheme_baseline"]["schemeId"] == "scheme-1"
    assert len(service.store.list_experiments(research["id"], include_archived=True)) == 1
    runs = service.store.list_research_runs(research["id"])
    assert [item["status"] for item in runs] == ["ARCHIVED", "RUNNING"]




@pytest.mark.parametrize(
    ("fidelity", "backend"),
    [
        ("F3 — MATLAB 3D", "python"),
        ("F2 — Python 3D", "matlab"),
    ],
)
def test_experiment_create_api_rejects_backend_that_does_not_match_fidelity(
    service: ResearchService, monkeypatch, fidelity: str, backend: str,
) -> None:
    research = _research(service)
    monkeypatch.setattr(fastapi_app, "service", service)

    response = TestClient(fastapi_app.app).post(
        f"/api/research/{research['id']}/experiments",
        json={"fidelity": fidelity, "backend": backend},
    )

    assert response.status_code == 422
    assert service.store.list_experiments(research["id"]) == []


def test_experiment_create_schema_rejects_simulate_backend() -> None:
    with pytest.raises(ValidationError, match="simulate"):
        ExperimentCreate(backend="simulate")


def test_service_defensively_rejects_constructed_simulate_backend(
    service: ResearchService,
) -> None:
    research = _research(service)
    unvalidated = ExperimentCreate.model_construct(backend="simulate")

    with pytest.raises(ValueError, match="simulate"):
        service.create_experiment(research["id"], unvalidated)
    assert service.store.list_experiments(research["id"]) == []


class _RecordingMatlabWorker:
    def __init__(self) -> None:
        self.submissions: list[tuple[dict, str, str]] = []

    def submit(self, task, research_id, experiment_id, done):
        self.submissions.append((task, research_id, experiment_id))
        return "matlab_test_run", Future()

    def close(self) -> None:
        return None


def test_f3_warm_start_runs_full_optimization_without_fixed_density_mode(
    service: ResearchService, monkeypatch,
) -> None:
    density = [[[0.5 for _ in range(4)] for _ in range(3)] for _ in range(2)]
    source = {"result": {"artifacts": {"density": density}}}
    monkeypatch.setattr(
        service.store, "get_experiment",
        lambda experiment_id: source if experiment_id == "E01" else None,
    )
    experiment = {
        "id": "E02", "fidelity": "F3 — MATLAB 3D", "mesh_level": "fine3d",
        "backend": "matlab", "parameters": {"volfrac": 0.4}, "warm_start": "E01",
    }
    research = {"id": "R-001", "geometry": {"dimensions": [3, 1, 0.75]}, "contract": {}}

    task, _, _ = service._prepare_claimed_experiment(experiment, research)

    assert task["params"]["initial_density"] == density
    assert "verification_mode" not in task["params"]
    assert "grid3d" not in task["params"]


@pytest.mark.skip(reason="2.1.0 replaces the separate Step4 pre-run decision with one-time stage authorization")
def test_f3_requires_approved_research_state_before_run_or_command(
    service: ResearchService,
) -> None:
    research = _research(service)
    service.matlab_worker.close()
    matlab = _RecordingMatlabWorker()
    service.matlab_worker = matlab
    experiment = service.create_experiment(
        research["id"],
        ExperimentCreate(fidelity="F3 — MATLAB 3D", mesh_level="fine3d", backend="matlab"),
    )

    decision = service.store.get_decision(experiment["decision_id"])
    assert decision["status"] == "PENDING"
    with pytest.raises(ValueError, match="APPROVED"):
        service.run_experiment(experiment["id"])
    command = service.execute_command(research["id"], "/run", experiment["id"])
    assert command.ok is False
    assert "APPROVED" in command.message
    assert matlab.submissions == []
    assert service.store.get_experiment(experiment["id"])["run_id"] is None

    service.approve_decision(decision["id"])

    assert len(matlab.submissions) == 1
    task, submitted_research_id, submitted_experiment_id = matlab.submissions[0]
    assert submitted_research_id == research["id"]
    assert submitted_experiment_id == experiment["id"]
    assert task["mesh_level"] == "fine3d"
    persisted = service.store.get_experiment(experiment["id"])
    assert persisted["backend"] == "matlab"
    assert persisted["run_id"] == "matlab_test_run"


@pytest.mark.skip(reason="2.1.0 replaces the separate Step4 pre-run decision with one-time stage authorization")
def test_rejected_f3_cannot_be_started_directly(
    service: ResearchService,
) -> None:
    research = _research(service)
    experiment = service.create_experiment(
        research["id"],
        ExperimentCreate(fidelity="F3 — MATLAB 3D", mesh_level="fine3d", backend="matlab"),
    )
    service.reject_decision(experiment["decision_id"])

    with pytest.raises(ValueError, match="APPROVED"):
        service.run_experiment(experiment["id"])


@pytest.mark.skip(reason="2.1.0 replaces the separate Step4 pre-run decision with one-time stage authorization")
def test_f3_without_a_decision_cannot_be_started(
    service: ResearchService,
) -> None:
    research = _research(service)
    service.matlab_worker.close()
    matlab = _RecordingMatlabWorker()
    service.matlab_worker = matlab
    experiment = service.store.create_experiment({
        "id": "E99",
        "research_id": research["id"],
        "purpose": "legacy high fidelity row",
        "fidelity": "F3 — MATLAB 3D",
        "mesh_level": "fine3d",
        "backend": "matlab",
        "parameters": ExperimentCreate().parameters,
        "status": "WAITING",
        "safety": "HIGH",
    })

    with pytest.raises(ValueError, match="APPROVED.*MISSING"):
        service.run_experiment(experiment["id"])

    assert matlab.submissions == []
    assert service.store.get_experiment(experiment["id"])["run_id"] is None


class _NoSubmitPool:
    def submit(self, *args, **kwargs):
        pytest.fail("simulate reached the formal process pool")

    def shutdown(self, *args, **kwargs) -> None:
        return None


def test_formal_queue_rejects_simulate_before_submission(tmp_path) -> None:
    queue = ExperimentQueue(tmp_path / "progress", max_workers=1)
    queue._pool.shutdown(wait=True)
    queue._pool = _NoSubmitPool()
    try:
        with pytest.raises(ValueError, match="simulate"):
            queue.submit({}, backend="simulate")
        assert list((tmp_path / "progress").iterdir()) == []
    finally:
        queue.shutdown()


def test_queue_worker_defensively_rejects_simulate(monkeypatch, tmp_path) -> None:
    class _ForbiddenSolverRunner:
        def __init__(self, *args, **kwargs):
            pytest.fail("simulate reached SolverRunner")

    import experiments.solver_runner

    monkeypatch.setattr(experiments.solver_runner, "SolverRunner", _ForbiddenSolverRunner)
    with pytest.raises(ValueError, match="simulate"):
        _run_solver({}, "simulate", str(tmp_path / "progress.json"))


@pytest.mark.skipif(os.name != "nt", reason="Windows target handles block os.replace")
def test_atomic_progress_write_waits_for_transient_windows_target_lock(tmp_path) -> None:
    target = tmp_path / "progress.json"
    target.write_text('{"iteration": 0}', encoding="utf-8")
    locked_reader = target.open("r", encoding="utf-8")

    def release_reader() -> None:
        time.sleep(0.05)
        locked_reader.close()

    release = threading.Thread(target=release_reader)
    release.start()
    try:
        _atomic_json(target, {"iteration": 1})
    finally:
        locked_reader.close()
        release.join(timeout=1)

    assert json.loads(target.read_text(encoding="utf-8")) == {"iteration": 1}


class _BlockingQueue:
    def __init__(self) -> None:
        self.submissions = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def submit(self, task, backend="python", done=None):
        with self._lock:
            self.submissions += 1
            run_id = f"test_run_{self.submissions}"
        self.entered.set()
        assert self.release.wait(2), "test queue was not released"
        return run_id

    def poll(self, run_id):
        return {"run_id": run_id, "status": "RUNNING"}

    def shutdown(self, wait=False) -> None:
        self.release.set()


class _RecordingQueue:
    def __init__(self) -> None:
        self.submissions = 0

    def submit(self, task, backend="python", done=None):
        self.submissions += 1
        return f"test_run_{self.submissions}"

    def poll(self, run_id):
        return {"run_id": run_id, "status": "RUNNING"}

    def shutdown(self, wait=False) -> None:
        return None


def _replace_queue(service: ResearchService, queue) -> None:
    service.queue.shutdown(wait=True)
    service.queue = queue


def _pending_f0(service: ResearchService, research_id: str) -> dict:
    return service.create_experiment(
        research_id,
        ExperimentCreate(requires_approval=True),
    )


def test_concurrent_run_claim_submits_an_experiment_only_once(
    service: ResearchService,
) -> None:
    research = _research(service)
    experiment = _pending_f0(service, research["id"])
    assert service.store.resolve_decision_if_pending(experiment["decision_id"], "APPROVED")
    queue = _BlockingQueue()
    _replace_queue(service, queue)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            service.run_experiment(experiment["id"])
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=run)
    first.start()
    assert queue.entered.wait(1)
    second = threading.Thread(target=run)
    second.start()
    second.join(0.5)

    assert queue.submissions == 1
    queue.release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []


@pytest.mark.skip(reason="obsolete separate pre-run decision race; covered by one-time authorization race in v2.1")
def test_reject_winning_race_prevents_approve_from_submitting(
    service: ResearchService, monkeypatch,
) -> None:
    research = _research(service)
    experiment = service.create_experiment(
        research["id"],
        ExperimentCreate(fidelity="F3 — MATLAB 3D", mesh_level="fine3d", backend="matlab"),
    )
    service.matlab_worker.close()
    matlab = _RecordingMatlabWorker()
    service.matlab_worker = matlab
    reject_entered = threading.Event()
    release_reject = threading.Event()
    original_resolve = service.store.resolve_decision_if_pending

    def blocking_resolve(decision_id: str, status: str):
        if status == "REJECTED":
            reject_entered.set()
            assert release_reject.wait(2), "reject test was not released"
        return original_resolve(decision_id, status)

    monkeypatch.setattr(service.store, "resolve_decision_if_pending", blocking_resolve)
    reject = threading.Thread(target=service.reject_decision, args=(experiment["decision_id"],))
    reject.start()
    assert reject_entered.wait(1)
    approve = threading.Thread(target=service.approve_decision, args=(experiment["decision_id"],))
    approve.start()
    approve.join(0.5)
    release_reject.set()
    reject.join(2)
    approve.join(2)

    assert matlab.submissions == []
    assert service.store.get_decision(experiment["decision_id"])["status"] == "REJECTED"
    assert service.store.get_experiment(experiment["id"])["status"] == "CANCELLED"


def test_persisted_requires_approval_without_decision_blocks_f0(
    service: ResearchService,
) -> None:
    research = _research(service)
    queue = _RecordingQueue()
    _replace_queue(service, queue)
    experiment = service.store.create_experiment({
        "id": "E98", "research_id": research["id"], "purpose": "legacy approval",
        "fidelity": "F0 — 2D Coarse", "mesh_level": "coarse", "backend": "python",
        "parameters": ExperimentCreate().parameters, "status": "WAITING", "safety": "LOW",
        "requires_approval": True,
    })

    assert experiment["requires_approval"] is True
    with pytest.raises(ValueError, match="APPROVED.*MISSING"):
        service.run_experiment(experiment["id"])
    assert queue.submissions == 0


def test_autonomous_low_risk_f0_without_decision_runs(
    service: ResearchService,
) -> None:
    research = service.create_research(ResearchCreate(
        name="autonomous low risk", mode="AUTONOMOUS", budget_total=4,
    ))
    queue = _RecordingQueue()
    _replace_queue(service, queue)

    experiment = service.create_experiment(research["id"], ExperimentCreate())

    assert experiment["requires_approval"] is False
    assert service.store.list_decisions(research["id"]) == []
    assert queue.submissions == 1
    assert service.store.get_experiment(experiment["id"])["status"] == "RUNNING"


def test_submit_failure_rolls_claim_back_to_failed(service: ResearchService) -> None:
    research = _research(service)
    experiment = _pending_f0(service, research["id"])
    assert service.store.resolve_decision_if_pending(experiment["decision_id"], "APPROVED")

    class _FailingQueue(_RecordingQueue):
        def submit(self, task, backend="python", done=None):
            raise RuntimeError("queue unavailable")

    _replace_queue(service, _FailingQueue())
    with pytest.raises(RuntimeError, match="queue unavailable"):
        service.run_experiment(experiment["id"])

    persisted = service.store.get_experiment(experiment["id"])
    assert persisted["status"] == "FAILED"
    assert persisted["error"] == "queue unavailable"
    assert persisted["completed_at"] is not None


@pytest.mark.skip(reason="obsolete separate pre-run decision race; covered by one-time authorization race in v2.1")
def test_reject_and_run_claim_interleaving_never_submits_after_rejected(
    service: ResearchService, monkeypatch,
) -> None:
    research = _research(service)
    experiment = service.create_experiment(
        research["id"],
        ExperimentCreate(fidelity="F3 — MATLAB 3D", mesh_level="fine3d", backend="matlab"),
    )
    service.matlab_worker.close()
    matlab = _RecordingMatlabWorker()
    service.matlab_worker = matlab
    reject_entered = threading.Event()
    release_reject = threading.Event()
    original_resolve = service.store.resolve_decision_if_pending
    reject_errors: list[BaseException] = []
    run_errors: list[BaseException] = []

    def blocking_resolve(decision_id: str, status: str):
        if status == "REJECTED":
            reject_entered.set()
            assert release_reject.wait(2), "reject test was not released"
        return original_resolve(decision_id, status)

    def reject() -> None:
        try:
            service.reject_decision(experiment["decision_id"])
        except BaseException as exc:
            reject_errors.append(exc)

    def run() -> None:
        try:
            service.run_experiment(experiment["id"])
        except BaseException as exc:
            run_errors.append(exc)

    monkeypatch.setattr(service.store, "resolve_decision_if_pending", blocking_resolve)
    reject_thread = threading.Thread(target=reject)
    reject_thread.start()
    assert reject_entered.wait(1)
    run_thread = threading.Thread(target=run)
    run_thread.start()
    run_thread.join(0.25)
    release_reject.set()
    reject_thread.join(2)
    run_thread.join(2)

    assert reject_errors == []
    assert len(run_errors) == 1
    assert isinstance(run_errors[0], ValueError)
    assert "APPROVED" in str(run_errors[0])
    assert matlab.submissions == []
    assert service.store.get_decision(experiment["decision_id"])["status"] == "REJECTED"
    assert service.store.get_experiment(experiment["id"])["status"] == "CANCELLED"


def test_approve_claim_and_reject_interleaving_keeps_claimed_run_approved(
    service: ResearchService,
) -> None:
    research = _research(service)
    experiment = _pending_f0(service, research["id"])
    queue = _BlockingQueue()
    _replace_queue(service, queue)
    approve_errors: list[BaseException] = []

    def approve() -> None:
        try:
            service.approve_decision(experiment["decision_id"])
        except BaseException as exc:
            approve_errors.append(exc)

    approve_thread = threading.Thread(target=approve)
    approve_thread.start()
    assert queue.entered.wait(1)
    claimed = service.store.get_experiment(experiment["id"])
    assert claimed["status"] == "RUNNING"
    assert claimed["run_id"].startswith("claim_")

    rejected = service.reject_decision(experiment["decision_id"])

    assert rejected["status"] == "APPROVED"
    assert service.store.get_decision(experiment["decision_id"])["status"] == "APPROVED"
    assert service.store.get_experiment(experiment["id"])["status"] == "RUNNING"
    assert queue.submissions == 1
    queue.release.set()
    approve_thread.join(2)
    assert not approve_thread.is_alive()
    assert approve_errors == []


def test_two_services_sharing_sqlite_claim_only_one_submission(tmp_path) -> None:
    data_dir = tmp_path / "shared-research-state"
    first = ResearchService(data_dir, max_workers=1)
    second = ResearchService(data_dir, max_workers=1)
    try:
        research = _research(first)
        experiment = _pending_f0(first, research["id"])
        assert first.store.resolve_decision_if_pending(experiment["decision_id"], "APPROVED")
        first_queue = _BlockingQueue()
        second_queue = _RecordingQueue()
        _replace_queue(first, first_queue)
        _replace_queue(second, second_queue)
        errors: list[BaseException] = []

        def first_run() -> None:
            try:
                first.run_experiment(experiment["id"])
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=first_run)
        thread.start()
        assert first_queue.entered.wait(1)
        second.run_experiment(experiment["id"])

        assert first_queue.submissions + second_queue.submissions == 1
        first_queue.release.set()
        thread.join(2)
        assert not thread.is_alive()
        assert errors == []
    finally:
        first.close()
        second.close()


class _BlockingMatlabWorker(_RecordingMatlabWorker):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def submit(self, task, research_id, experiment_id, done):
        self.submissions.append((task, research_id, experiment_id))
        self.entered.set()
        assert self.release.wait(2), "MATLAB submit test was not released"
        return "matlab_shared_run", Future()

    def close(self) -> None:
        self.release.set()


@pytest.mark.skip(reason="obsolete separate pre-run decision race; covered by one-time authorization race in v2.1")
def test_two_services_approve_reject_cas_matches_actual_submission(
    tmp_path, monkeypatch,
) -> None:
    data_dir = tmp_path / "shared-decision-state"
    approving = ResearchService(data_dir, max_workers=1)
    rejecting = ResearchService(data_dir, max_workers=1)
    try:
        research = _research(approving)
        experiment = approving.create_experiment(
            research["id"],
            ExperimentCreate(fidelity="F3 — MATLAB 3D", mesh_level="fine3d", backend="matlab"),
        )
        approving.matlab_worker.close()
        matlab = _BlockingMatlabWorker()
        approving.matlab_worker = matlab
        rejecting.matlab_worker.close()
        rejecting.matlab_worker = _RecordingMatlabWorker()
        reject_read = threading.Event()
        calls = 0
        original_require = rejecting._require_decision

        def stale_second_read(decision_id: str):
            nonlocal calls
            value = original_require(decision_id)
            calls += 1
            if calls == 2:
                reject_read.set()
                assert matlab.entered.wait(2), "approve did not reach MATLAB submit"
            return value

        monkeypatch.setattr(rejecting, "_require_decision", stale_second_read)
        reject_errors: list[BaseException] = []
        approve_errors: list[BaseException] = []

        def reject() -> None:
            try:
                rejecting.reject_decision(experiment["decision_id"])
            except BaseException as exc:
                reject_errors.append(exc)

        def approve() -> None:
            try:
                approving.approve_decision(experiment["decision_id"])
            except BaseException as exc:
                approve_errors.append(exc)

        reject_thread = threading.Thread(target=reject)
        reject_thread.start()
        assert reject_read.wait(1)
        approve_thread = threading.Thread(target=approve)
        approve_thread.start()
        assert matlab.entered.wait(1)
        reject_thread.join(2)
        matlab.release.set()
        approve_thread.join(2)

        assert reject_errors == []
        assert approve_errors == []
        assert approving.store.get_decision(experiment["decision_id"])["status"] == "APPROVED"
        assert approving.store.get_experiment(experiment["id"])["status"] == "RUNNING"
        assert len(matlab.submissions) == 1
    finally:
        approving.close()
        rejecting.close()


@pytest.mark.parametrize("failure_point", ["build", "cache"])
def test_preparation_failure_after_claim_rolls_back_failed(
    service: ResearchService, monkeypatch, failure_point: str,
) -> None:
    research = _research(service)
    experiment = _pending_f0(service, research["id"])
    assert service.store.resolve_decision_if_pending(experiment["decision_id"], "APPROVED")
    queue = _RecordingQueue()
    _replace_queue(service, queue)

    if failure_point == "build":
        monkeypatch.setattr(
            research_service_module, "build_solver_task",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("build failed")),
        )
    else:
        monkeypatch.setattr(
            service.cache, "get",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cache failed")),
        )

    with pytest.raises(RuntimeError, match=f"{failure_point} failed"):
        service.run_experiment(experiment["id"])

    persisted = service.store.get_experiment(experiment["id"])
    assert persisted["status"] == "FAILED"
    assert persisted["error"] == f"{failure_point} failed"
    assert persisted["completed_at"] is not None
    assert queue.submissions == 0


def test_initialize_migrates_real_legacy_experiment_schema(tmp_path) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE experiments (
            id TEXT PRIMARY KEY, research_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            purpose TEXT NOT NULL, fidelity TEXT NOT NULL, mesh_level TEXT NOT NULL,
            backend TEXT NOT NULL, parameters_json TEXT NOT NULL, warm_start TEXT,
            status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
            current_iteration INTEGER NOT NULL DEFAULT 0, run_id TEXT,
            safety TEXT NOT NULL DEFAULT 'LOW', result_json TEXT, error TEXT,
            created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
            proposal_id TEXT, intent TEXT NOT NULL DEFAULT 'MANUAL',
            cached INTEGER NOT NULL DEFAULT 0
        )""")

    ResearchStateStore(database)

    with sqlite3.connect(database) as db:
        columns = {row[1]: row for row in db.execute("PRAGMA table_info(experiments)")}
    assert "requires_approval" in columns
    assert columns["requires_approval"][4] == "0"


def test_decisions_with_same_second_have_stable_insertion_order(service: ResearchService) -> None:
    research = _research(service)
    for decision_id in ("D-SAME-1", "D-SAME-2"):
        service.store.create_decision({
            "id": decision_id, "research_id": research["id"], "experiment_id": None,
            "intent": "RUN_EXPERIMENT", "reason": decision_id, "proposal": {},
            "risk": "LOW", "status": "PENDING",
        })

    ordered = [item["id"] for item in service.store.list_decisions(research["id"])
               if item["id"].startswith("D-SAME-")]
    assert ordered == ["D-SAME-1", "D-SAME-2"]


def test_sqlite_claim_cas_allows_one_winner_across_store_instances(
    service: ResearchService,
) -> None:
    research = _research(service)
    experiment = _pending_f0(service, research["id"])
    first = ResearchStateStore(service.store.db_path)
    second = ResearchStateStore(service.store.db_path)
    start = threading.Barrier(2)
    results: list[bool] = []
    errors: list[BaseException] = []

    def claim(store: ResearchStateStore, claim_id: str) -> None:
        try:
            start.wait(timeout=1)
            results.append(store.claim_experiment_for_run(experiment["id"], claim_id))
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=claim, args=(first, "claim_first")),
        threading.Thread(target=claim, args=(second, "claim_second")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)

    assert errors == []
    assert sorted(results) == [False, True]
    persisted = service.store.get_experiment(experiment["id"])
    assert persisted["status"] == "RUNNING"
    assert persisted["run_id"] in {"claim_first", "claim_second"}


def test_submitted_solver_run_id_persistence_failure_keeps_durable_claim(
    service: ResearchService, monkeypatch,
) -> None:
    research = _research(service)
    experiment = _pending_f0(service, research["id"])
    assert service.store.resolve_decision_if_pending(experiment["decision_id"], "APPROVED")

    class _KnownRunQueue(_RecordingQueue):
        def submit(self, task, backend="python", done=None):
            self.submissions += 1
            return "solver_real_run_42"

    queue = _KnownRunQueue()
    _replace_queue(service, queue)
    original_update = service.store.update_experiment

    def fail_real_run_id(experiment_id: str, **fields):
        if fields.get("run_id") == "solver_real_run_42":
            raise RuntimeError("database unavailable after submit")
        return original_update(experiment_id, **fields)

    monkeypatch.setattr(service.store, "update_experiment", fail_real_run_id)
    with pytest.raises(RuntimeError) as raised:
        service.run_experiment(experiment["id"])

    message = str(raised.value)
    persisted = service.store.get_experiment(experiment["id"])
    assert "solver_real_run_42" in message
    assert persisted["run_id"] in message
    assert persisted["run_id"].startswith("claim_")
    assert persisted["status"] == "RUNNING"
    assert persisted["completed_at"] is None
    assert persisted["error"] is None
    assert queue.submissions == 1


def test_cache_hit_run_id_persistence_failure_rolls_claim_back_failed(
    service: ResearchService, monkeypatch,
) -> None:
    research = _research(service)
    experiment = _pending_f0(service, research["id"])
    assert service.store.resolve_decision_if_pending(experiment["decision_id"], "APPROVED")
    _replace_queue(service, _RecordingQueue())
    monkeypatch.setattr(service.cache, "get", lambda task: {"solver": {"backend": "python"}})
    original_update = service.store.update_experiment

    def fail_cache_run_id(experiment_id: str, **fields):
        if fields.get("run_id") == "cache_hit":
            raise RuntimeError("cache run_id persistence failed")
        return original_update(experiment_id, **fields)

    monkeypatch.setattr(service.store, "update_experiment", fail_cache_run_id)
    with pytest.raises(RuntimeError, match="cache run_id persistence failed"):
        service.run_experiment(experiment["id"])

    persisted = service.store.get_experiment(experiment["id"])
    assert persisted["status"] == "FAILED"
    assert persisted["completed_at"] is not None
    assert persisted["error"] == "cache run_id persistence failed"
    assert persisted["run_id"].startswith("claim_")


def test_queue_worker_rejects_matlab_with_value_error_before_dispatch(tmp_path) -> None:
    with pytest.raises(ValueError, match="backend=matlab.*not allowed"):
        _run_solver({}, "matlab", str(tmp_path / "progress.json"))
