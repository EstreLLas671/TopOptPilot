"""Process-local verified MATLAB Runtime profiles for engineering runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable, Mapping

from topoptpilot_desktop.engineering.matlab import classify_runtime_root


class RuntimeProfileError(ValueError):
    """Raised when a Runtime profile is missing, stale, or unsafe."""

    def __init__(self, message: str, *, code: str = "RUNTIME_PROFILE_INVALID") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _Identity:
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    profile_id: str
    runtime_root: Path
    dll_path: Path
    solver_executable: Path
    runtime_identity: _Identity
    solver_identity: _Identity
    created_at: float
    usable: bool = True

    @property
    def runtime_release(self) -> str:
        return self.runtime_root.name

    def as_dict(self) -> dict[str, object]:
        return {
            "state": "ready",
            "root": str(self.runtime_root),
            "dllPath": str(self.dll_path),
            "solverExecutable": str(self.solver_executable),
            "profileId": self.profile_id,
            "usable": True,
            "diagnostic": "Runtime 与编译求解器已验证",
        }


def _identity(path: Path) -> _Identity:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return _Identity(stat.st_size, stat.st_mtime_ns, digest.hexdigest())


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _trusted_solver_entries(
    environ: Mapping[str, str],
    project_root: Path,
) -> tuple[set[Path], set[Path]]:
    files: set[Path] = set()
    roots: set[Path] = {
        (project_root / "build" / "solver").resolve(),
        (project_root / "dist" / "solver").resolve(),
        (project_root / "matlab" / "dist" / "solver").resolve(),
    }
    resource = environ.get("TOPPILOT_RESOURCE_ROOT")
    if resource:
        resource_root = Path(resource).expanduser().resolve()
        roots.update({
            (resource_root / "solver").resolve(),
            (resource_root / "bin" / "solver").resolve(),
            (resource_root / "runtime" / "solver").resolve(),
        })
    for raw in environ.get("TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST", "").split(os.pathsep):
        if not raw.strip():
            continue
        entry = Path(raw.strip()).expanduser().resolve()
        if entry.suffix.lower() == ".exe" or entry.is_file():
            files.add(entry)
        else:
            roots.add(entry)
    return files, roots



def _normalize_release(value: str) -> str:
    match = re.search(r"R?(20\d{2}[ab])", value, re.IGNORECASE)
    if match is None:
        return ""
    release = match.group(1)
    return f"R{release[:4]}{release[4].lower()}"


def _solver_release(solver: Path) -> str:
    metadata_path = solver.parent / "compiler-info.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    if not isinstance(metadata, dict):
        return ""
    declared = metadata.get("matlabRelease")
    if not isinstance(declared, str):
        return ""
    return _normalize_release(declared)

def stage_runtime_solver(profile: RuntimeProfile, run_dir: Path) -> Path:
    stage_dir = run_dir.resolve() / "runtime-staging"
    stage_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(stage_dir, 0o700)
    target = stage_dir / f"solver-{profile.solver_identity.sha256}.exe"
    with profile.solver_executable.open("rb") as source, target.open("xb") as destination:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            destination.write(block)
    os.chmod(target, 0o500)
    if _identity(target).sha256 != profile.solver_identity.sha256:
        target.unlink(missing_ok=True)
        raise RuntimeProfileError(
            "暂存求解器与已验证摘要不一致", code="RUNTIME_PROFILE_STALE"
        )
    return target


class RuntimeProfileStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 30 * 60,
        max_profiles: int = 128,
        clock: Callable[[], float] = time.monotonic,
        environ: Mapping[str, str] | None = None,
        project_root: Path | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_profiles = max_profiles
        self._clock = clock
        self._environ = environ
        self._project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self._profiles: dict[str, RuntimeProfile] = {}
        self._lock = RLock()

    def _environment(self) -> Mapping[str, str]:
        return self._environ if self._environ is not None else os.environ

    def _prune_locked(self, now: float) -> None:
        expired = [
            profile_id
            for profile_id, profile in self._profiles.items()
            if now - profile.created_at > self._ttl_seconds
        ]
        for profile_id in expired:
            self._profiles.pop(profile_id, None)

    @property
    def profile_count(self) -> int:
        with self._lock:
            self._prune_locked(self._clock())
            return len(self._profiles)

    def verify_compatible_installation(
        self,
        runtime_root: str | Path,
        runtime_release: str,
    ) -> RuntimeProfile:
        wanted_release = _normalize_release(runtime_release)
        if not wanted_release:
            raise RuntimeProfileError(
                "无法确认 MATLAB Runtime release",
                code="RUNTIME_RELEASE_UNKNOWN",
            )
        trusted_files, trusted_roots = _trusted_solver_entries(
            self._environment(), self._project_root
        )
        candidates = set(trusted_files)
        candidates.update(root / "TopOptSolver.exe" for root in trusted_roots)
        discovered_releases: set[str] = set()
        for solver in sorted(candidates, key=lambda item: str(item).lower()):
            if not solver.is_file():
                continue
            release = _solver_release(solver)
            if release:
                discovered_releases.add(release)
            if release == wanted_release:
                runtime_path = Path(runtime_root).expanduser().resolve()
                solver_path = solver.resolve()
                with self._lock:
                    self._prune_locked(self._clock())
                    reusable = [
                        profile.profile_id
                        for profile in self._profiles.values()
                        if profile.runtime_root == runtime_path
                        and profile.solver_executable == solver_path
                    ]
                for profile_id in reusable:
                    try:
                        return self.resolve(profile_id)
                    except RuntimeProfileError:
                        with self._lock:
                            self._profiles.pop(profile_id, None)
                return self.verify(runtime_path, solver_path)
        if discovered_releases:
            available = ", ".join(sorted(discovered_releases))
            raise RuntimeProfileError(
                f"已安装 Runtime {wanted_release} 与受信任求解器版本不匹配（求解器：{available}）",
                code="RUNTIME_SOLVER_MISMATCH",
            )
        raise RuntimeProfileError(
            "未找到带编译版本元数据的受信任求解器",
            code="RUNTIME_SOLVER_UNAVAILABLE",
        )

    def verify(self, runtime_root: str | Path, solver_executable: str | Path) -> RuntimeProfile:
        root = Path(runtime_root).expanduser().resolve()
        solver = Path(solver_executable).expanduser().resolve()
        status = classify_runtime_root(str(root))
        if status.state != "ready" or not status.dll_path:
            raise RuntimeProfileError("MATLAB Runtime 根目录未达到 ready 状态")
        if solver.suffix.lower() != ".exe" or not solver.is_file():
            raise RuntimeProfileError("编译 Runtime 求解器必须是存在的普通 .exe 文件")
        trusted_files, trusted_roots = _trusted_solver_entries(
            self._environment(), self._project_root
        )
        if solver not in trusted_files and not any(
            _is_within(solver, item) for item in trusted_roots
        ):
            raise RuntimeProfileError("编译 Runtime 求解器不在可信 allowlist 内")
        dll = Path(status.dll_path).resolve()
        if not dll.is_file():
            raise RuntimeProfileError("MATLAB Runtime DLL 不存在")
        profile = RuntimeProfile(
            profile_id=f"runtime-{uuid.uuid4().hex}",
            runtime_root=root,
            dll_path=dll,
            solver_executable=solver,
            runtime_identity=_identity(dll),
            solver_identity=_identity(solver),
            created_at=self._clock(),
        )
        with self._lock:
            self._prune_locked(self._clock())
            if len(self._profiles) >= self._max_profiles:
                raise RuntimeProfileError(
                    "Runtime 验证配置已达到容量上限",
                    code="RUNTIME_PROFILE_CAPACITY",
                )
            self._profiles[profile.profile_id] = profile
        return profile

    def resolve(self, profile_id: str) -> RuntimeProfile:
        with self._lock:
            profile = self._profiles.get(profile_id)
        if profile is None:
            raise RuntimeProfileError(
                "Runtime 验证配置不存在或 sidecar 已重启，请重新探测",
                code="RUNTIME_PROFILE_STALE",
            )
        if self._clock() - profile.created_at > self._ttl_seconds:
            with self._lock:
                self._profiles.pop(profile_id, None)
            raise RuntimeProfileError("Runtime 验证配置已过期，请重新探测", code="RUNTIME_PROFILE_EXPIRED")
        status = classify_runtime_root(str(profile.runtime_root))
        if status.state != "ready" or not status.dll_path:
            raise RuntimeProfileError("Runtime 探测后已变化或不再完整", code="RUNTIME_PROFILE_STALE")
        try:
            dll = Path(status.dll_path).resolve()
            if dll != profile.dll_path or _identity(dll) != profile.runtime_identity:
                raise RuntimeProfileError("Runtime DLL 在探测后已变化", code="RUNTIME_PROFILE_STALE")
            if profile.solver_executable.suffix.lower() != ".exe" or not profile.solver_executable.is_file():
                raise RuntimeProfileError("编译求解器在探测后已删除", code="RUNTIME_PROFILE_STALE")
            if _identity(profile.solver_executable) != profile.solver_identity:
                raise RuntimeProfileError("编译求解器在探测后已变化", code="RUNTIME_PROFILE_STALE")
        except OSError as exc:
            raise RuntimeProfileError("Runtime 或编译求解器在探测后已变化", code="RUNTIME_PROFILE_STALE") from exc
        return profile

    def verify_bundled_resource(self) -> RuntimeProfile | None:
        resource = self._environment().get("TOPPILOT_RESOURCE_ROOT")
        if not resource:
            return None
        resource_root = Path(resource).expanduser().resolve()
        manifest_path = resource_root / "runtime" / "runtime-manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeProfileError(
                "Runtime bundle manifest 无法读取",
                code="RUNTIME_BUNDLE_INVALID",
            ) from exc
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or manifest.get("packageKind") != "topoptpilot-runtime":
            raise RuntimeProfileError(
                "Runtime bundle manifest 类型或版本无效",
                code="RUNTIME_BUNDLE_INVALID",
            )

        def bundled_path(field: str, *, directory: bool = False) -> Path:
            raw = manifest.get(field)
            if not isinstance(raw, str) or not raw.strip():
                raise RuntimeProfileError(f"Runtime bundle manifest 缺少 {field}", code="RUNTIME_BUNDLE_INVALID")
            relative = Path(raw)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeProfileError(f"Runtime bundle manifest 的 {field} 越界", code="RUNTIME_BUNDLE_INVALID")
            target = (resource_root / relative).resolve()
            if not _is_within(target, resource_root):
                raise RuntimeProfileError(f"Runtime bundle manifest 的 {field} 越界", code="RUNTIME_BUNDLE_INVALID")
            exists = target.is_dir() if directory else target.is_file()
            if not exists:
                raise RuntimeProfileError(f"Runtime bundle 资源缺失：{field}", code="RUNTIME_BUNDLE_INVALID")
            return target

        runtime_root = bundled_path("runtimeRoot", directory=True)
        declared_dll = bundled_path("runtimeDll")
        solver = bundled_path("solver")
        expected_dll = manifest.get("runtimeDllSha256")
        expected_solver = manifest.get("solverSha256")
        if not isinstance(expected_dll, str) or not isinstance(expected_solver, str):
            raise RuntimeProfileError("Runtime bundle manifest 缺少摘要", code="RUNTIME_BUNDLE_INVALID")
        if _identity(declared_dll).sha256.lower() != expected_dll.lower():
            raise RuntimeProfileError("Runtime DLL 摘要与 manifest 不一致", code="RUNTIME_BUNDLE_TAMPERED")
        if _identity(solver).sha256.lower() != expected_solver.lower():
            raise RuntimeProfileError("Runtime solver 摘要与 manifest 不一致", code="RUNTIME_BUNDLE_TAMPERED")
        profile = self.verify(runtime_root, solver)
        if profile.dll_path != declared_dll:
            with self._lock:
                self._profiles.pop(profile.profile_id, None)
            raise RuntimeProfileError("Runtime DLL 路径与 manifest 不一致", code="RUNTIME_BUNDLE_INVALID")
        return profile

    def verify_environment(self) -> RuntimeProfile:
        environ = self._environment()
        root = environ.get("TOPOPTPILOT_RUNTIME_ROOT")
        solver = environ.get("TOPOPTPILOT_RUNTIME_SOLVER")
        if not root or not solver:
            raise RuntimeProfileError(
                "compiled-runtime 需要已验证 runtimeProfileId，或同时配置 TOPOPTPILOT_RUNTIME_ROOT 与 TOPOPTPILOT_RUNTIME_SOLVER"
            )
        return self.verify(root, solver)


runtime_profiles = RuntimeProfileStore()
